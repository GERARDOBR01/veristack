"""
retrieval_engine.py
Motor de Recuperación de Evidencia — visual-lv

Busca en 3 capas de conocimiento (JSONs procesados por Gemini Pro):
  Capa 1 — conocimiento permanente (básicos de display, siempre activa)
  Capa 2 — mecánica de campaña activa (caduca por temporada)
  Capa 3 — criterios de sección específica (un archivo por tipo_foto)

Prioridad de fuente:
  Reglas generales:     Capa1 > Capa2 > Capa3
  Criterios de sección: Capa3 > Capa2 > Capa1
  (sección = hay resultados en Capa3 con tipo_foto definido)

Sin modelo. Sin llamadas a API. JSONs en disco únicamente.
Input:  criterio (str) + ResultadoPipeline del mandatory + tipo_foto opcional
Output: ResultadoRetrieval con evidencias ordenadas por relevancia y peso

──────────────────────────────────────────────────────────────────
Schema esperado por cada JSON de capa:
{
  "version": "1.0",
  "descripcion": "...",          ← solo Capa1
  "etapa": "...",                ← solo Capa2
  "vigencia_inicio": "YYYY-MM-DD", ← solo Capa2
  "vigencia_fin":   "YYYY-MM-DD",  ← solo Capa2
  "tipo_foto": "focal_show",     ← solo Capa3
  "criterios": [
    {
      "id":       "triangulacion",
      "aliases":  ["triangulo", "disposicion_triangular"],
      "texto":    "Texto exacto del manual...",
      "peso":     "MANDATORY | RECOMMENDATION | EXCEPTION",
      "aplica_a": ["focal_show", "tringla"] | null,
      "etapa_aplicable": ["1", "2"] | null    ← v1.1: null = todas las etapas
    }
  ]
}

Filtrado por etapa (schema v1.1):
  Si se conoce la etapa activa (parámetro etapa_activa o ConfigRetrieval.etapa_activa)
  y un criterio declara etapa_aplicable que NO incluye esa etapa, el criterio es
  NO_APLICA: no genera evidencia, buscar_lote lo omite del resultado (no llega a
  confidence ni al modelo). Sin etapa conocida o con etapa_aplicable null,
  el comportamiento es el histórico: el criterio aplica.
──────────────────────────────────────────────────────────────────
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from mandatory_engine import ResultadoPipeline, Severidad

logger = logging.getLogger("visual_lv.retrieval")
logger.addHandler(logging.NullHandler())  # la app decide los handlers/nivel

# Versiones de schema que este motor sabe interpretar. Un JSON con otra
# schema_version se carga igual, pero genera WARNING (no crash).
SCHEMAS_VERSION_ESPERADAS = frozenset({"1.0", "1.1"})


# ──────────────────────────────────────────────
# TIPOS
# ──────────────────────────────────────────────

class Peso(str, Enum):
    MANDATORY      = "MANDATORY"
    RECOMMENDATION = "RECOMMENDATION"
    EXCEPTION      = "EXCEPTION"


class Confianza(str, Enum):
    ALTO  = "ALTO"
    MEDIO = "MEDIO"
    BAJO  = "BAJO"


@dataclass
class EvidenciaRetrieved:
    criterio:  str
    evidencia: str
    capa:      int         # 1, 2 o 3
    peso:      Peso
    confianza: Confianza


@dataclass
class ResultadoRetrieval:
    criterio:          str
    evidencias:        list[EvidenciaRetrieved] = field(default_factory=list)
    capas_consultadas: list[int]                = field(default_factory=list)
    capas_vacias:      list[int]                = field(default_factory=list)
    sin_evidencia:     bool                     = False
    resumen:           str                      = ""
    versiones_capas:   dict                     = field(default_factory=dict)
    # v1.1: True si el criterio declara etapa_aplicable y la etapa activa no está
    # incluida. buscar_lote omite estos resultados (no llegan a confidence/modelo).
    no_aplica:         bool                     = False


# ──────────────────────────────────────────────
# CONFIGURACIÓN
# Instanciar por industria o canal para apuntar a diferentes rutas.
# ──────────────────────────────────────────────

@dataclass
class ConfigRetrieval:
    ruta_capa1:              str = "knowledge/capa1_display_basics.json"
    ruta_capa2:              str = "knowledge/capa2_campana_activa.json"
    ruta_capa3_template:     str = "knowledge/capa3_{tipo_foto}.json"
    max_evidencias_por_capa: int = 3
    # Mínimo de keywords del criterio que deben aparecer en ID/aliases → MEDIO
    min_keywords_id:         int = 1
    # Mínimo de keywords que deben aparecer en el texto → BAJO
    min_keywords_texto:      int = 2
    # Etapa activa de la campaña seleccionada en la UI (ej. "E1"). None = no se
    # filtra por etapa_aplicable (comportamiento previo a schema v1.1).
    etapa_activa:            Optional[str] = None


# ──────────────────────────────────────────────
# TABLAS DE ORDENAMIENTO
# ──────────────────────────────────────────────

_PESO_RANK: dict[Peso, int] = {
    Peso.MANDATORY:      3,
    Peso.RECOMMENDATION: 2,
    Peso.EXCEPTION:      1,
}

_CONFIANZA_RANK: dict[Confianza, int] = {
    Confianza.ALTO:  3,
    Confianza.MEDIO: 2,
    Confianza.BAJO:  1,
}

# Prioridad de capa según modo (mayor = se muestra primero)
_PRIORIDAD_GENERAL:  dict[int, int] = {1: 3, 2: 2, 3: 1}
_PRIORIDAD_SECCION:  dict[int, int] = {1: 1, 2: 2, 3: 3}


# ──────────────────────────────────────────────
# COERCIÓN DE TIPOS
# ──────────────────────────────────────────────

def _to_str(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _to_list(value) -> list:
    if isinstance(value, list):
        return value
    return []


def _coerce_peso(raw) -> Peso:
    try:
        return Peso((raw or "").upper())
    except ValueError:
        return Peso.RECOMMENDATION


# ──────────────────────────────────────────────
# CARGA DE CAPAS
# Retorna [] si el archivo no existe, está vacío, o es inválido.
# ──────────────────────────────────────────────

def _cargar_capa_full(ruta: str, etiqueta: str = "") -> tuple[list[dict], dict]:
    """
    Carga una capa y su metadata de versionado.
    Retorna (criterios, meta) donde
        meta = {"schema_version": str|None, "fecha_actualizacion": str|None}.
    Loggea schema_version + fecha_actualizacion al cargar; WARNING si la
    schema_version no coincide con la esperada o falta. Nunca lanza excepción:
    ante archivo ausente/ inválido retorna ([], {}).
    """
    try:
        path = Path(ruta)
        if not path.exists():
            return [], {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return [], {}
    except Exception as exc:
        logger.warning("[%s] no se pudo cargar capa %s: %s", etiqueta or "capa", ruta, exc)
        return [], {}

    criterios = [e for e in data.get("criterios", []) if isinstance(e, dict)]

    schema_version = data.get("schema_version")
    fecha          = data.get("fecha_actualizacion")
    tag            = etiqueta or "capa"

    if schema_version is None:
        logger.warning("[%s] sin schema_version — se carga igual (%d criterios)", tag, len(criterios))
    elif schema_version not in SCHEMAS_VERSION_ESPERADAS:
        logger.warning(
            "[%s] schema_version=%s no está entre las esperadas %s — se carga igual (fecha=%s)",
            tag, schema_version, sorted(SCHEMAS_VERSION_ESPERADAS), fecha,
        )
    else:
        logger.info("[%s] schema_version=%s fecha=%s (%d criterios)", tag, schema_version, fecha, len(criterios))

    return criterios, {"schema_version": schema_version, "fecha_actualizacion": fecha}


def _cargar_capa(ruta: str) -> list[dict]:
    """Wrapper retrocompatible: solo los criterios, sin metadata."""
    criterios, _ = _cargar_capa_full(ruta)
    return criterios


# Fix PT-1 (stress fase 2): tipo_foto entra a un .format() de ruta — un valor
# con separadores ("x/../../otro") sacaba la carga de capa3 FUERA de knowledge/
# (Windows resuelve ".." léxicamente aunque el directorio intermedio no exista).
# Solo identificadores simples consultan capa3.
_TIPO_FOTO_SEGURO_RE = re.compile(r"[A-Za-z0-9_-]+")


def _ruta_capa3(template: str, tipo_foto: Optional[str]) -> Optional[str]:
    """Retorna None si tipo_foto no está disponible, no es un identificador
    seguro (fix PT-1) o el template es inválido."""
    tipo = _to_str(tipo_foto)
    if not tipo:
        return None
    if not _TIPO_FOTO_SEGURO_RE.fullmatch(tipo):
        logger.warning("tipo_foto %r no es un identificador seguro — capa3 no se consulta", tipo)
        return None
    try:
        return template.format(tipo_foto=tipo)
    except (KeyError, ValueError):
        return None


# ──────────────────────────────────────────────
# MATCHING DETERMINISTA
# Cuatro niveles, sin modelo, sin embeddings.
# ──────────────────────────────────────────────

def _norm(s: str) -> str:
    return s.lower().replace("_", " ").strip()


def _keywords(criterio: str) -> list[str]:
    """Tokens significativos del criterio (≥ 3 caracteres)."""
    return [t for t in _norm(criterio).split() if len(t) >= 3]


def _score_entry(
    criterio: str,
    entry:    dict,
    config:   ConfigRetrieval,
) -> Optional[Confianza]:
    """
    Compara el criterio buscado contra una entrada del JSON.
    Retorna el nivel de confianza del match, o None si no hay match relevante.

    Jerarquía de matching:
      1. ID exacto                  → ALTO
      2. Alias exacto               → ALTO
      3. Keywords en ID + aliases   → MEDIO  (configurable: min_keywords_id)
      4. Keywords en texto          → BAJO   (solo si criterio tiene ≥2 keywords)
    """
    criterio_norm = _norm(criterio)
    entry_id      = _norm(_to_str(entry.get("id")) or "")
    aliases       = [_norm(a) for a in _to_list(entry.get("aliases")) if isinstance(a, str)]
    texto         = _norm(_to_str(entry.get("texto")) or "")

    # Nivel 1 y 2: coincidencia exacta
    if criterio_norm == entry_id or criterio_norm in aliases:
        return Confianza.ALTO

    kws = _keywords(criterio)
    if not kws:
        return None

    # Nivel 3: keywords en ID y aliases
    campo_id = entry_id + " " + " ".join(aliases)
    hits_id = sum(1 for k in kws if k in campo_id)
    if hits_id >= config.min_keywords_id:
        return Confianza.MEDIO

    # Nivel 4: keywords en el texto del manual
    # Solo activa con ≥2 keywords: un token único no distingue criterios distintos.
    if len(kws) < 2:
        return None
    hits_texto = sum(1 for k in kws if re.search(r'\b' + re.escape(k) + r'\b', texto))
    if hits_texto >= config.min_keywords_texto:
        return Confianza.BAJO

    return None


def _aplica_a_tipo(entry: dict, tipo_foto: Optional[str]) -> bool:
    """True si la entrada aplica al tipo_foto dado, o si es universal (aplica_a vacío/null)."""
    aplica_a = _to_list(entry.get("aplica_a"))
    if not aplica_a:
        return True          # null / [] = aplica a todos
    if tipo_foto is None:
        return True          # sin contexto de tipo: no filtrar
    return tipo_foto in aplica_a


def _norm_etapa(valor) -> Optional[str]:
    """
    Número de etapa como string, o None si no se puede determinar.
    Acepta las dos formas en uso: "E1" (UI) y "1" (etapa_aplicable del schema v1.1).
    """
    s = _to_str(valor)
    if not s:
        return None
    m = re.fullmatch(r"[eE]?\s*(\d+)", s)
    return m.group(1) if m else None


def _aplica_a_etapa(entry: dict, etapa_activa: Optional[str]) -> bool:
    """
    True si la entrada aplica a la etapa activa, o si es universal.
    Ante ambigüedad (etapa desconocida o valores no normalizables) NO filtra:
    un criterio jamás se descarta en silencio por datos dudosos.
    """
    etapas = _to_list(entry.get("etapa_aplicable"))
    if not etapas:
        return True          # null / [] = aplica a todas las etapas
    activa = _norm_etapa(etapa_activa)
    if activa is None:
        return True          # sin contexto de etapa: no filtrar
    declaradas = {_norm_etapa(e) for e in etapas} - {None}
    if not declaradas:
        return True          # etapa_aplicable no normalizable: no filtrar
    return activa in declaradas


def _criterio_no_aplica_por_etapa(
    criterio:     str,
    capas:        list[list[dict]],
    etapa_activa: Optional[str],
) -> bool:
    """
    True si el criterio (por ID exacto) existe en el knowledge base y TODAS las
    entradas con ese ID declaran etapa_aplicable que excluye la etapa activa.
    Si alguna entrada con ese ID aplica (o es universal), el criterio aplica.
    """
    criterio_norm = _norm(criterio)
    encontrado    = False
    for entradas in capas:
        for entry in entradas:
            if _norm(_to_str(entry.get("id")) or "") != criterio_norm:
                continue
            encontrado = True
            if _aplica_a_etapa(entry, etapa_activa):
                return False
    return encontrado


def _buscar_en_capa(
    criterio:     str,
    entradas:     list[dict],
    numero_capa:  int,
    tipo_foto:    Optional[str],
    config:       ConfigRetrieval,
    etapa_activa: Optional[str] = None,
) -> list[EvidenciaRetrieved]:
    resultados: list[EvidenciaRetrieved] = []

    for entry in entradas:
        if not _aplica_a_tipo(entry, tipo_foto):
            continue
        if not _aplica_a_etapa(entry, etapa_activa):
            continue
        confianza = _score_entry(criterio, entry, config)
        if confianza is None:
            continue
        texto = _to_str(entry.get("texto"))
        if not texto:
            continue
        resultados.append(EvidenciaRetrieved(
            criterio  = criterio,
            evidencia = texto,
            capa      = numero_capa,
            peso      = _coerce_peso(entry.get("peso")),
            confianza = confianza,
        ))

    # Ordenar dentro de la capa: peso desc → confianza desc
    resultados.sort(
        key=lambda e: (_PESO_RANK.get(e.peso, 0), _CONFIANZA_RANK.get(e.confianza, 0)),
        reverse=True,
    )
    return resultados[: config.max_evidencias_por_capa]


# ──────────────────────────────────────────────
# ORDENAMIENTO FINAL
# ──────────────────────────────────────────────

def _ordenar_evidencias(
    evidencias: list[EvidenciaRetrieved],
    es_seccion: bool,
) -> list[EvidenciaRetrieved]:
    tabla = _PRIORIDAD_SECCION if es_seccion else _PRIORIDAD_GENERAL
    return sorted(
        evidencias,
        key=lambda e: (
            tabla.get(e.capa, 0),
            _PESO_RANK.get(e.peso, 0),
            _CONFIANZA_RANK.get(e.confianza, 0),
        ),
        reverse=True,
    )


# ──────────────────────────────────────────────
# LÓGICA INTERNA COMPARTIDA
# Separa la búsqueda del IO de capas para que buscar_lote
# pueda reutilizarla sin recargar los archivos.
# ──────────────────────────────────────────────

def _ejecutar_busqueda(
    criterio:            str,
    capa1_entradas:      list[dict],
    capa2_entradas:      list[dict],
    capa3_entradas:      list[dict],
    capa3_disponible:    bool,
    tipo_foto:           Optional[str],
    resultado_mandatory: ResultadoPipeline,
    config:              ConfigRetrieval,
    versiones_capas:     Optional[dict] = None,
    etapa_activa:        Optional[str] = None,
) -> ResultadoRetrieval:
    capas = [capa1_entradas, capa2_entradas, capa3_entradas]
    if _criterio_no_aplica_por_etapa(criterio, capas, etapa_activa):
        return ResultadoRetrieval(
            criterio        = criterio,
            sin_evidencia   = True,
            no_aplica       = True,
            resumen         = f"RETRIEVAL: {criterio} | NO_APLICA (etapa activa {etapa_activa})",
            versiones_capas = dict(versiones_capas) if versiones_capas else {},
        )

    ev1 = _buscar_en_capa(criterio, capa1_entradas, 1, tipo_foto, config, etapa_activa)
    ev2 = _buscar_en_capa(criterio, capa2_entradas, 2, tipo_foto, config, etapa_activa)
    ev3 = _buscar_en_capa(criterio, capa3_entradas, 3, tipo_foto, config, etapa_activa)

    capas_consultadas = [1, 2] + ([3] if capa3_disponible else [])
    capas_vacias = [
        n for n, ent in [(1, capa1_entradas), (2, capa2_entradas), (3, capa3_entradas)]
        if not ent and n in capas_consultadas
    ]

    es_seccion = bool(ev3 and tipo_foto)
    todas = _ordenar_evidencias(ev1 + ev2 + ev3, es_seccion)

    return ResultadoRetrieval(
        criterio          = criterio,
        evidencias        = todas,
        capas_consultadas = capas_consultadas,
        capas_vacias      = capas_vacias,
        sin_evidencia     = not todas,
        resumen           = _generar_resumen(criterio, todas, capas_consultadas, capas_vacias, resultado_mandatory),
        versiones_capas   = dict(versiones_capas) if versiones_capas else {},
    )


# ──────────────────────────────────────────────
# ENGINE PRINCIPAL
# ──────────────────────────────────────────────

def buscar(
    criterio:            str,
    resultado_mandatory: ResultadoPipeline,
    tipo_foto:           Optional[str] = None,
    config:              Optional[ConfigRetrieval] = None,
    etapa_activa:        Optional[str] = None,
) -> ResultadoRetrieval:
    """
    Busca evidencia para un criterio en las 3 capas de conocimiento.
    Retorna evidencias ordenadas: peso de fuente × peso de regla.
    Si el criterio no aplica a la etapa activa (etapa_aplicable, schema v1.1),
    retorna ResultadoRetrieval con no_aplica=True y sin evidencias.
    La etapa se toma del parámetro o, en su defecto, de config.etapa_activa.
    """
    if not isinstance(criterio, str) or not criterio.strip():
        return ResultadoRetrieval(
            criterio      = str(criterio),
            sin_evidencia = True,
            resumen       = f"criterio inválido: se esperaba string no vacío, recibido {type(criterio).__name__}",
        )

    if not isinstance(resultado_mandatory, ResultadoPipeline):
        resultado_mandatory = ResultadoPipeline(
            veredicto_final = Severidad.NO_CALIFICA,
            resumen         = "ResultadoPipeline inválido — contexto mandatory ausente",
        )

    criterio  = criterio.strip()
    tipo_foto = _to_str(tipo_foto)

    if config is None:
        config = ConfigRetrieval()

    etapa_activa = _to_str(etapa_activa) or _to_str(config.etapa_activa)

    ruta_c3 = _ruta_capa3(config.ruta_capa3_template, tipo_foto)

    capa1_entradas, meta1 = _cargar_capa_full(config.ruta_capa1, "capa1")
    capa2_entradas, meta2 = _cargar_capa_full(config.ruta_capa2, "capa2")
    if ruta_c3:
        capa3_entradas, meta3 = _cargar_capa_full(ruta_c3, "capa3")
    else:
        capa3_entradas, meta3 = [], {}

    versiones = _construir_versiones(meta1, meta2, meta3, ruta_c3 is not None)

    return _ejecutar_busqueda(
        criterio            = criterio,
        capa1_entradas      = capa1_entradas,
        capa2_entradas      = capa2_entradas,
        capa3_entradas      = capa3_entradas,
        capa3_disponible    = ruta_c3 is not None,
        tipo_foto           = tipo_foto,
        resultado_mandatory = resultado_mandatory,
        config              = config,
        versiones_capas     = versiones,
        etapa_activa        = etapa_activa,
    )


def buscar_lote(
    criterios:           list[str],
    resultado_mandatory: ResultadoPipeline,
    tipo_foto:           Optional[str] = None,
    config:              Optional[ConfigRetrieval] = None,
    etapa_activa:        Optional[str] = None,
) -> list[ResultadoRetrieval]:
    """
    Busca evidencia para múltiples criterios.
    Las capas se cargan una sola vez — eficiente para 10+ criterios seguidos.
    Los criterios que no aplican a la etapa activa (etapa_aplicable, schema v1.1)
    se OMITEN del resultado: no llegan a confidence ni se delegan al modelo.
    La etapa se toma del parámetro o, en su defecto, de config.etapa_activa.
    """
    if not isinstance(criterios, list):
        return []

    if not isinstance(resultado_mandatory, ResultadoPipeline):
        resultado_mandatory = ResultadoPipeline(
            veredicto_final = Severidad.NO_CALIFICA,
            resumen         = "ResultadoPipeline inválido — contexto mandatory ausente",
        )

    tipo_foto = _to_str(tipo_foto)

    if config is None:
        config = ConfigRetrieval()

    etapa_activa = _to_str(etapa_activa) or _to_str(config.etapa_activa)

    # Cargar las 3 capas una sola vez
    ruta_c3        = _ruta_capa3(config.ruta_capa3_template, tipo_foto)
    capa1_entradas, meta1 = _cargar_capa_full(config.ruta_capa1, "capa1")
    capa2_entradas, meta2 = _cargar_capa_full(config.ruta_capa2, "capa2")
    if ruta_c3:
        capa3_entradas, meta3 = _cargar_capa_full(ruta_c3, "capa3")
    else:
        capa3_entradas, meta3 = [], {}
    capa3_disponible = ruta_c3 is not None

    versiones = _construir_versiones(meta1, meta2, meta3, capa3_disponible)

    resultados: list[ResultadoRetrieval] = []
    for criterio in criterios:
        if not isinstance(criterio, str) or not criterio.strip():
            continue
        resultado = _ejecutar_busqueda(
            criterio            = criterio.strip(),
            capa1_entradas      = capa1_entradas,
            capa2_entradas      = capa2_entradas,
            capa3_entradas      = capa3_entradas,
            capa3_disponible    = capa3_disponible,
            tipo_foto           = tipo_foto,
            resultado_mandatory = resultado_mandatory,
            config              = config,
            versiones_capas     = versiones,
            etapa_activa        = etapa_activa,
        )
        if resultado.no_aplica:
            logger.info("[retrieval] %s NO_APLICA — etapa_aplicable excluye la etapa activa %s",
                        resultado.criterio, etapa_activa)
            continue
        resultados.append(resultado)

    return resultados


def _construir_versiones(meta1: dict, meta2: dict, meta3: dict, capa3_disponible: bool) -> dict:
    """{"capa1": <schema_version>, "capa2": ..., "capa3": ...} — capa3 solo si está disponible."""
    versiones = {
        "capa1": meta1.get("schema_version"),
        "capa2": meta2.get("schema_version"),
    }
    if capa3_disponible:
        versiones["capa3"] = meta3.get("schema_version")
    return versiones


def _generar_resumen(
    criterio:            str,
    evidencias:          list[EvidenciaRetrieved],
    capas_consultadas:   list[int],
    capas_vacias:        list[int],
    resultado_mandatory: ResultadoPipeline,
) -> str:
    partes = [f"RETRIEVAL: {criterio}"]

    if not resultado_mandatory.puede_continuar:
        partes.append("MANDATORY bloqueó el pipeline")

    if evidencias:
        n_mandatory = sum(1 for e in evidencias if e.peso == Peso.MANDATORY)
        capas_usadas = sorted({e.capa for e in evidencias})
        partes.append(f"{len(evidencias)} evidencia(s)")
        if n_mandatory:
            partes.append(f"{n_mandatory} MANDATORY")
        partes.append("capas=" + "+".join(str(c) for c in capas_usadas))
    else:
        partes.append("SIN EVIDENCIA")

    if capas_vacias:
        partes.append(f"capas_vacías={capas_vacias}")

    return " | ".join(partes)


# ──────────────────────────────────────────────
# TESTS RÁPIDOS
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    import os

    # ── Datos de prueba ─────────────────────────────────────────
    CAPA1_DATA = {
        "version": "1.0",
        "descripcion": "Básicos de display permanentes",
        "criterios": [
            {
                "id": "triangulacion",
                "aliases": ["triangulo", "disposicion_triangular"],
                "texto": "Los productos se deben disponer en forma triangular con el producto principal al centro.",
                "peso": "MANDATORY",
                "aplica_a": None,
            },
            {
                "id": "precio_visible",
                "aliases": ["etiqueta_precio", "visibilidad_precio"],
                "texto": "El precio debe ser visible desde el frente sin necesidad de manipular el producto.",
                "peso": "MANDATORY",
                "aplica_a": None,
            },
            {
                "id": "limpieza_area",
                "aliases": ["orden", "limpieza"],
                "texto": "El área de display debe estar limpia y libre de material ajeno a la exhibición.",
                "peso": "RECOMMENDATION",
                "aplica_a": None,
            },
        ],
    }

    CAPA2_DATA = {
        "version": "1.0",
        "etapa": "verano_2025",
        "vigencia_inicio": "2025-06-01",
        "vigencia_fin": "2025-08-31",
        "criterios": [
            {
                "id": "grafico_etapa",
                "aliases": ["grafico_campana", "grafico_temporada", "grafico_verano"],
                "texto": "El gráfico de campaña verano 2025 debe estar presente en la posición superior del focal.",
                "peso": "MANDATORY",
                "aplica_a": None,
            },
            {
                "id": "producto_estrella_verano",
                "aliases": ["hero_product", "producto_destacado"],
                "texto": "El producto estrella de la temporada verano 2025 debe ocupar la posición central y de mayor jerarquía.",
                "peso": "RECOMMENDATION",
                "aplica_a": ["focal_show", "mesa_show"],
            },
            {
                "id": "parche_segunda_etapa",
                "aliases": ["parche 20", "beneficio adicional"],
                "texto": "Colocar el parche +20 sobre el gráfico base durante la segunda y tercera etapa.",
                "peso": "MANDATORY",
                "aplica_a": None,
                "etapa_aplicable": ["2", "3"],
            },
        ],
    }

    CAPA3_FOCAL_DATA = {
        "version": "1.0",
        "tipo_foto": "focal_show",
        "criterios": [
            {
                "id": "distribucion_niveles",
                "aliases": ["niveles", "altura_producto", "ocupacion_vertical"],
                "texto": "En focal show los productos deben ocupar al menos 4 niveles de altura del mueble.",
                "peso": "MANDATORY",
                "aplica_a": ["focal_show"],
            },
            {
                "id": "triangulacion",
                "aliases": ["triangulo_focal"],
                "texto": "La triangulación en focal show debe tener el producto de mayor altura al centro.",
                "peso": "MANDATORY",
                "aplica_a": ["focal_show"],
            },
            {
                "id": "precio_visible",
                "aliases": ["etiqueta_visible"],
                "texto": "En focal show todas las etiquetas de precio deben ser visibles de frente, sin estar tapadas.",
                "peso": "RECOMMENDATION",
                "aplica_a": ["focal_show"],
            },
        ],
    }

    # ── Setup: escribir JSONs en directorio temporal ─────────────
    tmp = tempfile.mkdtemp(prefix="visual_lv_test_")
    knowledge_dir = Path(tmp) / "knowledge"
    knowledge_dir.mkdir()

    (knowledge_dir / "capa1_display_basics.json").write_text(
        json.dumps(CAPA1_DATA, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (knowledge_dir / "capa2_campana_activa.json").write_text(
        json.dumps(CAPA2_DATA, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (knowledge_dir / "capa3_focal_show.json").write_text(
        json.dumps(CAPA3_FOCAL_DATA, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    config_test = ConfigRetrieval(
        ruta_capa1          = str(knowledge_dir / "capa1_display_basics.json"),
        ruta_capa2          = str(knowledge_dir / "capa2_campana_activa.json"),
        ruta_capa3_template = str(knowledge_dir / "capa3_{tipo_foto}.json"),
    )

    from mandatory_engine import ResultadoCriterio, Fuente, Confianza as ConfMandatory

    mandatory_ok = ResultadoPipeline(
        veredicto_final = Severidad.CUMPLE,
        puede_continuar = True,
        resumen         = "Todo CUMPLE",
    )
    mandatory_bloqueado = ResultadoPipeline(
        veredicto_final = Severidad.GRAVE,
        puede_continuar = False,
        resumen         = "Pipeline bloqueado por imagen oscura",
    )

    # ── Casos de prueba ──────────────────────────────────────────
    casos = [
        {
            "nombre":    "Criterio exacto — presente en Capa1 y Capa3 (sección: focal_show)",
            "criterio":  "triangulacion",
            "tipo_foto": "focal_show",
            "mandatory": mandatory_ok,
        },
        {
            "nombre":    "Criterio de campaña — presente solo en Capa2",
            "criterio":  "grafico_etapa",
            "tipo_foto": "focal_show",
            "mandatory": mandatory_ok,
        },
        {
            "nombre":    "Criterio por keywords — 'precio' coincide en varios",
            "criterio":  "precio_visible",
            "tipo_foto": "focal_show",
            "mandatory": mandatory_ok,
        },
        {
            "nombre":    "Sin tipo_foto — solo Capa1 y Capa2, prioridad general",
            "criterio":  "triangulacion",
            "tipo_foto": None,
            "mandatory": mandatory_ok,
        },
        {
            "nombre":    "Criterio inexistente — SIN EVIDENCIA",
            "criterio":  "criterio_que_no_existe",
            "tipo_foto": "focal_show",
            "mandatory": mandatory_ok,
        },
        {
            "nombre":    "Pipeline mandatory bloqueado — retrieval sigue operando",
            "criterio":  "triangulacion",
            "tipo_foto": "focal_show",
            "mandatory": mandatory_bloqueado,
        },
        {
            "nombre":    "Capa3 inexistente (tipo_foto sin archivo) — degradación graceful",
            "criterio":  "triangulacion",
            "tipo_foto": "tringla",      # no hay capa3_tringla.json en el tmp
            "mandatory": mandatory_ok,
        },
        {
            "nombre":    "Criterio inválido — guard de input",
            "criterio":  "",
            "tipo_foto": "focal_show",
            "mandatory": mandatory_ok,
        },
        {
            "nombre":    "resultado_mandatory inválido — guard de input",
            "criterio":  "triangulacion",
            "tipo_foto": "focal_show",
            "mandatory": {"no_es": "un_pipeline"},
        },
        {
            "nombre":    "Filtro etapa v1.1 — criterio de etapa 2/3 con E1 activa → NO_APLICA",
            "criterio":  "parche_segunda_etapa",
            "tipo_foto": "focal_show",
            "mandatory": mandatory_ok,
            "etapa":     "E1",
        },
        {
            "nombre":    "Filtro etapa v1.1 — criterio de etapa 2/3 con E2 activa → aplica",
            "criterio":  "parche_segunda_etapa",
            "tipo_foto": "focal_show",
            "mandatory": mandatory_ok,
            "etapa":     "E2",
        },
        {
            "nombre":    "Filtro etapa v1.1 — sin etapa activa → no se filtra (histórico)",
            "criterio":  "parche_segunda_etapa",
            "tipo_foto": "focal_show",
            "mandatory": mandatory_ok,
        },
    ]

    for caso in casos:
        print(f"\n{'='*65}")
        print(f"CASO: {caso['nombre']}")
        print(f"{'='*65}")
        resultado = buscar(
            criterio            = caso["criterio"],
            resultado_mandatory = caso["mandatory"],
            tipo_foto           = caso.get("tipo_foto"),
            config              = config_test,
            etapa_activa        = caso.get("etapa"),
        )
        print(f"RESUMEN:           {resultado.resumen}")
        print(f"SIN EVIDENCIA:     {resultado.sin_evidencia}")
        print(f"NO APLICA:         {resultado.no_aplica}")
        print(f"CAPAS CONSULTADAS: {resultado.capas_consultadas}")
        print(f"CAPAS VACÍAS:      {resultado.capas_vacias}")
        if resultado.evidencias:
            print("EVIDENCIAS:")
            for ev in resultado.evidencias:
                print(f"  [Capa{ev.capa}][{ev.peso.value}][{ev.confianza.value}]")
                print(f"    {ev.evidencia[:90]}{'...' if len(ev.evidencia) > 90 else ''}")

    # ── Test buscar_lote ─────────────────────────────────────────
    print(f"\n{'='*65}")
    print("LOTE: triangulacion + grafico_etapa + precio_visible")
    print(f"{'='*65}")
    lote = buscar_lote(
        criterios           = ["triangulacion", "grafico_etapa", "precio_visible"],
        resultado_mandatory = mandatory_ok,
        tipo_foto           = "focal_show",
        config              = config_test,
    )
    for r in lote:
        print(f"\n  [{r.criterio}] {r.resumen}")
        for ev in r.evidencias:
            print(f"    [Capa{ev.capa}][{ev.peso.value}][{ev.confianza.value}] {ev.evidencia[:70]}...")

    # Limpiar archivos temporales
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
