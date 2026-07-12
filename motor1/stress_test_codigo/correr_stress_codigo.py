"""
correr_stress_codigo.py — Stress test de CÓDIGO (sin modelo) contra Motor 1.

Contraparte sin-IA del stress test del 11 Jul. Ejecuta los casos de
EXPECTATIVAS.md contra pipeline.ejecutar() real con fixtures sintéticos.

Garantías de cero tokens (por construcción, no por confianza):
  1. GEMINI_API_KEY se remueve del entorno del proceso → _cargar_claves_api()
     retorna [] y _post_gemini ni siquiera intenta la red.
  2. urllib.request.urlopen se reemplaza GLOBALMENTE por un guard que cuenta
     y rechaza cualquier intento de salida (en G1 simula HTTP 429, nunca red real).
  3. time.sleep se reemplaza por un contador: se reporta cuánto HABRÍA dormido.

Producción solo lectura: knowledge corrupto = copias en fixtures/knowledge_roto/.

Uso:  python correr_stress_codigo.py
Salida: resultados/resultados.json + resumen por consola.
"""

import io
import json
import logging
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent.parent
FIXTURES = AQUI / "fixtures"
KROTO = FIXTURES / "knowledge_roto"
KPROD = REPO / "pipeline" / "knowledge"
SALIDA = AQUI / "resultados"

sys.path.insert(0, str(REPO / "pipeline"))
sys.path.insert(0, str(REPO / "core"))

# ── Garantía 1: sin key en el entorno ───────────────────────────────
os.environ.pop("GEMINI_API_KEY", None)

import pipeline                                    # noqa: E402
import photo_analyzer                              # noqa: E402
from mandatory_engine import Severidad             # noqa: E402
from retrieval_engine import ConfigRetrieval       # noqa: E402
from pipeline import ConfigPipeline                # noqa: E402

# ── Garantía 2: guard anti-red global ───────────────────────────────
RED = {"intentos": 0, "modo": "bloquear"}
_urlopen_original = urllib.request.urlopen

def _urlopen_guard(*args, **kwargs):
    RED["intentos"] += 1
    if RED["modo"] == "http429":
        raise urllib.error.HTTPError(
            "https://mock.invalid", 429, "Too Many Requests", {},
            io.BytesIO(b'{"error":{"status":"RESOURCE_EXHAUSTED"}}'))
    raise RuntimeError("GUARD ANTI-RED: intento de salida bloqueado por el stress test")

urllib.request.urlopen = _urlopen_guard

# ── Garantía 3: sleep contado, no dormido ───────────────────────────
SLEEP = {"total_s": 0.0, "llamadas": 0}
_sleep_original = time.sleep

def _sleep_contado(segundos):
    SLEEP["total_s"] += float(segundos)
    SLEEP["llamadas"] += 1

time.sleep = _sleep_contado

# ── Captura de logs (lo único que el motor "dice" cuando degrada) ───
class _CapturaLogs(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.registros: list[str] = []
    def emit(self, record):
        self.registros.append(f"{record.levelname} {record.name} | {record.getMessage()}")

_captura = _CapturaLogs()
logging.getLogger().addHandler(_captura)
logging.getLogger().setLevel(logging.WARNING)


def _config_sana(ruta_capa1=None, ruta_capa2=None, ruta_capa3_tpl=None) -> ConfigPipeline:
    """Como app.py: rutas ABSOLUTAS al knowledge (el default relativo es el bug de Sesión R)."""
    cfg = ConfigPipeline()
    cfg.config_retrieval = ConfigRetrieval(
        ruta_capa1          = str(ruta_capa1 or KPROD / "capa1_display_basics.json"),
        ruta_capa2          = str(ruta_capa2 or KPROD / "capa2_campana_activa.json"),
        ruta_capa3_template = str(ruta_capa3_tpl or KPROD / "capa3_{tipo_foto}.json"),
        etapa_activa        = "E1",
    )
    return cfg


def _resumen_resultado(r) -> dict:
    por_sev = {}
    for c in r.criterios:
        por_sev[c.veredicto.value] = por_sev.get(c.veredicto.value, 0) + 1
    return {
        "veredicto_global":  r.veredicto_global.value,
        "puede_continuar":   r.puede_continuar,
        "n_criterios":       len(r.criterios),
        "criterios_por_severidad": por_sev,
        "decididos_codigo":  r.criterios_decididos_por_codigo,
        "delegados_modelo":  r.criterios_delegados_a_modelo,
        "ids_criterios":     sorted(c.criterio for c in r.criterios),
        "resumen_ejecutivo": r.resumen_ejecutivo,
    }


CASOS: list[dict] = []

def correr_caso(id_caso: str, descripcion: str, fn):
    red0, sleep0 = RED["intentos"], SLEEP["total_s"]
    _captura.registros.clear()
    t0 = time.perf_counter()
    caso = {"id": id_caso, "descripcion": descripcion}
    try:
        caso["observado"] = fn()
        caso["excepcion"] = None
    except Exception as exc:
        caso["observado"] = None
        caso["excepcion"] = {
            "tipo": type(exc).__name__,
            "mensaje": str(exc),
            "traceback_ultima_linea": traceback.format_exc().strip().splitlines()[-3:],
        }
    caso["duracion_s"]        = round(time.perf_counter() - t0, 3)
    caso["intentos_red"]      = RED["intentos"] - red0
    caso["sleep_solicitado_s"] = round(SLEEP["total_s"] - sleep0, 1)
    caso["logs_warning_error"] = list(_captura.registros)
    CASOS.append(caso)
    ex = f" EXCEPCION={caso['excepcion']['tipo']}" if caso["excepcion"] else ""
    print(f"[{id_caso}] {caso['duracion_s']}s red={caso['intentos_red']}{ex}")


def _ejecutar(imagen, etapa="E1", tipo="focal_show", cfg=None):
    r = pipeline.ejecutar(str(imagen) if isinstance(imagen, Path) else imagen,
                          etapa, tipo, config=cfg or _config_sana())
    return _resumen_resultado(r)


# ════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    SALIDA.mkdir(exist_ok=True)

    # ── BASELINE: corrida sana de referencia ─────────────────────────
    correr_caso("BASELINE", "base_valida.png + E1 + focal_show + knowledge real",
                lambda: _ejecutar(FIXTURES / "base_valida.png"))

    # ── B: frontera exacta de brillo ────────────────────────────────
    for t in ("39_0", "39_9", "40_0", "40_1", "41_0"):
        ruta = FIXTURES / f"brillo_{t}.png"
        def _caso_brillo(ruta=ruta):
            facts = photo_analyzer.extract_basic_facts(str(ruta))
            res = _ejecutar(ruta)
            res["brillo_medido_photo_analyzer"] = facts["brightness"]
            res["quality_photo_analyzer"] = facts["quality"]
            return res
        correr_caso(f"B_{t}", f"fixture brillo {t.replace('_', '.')}", _caso_brillo)

    # ── A: archivos rotos ───────────────────────────────────────────
    def _caso_archivo(ruta):
        facts = photo_analyzer.extract_basic_facts(str(ruta))
        res = _ejecutar(ruta)
        res["photo_analyzer_facts"] = {
            "brightness": facts.get("brightness"),
            "quality":    facts.get("quality"),
            "error":      facts.get("error"),
        }
        return res

    correr_caso("A1_inexistente", "ruta de imagen que no existe",
                lambda: _caso_archivo(FIXTURES / "no_existe_esta_foto.webp"))
    correr_caso("A2_cero_bytes", "archivo .webp de 0 bytes",
                lambda: _caso_archivo(FIXTURES / "vacio.webp"))
    correr_caso("A3_txt_renombrado", ".txt renombrado a .webp",
                lambda: _caso_archivo(FIXTURES / "texto.webp"))
    correr_caso("A4_jpeg_truncado", "JPEG cortado al 50%",
                lambda: _caso_archivo(FIXTURES / "truncada.jpg"))
    correr_caso("A5_gigante", "PNG que declara 16000x16000 (256 MP)",
                lambda: _caso_archivo(FIXTURES / "gigante.png"))

    # ── C: etapa_activa basura ──────────────────────────────────────
    correr_caso("C1_E99", "etapa_activa='E99' (etapa inexistente)",
                lambda: _ejecutar(FIXTURES / "base_valida.png", etapa="E99"))
    def _caso_etapa(etapa):
        cfg = _config_sana()
        cfg.config_retrieval.etapa_activa = etapa if isinstance(etapa, str) else None
        res = _ejecutar(FIXTURES / "base_valida.png", etapa=etapa, cfg=cfg)
        res["menciona_etapa_no_definida"] = (
            "etapa_no_definida" in json.dumps(res["ids_criterios"] + [res["resumen_ejecutivo"]]))
        return res
    correr_caso("C2_vacia", "etapa_activa='' — ¿el NO_CALIFICA se ve en el resultado?",
                lambda: _caso_etapa(""))
    correr_caso("C3_none", "etapa_activa=None", lambda: _caso_etapa(None))
    correr_caso("C4_int", "etapa_activa=12345 (int) — crash esperado en pipeline.py:135",
                lambda: _caso_etapa(12345))

    # ── K: knowledge roto (copias; producción intacta) ──────────────
    correr_caso("K1_capa2_corrupta", "capa2 con sintaxis JSON inválida",
                lambda: _ejecutar(FIXTURES / "base_valida.png",
                                  cfg=_config_sana(ruta_capa2=KROTO / "capa2_corrupta.json")))
    correr_caso("K2_capa2_vacia", "capa2 = {'criterios': []}",
                lambda: _ejecutar(FIXTURES / "base_valida.png",
                                  cfg=_config_sana(ruta_capa2=KROTO / "capa2_vacia.json")))
    correr_caso("K3_todo_corrupto", "las 3 capas corruptas a la vez",
                lambda: _ejecutar(FIXTURES / "base_valida.png",
                                  cfg=_config_sana(
                                      ruta_capa1=KROTO / "capa1_corrupta.json",
                                      ruta_capa2=KROTO / "capa2_corrupta.json",
                                      ruta_capa3_tpl=KROTO / "capa3_corrupta.json")))

    # ── T: tipo_foto no reconocido ──────────────────────────────────
    correr_caso("T1_tipo_random", "tipo_foto='foto_rara_xyz'",
                lambda: _ejecutar(FIXTURES / "base_valida.png", tipo="foto_rara_xyz"))

    # ── P0: photo_analyzer truena con excepción ─────────────────────
    def _caso_paso0():
        original = photo_analyzer.extract_basic_facts
        def _revienta(*a, **k):
            raise RuntimeError("PASO_0 forzado a fallar por el stress test")
        photo_analyzer.extract_basic_facts = _revienta
        try:
            res = _ejecutar(FIXTURES / "base_valida.png")
        finally:
            photo_analyzer.extract_basic_facts = original
        blob = json.dumps([res["resumen_ejecutivo"]] + res["ids_criterios"]).lower()
        res["traza_del_fallo_en_resultado"] = ("paso_0" in blob or "error" in blob
                                               or "photo_analyzer" in blob
                                               or "archivo_invalido" in blob)
        return res
    correr_caso("P0_excepcion", "extract_basic_facts lanza RuntimeError — ¿queda traza?",
                _caso_paso0)

    # ── G1: 3 keys inválidas (429 mockeado, cero red real) ──────────
    def _caso_keys():
        original = pipeline._cargar_claves_api
        pipeline._cargar_claves_api = lambda: ["FAKE1", "FAKE2", "FAKE3"]
        RED["modo"] = "http429"
        try:
            res = _ejecutar(FIXTURES / "base_valida.png")
        finally:
            RED["modo"] = "bloquear"
            pipeline._cargar_claves_api = original
        blob = json.dumps([res["resumen_ejecutivo"]]).lower()
        res["cuota_distinguible_en_resultado"] = ("429" in blob or "cuota" in blob
                                                  or "resource_exhausted" in blob
                                                  or "clave" in blob or "key" in blob)
        return res
    correr_caso("G1_tres_keys_429", "3 keys fake, urlopen mockeado a HTTP 429", _caso_keys)

    # ── G2: verificación del guard anti-red ─────────────────────────
    sin_red = [c["id"] for c in CASOS if c["id"] != "G1_tres_keys_429" and c["intentos_red"] > 0]
    print("\nGuard anti-red:", "OK — 0 intentos fuera de G1" if not sin_red
          else f"VIOLADO en: {sin_red}")

    salida = {
        "fecha": time.strftime("%Y-%m-%d %H:%M:%S"),
        "guard_anti_red_ok": not sin_red,
        "casos_con_red_inesperada": sin_red,
        "casos": CASOS,
    }
    (SALIDA / "resultados.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(CASOS)} casos ejecutados -> {SALIDA / 'resultados.json'}")
