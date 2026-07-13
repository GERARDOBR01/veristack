"""
correr_stress_fase2.py — Stress de código Fase 2 (Sesión HH).

Sangra los módulos que la Fase FF nunca tocó: retrieval/knowledge (CR-2),
merge PASO_7 (CR-3/H1 + respuestas hostiles del modelo), confidence_engine
y el ciclo de lotes contra keys muertas (H3/H5).

100% offline: guard anti-red global (urllib.request.urlopen interceptado),
GEMINI_API_KEY fuera del entorno, time.sleep mockeado en el grupo B.
Producción solo se LEE; las copias rotas viven en fixtures/ de esta carpeta.

Uso:  python correr_stress_fase2.py
Salida: resultados/resultados.json + resumen por consola.
Las expectativas por caso están en EXPECTATIVAS.md (escritas ANTES de correr).
"""

import io
import json
import os
import shutil
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
sys.path.insert(0, str(REPO / "core"))

# El modelo debe quedar deshabilitado fuera de los mocks del grupo B.
os.environ.pop("GEMINI_API_KEY", None)

import pipeline                                    # noqa: E402
import confidence_engine                           # noqa: E402
from confidence_engine import ResultadoConfianza   # noqa: E402
from mandatory_engine import ResultadoPipeline, Severidad  # noqa: E402
from retrieval_engine import (                     # noqa: E402
    Confianza, ConfigRetrieval, Peso, ResultadoRetrieval,
)
from pipeline import ConfigPipeline               # noqa: E402

FIXTURES    = AQUI / "fixtures"
RESULTADOS  = AQUI / "resultados"
KNOW_REAL   = REPO / "pipeline" / "knowledge"
KNOW_OK     = FIXTURES / "knowledge_ok"
KNOW_ROTO   = FIXTURES / "knowledge_roto"

# ──────────────────────────────────────────────
# GUARD ANTI-RED GLOBAL
# Todo urlopen pasa por aquí. Sin mock autorizado → cuenta y revienta.
# ──────────────────────────────────────────────

_urlopen_real = urllib.request.urlopen
GUARD = {"no_autorizados": 0, "mock": None, "llamadas_mock": 0}


def _urlopen_guard(*args, **kwargs):
    if GUARD["mock"] is not None:
        GUARD["llamadas_mock"] += 1
        return GUARD["mock"](*args, **kwargs)
    GUARD["no_autorizados"] += 1
    raise RuntimeError("GUARD ANTI-RED: intento de salida no autorizado")


urllib.request.urlopen = _urlopen_guard


class MockRed:
    """Context manager: autoriza un mock de urlopen solo dentro del bloque."""

    def __init__(self, fn):
        self.fn = fn

    def __enter__(self):
        GUARD["mock"] = self.fn
        GUARD["llamadas_mock"] = 0
        return self

    def __exit__(self, *a):
        GUARD["mock"] = None
        return False


def _http_429(url):
    return urllib.error.HTTPError(
        url, 429, "Too Many Requests", {},
        io.BytesIO(b'{"error": {"status": "RESOURCE_EXHAUSTED"}}'),
    )


class _RespuestaOK:
    """Respuesta 200 de Gemini con evaluaciones inyectadas."""

    def __init__(self, evaluaciones):
        payload = {
            "candidates": [{"content": {"parts": [
                {"text": json.dumps({"evaluaciones": evaluaciones}, ensure_ascii=False)}
            ]}}],
            "usageMetadata": {"totalTokenCount": 100},
        }
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ──────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────

JSON_ROTO = '{ "criterios": [ este json está roto a propósito'

DECOY = {
    "schema_version": "1.1",
    "criterios": [{
        "id": "criterio_decoy_traversal",
        "aliases": [],
        "texto": "DECOY: si este criterio aparece en el resultado, el path traversal cargó un archivo fuera de knowledge/.",
        "peso": "MANDATORY",
        "aplica_a": None,
    }],
}

CAPA_BASURA = {
    "schema_version": "1.1",
    "criterios": [
        {"id": 12345, "texto": "id numérico", "peso": "MANDATORY"},
        {"id": "texto_none", "texto": None, "peso": "MANDATORY"},
        {"id": "aliases_dict", "aliases": {"a": 1}, "texto": "aliases no-lista", "peso": "MANDATORY"},
        {"id": "peso_basura", "texto": "peso inválido", "peso": "MUYGRAVE"},
        {"id": "etapa_basura", "texto": "etapa_aplicable no normalizable", "peso": "MANDATORY",
         "etapa_aplicable": "esto-no-es-lista"},
        "esto no es un dict",
        {"id": "criterio_sano", "aliases": ["sano"], "texto": "el único criterio sano de esta capa",
         "peso": "MANDATORY", "aplica_a": None},
    ],
}


def preparar_fixtures():
    for d in (KNOW_OK, KNOW_ROTO, RESULTADOS):
        d.mkdir(parents=True, exist_ok=True)
    for nombre in ("capa1_display_basics.json", "capa2_campana_activa.json",
                   "capa3_focal_show.json"):
        origen = KNOW_REAL / nombre
        if not origen.exists():
            raise SystemExit(f"FALTA knowledge real: {origen} — abortando (no se inventa nada)")
        shutil.copy2(origen, KNOW_OK / nombre)
        (KNOW_ROTO / nombre).write_text(JSON_ROTO, encoding="utf-8")
    (FIXTURES / "decoy.json").write_text(
        json.dumps(DECOY, ensure_ascii=False, indent=2), encoding="utf-8")
    (FIXTURES / "capa_basura.json").write_text(
        json.dumps(CAPA_BASURA, ensure_ascii=False, indent=2), encoding="utf-8")


def config_con(knowledge_dir: Path) -> ConfigPipeline:
    cfg = ConfigPipeline()
    cfg.config_retrieval = ConfigRetrieval(
        ruta_capa1          = str(knowledge_dir / "capa1_display_basics.json"),
        ruta_capa2          = str(knowledge_dir / "capa2_campana_activa.json"),
        ruta_capa3_template = str(knowledge_dir / "capa3_{tipo_foto}.json"),
    )
    return cfg


# ──────────────────────────────────────────────
# INFRA DE CASOS
# ──────────────────────────────────────────────

CASOS: list[dict] = []


def caso(id_, descripcion, fn):
    print(f"\n{'=' * 70}\n[{id_}] {descripcion}\n{'=' * 70}")
    registro = {"id": id_, "descripcion": descripcion, "crash": False}
    try:
        registro.update(fn() or {})
    except Exception as exc:
        registro["crash"] = True
        registro["excepcion"] = f"{type(exc).__name__}: {exc}"
        registro["traceback"] = traceback.format_exc(limit=4)
        print(f"  CRASH: {registro['excepcion']}")
    CASOS.append(registro)
    return registro


def resumen_resultado(r) -> dict:
    nombres = [c.criterio for c in r.criterios]
    return {
        "veredicto":  r.veredicto_global.value,
        "n_criterios": len(r.criterios),
        "codigo":     r.criterios_decididos_por_codigo,
        "modelo":     r.criterios_delegados_a_modelo,
        "versiones_capas": r.versiones_capas,
        "resumen_inicio":  r.resumen_ejecutivo[:200],
        "criterios_mandatory_visibles": [
            n for n in nombres
            if n in {"etapa_no_definida", "grafico_no_detectado",
                     "grafico_etapa_no_verificable", "tipo_foto_desconocido",
                     "archivo_invalido"}
        ],
    }


META_SANA_E1 = {"grafico_detectado": "Gran Barata"}
CAMPANA = "gran_barata_pv2026"


def rc_delegado(nombre: str) -> ResultadoConfianza:
    return ResultadoConfianza(
        criterio         = nombre,
        veredicto        = Severidad.CUMPLE,     # preliminar de confidence
        confianza        = Confianza.ALTO,
        fuente_dominante = "CAPA2",
        peso_dominante   = Peso.MANDATORY,
        delegar_a_modelo = True,
        razon            = "preliminar — juicio visual delegado",
    )


# ──────────────────────────────────────────────
# GRUPO R — knowledge roto (CR-2)
# ──────────────────────────────────────────────

def r0_baseline():
    r = pipeline.ejecutar(None, "E1", "focal_show",
                          metadata_extra=dict(META_SANA_E1),
                          config=config_con(KNOW_OK))
    out = resumen_resultado(r)
    print(f"  veredicto={out['veredicto']}  criterios={out['n_criterios']}")
    return out


def r1_capa2_rota():
    mix = FIXTURES / "knowledge_capa2_rota"
    mix.mkdir(exist_ok=True)
    shutil.copy2(KNOW_OK / "capa1_display_basics.json", mix / "capa1_display_basics.json")
    shutil.copy2(KNOW_OK / "capa3_focal_show.json",     mix / "capa3_focal_show.json")
    (mix / "capa2_campana_activa.json").write_text(JSON_ROTO, encoding="utf-8")

    r = pipeline.ejecutar(None, "E1", "focal_show",
                          metadata_extra=dict(META_SANA_E1),
                          config=config_con(mix))
    out = resumen_resultado(r)
    texto_visible = (r.resumen_ejecutivo + " ".join(c.razon for c in r.criterios)).lower()
    out["traza_visible_del_fallo"] = any(
        t in texto_visible for t in ("capa2", "knowledge", "corrupt", "no se pudo cargar"))
    print(f"  veredicto={out['veredicto']}  criterios={out['n_criterios']} "
          f"(baseline={CASOS[0].get('n_criterios')})  "
          f"traza_visible={out['traza_visible_del_fallo']}  "
          f"versiones_capas={out['versiones_capas']}")
    return out


def r2a_tres_rotas_mandatory_cumple():
    r = pipeline.ejecutar(None, CAMPANA, "focal_show",
                          metadata_extra={"grafico_detectado": CAMPANA},
                          config=config_con(KNOW_ROTO))
    out = resumen_resultado(r)
    out["cumple_fantasma"] = (out["veredicto"] == "CUMPLE" and out["n_criterios"] == 0)
    print(f"  veredicto={out['veredicto']}  criterios={out['n_criterios']}  "
          f"CUMPLE_FANTASMA={out['cumple_fantasma']}")
    print(f"  resumen: {out['resumen_inicio']}")
    return out


def r2b_tres_rotas_no_califica():
    r = pipeline.ejecutar(None, "E1", "focal_show",
                          metadata_extra=dict(META_SANA_E1),
                          config=config_con(KNOW_ROTO))
    out = resumen_resultado(r)
    texto = (r.resumen_ejecutivo + " ".join(c.razon for c in r.criterios)).lower()
    out["causa_knowledge_visible"] = any(t in texto for t in ("capa", "knowledge", "corrupt"))
    print(f"  veredicto={out['veredicto']}  criterios={out['n_criterios']}  "
          f"causa_knowledge_visible={out['causa_knowledge_visible']}")
    return out


def r3_path_traversal():
    tipo_hostil = "x/../../decoy"
    r = pipeline.ejecutar(None, None, tipo_hostil,
                          metadata_extra={"grafico_detectado": None},
                          config=config_con(KNOW_OK))
    out = resumen_resultado(r)
    out["decoy_cargado"] = any(c.criterio == "criterio_decoy_traversal" for c in r.criterios)
    print(f"  veredicto={out['veredicto']}  criterios={out['n_criterios']}  "
          f"DECOY_CARGADO={out['decoy_cargado']}")
    return out


def r4_capa_basura():
    mix = FIXTURES / "knowledge_capa1_basura"
    mix.mkdir(exist_ok=True)
    shutil.copy2(FIXTURES / "capa_basura.json", mix / "capa1_display_basics.json")
    shutil.copy2(KNOW_OK / "capa2_campana_activa.json", mix / "capa2_campana_activa.json")
    shutil.copy2(KNOW_OK / "capa3_focal_show.json",     mix / "capa3_focal_show.json")

    r = pipeline.ejecutar(None, "E1", "focal_show",
                          metadata_extra=dict(META_SANA_E1),
                          config=config_con(mix))
    out = resumen_resultado(r)
    nombres = {c.criterio for c in r.criterios}
    out["criterio_sano_presente"]  = "criterio_sano" in nombres
    out["basura_filtrada"]         = "12345" not in nombres
    print(f"  veredicto={out['veredicto']}  criterios={out['n_criterios']}  "
          f"sano={out['criterio_sano_presente']}  basura_fuera={out['basura_filtrada']}")
    return out


# ──────────────────────────────────────────────
# GRUPO M — merge PASO_7 (CR-3/H1 + modelo hostil)
# ──────────────────────────────────────────────

def m1_no_califica_invisible():
    r = pipeline.ejecutar(None, "E1", "focal_show",
                          metadata_extra=dict(META_SANA_E1),
                          config=config_con(KNOW_OK))
    out = resumen_resultado(r)
    out["mandatory_no_califica_en_criterios"] = bool(out["criterios_mandatory_visibles"])
    out["mencion_en_resumen"] = "grafico_etapa_no_verificable" in r.resumen_ejecutivo
    print(f"  veredicto={out['veredicto']}  "
          f"NO_CALIFICA de mandatory visible en criterios={out['mandatory_no_califica_en_criterios']}  "
          f"en resumen={out['mencion_en_resumen']}")
    return out


def m2_veredicto_malformado():
    rc = rc_delegado("planchado_prendas")
    respuesta = json.dumps({"evaluaciones": [
        {"criterio": "planchado_prendas", "veredicto": "Cumple ✓", "razon": "se ve impecable"},
    ]}, ensure_ascii=False)
    pipeline._merge_veredictos([rc], respuesta, {"planchado_prendas"})
    out = {
        "veredicto_final": rc.veredicto.value,
        "razon":           rc.razon,
        "cumple_fantasma": rc.veredicto == Severidad.CUMPLE,
    }
    print(f"  veredicto={out['veredicto_final']}  CUMPLE_FANTASMA={out['cumple_fantasma']}")
    print(f"  razon: {rc.razon[:120]}")
    return out


def m3_criterio_inventado():
    rc_del  = rc_delegado("criterio_delegado")
    rc_fijo = rc_delegado("criterio_de_codigo")
    rc_fijo.delegar_a_modelo = False
    rc_fijo.veredicto        = Severidad.GRAVE
    respuesta = json.dumps({"evaluaciones": [
        {"criterio": "criterio_inventado_por_modelo", "veredicto": "GRAVE", "razon": "invento"},
        {"criterio": "criterio_de_codigo", "veredicto": "CUMPLE", "razon": "intento de pisar un GRAVE"},
        {"criterio": "criterio_delegado", "veredicto": "OBSERVACION", "razon": "real"},
    ]})
    merged = pipeline._merge_veredictos([rc_del, rc_fijo], respuesta, {"criterio_delegado"})
    out = {
        "grave_de_codigo_intacto":  rc_fijo.veredicto == Severidad.GRAVE,
        "inventado_ignorado":       all(c.criterio != "criterio_inventado_por_modelo" for c in merged),
        "delegado_actualizado":     rc_del.veredicto == Severidad.OBSERVACION,
    }
    print(f"  GRAVE intacto={out['grave_de_codigo_intacto']}  "
          f"inventado ignorado={out['inventado_ignorado']}  "
          f"delegado ok={out['delegado_actualizado']}")
    return out


def m4_duplicados():
    rc = rc_delegado("criterio_x")
    respuesta = json.dumps({"evaluaciones": [
        {"criterio": "criterio_x", "veredicto": "CUMPLE", "razon": "primera"},
        {"criterio": "criterio_x", "veredicto": "GRAVE",  "razon": "segunda"},
    ]})
    pipeline._merge_veredictos([rc], respuesta, {"criterio_x"})
    out = {"veredicto_final": rc.veredicto.value, "gana_ultima": rc.veredicto == Severidad.GRAVE}
    print(f"  veredicto={out['veredicto_final']} (esperado: la última gana)")
    return out


def m5_modelo_crea_grave():
    rc = rc_delegado("criterio_visual")
    respuesta = json.dumps({"evaluaciones": [
        {"criterio": "criterio_visual", "veredicto": "GRAVE", "razon": "incumplimiento visible"},
    ]})
    pipeline._merge_veredictos([rc], respuesta, {"criterio_visual"})
    out = {"veredicto_final": rc.veredicto.value,
           "modelo_puede_crear_grave": rc.veredicto == Severidad.GRAVE}
    print(f"  veredicto={out['veredicto_final']} (diseño: crear GRAVE visual sí; pisar GRAVE de código no)")
    return out


# ──────────────────────────────────────────────
# GRUPO C — confidence_engine
# ──────────────────────────────────────────────

MANDATORY_OK = ResultadoPipeline(
    veredicto_final=Severidad.CUMPLE, puede_continuar=True, resumen="ok")


def c1_retrieval_inconsistente():
    r = ResultadoRetrieval(criterio="x", evidencias=[], sin_evidencia=False)
    try:
        confidence_engine.evaluar(r, MANDATORY_OK)
        return {"crash_interno": False}
    except IndexError as exc:
        print(f"  IndexError confirmado: {exc}")
        return {"crash_interno": True, "excepcion": f"IndexError: {exc}"}


def c2_lote_mixto():
    valido = ResultadoRetrieval(criterio="ok", evidencias=[], sin_evidencia=True)
    lote = confidence_engine.evaluar_lote([valido, {"a": 1}, None, 42], MANDATORY_OK)
    out = {"evaluados": len(lote), "solo_el_valido": len(lote) == 1}
    print(f"  evaluados={out['evaluados']} (esperado 1)")
    return out


def c3_no_aplica_directo():
    r = ResultadoRetrieval(criterio="parche_segunda_etapa", sin_evidencia=True, no_aplica=True)
    res = confidence_engine.evaluar(r, MANDATORY_OK)
    out = {"veredicto": res.veredicto.value, "razon": res.razon[:80]}
    print(f"  NO_APLICA evaluado directo → {out['veredicto']} ('{out['razon']}')")
    return out


# ──────────────────────────────────────────────
# GRUPO B — lotes contra keys muertas (H3/H5)
# ──────────────────────────────────────────────

def _con_keys_falsas_y_sleep_contado(fn):
    """Ejecuta fn con 3 keys falsas y time.sleep contado (sin dormir)."""
    sleeps = {"n": 0, "total_s": 0.0}
    cargar_real, sleep_real = pipeline._cargar_claves_api, time.sleep

    def _sleep_falso(s):
        sleeps["n"] += 1
        sleeps["total_s"] += s

    pipeline._cargar_claves_api = lambda: ["k1", "k2", "k3"]
    time.sleep = _sleep_falso
    try:
        resultado = fn()
    finally:
        pipeline._cargar_claves_api = cargar_real
        time.sleep = sleep_real
    return resultado, sleeps


def _correr_lotes(n_delegados, mock):
    delegados = [rc_delegado(f"criterio_{i:03d}") for i in range(n_delegados)]
    with MockRed(mock):
        (respuesta, tokens), sleeps = _con_keys_falsas_y_sleep_contado(
            lambda: pipeline._evaluar_delegados_en_lotes(
                delegados, {}, {"tipo_foto": "focal_show", "etapa_activa": "E1"}, None))
        requests = GUARD["llamadas_mock"]
    merged = pipeline._merge_veredictos(
        delegados, respuesta or "", {c.criterio for c in delegados})
    return delegados, merged, respuesta, requests, sleeps


def b1_todas_muertas():
    def mock(req, timeout=None, context=None):
        raise _http_429(req.full_url)

    delegados, merged, respuesta, requests, sleeps = _correr_lotes(45, mock)
    no_cal = sum(1 for c in merged if c.veredicto == Severidad.NO_CALIFICA)
    out = {
        "lotes": 3, "requests_totales": requests,
        "requests_tras_saber_keys_muertas": max(0, requests - 3),
        "sleeps": sleeps, "criterios_no_califica": no_cal,
        "razon_distingue_cuota": all(
            "Sin respuesta" in c.veredicto.value or "Sin respuesta" in c.razon
            for c in merged),
    }
    print(f"  requests={requests} (3 bastaban para saberlo)  "
          f"sleeps={sleeps['n']} ({sleeps['total_s']}s)  NO_CALIFICA={no_cal}/45")
    return out


def b2_mueren_a_mitad():
    estado = {"llamada": 0}
    evaluaciones_lote1 = [
        {"criterio": f"criterio_{i:03d}", "veredicto": "OBSERVACION", "razon": "real"}
        for i in range(15)
    ]

    def mock(req, timeout=None, context=None):
        estado["llamada"] += 1
        if estado["llamada"] == 1:
            return _RespuestaOK(evaluaciones_lote1)
        raise _http_429(req.full_url)

    delegados, merged, respuesta, requests, sleeps = _correr_lotes(45, mock)
    reales  = sum(1 for c in merged if c.veredicto == Severidad.OBSERVACION)
    de_cuota = sum(1 for c in merged if c.veredicto == Severidad.NO_CALIFICA)
    out = {
        "requests_totales": requests,
        "requests_desperdiciados_lotes_2_3": requests - 1,
        "sleeps": sleeps,
        "veredictos_reales": reales,
        "no_califica_por_cuota": de_cuota,
        "resultado_parcial_marcado_en_resultadofinal": False,  # no existe el campo
    }
    print(f"  requests={requests} (1 útil + {requests - 1} contra keys muertas)  "
          f"reales={reales}  NO_CALIFICA por cuota={de_cuota} — mezclados sin distinción global")
    return out


def b3_escala_benchmark():
    def mock(req, timeout=None, context=None):
        raise _http_429(req.full_url)

    _, _, _, requests, sleeps = _correr_lotes(122, mock)
    out = {
        "lotes": 9, "requests_por_foto": requests,
        "sleep_por_foto_s": sleeps["total_s"],
        "proyeccion_25_fotos": {
            "requests": requests * 25,
            "sleep_min": round(sleeps["total_s"] * 25 / 60, 1),
        },
    }
    print(f"  por foto: {requests} requests + {sleeps['total_s']}s dormidos  "
          f"→ 25 fotos: {requests * 25} requests + {out['proyeccion_25_fotos']['sleep_min']} min dormidos")
    return out


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main() -> int:
    preparar_fixtures()

    caso("R0", "Baseline — knowledge intacto, E1 + focal_show", r0_baseline)
    caso("R1", "CR-2: capa2 con JSON roto — ¿corrida 'normal' amputada en silencio?", r1_capa2_rota)
    caso("R2a", "CR-2: las 3 capas rotas + mandatory todo CUMPLE — ¿CUMPLE fantasma?", r2a_tres_rotas_mandatory_cumple)
    caso("R2b", "CR-2: las 3 capas rotas + etapa E1 — variante NO_CALIFICA", r2b_tres_rotas_no_califica)
    caso("R3", "Path traversal en tipo_foto → ¿carga knowledge fuera de knowledge/?", r3_path_traversal)
    caso("R4", "Capa con entradas basura — coerciones de retrieval", r4_capa_basura)

    caso("M1", "CR-3/H1: NO_CALIFICA de mandatory invisible en ResultadoFinal", m1_no_califica_invisible)
    caso("M2", "Modelo responde veredicto malformado → ¿CUMPLE fantasma?", m2_veredicto_malformado)
    caso("M3", "Modelo inventa criterios / intenta pisar GRAVE de código", m3_criterio_inventado)
    caso("M4", "Modelo duplica evaluaciones del mismo criterio", m4_duplicados)
    caso("M5", "Modelo crea un GRAVE de juicio visual (diseño)", m5_modelo_crea_grave)

    caso("C1", "ResultadoRetrieval inconsistente (evidencias=[] + sin_evidencia=False)", c1_retrieval_inconsistente)
    caso("C2", "evaluar_lote con lista mixta de tipos", c2_lote_mixto)
    caso("C3", "no_aplica=True evaluado directo (semántica NO_APLICA vs NO_CALIFICA)", c3_no_aplica_directo)

    caso("B1", "H3: 3 lotes contra 3 keys muertas desde el arranque", b1_todas_muertas)
    caso("B2", "H3: keys mueren tras el lote 1 — resultado parcial sin marca", b2_mueren_a_mitad)
    caso("B3", "H3: escala benchmark (122 delegados, 9 lotes) — el costo del no-breaker", b3_escala_benchmark)

    print(f"\n{'=' * 70}")
    print(f"GUARD ANTI-RED: intentos no autorizados = {GUARD['no_autorizados']} (esperado 0)")
    crashes = [c["id"] for c in CASOS if c.get("crash")]
    print(f"CASOS: {len(CASOS)} | crashes no controlados: {crashes or 'ninguno'}")

    salida = {
        "sesion": "HH — stress fase 2 (retrieval/merge/confidence/lotes)",
        "guard_red_no_autorizados": GUARD["no_autorizados"],
        "casos": CASOS,
    }
    (RESULTADOS / "resultados.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"Resultados -> {RESULTADOS / 'resultados.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
