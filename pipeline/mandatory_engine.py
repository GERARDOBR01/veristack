"""
mandatory_engine.py
Motor de Reglas Mandatorias — visual-lv

Jerarquía de ejecución:
  GRAVE       → falla crítica, detiene evaluación
  OBSERVACION → falla menor, continúa
  NO_CALIFICA → dato insuficiente para evaluar
  CUMPLE      → criterio verificado sin observaciones

El modelo NO participa aquí.
Input:  metadata JSON de photo_analyzer.py
Output: lista de resultados ordenados por severidad
"""

import logging
import re
import unicodedata

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


# ──────────────────────────────────────────────
# TIPOS
# ──────────────────────────────────────────────

class Severidad(str, Enum):
    GRAVE       = "GRAVE"
    OBSERVACION = "OBSERVACION"
    NO_CALIFICA = "NO_CALIFICA"
    CUMPLE      = "CUMPLE"


class Fuente(str, Enum):
    CODIGO = "CODIGO"
    MODELO = "MODELO"


class Confianza(str, Enum):
    ALTO  = "ALTO"
    MEDIO = "MEDIO"
    BAJO  = "BAJO"


@dataclass
class ResultadoCriterio:
    criterio:    str
    severidad:   Severidad
    fuente:      Fuente
    descripcion: str
    evidencia:   Optional[str] = None
    confianza:   Confianza = Confianza.ALTO


@dataclass
class ResultadoPipeline:
    veredicto_final: Severidad
    criterios:       list[ResultadoCriterio] = field(default_factory=list)
    puede_continuar: bool = True
    resumen:         str  = ""


# ──────────────────────────────────────────────
# CONFIGURACIÓN DE THRESHOLDS
# Instanciar con valores distintos por industria o canal.
# ──────────────────────────────────────────────

@dataclass
class ConfigEngine:
    brillo_minimo:             float     = 40.0
    nitidez_minima:            float     = 30.0
    espacio_vacio_grave:       float     = 60.0
    espacio_vacio_observacion: float     = 40.0
    # v2 (Sesión GG): % de píxeles quemados (>250) tolerable — arriba, la foto
    # perdió el detalle aunque el brillo MEDIO parezca aceptable.
    quemado_maximo_pct:        float     = 50.0
    # v2: lado menor mínimo en píxeles. 0 = regla deshabilitada (el umbral
    # real se fija tras calibrar contra fotos reales — la calibración
    # propone, no aplica).
    resolucion_minima_px:      float     = 0.0
    tipos_foto_validos:        frozenset = field(
        default_factory=lambda: frozenset({"focal_show", "tringla", "mesa_show", "panoramica"})
    )


# ──────────────────────────────────────────────
# COERCIÓN DE TIPOS
# ──────────────────────────────────────────────

def _to_float(value, default: float) -> float:
    """Convierte value a float; usa default si es None o no convertible."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_str(value) -> Optional[str]:
    """Retorna None si value es None, vacío o solo espacios."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


# ──────────────────────────────────────────────
# WRAPPER DE REGLA
# bloqueante=True detiene el pipeline si la regla produce GRAVE.
# ──────────────────────────────────────────────

@dataclass
class Regla:
    fn:         Callable[["dict", ConfigEngine], ResultadoCriterio]
    bloqueante: bool = False


# ──────────────────────────────────────────────
# REGLAS MANDATORIAS
# Orden = prioridad de ejecución
# Todas retornan ResultadoCriterio — CUMPLE incluido.
# ──────────────────────────────────────────────

def _regla_archivo_invalido(meta: dict, config: ConfigEngine) -> ResultadoCriterio:
    """
    v2 (fix CR-1/GD-1): si photo_analyzer no pudo analizar la imagen
    (archivo inexistente, corrupto, truncado, no-imagen, bomba de
    descompresión) o el pre-análisis reventó, el veredicto debe decir la
    CAUSA REAL — no el falso "imagen oscura" (brillo 0.0 por defecto) ni la
    foto fantasma "perfecta" (defaults brillo=100).
    """
    if not meta.get("analisis_fallido"):
        return ResultadoCriterio(
            criterio    = "archivo_invalido",
            severidad   = Severidad.CUMPLE,
            fuente      = Fuente.CODIGO,
            descripcion = "El archivo de imagen se cargó y analizó correctamente.",
            confianza   = Confianza.ALTO,
        )
    causa = _to_str(meta.get("causa_analisis")) or "causa desconocida"
    return ResultadoCriterio(
        criterio    = "archivo_invalido",
        severidad   = Severidad.GRAVE,
        fuente      = Fuente.CODIGO,
        descripcion = "El archivo de imagen no pudo analizarse. Vuelve a subir la foto original.",
        evidencia   = f"causa={causa}",
        confianza   = Confianza.ALTO,
    )


def _regla_imagen_sobreexpuesta(meta: dict, config: ConfigEngine) -> ResultadoCriterio:
    """v2: exposición por histograma — % de píxeles quemados (>250), no la media."""
    quemado = _to_float(meta.get("quemado_pct"), default=0.0)
    if quemado > config.quemado_maximo_pct:
        return ResultadoCriterio(
            criterio    = "imagen_sobreexpuesta",
            severidad   = Severidad.GRAVE,
            fuente      = Fuente.CODIGO,
            descripcion = "La imagen está sobreexpuesta: el detalle se perdió en las zonas quemadas.",
            evidencia   = f"quemado_pct={quemado} (máximo aceptable: {config.quemado_maximo_pct})",
            confianza   = Confianza.ALTO,
        )
    return ResultadoCriterio(
        criterio    = "imagen_sobreexpuesta",
        severidad   = Severidad.CUMPLE,
        fuente      = Fuente.CODIGO,
        descripcion = f"Exposición aceptable (quemado_pct={quemado}).",
        confianza   = Confianza.ALTO,
    )


def _regla_resolucion_minima(meta: dict, config: ConfigEngine) -> ResultadoCriterio:
    """v2: deshabilitada con resolucion_minima_px=0 (default) hasta calibrar."""
    if config.resolucion_minima_px <= 0:
        return ResultadoCriterio(
            criterio    = "resolucion_minima",
            severidad   = Severidad.CUMPLE,
            fuente      = Fuente.CODIGO,
            descripcion = "Regla de resolución mínima deshabilitada (umbral 0).",
            confianza   = Confianza.ALTO,
        )
    lado_menor = _to_float(meta.get("resolucion_menor_px"), default=0.0)
    if 0 < lado_menor < config.resolucion_minima_px:
        return ResultadoCriterio(
            criterio    = "resolucion_insuficiente",
            severidad   = Severidad.GRAVE,
            fuente      = Fuente.CODIGO,
            descripcion = "La resolución de la imagen es insuficiente para verificar detalle.",
            evidencia   = f"lado_menor={lado_menor}px (mínimo: {config.resolucion_minima_px}px)",
            confianza   = Confianza.ALTO,
        )
    return ResultadoCriterio(
        criterio    = "resolucion_minima",
        severidad   = Severidad.CUMPLE,
        fuente      = Fuente.CODIGO,
        descripcion = f"Resolución aceptable (lado menor {lado_menor}px).",
        confianza   = Confianza.ALTO,
    )


def _regla_imagen_oscura(meta: dict, config: ConfigEngine) -> ResultadoCriterio:
    brillo = _to_float(meta.get("brillo"), default=100.0)
    if brillo < config.brillo_minimo:
        return ResultadoCriterio(
            criterio    = "imagen_oscura",
            severidad   = Severidad.GRAVE,
            fuente      = Fuente.CODIGO,
            descripcion = "La imagen es demasiado oscura para evaluar criterios visuales.",
            evidencia   = f"brillo={brillo} (mínimo aceptable: {config.brillo_minimo})",
            confianza   = Confianza.ALTO,
        )
    return ResultadoCriterio(
        criterio    = "imagen_oscura",
        severidad   = Severidad.CUMPLE,
        fuente      = Fuente.CODIGO,
        descripcion = f"Brillo aceptable ({brillo}).",
        confianza   = Confianza.ALTO,
    )


def _regla_imagen_borrosa(meta: dict, config: ConfigEngine) -> ResultadoCriterio:
    nitidez = _to_float(meta.get("nitidez"), default=100.0)
    if nitidez < config.nitidez_minima:
        return ResultadoCriterio(
            criterio    = "imagen_borrosa",
            severidad   = Severidad.GRAVE,
            fuente      = Fuente.CODIGO,
            descripcion = "La imagen no tiene suficiente nitidez para verificar detalles.",
            evidencia   = f"nitidez={nitidez} (mínimo aceptable: {config.nitidez_minima})",
            confianza   = Confianza.ALTO,
        )
    return ResultadoCriterio(
        criterio    = "imagen_borrosa",
        severidad   = Severidad.CUMPLE,
        fuente      = Fuente.CODIGO,
        descripcion = f"Nitidez aceptable ({nitidez}).",
        confianza   = Confianza.ALTO,
    )


def _regla_espacio_vacio(meta: dict, config: ConfigEngine) -> ResultadoCriterio:
    espacio_vacio = _to_float(meta.get("espacio_vacio_pct"), default=0.0)
    if espacio_vacio > config.espacio_vacio_grave:
        return ResultadoCriterio(
            criterio    = "espacio_vacio_excesivo",
            severidad   = Severidad.GRAVE,
            fuente      = Fuente.CODIGO,
            descripcion = f"El espacio vacío supera el {config.espacio_vacio_grave}%. El focal no está completo.",
            evidencia   = f"espacio_vacio={espacio_vacio}%",
            confianza   = Confianza.ALTO,
        )
    if espacio_vacio > config.espacio_vacio_observacion:
        return ResultadoCriterio(
            criterio    = "espacio_vacio_elevado",
            severidad   = Severidad.OBSERVACION,
            fuente      = Fuente.CODIGO,
            descripcion = "El espacio vacío es elevado. Revisar surtido.",
            evidencia   = f"espacio_vacio={espacio_vacio}%",
            confianza   = Confianza.ALTO,
        )
    return ResultadoCriterio(
        criterio    = "espacio_vacio",
        severidad   = Severidad.CUMPLE,
        fuente      = Fuente.CODIGO,
        descripcion = f"Espacio vacío dentro de límites ({espacio_vacio}%).",
        confianza   = Confianza.ALTO,
    )


# ── Comparación gráfico vs etapa (fix sesión 7 Jul 2026) ─────────────
# Visión lee el NOMBRE visible del gráfico ("Gran Barata", "Gran Barata 40%");
# etapa_activa puede ser el ID de campaña ("gran_barata_pv2026") o solo la
# etiqueta de etapa ("E1", lo que manda la UI). La comparación estricta !=
# disparaba GRAVE en toda foto con gráfico (0/5 precisión).

_ETIQUETA_ETAPA_RE = re.compile(r"^e?\d{1,2}$")


def _canon_grafico(texto: str) -> str:
    """Minúsculas, sin acentos, solo [a-z0-9]."""
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _tokens_canon(texto: str) -> list[str]:
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    return [tk for tk in re.split(r"[^a-z0-9]+", t) if tk]


def _nucleo_campana(etapa: str) -> list[str]:
    """Tokens que NOMBRAN la campaña en el ID de etapa: alfabéticos puros de
    ≥3 letras ("gran_barata_pv2026" → [gran, barata]; "E1" → [])."""
    return [tk for tk in _tokens_canon(etapa) if tk.isalpha() and len(tk) >= 3]


def _corresponde_grafico_etapa(grafico: str, etapa: str) -> Optional[bool]:
    """
    True  → el gráfico corresponde a la etapa/campaña activa.
    False → NO corresponde (mismatch real → GRAVE).
    None  → no comparable por código: etapa_activa no nombra campaña
            (ej. etiqueta "E1") y el gráfico no es etiqueta de etapa.
    """
    g, e = _canon_grafico(grafico), _canon_grafico(etapa)
    if g == e:
        return True
    if _ETIQUETA_ETAPA_RE.match(g) and _ETIQUETA_ETAPA_RE.match(e):
        return False  # dos etiquetas de etapa distintas (E1 vs E2)
    nucleo = _nucleo_campana(etapa)
    if not nucleo:
        return None
    if set(nucleo) <= set(_tokens_canon(grafico)):
        return True  # "Gran Barata 40%" / "Vive la Gran Barata" ⊇ {gran, barata}
    nucleo_junto = "".join(nucleo)
    if nucleo_junto in g or g in nucleo_junto:
        return True  # variantes sin separadores ("granbarata")
    return False


def _regla_grafico_etapa(meta: dict, config: ConfigEngine) -> ResultadoCriterio:
    etapa   = _to_str(meta.get("etapa_activa"))
    grafico = _to_str(meta.get("grafico_detectado"))

    # INSTRUMENTACIÓN DIAGNÓSTICO (sesión bug grafico_etapa_incorrecta):
    # valores exactos y tipo de dato justo antes de la comparación.
    logging.getLogger("mandatory_engine").info(
        "[DIAG grafico_etapa] crudo etapa_activa=%r (%s) | crudo grafico_detectado=%r (%s) "
        "| comparado etapa=%r (%s) vs grafico=%r (%s)",
        meta.get("etapa_activa"), type(meta.get("etapa_activa")).__name__,
        meta.get("grafico_detectado"), type(meta.get("grafico_detectado")).__name__,
        etapa, type(etapa).__name__, grafico, type(grafico).__name__,
    )

    if not etapa:
        return ResultadoCriterio(
            criterio    = "etapa_no_definida",
            severidad   = Severidad.NO_CALIFICA,
            fuente      = Fuente.CODIGO,
            descripcion = "No se especificó la etapa activa. No es posible validar el gráfico.",
            confianza   = Confianza.ALTO,
        )
    if grafico is None:
        return ResultadoCriterio(
            criterio    = "grafico_no_detectado",
            severidad   = Severidad.NO_CALIFICA,
            fuente      = Fuente.CODIGO,
            descripcion = "No se detectó gráfico en la imagen. Requiere revisión manual.",
            confianza   = Confianza.MEDIO,
        )
    corresponde = _corresponde_grafico_etapa(grafico, etapa)
    if corresponde is None:
        return ResultadoCriterio(
            criterio    = "grafico_etapa_no_verificable",
            severidad   = Severidad.NO_CALIFICA,
            fuente      = Fuente.CODIGO,
            descripcion = (f"La etapa activa '{etapa}' es una etiqueta de etapa, no un ID "
                           "de campaña — el código no puede validar que el gráfico "
                           f"'{grafico}' corresponda. Requiere el ID de campaña o revisión manual."),
            evidencia   = f"grafico_detectado={grafico}, etapa_activa={etapa}",
            confianza   = Confianza.MEDIO,
        )
    if not corresponde:
        return ResultadoCriterio(
            criterio    = "grafico_etapa_incorrecta",
            severidad   = Severidad.GRAVE,
            fuente      = Fuente.CODIGO,
            descripcion = f"El gráfico '{grafico}' no corresponde a la etapa activa '{etapa}'.",
            evidencia   = f"grafico_detectado={grafico}, etapa_activa={etapa}",
            confianza   = Confianza.ALTO,
        )
    return ResultadoCriterio(
        criterio    = "grafico_etapa",
        severidad   = Severidad.CUMPLE,
        fuente      = Fuente.CODIGO,
        descripcion = f"Gráfico '{grafico}' corresponde a etapa '{etapa}'.",
        confianza   = Confianza.ALTO,
    )


def _regla_tipo_foto_valido(meta: dict, config: ConfigEngine) -> ResultadoCriterio:
    tipo = _to_str(meta.get("tipo_foto"))

    if tipo is None:
        return ResultadoCriterio(
            criterio    = "tipo_foto_desconocido",
            severidad   = Severidad.NO_CALIFICA,
            fuente      = Fuente.CODIGO,
            descripcion = "No se pudo clasificar el tipo de foto.",
            confianza   = Confianza.MEDIO,
        )
    if tipo not in config.tipos_foto_validos:
        return ResultadoCriterio(
            criterio    = "tipo_foto_invalido",
            severidad   = Severidad.OBSERVACION,
            fuente      = Fuente.CODIGO,
            descripcion = f"Tipo de foto '{tipo}' no reconocido. Evaluación parcial.",
            evidencia   = f"tipo_foto={tipo}",
            confianza   = Confianza.MEDIO,
        )
    return ResultadoCriterio(
        criterio    = "tipo_foto_valido",
        severidad   = Severidad.CUMPLE,
        fuente      = Fuente.CODIGO,
        descripcion = f"Tipo de foto '{tipo}' reconocido.",
        confianza   = Confianza.ALTO,
    )


# ──────────────────────────────────────────────
# REGISTRO DE REGLAS — orden de ejecución
# ──────────────────────────────────────────────

REGLAS_MANDATORY: list[Regla] = [
    Regla(_regla_archivo_invalido,     bloqueante=True),   # 0. ¿El archivo es una imagen analizable?
    Regla(_regla_imagen_oscura,        bloqueante=True),   # 1. ¿Se puede ver algo?
    Regla(_regla_imagen_sobreexpuesta, bloqueante=True),   # 2. ¿Se quemó el detalle?
    Regla(_regla_imagen_borrosa,       bloqueante=True),   # 3. ¿Se puede leer detalle?
    Regla(_regla_resolucion_minima,    bloqueante=True),   # 4. ¿Alcanza la resolución? (off por default)
    Regla(_regla_tipo_foto_valido,     bloqueante=False),  # 5. ¿Sabemos qué tipo de foto es?
    Regla(_regla_espacio_vacio,        bloqueante=False),  # 6. ¿Hay producto en el focal?
    Regla(_regla_grafico_etapa,        bloqueante=False),  # 7. ¿El gráfico de campaña es correcto?
]


# ──────────────────────────────────────────────
# ENGINE PRINCIPAL
# ──────────────────────────────────────────────

def ejecutar(metadata: dict, config: Optional[ConfigEngine] = None) -> ResultadoPipeline:
    """
    Corre todas las reglas mandatorias en orden jerárquico.
    Detiene si encuentra un GRAVE en una regla bloqueante.
    """
    if not isinstance(metadata, dict):
        return ResultadoPipeline(
            veredicto_final = Severidad.GRAVE,
            puede_continuar = False,
            resumen         = f"metadata inválido: se esperaba dict, recibido {type(metadata).__name__}",
        )

    if config is None:
        config = ConfigEngine()

    resultados: list[ResultadoCriterio] = []
    puede_continuar = True

    for regla in REGLAS_MANDATORY:
        try:
            resultado = regla.fn(metadata, config)
        except Exception as exc:
            resultado = ResultadoCriterio(
                criterio    = getattr(regla.fn, "__name__", "regla_desconocida"),
                severidad   = Severidad.NO_CALIFICA,
                fuente      = Fuente.CODIGO,
                descripcion = f"Error interno al evaluar regla: {exc}",
                confianza   = Confianza.BAJO,
            )

        resultados.append(resultado)

        if resultado.severidad == Severidad.GRAVE and regla.bloqueante:
            puede_continuar = False
            break

    veredicto = _calcular_veredicto(resultados)
    resumen   = _generar_resumen(veredicto, resultados, puede_continuar)

    return ResultadoPipeline(
        veredicto_final = veredicto,
        criterios       = resultados,
        puede_continuar = puede_continuar,
        resumen         = resumen,
    )


def _calcular_veredicto(resultados: list[ResultadoCriterio]) -> Severidad:
    if not resultados:
        return Severidad.CUMPLE

    jerarquia = [Severidad.GRAVE, Severidad.OBSERVACION, Severidad.NO_CALIFICA, Severidad.CUMPLE]
    for nivel in jerarquia:
        if any(r.severidad == nivel for r in resultados):
            return nivel
    return Severidad.CUMPLE


def _generar_resumen(veredicto: Severidad, resultados: list[ResultadoCriterio], puede_continuar: bool) -> str:
    graves      = [r for r in resultados if r.severidad == Severidad.GRAVE]
    observacion = [r for r in resultados if r.severidad == Severidad.OBSERVACION]
    no_cal      = [r for r in resultados if r.severidad == Severidad.NO_CALIFICA]

    partes = [f"VEREDICTO MANDATORY: {veredicto.value}"]
    if graves:
        partes.append(f"GRAVES ({len(graves)}): " + " | ".join(r.criterio for r in graves))
    if observacion:
        partes.append(f"OBSERVACIONES ({len(observacion)}): " + " | ".join(r.criterio for r in observacion))
    if no_cal:
        partes.append(f"NO CALIFICA ({len(no_cal)}): " + " | ".join(r.criterio for r in no_cal))
    if not puede_continuar:
        partes.append("→ Pipeline detenido. Foto no evaluable.")

    return " | ".join(partes)


# ──────────────────────────────────────────────
# TESTS RÁPIDOS
# ──────────────────────────────────────────────

if __name__ == "__main__":
    config_farma = ConfigEngine(brillo_minimo=50.0, nitidez_minima=40.0)

    casos = [
        {
            "nombre": "Foto oscura — debe bloquear pipeline",
            "meta":   {"brillo": 20, "nitidez": 80, "espacio_vacio_pct": 30,
                       "tipo_foto": "focal_show", "etapa_activa": "E1", "grafico_detectado": "E1"},
        },
        {
            "nombre": "Gráfico de etapa incorrecta — GRAVE sin bloqueo",
            "meta":   {"brillo": 120, "nitidez": 85, "espacio_vacio_pct": 25,
                       "tipo_foto": "focal_show", "etapa_activa": "E2", "grafico_detectado": "E1"},
        },
        {
            "nombre": "Focal bien armado — todo CUMPLE",
            "meta":   {"brillo": 130, "nitidez": 90, "espacio_vacio_pct": 20,
                       "tipo_foto": "focal_show", "etapa_activa": "E1", "grafico_detectado": "E1"},
        },
        {
            "nombre": "Espacio vacío excesivo — GRAVE sin bloqueo",
            "meta":   {"brillo": 115, "nitidez": 88, "espacio_vacio_pct": 70,
                       "tipo_foto": "focal_show", "etapa_activa": "E1", "grafico_detectado": "E1"},
        },
        {
            "nombre": "metadata None — guard de input",
            "meta":   None,
        },
        {
            "nombre": "Campos con tipos incorrectos — coerción",
            "meta":   {"brillo": "oscuro", "nitidez": None, "espacio_vacio_pct": "30%",
                       "tipo_foto": "focal_show", "etapa_activa": "E1", "grafico_detectado": "E1"},
        },
        {
            "nombre": "grafico_detectado vacío — NO_CALIFICA",
            "meta":   {"brillo": 120, "nitidez": 85, "espacio_vacio_pct": 25,
                       "tipo_foto": "focal_show", "etapa_activa": "E1", "grafico_detectado": ""},
        },
        {
            "nombre": "Config farma — thresholds más altos",
            "meta":   {"brillo": 45, "nitidez": 35, "espacio_vacio_pct": 20,
                       "tipo_foto": "focal_show", "etapa_activa": "E1", "grafico_detectado": "E1"},
            "config": config_farma,
        },
    ]

    for caso in casos:
        print(f"\n{'='*60}")
        print(f"CASO: {caso['nombre']}")
        print(f"{'='*60}")
        resultado = ejecutar(caso["meta"], config=caso.get("config"))
        print(f"RESUMEN: {resultado.resumen}")
        print(f"PUEDE CONTINUAR: {resultado.puede_continuar}")
        print("CRITERIOS:")
        for c in resultado.criterios:
            print(f"  [{c.severidad.value}] {c.criterio} — {c.descripcion}")
            if c.evidencia:
                print(f"    evidencia: {c.evidencia}")
