"""
pipeline.py
Orquestador del Pipeline de Verificación — visual-lv

Encadena en orden fijo:
  PASO 0 — Prepara metadata (photo_analyzer + datos del usuario)
  PASO 1 — mandatory_engine  → reglas duras, sin modelo
  PASO 2 — retrieval_engine  → evidencia del knowledge base
  PASO 3 — confidence_engine → calibra confianza por criterio
  PASO 4 — Separa: código (definitivo) vs modelo (a delegar)
  PASO 5 — Construye prompt estructurado para criterios delegados
  PASO 6 — Llama al modelo (Gemini 1.5 Pro)
  PASO 7 — Merge: veredictos del código + respuesta del modelo
  PASO 8 — Produce ResultadoFinal

No tiene lógica de evaluación propia — solo dirige el flujo.
El modelo entra ÚNICAMENTE en PASO 6, nunca antes.
"""

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import mandatory_engine
import retrieval_engine
import confidence_engine

from mandatory_engine import ConfigEngine, ResultadoPipeline, Severidad
from retrieval_engine import Confianza, ConfigRetrieval, Peso, ResultadoRetrieval
from confidence_engine import ConfigConfianza, ResultadoConfianza


# ──────────────────────────────────────────────
# TIPOS
# ──────────────────────────────────────────────

@dataclass
class ResultadoFinal:
    veredicto_global:               Severidad
    criterios:                      list[ResultadoConfianza] = field(default_factory=list)
    resumen_ejecutivo:              str  = ""
    puede_continuar:                bool = True
    tokens_modelo_usados:           int  = 0
    criterios_decididos_por_codigo: int  = 0
    criterios_delegados_a_modelo:   int  = 0


# ──────────────────────────────────────────────
# CONFIGURACIÓN
# Un solo objeto que agrega las configs de cada motor.
# ──────────────────────────────────────────────

@dataclass
class ConfigPipeline:
    config_mandatory:  ConfigEngine    = field(default_factory=ConfigEngine)
    config_retrieval:  ConfigRetrieval = field(default_factory=ConfigRetrieval)
    config_confianza:  ConfigConfianza = field(default_factory=ConfigConfianza)
    modelo_max_tokens: int             = 2000


# ──────────────────────────────────────────────
# HELPERS — KNOWLEDGE BASE
# ──────────────────────────────────────────────

def _leer_capa(ruta: str) -> list[dict]:
    """Carga entradas de un JSON de capa. Retorna [] si no existe o es inválido."""
    try:
        path = Path(ruta)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [e for e in data.get("criterios", []) if isinstance(e, dict)]
    except Exception:
        return []


def _extraer_criterios_del_knowledge(
    config:    ConfigRetrieval,
    tipo_foto: Optional[str],
) -> list[str]:
    """
    Extrae todos los IDs únicos del knowledge base activo.
    Lee Capa1 y Capa2 siempre; Capa3 solo si tipo_foto está disponible.
    """
    ids: set[str] = set()

    for ruta in [config.ruta_capa1, config.ruta_capa2]:
        for entry in _leer_capa(ruta):
            id_ = entry.get("id")
            if isinstance(id_, str) and id_.strip():
                ids.add(id_.strip())

    if tipo_foto:
        try:
            ruta_c3 = config.ruta_capa3_template.format(tipo_foto=tipo_foto)
            for entry in _leer_capa(ruta_c3):
                id_ = entry.get("id")
                if isinstance(id_, str) and id_.strip():
                    ids.add(id_.strip())
        except (KeyError, ValueError):
            pass

    return sorted(ids)  # orden determinista en cada ejecución


def _criterios_mandatory_solo_codigo(
    mandatory:    ResultadoPipeline,
    criterios_kb: set[str],
) -> list[ResultadoConfianza]:
    """
    Criterios GRAVE del mandatory que no tienen cobertura en el knowledge base.
    Sin esta conversión no entran al retrieval y quedan ausentes de
    ResultadoFinal.criterios aunque sí afectan el veredicto_global.
    """
    resultado = []
    for mc in mandatory.criterios:
        if mc.criterio in criterios_kb or mc.severidad != Severidad.GRAVE:
            continue
        resultado.append(ResultadoConfianza(
            criterio         = mc.criterio,
            veredicto        = mc.severidad,
            confianza        = Confianza.ALTO,
            fuente_dominante = "MANDATORY",
            peso_dominante   = Peso.MANDATORY,
            delegar_a_modelo = False,
            razon            = mc.descripcion,
        ))
    return resultado


# ──────────────────────────────────────────────
# HELPERS — METADATA
# ──────────────────────────────────────────────

def _preparar_metadata(
    imagen_path:    Optional[str],
    etapa_activa:   str,
    tipo_foto:      Optional[str],
    metadata_extra: Optional[dict],
) -> dict:
    """
    Combina salida de photo_analyzer con los metadatos del usuario.
    Si photo_analyzer no está disponible o falla, usa defaults seguros.
    metadata_extra sobreescribe cualquier campo (útil en tests y overrides).

    Mapeo de nombres photo_analyzer → mandatory_engine:
      brightness        → brillo           (0-100, escala coincide)
      sharpness_score   → nitidez          (varianza Laplaciana, mismo rango)
      empty_space_ratio → espacio_vacio_pct (ratio 0-1 → porcentaje 0-100)
      photo_type        → tipo_foto
    """
    base: dict = {
        "brillo":            100.0,
        "nitidez":           100.0,
        "espacio_vacio_pct": 0.0,
        "tipo_foto":         tipo_foto,
        "etapa_activa":      etapa_activa,
        "grafico_detectado": None,
    }

    if imagen_path:
        try:
            from photo_analyzer import classify_photo_type, extract_basic_facts
            facts    = extract_basic_facts(imagen_path)
            detected = classify_photo_type(imagen_path)
            base.update({
                "brillo":            facts.get("brightness", 100.0),
                "nitidez":           facts.get("sharpness_score", 100.0),
                "espacio_vacio_pct": round(facts.get("empty_space_ratio", 0.0) * 100, 1),
                "tipo_foto":         tipo_foto or detected,
            })
        except Exception:
            pass  # photo_analyzer no disponible o imagen inválida — defaults ya aplicados

    if metadata_extra:
        base.update(metadata_extra)

    return base


# ──────────────────────────────────────────────
# HELPERS — VEREDICTO GLOBAL
# Incluye mandatory.veredicto_final para capturar criterios
# evaluados por mandatory que no lleguen al retrieval.
# ──────────────────────────────────────────────

_SEVERIDAD_RANK: dict[Severidad, int] = {
    Severidad.GRAVE:       4,
    Severidad.OBSERVACION: 3,
    Severidad.NO_CALIFICA: 2,
    Severidad.CUMPLE:      1,
}

def _calcular_veredicto_global(
    criterios: list[ResultadoConfianza],
    mandatory: ResultadoPipeline,
) -> Severidad:
    jerarquia = [Severidad.GRAVE, Severidad.OBSERVACION, Severidad.NO_CALIFICA, Severidad.CUMPLE]
    severidades = {c.veredicto for c in criterios} | {mandatory.veredicto_final}
    for nivel in jerarquia:
        if nivel in severidades:
            return nivel
    return Severidad.CUMPLE


# ──────────────────────────────────────────────
# HELPERS — MODELO
# ──────────────────────────────────────────────

def _construir_prompt(
    delegados:              list[ResultadoConfianza],
    retrieval_por_criterio: dict[str, ResultadoRetrieval],
    metadata:               dict,
) -> str:
    """
    Prompt estructurado para el modelo. Solo incluye criterios delegados.
    El modelo debe responder en JSON estricto — no en texto libre.
    """
    if not delegados:
        return ""

    tipo   = metadata.get("tipo_foto", "desconocido")
    etapa  = metadata.get("etapa_activa", "no especificada")

    lineas = [
        "Eres un evaluador especialista en visual merchandising retail.",
        "Tu rol es evaluar ÚNICAMENTE los criterios listados a continuación.",
        "NO agregues observaciones sobre otros aspectos de la imagen.",
        "NO inventes criterios adicionales fuera de los que se te piden.",
        "",
        "Responde EXCLUSIVAMENTE con este JSON (sin texto adicional antes ni después):",
        '{"evaluaciones": [{"criterio": "<id>", "veredicto": "CUMPLE|OBSERVACION|GRAVE|NO_CALIFICA", "razon": "<razón concisa basada en la evidencia>"}]}',
        "",
        f"Tipo de foto analizada: {tipo}",
        f"Etapa de campaña activa: {etapa}",
        "",
        "CRITERIOS A EVALUAR:",
        "─" * 52,
    ]

    for rc in delegados:
        lineas.append(f"\nCriterio: {rc.criterio}")
        lineas.append(f"Razón para delegar: {rc.razon}")

        retrieval = retrieval_por_criterio.get(rc.criterio)
        if retrieval and retrieval.evidencias:
            lineas.append("Evidencia del knowledge base:")
            for ev in retrieval.evidencias[:2]:
                lineas.append(f"  [{ev.peso.value}][Capa{ev.capa}] {ev.evidencia}")
        else:
            lineas.append("Evidencia: no disponible — evalúa según tu conocimiento del criterio.")

    return "\n".join(lineas)


# ── Configuración del modelo ───────────────────────────────────────
GEMINI_MODEL     = "gemini-1.5-pro"
GEMINI_ENDPOINT  = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
GEMINI_TIMEOUT_S = 30

# Instrucción de formato que se agrega al final del prompt antes de enviarlo
# al modelo. El prompt original (de _construir_prompt) no se modifica.
_INSTRUCCION_FORMATO_JSON = (
    "\n\nResponde EXCLUSIVAMENTE con un arreglo JSON válido, sin texto ni "
    "markdown antes o después, con exactamente esta forma:\n"
    "[\n"
    "  {\n"
    '    "criterio": "nombre_del_criterio",\n'
    '    "veredicto": "GRAVE|OBSERVACION|NO_CALIFICA|CUMPLE",\n'
    '    "razon": "explicación breve en español"\n'
    "  }\n"
    "]"
)


def _contexto_ssl() -> ssl.SSLContext:
    """
    Contexto TLS por defecto. Si el entorno expone un bundle de CA adicional
    (proxy corporativo / agent proxy), lo agrega sin reemplazar los CAs del
    sistema. Nunca deshabilita la verificación.
    """
    ctx = ssl.create_default_context()
    for ca in (os.environ.get("SSL_CERT_FILE"),
               os.environ.get("REQUESTS_CA_BUNDLE"),
               "/root/.ccr/ca-bundle.crt"):
        try:
            if ca and Path(ca).exists():
                ctx.load_verify_locations(cafile=ca)
        except Exception:
            pass
    return ctx


def _extraer_texto(payload: dict) -> str:
    """Texto plano del primer candidato de la respuesta de Gemini."""
    try:
        candidato = (payload.get("candidates") or [])[0]
        partes    = candidato["content"]["parts"]
        return "".join(p.get("text", "") for p in partes if isinstance(p, dict))
    except (IndexError, KeyError, TypeError):
        return ""


def _extraer_tokens(payload: dict) -> int:
    """Total de tokens reportados por usageMetadata.totalTokenCount."""
    try:
        return int(payload.get("usageMetadata", {}).get("totalTokenCount", 0))
    except (TypeError, ValueError):
        return 0


def _normalizar_respuesta(texto: str) -> Optional[str]:
    """
    El modelo responde con un arreglo [{criterio, veredicto, razon}, ...].
    _merge_veredictos() espera el shape {"evaluaciones": [...]}, así que aquí
    se parsea la respuesta (tolerando fences ```json) y se reescribe al shape
    esperado, sin tocar el módulo de merge. Retorna None si no se puede parsear.
    """
    if not texto:
        return None

    limpio = texto.strip()
    if limpio.startswith("```"):
        limpio = re.sub(r"^```[a-zA-Z]*\s*", "", limpio)
        limpio = re.sub(r"\s*```$", "", limpio).strip()

    try:
        parsed = json.loads(limpio)
    except (json.JSONDecodeError, TypeError):
        return None

    if isinstance(parsed, list):
        evaluaciones = parsed
    elif isinstance(parsed, dict) and isinstance(parsed.get("evaluaciones"), list):
        evaluaciones = parsed["evaluaciones"]
    elif isinstance(parsed, dict):
        evaluaciones = [parsed]
    else:
        return None

    return json.dumps({"evaluaciones": evaluaciones}, ensure_ascii=False)


def _llamar_modelo(prompt: str) -> tuple[str, int]:
    """
    Llama a Gemini 1.5 Pro con el prompt ya construido por _construir_prompt().
    Agrega la instrucción de formato JSON al final y normaliza la respuesta al
    shape que _merge_veredictos() sabe parsear.

    Retorna (json_respuesta, tokens_usados).
    Ante cualquier fallo de API o respuesta inválida retorna ("", 0|tokens) —
    loguea a stderr y nunca lanza excepción (PASO 6 no debe tumbar el pipeline).
    """
    if not prompt:
        return "", 0

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[_llamar_modelo] GEMINI_API_KEY no está definida en el entorno.",
              file=sys.stderr)
        return "", 0

    url    = GEMINI_ENDPOINT.format(model=GEMINI_MODEL) + f"?key={api_key}"
    cuerpo = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt + _INSTRUCCION_FORMATO_JSON}]}
        ],
        "generationConfig": {
            "temperature":        0.0,
            "response_mime_type": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data    = json.dumps(cuerpo).encode("utf-8"),
        method  = "POST",
        headers = {"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT_S,
                                    context=_contexto_ssl()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalle = ""
        try:
            detalle = exc.read().decode("utf-8", "replace")
        except Exception:
            pass
        print(f"[_llamar_modelo] HTTPError {exc.code} de Gemini: {detalle[:500]}",
              file=sys.stderr)
        return "", 0
    except Exception as exc:
        print(f"[_llamar_modelo] Error al llamar a Gemini: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return "", 0

    tokens      = _extraer_tokens(payload)
    normalizado = _normalizar_respuesta(_extraer_texto(payload))
    if normalizado is None:
        print("[_llamar_modelo] Respuesta del modelo no es JSON válido; se ignora.",
              file=sys.stderr)
        return "", tokens

    return normalizado, tokens


def _merge_veredictos(
    criterios:        list[ResultadoConfianza],
    respuesta_modelo: str,
    ids_delegados:    set[str],
) -> list[ResultadoConfianza]:
    """
    Actualiza los criterios delegados con los veredictos del modelo.
    Si la respuesta no es JSON válido (ej. stub), los delegados conservan
    su veredicto de confidence_engine sin modificación.
    """
    evaluaciones: dict[str, dict] = {}
    try:
        parsed = json.loads(respuesta_modelo)
        for ev in parsed.get("evaluaciones", []):
            cid = str(ev.get("criterio", "")).strip()
            if cid:
                evaluaciones[cid] = ev
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    for rc in criterios:
        if rc.criterio not in ids_delegados:
            continue
        ev = evaluaciones.get(rc.criterio)
        if ev:
            try:
                rc.veredicto = Severidad(str(ev.get("veredicto", "")).upper())
            except ValueError:
                pass
            razon_modelo = str(ev.get("razon", "")).strip()
            if razon_modelo:
                rc.razon = f"[MODELO] {razon_modelo}"
        else:
            rc.razon = f"{rc.razon} | [MODELO] Sin respuesta para este criterio."

    return criterios


# ──────────────────────────────────────────────
# HELPERS — RESUMEN
# ──────────────────────────────────────────────

def _construir_resumen_ejecutivo(
    veredicto_global: Severidad,
    criterios:        list[ResultadoConfianza],
    mandatory:        ResultadoPipeline,
    n_codigo:         int,
    n_delegados:      int,
) -> str:
    graves  = [c for c in criterios if c.veredicto == Severidad.GRAVE]
    obs     = [c for c in criterios if c.veredicto == Severidad.OBSERVACION]
    no_cal  = [c for c in criterios if c.veredicto == Severidad.NO_CALIFICA]

    partes = [f"VEREDICTO GLOBAL: {veredicto_global.value}"]
    if graves:
        partes.append(f"GRAVES ({len(graves)}): " + " | ".join(c.criterio for c in graves))
    if obs:
        partes.append(f"OBSERVACIONES ({len(obs)}): " + " | ".join(c.criterio for c in obs))
    if no_cal:
        partes.append(f"NO CALIFICA ({len(no_cal)}): " + " | ".join(c.criterio for c in no_cal))
    partes.append(f"código={n_codigo} | modelo={n_delegados}")
    if not mandatory.puede_continuar:
        partes.append("MANDATORY bloqueó el pipeline")

    return " | ".join(partes)


# ──────────────────────────────────────────────
# ENGINE PRINCIPAL
# ──────────────────────────────────────────────

def ejecutar(
    imagen_path:    Optional[str],
    etapa_activa:   str,
    tipo_foto:      Optional[str] = None,
    metadata_extra: Optional[dict] = None,
    config:         Optional[ConfigPipeline] = None,
) -> ResultadoFinal:
    """
    Ejecuta el pipeline completo de verificación visual.

    Args:
        imagen_path:    Ruta a la imagen. None si no hay imagen disponible.
        etapa_activa:   ID de la etapa de campaña vigente (ej. "verano_2025").
        tipo_foto:      Tipo de foto conocido por el usuario. Sobreescribe la detección
                        automática de photo_analyzer.
        metadata_extra: Metadatos adicionales o de sobreescritura. En tests permite
                        inyectar metadata sin necesitar PIL/numpy.
        config:         Configuración agregada de todos los motores.
    """
    if config is None:
        config = ConfigPipeline()

    # ── PASO 0: preparar metadata ──────────────────────────────────
    metadata          = _preparar_metadata(imagen_path, etapa_activa, tipo_foto, metadata_extra)
    tipo_foto_efectivo = metadata.get("tipo_foto")

    # ── PASO 1: mandatory — reglas duras ──────────────────────────
    mandatory = mandatory_engine.ejecutar(metadata, config.config_mandatory)

    if not mandatory.puede_continuar:
        return ResultadoFinal(
            veredicto_global               = Severidad.GRAVE,
            criterios                      = [],
            resumen_ejecutivo              = f"Pipeline detenido en PASO 1 (mandatory). {mandatory.resumen}",
            puede_continuar                = False,
            tokens_modelo_usados           = 0,
            criterios_decididos_por_codigo = 0,
            criterios_delegados_a_modelo   = 0,
        )

    # ── PASO 2: retrieval — evidencia del knowledge base ──────────
    criterios_ids   = _extraer_criterios_del_knowledge(config.config_retrieval, tipo_foto_efectivo)
    mandatory_extras = _criterios_mandatory_solo_codigo(mandatory, set(criterios_ids))
    retrieval_list = retrieval_engine.buscar_lote(
        criterios           = criterios_ids,
        resultado_mandatory = mandatory,
        tipo_foto           = tipo_foto_efectivo,
        config              = config.config_retrieval,
    )
    retrieval_por_criterio = {r.criterio: r for r in retrieval_list}

    # ── PASO 3: confidence — calibrar confianza ───────────────────
    confianza_list = confidence_engine.evaluar_lote(
        resultados_retrieval = retrieval_list,
        resultado_mandatory  = mandatory,
        config               = config.config_confianza,
    )

    # ── PASO 4: separar criterios por destino ─────────────────────
    delegados    = [c for c in confianza_list if c.delegar_a_modelo]
    no_delegados = [c for c in confianza_list if not c.delegar_a_modelo]

    # ── PASO 5: construir prompt ───────────────────────────────────
    prompt = _construir_prompt(delegados, retrieval_por_criterio, metadata)

    # ── PASO 6: llamar al modelo ───────────────────────────────────
    respuesta_modelo, tokens_modelo = _llamar_modelo(prompt)

    # ── PASO 7: merge — código + modelo ───────────────────────────
    criterios_finales = _merge_veredictos(
        criterios        = confianza_list,
        respuesta_modelo = respuesta_modelo,
        ids_delegados    = {c.criterio for c in delegados},
    )

    # ── PASO 8: resultado final ────────────────────────────────────
    criterios_finales = criterios_finales + mandatory_extras
    veredicto_global  = _calcular_veredicto_global(criterios_finales, mandatory)
    n_codigo          = len(no_delegados) + len(mandatory_extras)
    n_delegados       = len(delegados)

    return ResultadoFinal(
        veredicto_global               = veredicto_global,
        criterios                      = criterios_finales,
        resumen_ejecutivo              = _construir_resumen_ejecutivo(
            veredicto_global, criterios_finales, mandatory, n_codigo, n_delegados
        ),
        puede_continuar                = True,
        tokens_modelo_usados           = tokens_modelo,
        criterios_decididos_por_codigo = n_codigo,
        criterios_delegados_a_modelo   = n_delegados,
    )


# ──────────────────────────────────────────────
# TESTS RÁPIDOS
# Sin imagen real — metadata_extra inyecta los valores directamente.
# Retrieval y confidence dependen de knowledge/ en disco.
# ──────────────────────────────────────────────

if __name__ == "__main__":

    def _imprimir(label: str, r: ResultadoFinal) -> None:
        print(f"\n{'='*65}")
        print(f"CASO: {label}")
        print(f"{'='*65}")
        print(f"  veredicto_global:    {r.veredicto_global.value}")
        print(f"  puede_continuar:     {r.puede_continuar}")
        print(f"  criterios código:    {r.criterios_decididos_por_codigo}")
        print(f"  criterios modelo:    {r.criterios_delegados_a_modelo}")
        print(f"  tokens modelo:       {r.tokens_modelo_usados}")
        print(f"  resumen_ejecutivo:   {r.resumen_ejecutivo}")
        if r.criterios:
            print("  criterios:")
            for c in r.criterios:
                delegado = "→ modelo" if c.delegar_a_modelo else "→ código"
                print(f"    [{c.veredicto.value:<12}][{c.confianza.value:<5}] {c.criterio:<25} {delegado}")

    # ── Caso 1: mandatory bloquea por imagen oscura ───────────────
    _imprimir(
        "PASO 1 bloqueado — imagen oscura (brillo=15)",
        ejecutar(
            imagen_path    = None,
            etapa_activa   = "verano_2025",
            tipo_foto      = "focal_show",
            metadata_extra = {
                "brillo": 15,
                "nitidez": 80,
                "espacio_vacio_pct": 25,
                "grafico_detectado": "verano_2025",
            },
        ),
    )

    # ── Caso 2: foto bien armada — pipeline completo ──────────────
    _imprimir(
        "Happy path — focal bien armado",
        ejecutar(
            imagen_path    = None,
            etapa_activa   = "verano_2025",
            tipo_foto      = "focal_show",
            metadata_extra = {
                "brillo": 120,
                "nitidez": 85,
                "espacio_vacio_pct": 25,
                "grafico_detectado": "verano_2025",
            },
        ),
    )

    # ── Caso 3: gráfico de etapa incorrecto — GRAVE sin bloqueo ──
    _imprimir(
        "Gráfico de etapa incorrecta — GRAVE sin bloqueo",
        ejecutar(
            imagen_path    = None,
            etapa_activa   = "verano_2025",
            tipo_foto      = "focal_show",
            metadata_extra = {
                "brillo": 120,
                "nitidez": 85,
                "espacio_vacio_pct": 25,
                "grafico_detectado": "primavera_2024",  # etapa incorrecta
            },
        ),
    )

    # ── Caso 4: espacio vacío excesivo — GRAVE sin bloqueo ───────
    _imprimir(
        "Espacio vacío excesivo — GRAVE sin bloqueo",
        ejecutar(
            imagen_path    = None,
            etapa_activa   = "verano_2025",
            tipo_foto      = "focal_show",
            metadata_extra = {
                "brillo": 115,
                "nitidez": 88,
                "espacio_vacio_pct": 75,
                "grafico_detectado": "verano_2025",
            },
        ),
    )

    # ── Caso 5: tipo_foto desconocido — Capa3 no disponible ──────
    _imprimir(
        "Tipo foto desconocido — sin Capa3",
        ejecutar(
            imagen_path    = None,
            etapa_activa   = "verano_2025",
            tipo_foto      = None,
            metadata_extra = {
                "brillo": 110,
                "nitidez": 80,
                "espacio_vacio_pct": 30,
            },
        ),
    )

    # ──────────────────────────────────────────────────────────────
    # TEST DE INTEGRACIÓN — Caso 3 contra el modelo real (Gemini 1.5 Pro)
    # Requiere GEMINI_API_KEY en el entorno. Sin la key, _llamar_modelo
    # loguea a stderr y degrada de forma controlada (los criterios
    # delegados conservan su veredicto de confidence_engine).
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'#'*65}")
    print("# TEST DE INTEGRACIÓN — Caso 3 con modelo real")
    print(f"# GEMINI_API_KEY presente: {'sí' if os.environ.get('GEMINI_API_KEY') else 'NO'}")
    print(f"{'#'*65}")

    resultado_int = ejecutar(
        imagen_path    = None,
        etapa_activa   = "verano_2025",
        tipo_foto      = "focal_show",
        metadata_extra = {
            "brillo": 120,
            "nitidez": 85,
            "espacio_vacio_pct": 25,
            "grafico_detectado": "primavera_2024",  # gráfico de etapa incorrecta
        },
    )

    print(f"\n  veredicto_global:    {resultado_int.veredicto_global.value}")
    print(f"  puede_continuar:     {resultado_int.puede_continuar}")
    print(f"  criterios código:    {resultado_int.criterios_decididos_por_codigo}")
    print(f"  criterios modelo:    {resultado_int.criterios_delegados_a_modelo}")
    print(f"  tokens modelo:       {resultado_int.tokens_modelo_usados}")
    print(f"  resumen_ejecutivo:   {resultado_int.resumen_ejecutivo}")
    print("\n  DETALLE POR CRITERIO (incluye razones del modelo):")
    for c in resultado_int.criterios:
        destino = "→ modelo" if c.delegar_a_modelo else "→ código"
        print(f"\n    [{c.veredicto.value:<12}][{c.confianza.value:<5}] "
              f"{c.criterio:<25} {destino}")
        print(f"      fuente:  {c.fuente_dominante} ({c.peso_dominante.value})")
        print(f"      razón:   {c.razon}")
