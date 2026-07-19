# -*- coding: utf-8 -*-
"""
correr_motor1_benchmark.py — Runner: ejecuta Motor 1 real foto por foto,
mide el tiempo (segundos) y produce el JSON que consume arnes_benchmark.py.

Input (manifest CSV, rutas explícitas — sin defaults a datos reales):
  foto_id,archivo,etapa_activa,tipo_foto
  - archivo: ruta a la imagen real (relativa al manifest o absoluta)
  - tipo_foto puede ir vacío → detección automática de photo_analyzer

Output (resultados_sistema.json):
  {"meta": {...}, "fotos": [{"foto_id", "archivo", "tiempo_segundos",
   "veredicto_global", "detecciones": [{"criterio_id","criterio","veredicto","razon"}],
   "evaluacion_parcial", "causa_parcial", "tokens_modelo",
   "criterios_delegados", "criterios_evaluados", "criterios_no_califica",
   "criterios_degradados_por_cuota", "pct_degradado_por_cuota"}]}

Semántica de "detección" (documentada, no implícita): un criterio cuenta como
detección del sistema cuando su veredicto es GRAVE u OBSERVACION. CUMPLE y
NO_CALIFICA no son detecciones (NO_CALIFICA = el sistema no pudo evaluar,
que es distinto de detectar un problema).

Fidelidad de trazabilidad (evaluacion_parcial/causa_parcial): sin esto, una
corrida degradada por cuota (modelo sin responder → todo NO_CALIFICA) es
INDISTINGUIBLE de una corrida limpia con 0 hallazgos — ambas dan detecciones=[].
Fix H6 (Sesión KK): la fuente de verdad es `ResultadoFinal.evaluacion_parcial`
(nivel LOTE) + `pct_degradado_por_cuota` (% de delegados sin respuesta del
modelo, schema 1.2); la derivación por tokens==0 quedó como fallback para
resultados sin esos campos. Los conteos crudos se serializan siempre.

Uso:
  python correr_motor1_benchmark.py autotest
  python correr_motor1_benchmark.py correr --manifest M.csv --salida R.json

El autotest usa un ejecutor FICTICIO inyectado ("FIXTURE AUTOTEST") — verifica
la mecánica de medición/serialización sin llamar al modelo ni requerir fotos.
El pipeline real solo se importa en `correr`.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

VEREDICTOS_DETECCION = {"GRAVE", "OBSERVACION"}
COLUMNAS_MANIFEST = ["foto_id", "archivo", "etapa_activa", "tipo_foto"]

RAIZ_REPO     = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = RAIZ_REPO / "pipeline" / "knowledge"


class ErrorRunner(Exception):
    """Error de entrada — aborta sin escribir nada."""


def cargar_manifest(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        columnas = [c.strip() for c in (lector.fieldnames or [])]
        faltantes = [c for c in COLUMNAS_MANIFEST if c not in columnas]
        if faltantes:
            raise ErrorRunner(f"Manifest sin columnas requeridas: {faltantes}. "
                              f"Esperadas: {COLUMNAS_MANIFEST}")
        filas = [dict(r) for r in lector]

    if not filas:
        raise ErrorRunner("Manifest vacío — ninguna foto que correr.")

    vistos: set[str] = set()
    for i, fila in enumerate(filas, start=2):
        fid = (fila.get("foto_id") or "").strip()
        if not fid:
            raise ErrorRunner(f"Manifest línea {i}: foto_id vacío.")
        if fid.lower() in vistos:
            raise ErrorRunner(f"Manifest línea {i}: foto_id duplicado '{fid}'.")
        vistos.add(fid.lower())
        archivo = (fila.get("archivo") or "").strip()
        if not archivo:
            raise ErrorRunner(f"Manifest línea {i}: archivo vacío para foto {fid}.")
        ruta_img = (ruta.parent / archivo) if not Path(archivo).is_absolute() else Path(archivo)
        if not ruta_img.exists():
            raise ErrorRunner(f"Manifest línea {i}: la imagen no existe: {ruta_img} "
                              f"— no se corre nada con rutas rotas.")
        fila["_ruta_imagen"] = str(ruta_img)
    return filas


def _cargar_env(raiz: Path) -> None:
    """Carga KEY=VALUE de <repo>/.env (setdefault, nunca pisa el entorno).

    pipeline.py solo carga .env en su bloque __main__ — al importarlo como
    módulo la key no estaría; sin esto _llamar_modelo degradaría en silencio
    a NO_CALIFICA por GEMINI_API_KEY ausente.
    """
    ruta = raiz / ".env"
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _ids_graves_de_resumen(resumen: str) -> list[str]:
    """Extrae los ids GRAVES del resumen de mandatory embebido en resumen_ejecutivo.

    Formato de _generar_resumen: secciones e ids se unen ambos con ' | ', pero
    'GRAVES (n):' declara cuántos ids siguen — eso hace el parseo determinista.
    """
    tokens = [t.strip() for t in (resumen or "").split("|")]
    for i, token in enumerate(tokens):
        m = re.match(r"GRAVES \((\d+)\): (.*)", token)
        if m:
            n = int(m.group(1))
            ids = [m.group(2).strip()]
            ids += [tokens[i + j] for j in range(1, n) if i + j < len(tokens)]
            return [x for x in ids[:n] if x]
    return []


def _detecciones_de_bloqueo(resultado) -> list[dict]:
    """Caso pipeline detenido en PASO 1: criterios=[] pero el bloqueo ES una
    detección (ej. imagen_oscura en F13). Los ids salen del resumen."""
    resumen = str(getattr(resultado, "resumen_ejecutivo", "") or "")
    ids = _ids_graves_de_resumen(resumen) or ["pipeline_bloqueado_mandatory"]
    return [{"criterio_id": cid, "criterio": "", "veredicto": "GRAVE",
             "razon": resumen} for cid in ids]


def _veredicto_str(c) -> str:
    """Veredicto de un criterio como string en MAYÚSCULAS (Enum .value o str)."""
    return (getattr(getattr(c, "veredicto", None), "value", None)
            or str(getattr(c, "veredicto", "") or "")).upper()


def _extraer_detecciones(resultado) -> list[dict]:
    """Filtra los criterios del ResultadoFinal a detecciones (GRAVE/OBSERVACION)."""
    detecciones = []
    for c in getattr(resultado, "criterios", []) or []:
        veredicto = _veredicto_str(c)
        if veredicto in VEREDICTOS_DETECCION:
            detecciones.append({
                "criterio_id": str(getattr(c, "criterio", "")),
                "criterio":    "",
                "veredicto":   veredicto,
                "razon":       str(getattr(c, "razon", "") or ""),
            })
    return detecciones


def _metadata_parcial(resultado) -> dict:
    """Señal de evaluación parcial/degradada del ResultadoFinal.

    Fix H6 (Sesión KK): el pipeline SÍ expone `evaluacion_parcial`/`causa_parcial`
    (desde Sesión HH, a nivel de LOTE) y desde schema 1.2 también el % real de
    degradación por cuota (`criterios_degradados_por_cuota`/`pct_degradado_por_
    cuota`). Este runner los re-derivaba con una señal más gruesa (tokens==0 =
    degradación TOTAL) y por eso benchmark_mini del 19 Jul reportó `False` en 5
    fotos con 1-3 lotes caídos cada una. Ahora la fuente de verdad es el
    pipeline; la derivación por tokens==0 queda solo como fallback para
    resultados viejos/fixtures sin esos campos.

    Casos que NO son parciales por diseño: (a) bloqueo mandatory (delegados=0, es
    un stop duro con detecciones reales, no una degradación); (b) fallback GitHub
    exitoso (tokens>0 porque el segundo proveedor sí respondió).
    """
    tokens    = int(getattr(resultado, "tokens_modelo_usados", 0) or 0)
    delegados = int(getattr(resultado, "criterios_delegados_a_modelo", 0) or 0)
    criterios = getattr(resultado, "criterios", []) or []
    n_total   = len(criterios)
    n_nc      = sum(1 for c in criterios if _veredicto_str(c) == "NO_CALIFICA")

    parcial_pipeline = getattr(resultado, "evaluacion_parcial", None)
    if parcial_pipeline is not None:
        parcial = bool(parcial_pipeline)
        causa   = str(getattr(resultado, "causa_parcial", "") or "")
    else:
        # Fallback (resultado sin el campo): derivación gruesa por tokens==0.
        parcial = delegados > 0 and tokens == 0
        causa = ""
        if parcial:
            causa = (f"Modelo sin respuesta (0 tokens) con {delegados} criterio(s) "
                     f"delegado(s); {n_nc} degradado(s) a NO_CALIFICA. Causa probable: "
                     f"cuota agotada (429) o 503 en todas las claves/proveedores.")
    return {
        "evaluacion_parcial":    parcial,
        "causa_parcial":         causa,
        "tokens_modelo":         tokens,
        "criterios_delegados":   delegados,
        "criterios_evaluados":   n_total,
        "criterios_no_califica": n_nc,
        # H6: % real de silencio de cuota (delegados sin respuesta del modelo).
        # NO_CALIFICA respondidos por el modelo NO cuentan aquí.
        "criterios_degradados_por_cuota":
            int(getattr(resultado, "criterios_degradados_por_cuota", 0) or 0),
        "pct_degradado_por_cuota":
            float(getattr(resultado, "pct_degradado_por_cuota", 0.0) or 0.0),
    }


def correr(manifest: list[dict], ejecutar_fn: Callable, salida: Path) -> dict:
    """Corre `ejecutar_fn` por foto midiendo wall time. Escribe y devuelve el JSON."""
    fotos = []
    for fila in manifest:
        fid = fila["foto_id"].strip()
        t0 = time.perf_counter()
        resultado = ejecutar_fn(
            imagen_path  = fila["_ruta_imagen"],
            etapa_activa = (fila.get("etapa_activa") or "").strip() or None,
            tipo_foto    = (fila.get("tipo_foto") or "").strip() or None,
        )
        segundos = round(time.perf_counter() - t0, 2)
        veredicto_global = getattr(getattr(resultado, "veredicto_global", None), "value", None) \
                           or str(getattr(resultado, "veredicto_global", "") or "")
        detecciones = _extraer_detecciones(resultado)
        if getattr(resultado, "puede_continuar", True) is False and not detecciones:
            detecciones = _detecciones_de_bloqueo(resultado)
        foto = {
            "foto_id":          fid,
            "archivo":          fila["_ruta_imagen"],
            "tiempo_segundos":  segundos,
            "veredicto_global": veredicto_global,
            "detecciones":      detecciones,
        }
        foto.update(_metadata_parcial(resultado))
        fotos.append(foto)
        aviso = ""
        if foto["evaluacion_parcial"]:
            aviso = (f"  [PARCIAL: {foto['pct_degradado_por_cuota']}% degradado "
                     f"por cuota/proveedor]")
        print(f"  {fid}: {segundos}s, veredicto={veredicto_global}, "
              f"{len(detecciones)} detección(es){aviso}")

    datos = {
        "meta": {
            "generado":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fotos":     len(fotos),
            "semantica": "deteccion = criterio con veredicto GRAVE u OBSERVACION",
        },
        "fotos": fotos,
    }
    salida.parent.mkdir(parents=True, exist_ok=True)
    with open(salida, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    return datos


# ── AUTOTEST — ejecutor ficticio inyectado, cero pipeline real ─────

def autotest() -> int:
    import tempfile

    fallas: list[str] = []

    def check(nombre: str, condicion: bool):
        print(f"  [{'PASS' if condicion else 'FAIL'}] {nombre}")
        if not condicion:
            fallas.append(nombre)

    class _CriterioFicticio:
        def __init__(self, cid, veredicto, razon="FIXTURE AUTOTEST"):
            self.criterio, self.veredicto, self.razon = cid, veredicto, razon

    class _ResultadoFicticio:
        def __init__(self, criterios, veredicto_global="GRAVE",
                     tokens=1234, delegados=2):
            self.criterios = criterios
            self.veredicto_global = veredicto_global
            self.tokens_modelo_usados = tokens
            self.criterios_delegados_a_modelo = delegados

    def ejecutar_ficticio(imagen_path, etapa_activa, tipo_foto):
        time.sleep(0.05)   # tiempo medible pero corto
        return _ResultadoFicticio([
            _CriterioFicticio("criterio_ficticio_grave", "GRAVE"),
            _CriterioFicticio("criterio_ficticio_obs", "OBSERVACION"),
            _CriterioFicticio("criterio_ficticio_cumple", "CUMPLE"),
            _CriterioFicticio("criterio_ficticio_nc", "NO_CALIFICA"),
        ])

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        img = tmp / "FIXTURE_AUTOTEST.jpg"
        img.write_bytes(b"FIXTURE AUTOTEST no es una imagen real")

        # manifest válido
        manifest_csv = tmp / "manifest.csv"
        manifest_csv.write_text(
            "foto_id,archivo,etapa_activa,tipo_foto\n"
            f"FX1,{img.name},etapa_ficticia,\n"
            f"FX2,{img.name},etapa_ficticia,focal_show\n",
            encoding="utf-8")
        manifest = cargar_manifest(manifest_csv)
        check("manifest válido carga 2 fotos", len(manifest) == 2)

        datos = correr(manifest, ejecutar_ficticio, tmp / "resultados.json")
        f1 = datos["fotos"][0]
        check("solo GRAVE/OBSERVACION cuentan como detección",
              [d["criterio_id"] for d in f1["detecciones"]]
              == ["criterio_ficticio_grave", "criterio_ficticio_obs"])
        check("tiempo medido > 0 por foto",
              all(f["tiempo_segundos"] > 0 for f in datos["fotos"]))
        check("veredicto global serializado", f1["veredicto_global"] == "GRAVE")
        relectura = json.loads((tmp / "resultados.json").read_text(encoding="utf-8"))
        check("JSON relegible e íntegro", relectura["meta"]["fotos"] == 2
              and len(relectura["fotos"]) == 2)

        # guards que deben abortar
        def espera_error(nombre, contenido):
            ruta = tmp / "manifest_malo.csv"
            ruta.write_text(contenido, encoding="utf-8")
            try:
                cargar_manifest(ruta)
                check(nombre, False)
            except ErrorRunner:
                check(nombre, True)

        espera_error("manifest vacío aborta", "foto_id,archivo,etapa_activa,tipo_foto\n")
        espera_error("imagen inexistente aborta",
                     "foto_id,archivo,etapa_activa,tipo_foto\nFX1,no_existe.jpg,e,\n")
        espera_error("foto_id duplicado aborta",
                     "foto_id,archivo,etapa_activa,tipo_foto\n"
                     f"FX1,{img.name},e,\nfx1,{img.name},e,\n")
        espera_error("columnas faltantes aborta", "foto_id,archivo\nFX1,x.jpg\n")

        # caso bloqueado por mandatory (criterios=[], resumen con ids GRAVES)
        class _ResultadoBloqueado:
            criterios = []
            veredicto_global = "GRAVE"
            puede_continuar = False
            resumen_ejecutivo = ("Pipeline detenido en PASO 1 (mandatory). "
                                 "VEREDICTO MANDATORY: GRAVE | GRAVES (2): "
                                 "imagen_oscura | espacio_vacio_excesivo | "
                                 "NO CALIFICA (1): grafico_etapa | "
                                 "→ Pipeline detenido. Foto no evaluable.")

        def ejecutar_bloqueado(imagen_path, etapa_activa, tipo_foto):
            return _ResultadoBloqueado()

        datos_b = correr(cargar_manifest(manifest_csv)[:1], ejecutar_bloqueado,
                         tmp / "resultados_bloqueo.json")
        dets_b = datos_b["fotos"][0]["detecciones"]
        check("bloqueo mandatory: ids GRAVES extraídos del resumen",
              [d["criterio_id"] for d in dets_b] == ["imagen_oscura", "espacio_vacio_excesivo"])
        check("bloqueo mandatory: no arrastra NO_CALIFICA ni secciones",
              all("NO CALIFICA" not in d["criterio_id"] and "→" not in d["criterio_id"]
                  for d in dets_b))
        check("resumen sin GRAVES cae a id sintético",
              [d["criterio_id"] for d in _detecciones_de_bloqueo(type("R", (), {
                  "resumen_ejecutivo": "Pipeline detenido. VEREDICTO MANDATORY: GRAVE"})())]
              == ["pipeline_bloqueado_mandatory"])
        check("bloqueo mandatory NO se marca parcial (delegados=0, es stop duro)",
              datos_b["fotos"][0]["evaluacion_parcial"] is False)

        # ── Fidelidad de trazabilidad: degradada por cuota vs limpia con 0 hallazgos ──
        # Ambas dan detecciones=[]; sin evaluacion_parcial serían indistinguibles.
        def ejecutar_limpio(imagen_path, etapa_activa, tipo_foto):
            # Modelo respondió de verdad (tokens>0), todo CUMPLE → 0 detecciones reales.
            return _ResultadoFicticio(
                [_CriterioFicticio("c_cumple_1", "CUMPLE"),
                 _CriterioFicticio("c_cumple_2", "CUMPLE")],
                veredicto_global="CUMPLE", tokens=5000, delegados=2)

        def ejecutar_degradado(imagen_path, etapa_activa, tipo_foto):
            # Cuota agotada: modelo sin respuesta (tokens=0), delegados degradados a NO_CALIFICA.
            return _ResultadoFicticio(
                [_CriterioFicticio("c_nc_1", "NO_CALIFICA"),
                 _CriterioFicticio("c_nc_2", "NO_CALIFICA")],
                veredicto_global="NO_CALIFICA", tokens=0, delegados=2)

        una_foto = cargar_manifest(manifest_csv)[:1]
        d_limpio = correr(una_foto, ejecutar_limpio, tmp / "r_limpio.json")["fotos"][0]
        d_degr   = correr(una_foto, ejecutar_degradado, tmp / "r_degr.json")["fotos"][0]

        check("foto limpia: 0 detecciones y evaluacion_parcial=False",
              d_limpio["detecciones"] == [] and d_limpio["evaluacion_parcial"] is False)
        check("foto degradada por cuota: 0 detecciones pero evaluacion_parcial=True",
              d_degr["detecciones"] == [] and d_degr["evaluacion_parcial"] is True)
        check("degradada y limpia son DISTINGUIBLES pese a detecciones=[] en ambas",
              d_limpio["detecciones"] == d_degr["detecciones"] == []
              and d_limpio["evaluacion_parcial"] != d_degr["evaluacion_parcial"])
        check("degradada: causa_parcial no vacía, tokens=0, 2 NO_CALIFICA",
              bool(d_degr["causa_parcial"]) and d_degr["tokens_modelo"] == 0
              and d_degr["criterios_no_califica"] == 2)
        check("limpia: causa_parcial vacía, tokens>0, 0 NO_CALIFICA",
              d_limpio["causa_parcial"] == "" and d_limpio["tokens_modelo"] > 0
              and d_limpio["criterios_no_califica"] == 0)
        rel_degr = json.loads((tmp / "r_degr.json").read_text(encoding="utf-8"))
        check("evaluacion_parcial/causa_parcial PERSISTEN en el JSON de salida",
              rel_degr["fotos"][0]["evaluacion_parcial"] is True
              and rel_degr["fotos"][0]["causa_parcial"] != "")

        # ── Fix H6 (Sesión KK): el flag del PIPELINE manda ──────────────
        # Bug reproducido de benchmark_mini 19 Jul: foto con lotes caídos
        # (parcial a nivel lote) pero tokens>0 — la derivación por tokens==0
        # la reportaba como corrida completa. Ahora debe salir PARCIAL con %.
        def ejecutar_parcial_lote(imagen_path, etapa_activa, tipo_foto):
            r = _ResultadoFicticio(
                [_CriterioFicticio("c_ok", "CUMPLE"),
                 _CriterioFicticio("c_nc_lote", "NO_CALIFICA")],
                veredicto_global="CUMPLE", tokens=5000, delegados=137)
            r.evaluacion_parcial = True
            r.causa_parcial = "el modelo no respondió 3 de 10 lote(s) de criterios delegados"
            r.criterios_degradados_por_cuota = 45
            r.pct_degradado_por_cuota = 32.8
            return r

        d_pl = correr(una_foto, ejecutar_parcial_lote, tmp / "r_parcial_lote.json")["fotos"][0]
        check("H6: parcial a nivel LOTE (tokens>0) YA se reporta como parcial",
              d_pl["evaluacion_parcial"] is True and d_pl["tokens_modelo"] == 5000)
        check("H6: causa_parcial viene del pipeline, no derivada",
              "lote" in d_pl["causa_parcial"])
        check("H6: % degradado por cuota serializado (45 criterios, 32.8%)",
              d_pl["criterios_degradados_por_cuota"] == 45
              and d_pl["pct_degradado_por_cuota"] == 32.8)
        check("H6 fallback: fixture sin campos nuevos serializa 0/0.0",
              d_degr["criterios_degradados_por_cuota"] == 0
              and d_degr["pct_degradado_por_cuota"] == 0.0)

    print(f"\nAUTOTEST RUNNER: {'PASS' if not fallas else 'FAIL'} ({len(fallas)} falla(s))")
    return len(fallas)


# ── CLI ────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("autotest", help="verifica la mecánica con un ejecutor ficticio")
    p_run = sub.add_parser("correr", help="corre Motor 1 real sobre el manifest")
    p_run.add_argument("--manifest", required=True, type=Path)
    p_run.add_argument("--salida",   required=True, type=Path)
    args = parser.parse_args(argv)

    if args.comando == "autotest":
        return 1 if autotest() else 0

    # correr: PASO 0 — autotest como gate
    print("PASO 0 — autotest (gate obligatorio):")
    if autotest():
        print("ABORTADO: el autotest falló — no se corre Motor 1.")
        return 1

    _cargar_env(RAIZ_REPO)
    sys.path.insert(0, str(RAIZ_REPO / "pipeline"))
    sys.path.insert(0, str(RAIZ_REPO / "core"))
    import pipeline as motor1                       # noqa: E402 — import tardío a propósito
    from retrieval_engine import ConfigRetrieval    # noqa: E402
    if not os.environ.get("GEMINI_API_KEY"):
        print("ABORTADO: GEMINI_API_KEY ausente — el benchmark con foto real "
              "necesita el modelo; sin key todo saldría NO_CALIFICA.")
        return 1

    # Knowledge base con rutas ABSOLUTAS — igual que app.py (_config_pipeline).
    # ConfigRetrieval por defecto apunta a "knowledge/..." RELATIVO al cwd; desde
    # motor1/benchmark/ ese path no existe → el pipeline extraería 0 criterios y
    # TODA foto saldría NO_CALIFICA con 0 detecciones (benchmark basura, 0% acierto
    # sin error visible). Se fija explícito y se verifica que carga antes de gastar
    # una sola llamada al modelo.
    ruta_capa1 = KNOWLEDGE_DIR / "capa1_display_basics.json"
    ruta_capa2 = KNOWLEDGE_DIR / "capa2_campana_activa.json"
    faltan = [p.name for p in (ruta_capa1, ruta_capa2) if not p.exists()]
    if faltan:
        print(f"ABORTADO: knowledge base no encontrado {faltan} en {KNOWLEDGE_DIR}.")
        return 1

    def _config_bench(etapa_activa):
        return motor1.ConfigPipeline(
            config_retrieval=ConfigRetrieval(
                ruta_capa1          = str(ruta_capa1),
                ruta_capa2          = str(ruta_capa2),
                ruta_capa3_template = str(KNOWLEDGE_DIR / "capa3_{tipo_foto}.json"),
                etapa_activa        = etapa_activa,
            ))

    n_base = len(motor1._extraer_criterios_del_knowledge(
        _config_bench("E1").config_retrieval, None, "E1"))
    if n_base == 0:
        print("ABORTADO: el knowledge base cargó 0 criterios — no se corre un "
              "benchmark que saldría todo NO_CALIFICA.")
        return 1
    print(f"Knowledge base OK: {n_base} criterios base (E1) desde {KNOWLEDGE_DIR.name}/.")

    # Logging del pipeline VISIBLE (a stderr). Sin esto, los WARNING/ERROR de
    # PASO_4 (429 cuota agotada, 503, lotes fallidos) mueren en el NullHandler
    # y una corrida degradada parece una corrida normal — pasó el 9 Jul: 25
    # fotos todas NO_CALIFICA con las 3 claves en 429 y cero rastro del porqué.
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s | %(message)s")
    # Diagnóstico (Sesión KK): en benchmark el detalle por lote SÍ importa —
    # a nivel WARNING los "lote N/M OK ... tokens=" (INFO) morían y no se
    # podía auditar el consumo real de tokens/requests por lote.
    logging.getLogger("visual_lv.pipeline").setLevel(logging.INFO)

    # Pre-flight de CUOTA: 1 llamada mínima ANTES de gastar la corrida. Va por
    # _post_gemini (rota las claves solito): si devuelve None es que TODAS las
    # claves están agotadas/caídas → correr sería quemar intentos para producir
    # un benchmark basura (todo NO_CALIFICA degradado).
    cuerpo_min = {"contents": [{"role": "user", "parts": [{"text": "di ok"}]}],
                  "generationConfig": {"maxOutputTokens": 5}}
    if motor1._post_gemini(cuerpo_min, 20, "PREFLIGHT") is None:
        print("ABORTADO: pre-flight de cuota falló — ninguna GEMINI_API_KEY "
              "responde (429/503 en todas). Reintenta con cuota fresca.")
        return 1
    print("Pre-flight de cuota OK: el modelo responde.")

    def _ejecutar_con_kb(imagen_path, etapa_activa, tipo_foto):
        return motor1.ejecutar(imagen_path=imagen_path, etapa_activa=etapa_activa,
                               tipo_foto=tipo_foto, config=_config_bench(etapa_activa))

    try:
        manifest = cargar_manifest(args.manifest)
    except ErrorRunner as e:
        print(f"ABORTADO: {e}")
        return 1

    print(f"Corriendo Motor 1 sobre {len(manifest)} foto(s)…")
    datos = correr(manifest, _ejecutar_con_kb, args.salida)
    total = sum(f["tiempo_segundos"] for f in datos["fotos"])
    print(f"\nListo: {len(datos['fotos'])} fotos en {round(total, 1)}s -> {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
