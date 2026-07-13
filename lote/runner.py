# -*- coding: utf-8 -*-
"""
lote/runner.py — Núcleo del modo lote de producción: corre pipeline.ejecutar()
sobre N fotos de UNA campaña y devuelve un dict consolidado, listo para
reporteria (lote/reporte.py) y serialización JSON.

Contrato de salida (schema_lote 1.0):
  {"meta": {...}, "resumen": {...}, "fotos": [{...} por foto]}
  - resumen.lote_parcial: True si CUALQUIER foto salió con evaluacion_parcial
    o quedó sin procesar — un lote parcial NUNCA se presenta como completo.
  - fotos[].estado: "procesada" | "no_procesada_por_cuota" | "error"

Corte de lote por cuota (extiende el circuit breaker por-foto del pipeline):
si una foto termina con evaluacion_parcial=True Y el pipeline reporta todas
las claves agotadas (cuota_agotada_fn), las fotos restantes se marcan
no_procesada_por_cuota sin gastar un request.

Cero fallos silenciosos: una foto que revienta el pipeline queda como
estado="error" con la traza corta en su entrada — el lote continúa y el
resumen la cuenta. Nada desaparece del resultado que ve el usuario.

Uso:
  python -m lote.runner autotest      (desde la raíz del repo)

El autotest usa un ejecutor FICTICIO inyectado ("FIXTURE AUTOTEST") — verifica
la mecánica del lote sin llamar al modelo ni requerir fotos. El pipeline real
solo se importa vía crear_ejecutor_real() (lo usan verificar_lote.py y app.py).
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

SCHEMA_LOTE = "1.0"

RAIZ_REPO     = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = RAIZ_REPO / "pipeline" / "knowledge"

# Extensiones de imagen que barre el CLI (minúsculas).
EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".webp"}

# Orden de gravedad para el resumen y los reportes (más grave primero).
ORDEN_VEREDICTO = ["GRAVE", "OBSERVACION", "NO_CALIFICA", "CUMPLE"]


class ErrorLote(Exception):
    """Error de entrada — aborta sin escribir nada."""


# ──────────────────────────────────────────────────────────────
# EJECUTOR REAL (import tardío del pipeline — solo producción)
# ──────────────────────────────────────────────────────────────

def crear_ejecutor_real(etapa_activa: str):
    """Importa el pipeline real y regresa (ejecutar_fn, cuota_agotada_fn, n_criterios_base).

    - ejecutar_fn(imagen_path, tipo_foto) -> ResultadoFinal, con knowledge en
      rutas ABSOLUTAS (mismo patrón que app.py y el runner de benchmark: el
      default relativo al cwd extraería 0 criterios fuera de la raíz).
    - cuota_agotada_fn() -> bool: True si la última corrida dejó TODAS las
      claves del modelo en cuota/inválidas (insumo del corte de lote).
    - n_criterios_base: criterios que carga el knowledge para la etapa — el
      llamador debe abortar si es 0 (todo saldría NO_CALIFICA sin causa útil).
    """
    for _p in (str(RAIZ_REPO / "pipeline"), str(RAIZ_REPO / "core")):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    import pipeline as motor1                      # noqa: E402 — import tardío a propósito
    from retrieval_engine import ConfigRetrieval   # noqa: E402

    config = motor1.ConfigPipeline(
        config_retrieval=ConfigRetrieval(
            ruta_capa1          = str(KNOWLEDGE_DIR / "capa1_display_basics.json"),
            ruta_capa2          = str(KNOWLEDGE_DIR / "capa2_campana_activa.json"),
            ruta_capa3_template = str(KNOWLEDGE_DIR / "capa3_{tipo_foto}.json"),
            etapa_activa        = etapa_activa,
        ))

    n_base = len(motor1._extraer_criterios_del_knowledge(
        config.config_retrieval, None, etapa_activa))

    def ejecutar_fn(imagen_path: str, tipo_foto: Optional[str]):
        return motor1.ejecutar(imagen_path=imagen_path, etapa_activa=etapa_activa,
                               tipo_foto=tipo_foto, config=config)

    def cuota_agotada_fn() -> bool:
        return bool(getattr(motor1, "_ESTADO_CUOTA", {}).get("claves_agotadas"))

    return ejecutar_fn, cuota_agotada_fn, n_base


def cargar_env(raiz: Path = RAIZ_REPO) -> None:
    """Carga KEY=VALUE de <repo>/.env (setdefault, nunca pisa el entorno).
    pipeline.py solo carga .env en su __main__ — importado como módulo la key
    no estaría y todo delegado degradaría a NO_CALIFICA sin aviso previo."""
    ruta = raiz / ".env"
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        import os
        os.environ.setdefault(k.strip(), v.strip())


# ──────────────────────────────────────────────────────────────
# EXTRACCIÓN DEFENSIVA DEL ResultadoFinal (patrón del benchmark)
# ──────────────────────────────────────────────────────────────

def _valor(x) -> str:
    """Severidad/Confianza enum -> str; cualquier otra cosa -> str plano."""
    return str(getattr(x, "value", None) or (x if x is not None else "") or "")


def _entrada_de_resultado(ruta: str, resultado, segundos: float) -> dict:
    criterios = getattr(resultado, "criterios", []) or []
    conteos = {v: 0 for v in ORDEN_VEREDICTO}
    no_cumple = []
    for c in criterios:
        veredicto = _valor(getattr(c, "veredicto", "")).upper()
        if veredicto in conteos:
            conteos[veredicto] += 1
        if veredicto and veredicto != "CUMPLE":
            no_cumple.append({
                "criterio":  str(getattr(c, "criterio", "")),
                "veredicto": veredicto,
                "confianza": _valor(getattr(c, "confianza", "")),
                "fuente":    str(getattr(c, "fuente_dominante", "") or ""),
                "razon":     str(getattr(c, "razon", "") or ""),
            })

    resumen = str(getattr(resultado, "resumen_ejecutivo", "") or "")
    # Caso bloqueado por mandatory sin criterios (PASO 1): el bloqueo ES el
    # hallazgo — se sintetiza una fila para que el reporte nunca muestre una
    # foto GRAVE con detalle vacío.
    if not criterios and getattr(resultado, "puede_continuar", True) is False:
        no_cumple.append({
            "criterio":  "pipeline_bloqueado_mandatory",
            "veredicto": _valor(getattr(resultado, "veredicto_global", "GRAVE")).upper() or "GRAVE",
            "confianza": "ALTO",
            "fuente":    "MANDATORY",
            "razon":     resumen,
        })

    orden_rank = {v: i for i, v in enumerate(ORDEN_VEREDICTO)}
    no_cumple.sort(key=lambda d: (orden_rank.get(d["veredicto"], 99), d["criterio"]))

    return {
        "archivo":            ruta,
        "nombre":             Path(ruta).name,
        "estado":             "procesada",
        "veredicto_global":   _valor(getattr(resultado, "veredicto_global", "")).upper(),
        "resumen_ejecutivo":  resumen,
        "evaluacion_parcial": bool(getattr(resultado, "evaluacion_parcial", False)),
        "causa_parcial":      getattr(resultado, "causa_parcial", None),
        "duracion_s":         round(segundos, 2),
        "criterios_no_cumple": no_cumple,
        "n_graves":           conteos["GRAVE"],
        "n_observaciones":    conteos["OBSERVACION"],
        "n_no_califica":      conteos["NO_CALIFICA"],
        "n_cumple":           conteos["CUMPLE"],
    }


def _entrada_no_procesada(ruta: str, causa: str) -> dict:
    return {
        "archivo": ruta, "nombre": Path(ruta).name,
        "estado": "no_procesada_por_cuota",
        "veredicto_global": "", "resumen_ejecutivo": causa,
        "evaluacion_parcial": True, "causa_parcial": causa,
        "duracion_s": 0.0, "criterios_no_cumple": [],
        "n_graves": 0, "n_observaciones": 0, "n_no_califica": 0, "n_cumple": 0,
    }


def _entrada_error(ruta: str, exc: BaseException, segundos: float) -> dict:
    traza = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return {
        "archivo": ruta, "nombre": Path(ruta).name,
        "estado": "error",
        "veredicto_global": "", "resumen_ejecutivo": f"El pipeline lanzó un error: {traza}",
        "evaluacion_parcial": True, "causa_parcial": f"error del pipeline: {traza[:200]}",
        "duracion_s": round(segundos, 2), "criterios_no_cumple": [],
        "n_graves": 0, "n_observaciones": 0, "n_no_califica": 0, "n_cumple": 0,
    }


# ──────────────────────────────────────────────────────────────
# NÚCLEO
# ──────────────────────────────────────────────────────────────

def procesar_lote(
    fotos:             list[str],
    etapa_activa:      str,
    tipo_foto_default: Optional[str],
    ejecutar_fn:       Callable,
    cuota_agotada_fn:  Optional[Callable[[], bool]] = None,
    progreso_cb:       Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """Corre el pipeline foto por foto y consolida el lote.

    - fotos: rutas a imágenes (un lote = UNA campaña = una etapa_activa).
    - tipo_foto_default: tipo para todo el lote; None o "auto" -> detección
      automática de photo_analyzer (tipo_foto=None en la llamada).
    - ejecutar_fn(imagen_path, tipo_foto) -> ResultadoFinal (ya con config).
    - cuota_agotada_fn: si tras una foto parcial devuelve True, las fotos
      restantes se marcan no_procesada_por_cuota (corte de lote).
    - progreso_cb(i, total, nombre): para la barra de progreso de la UI.
    """
    if not fotos:
        raise ErrorLote("Lote vacío — ninguna foto que procesar.")
    etapa = str(etapa_activa or "").strip()
    if not etapa:
        raise ErrorLote("etapa_activa vacía — un lote es una campaña; se requiere la etapa.")

    tipo = (tipo_foto_default or "").strip() or None
    if tipo and tipo.lower() == "auto":
        tipo = None

    entradas: list[dict] = []
    corte_por_cuota: Optional[str] = None
    total = len(fotos)

    for i, ruta in enumerate([str(f) for f in fotos], start=1):
        if corte_por_cuota:
            entradas.append(_entrada_no_procesada(ruta, corte_por_cuota))
            continue
        t0 = time.perf_counter()
        try:
            resultado = ejecutar_fn(ruta, tipo)
            entrada = _entrada_de_resultado(ruta, resultado, time.perf_counter() - t0)
        except Exception as exc:  # una foto rota nunca tumba el lote — queda con traza
            entrada = _entrada_error(ruta, exc, time.perf_counter() - t0)
        entradas.append(entrada)
        if (entrada["evaluacion_parcial"] and entrada["estado"] == "procesada"
                and cuota_agotada_fn is not None and cuota_agotada_fn()):
            corte_por_cuota = ("claves del modelo agotadas/inválidas — el lote se "
                               "cortó para no quemar requests contra claves muertas; "
                               "reintentar estas fotos con cuota fresca")
        if progreso_cb:
            progreso_cb(i, total, Path(ruta).name)

    # ── resumen del lote ──
    procesadas = [e for e in entradas if e["estado"] == "procesada"]
    por_veredicto = {v: 0 for v in ORDEN_VEREDICTO}
    for e in procesadas:
        if e["veredicto_global"] in por_veredicto:
            por_veredicto[e["veredicto_global"]] += 1

    fotos_parciales = sum(1 for e in procesadas if e["evaluacion_parcial"])
    no_procesadas   = sum(1 for e in entradas if e["estado"] == "no_procesada_por_cuota")
    errores         = sum(1 for e in entradas if e["estado"] == "error")

    lote_parcial = bool(fotos_parciales or no_procesadas or errores)
    causa_lote: Optional[str] = None
    if corte_por_cuota:
        causa_lote = corte_por_cuota
    elif lote_parcial:
        partes = []
        if fotos_parciales:
            partes.append(f"{fotos_parciales} foto(s) con evaluación parcial (el modelo no respondió todos sus lotes)")
        if errores:
            partes.append(f"{errores} foto(s) con error del pipeline")
        causa_lote = "; ".join(partes)

    pct_cumplimiento = (round(100.0 * por_veredicto["CUMPLE"] / len(procesadas), 1)
                        if procesadas else None)

    return {
        "meta": {
            "schema_lote":       SCHEMA_LOTE,
            "generado":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "etapa_activa":      etapa,
            "tipo_foto_default": tipo or "auto",
            "fotos_totales":     total,
            "fotos_procesadas":  len(procesadas),
        },
        "resumen": {
            "por_veredicto":                 por_veredicto,
            "pct_cumplimiento":              pct_cumplimiento,
            "lote_parcial":                  lote_parcial,
            "causa_lote_parcial":            causa_lote,
            "fotos_parciales":               fotos_parciales,
            "fotos_no_procesadas_por_cuota": no_procesadas,
            "fotos_con_error":               errores,
        },
        "fotos": entradas,
    }


def listar_fotos_carpeta(carpeta: Path) -> list[str]:
    """Barre una carpeta (no recursivo) y regresa las imágenes ordenadas por nombre."""
    if not carpeta.is_dir():
        raise ErrorLote(f"La carpeta no existe: {carpeta}")
    fotos = sorted(str(p) for p in carpeta.iterdir()
                   if p.is_file() and p.suffix.lower() in EXTENSIONES_IMAGEN)
    if not fotos:
        raise ErrorLote(f"La carpeta no contiene imágenes ({'/'.join(sorted(EXTENSIONES_IMAGEN))}): {carpeta}")
    return fotos


# ──────────────────────────────────────────────────────────────
# AUTOTEST — ejecutor ficticio inyectado, cero pipeline real, cero red
# ──────────────────────────────────────────────────────────────

def autotest() -> int:
    fallas: list[str] = []

    def check(nombre: str, condicion: bool):
        print(f"  [{'PASS' if condicion else 'FAIL'}] {nombre}")
        if not condicion:
            fallas.append(nombre)

    class _Sev:
        def __init__(self, v): self.value = v

    class _Criterio:
        def __init__(self, cid, veredicto, razon="FIXTURE AUTOTEST"):
            self.criterio = cid
            self.veredicto = _Sev(veredicto)
            self.confianza = _Sev("ALTO")
            self.fuente_dominante = "FIXTURE"
            self.razon = razon

    class _Resultado:
        def __init__(self, veredicto, criterios, parcial=False, causa=None,
                     puede_continuar=True, resumen="FIXTURE AUTOTEST resumen"):
            self.veredicto_global = _Sev(veredicto)
            self.criterios = criterios
            self.resumen_ejecutivo = resumen
            self.evaluacion_parcial = parcial
            self.causa_parcial = causa
            self.puede_continuar = puede_continuar

    # 1) lote sano: 3 fotos, conteos y orden correctos
    resultados = {
        "a.jpg": _Resultado("CUMPLE", [_Criterio("c1", "CUMPLE")]),
        "b.jpg": _Resultado("GRAVE", [_Criterio("g1", "GRAVE"), _Criterio("o1", "OBSERVACION"),
                                      _Criterio("c2", "CUMPLE")]),
        "c.jpg": _Resultado("NO_CALIFICA", [_Criterio("n1", "NO_CALIFICA")]),
    }
    lote = procesar_lote(list(resultados), "etapa_ficticia", "auto",
                         lambda ruta, tipo: resultados[ruta])
    check("lote sano: 3 procesadas, 0 parcial",
          lote["meta"]["fotos_procesadas"] == 3 and not lote["resumen"]["lote_parcial"])
    check("conteo por veredicto correcto",
          lote["resumen"]["por_veredicto"] == {"GRAVE": 1, "OBSERVACION": 0,
                                               "NO_CALIFICA": 1, "CUMPLE": 1})
    check("pct_cumplimiento = 33.3", lote["resumen"]["pct_cumplimiento"] == 33.3)
    foto_b = next(f for f in lote["fotos"] if f["nombre"] == "b.jpg")
    check("criterios no-CUMPLE ordenados por gravedad y CUMPLE excluido",
          [c["criterio"] for c in foto_b["criterios_no_cumple"]] == ["g1", "o1"]
          and foto_b["n_cumple"] == 1)

    # 2) foto parcial SIN cuota agotada: lote parcial pero sin corte
    res_p = {"a.jpg": _Resultado("NO_CALIFICA", [], parcial=True, causa="el modelo no respondió 2 de 3 lote(s)"),
             "b.jpg": _Resultado("CUMPLE", [_Criterio("c1", "CUMPLE")])}
    lote_p = procesar_lote(list(res_p), "e", None, lambda r, t: res_p[r],
                           cuota_agotada_fn=lambda: False)
    check("parcial sin cuota: lote_parcial=True y la 2a foto SÍ se procesa",
          lote_p["resumen"]["lote_parcial"] and lote_p["meta"]["fotos_procesadas"] == 2
          and lote_p["resumen"]["fotos_no_procesadas_por_cuota"] == 0)

    # 3) corte por cuota: parcial + cuota agotada en la foto 2 de 5
    llamadas = []
    def _ejecutar_cuota(ruta, tipo):
        llamadas.append(ruta)
        if len(llamadas) == 2:
            return _Resultado("NO_CALIFICA", [], parcial=True, causa="claves agotadas")
        return _Resultado("CUMPLE", [_Criterio("c1", "CUMPLE")])
    lote_c = procesar_lote([f"{i}.jpg" for i in range(1, 6)], "e", "focal_show",
                           _ejecutar_cuota, cuota_agotada_fn=lambda: len(llamadas) >= 2)
    check("corte por cuota: solo 2 llamadas al pipeline para 5 fotos", len(llamadas) == 2)
    check("corte por cuota: 3 fotos no_procesada_por_cuota",
          lote_c["resumen"]["fotos_no_procesadas_por_cuota"] == 3
          and [f["estado"] for f in lote_c["fotos"]]
          == ["procesada", "procesada"] + ["no_procesada_por_cuota"] * 3)
    check("corte por cuota: causa del lote visible y lote_parcial=True",
          lote_c["resumen"]["lote_parcial"]
          and "claves del modelo agotadas" in (lote_c["resumen"]["causa_lote_parcial"] or ""))

    # 4) una foto revienta el pipeline: queda como error CON traza, el lote sigue
    def _ejecutar_explota(ruta, tipo):
        if ruta == "mala.jpg":
            raise RuntimeError("FIXTURE AUTOTEST boom")
        return _Resultado("CUMPLE", [_Criterio("c1", "CUMPLE")])
    lote_e = procesar_lote(["ok.jpg", "mala.jpg", "ok2.jpg"], "e", None, _ejecutar_explota)
    err = lote_e["fotos"][1]
    check("foto con error: estado=error, traza visible, lote continúa",
          err["estado"] == "error" and "boom" in err["resumen_ejecutivo"]
          and lote_e["fotos"][2]["estado"] == "procesada")
    check("foto con error: cuenta como lote_parcial",
          lote_e["resumen"]["lote_parcial"] and lote_e["resumen"]["fotos_con_error"] == 1)

    # 5) bloqueado por mandatory sin criterios: fila sintética visible
    res_b = {"x.jpg": _Resultado("GRAVE", [], puede_continuar=False,
                                 resumen="Pipeline detenido en PASO 1 (mandatory)")}
    lote_b = procesar_lote(["x.jpg"], "e", None, lambda r, t: res_b[r])
    fila = lote_b["fotos"][0]["criterios_no_cumple"]
    check("bloqueo mandatory sin criterios: fila sintética con el resumen",
          len(fila) == 1 and fila[0]["criterio"] == "pipeline_bloqueado_mandatory"
          and "PASO 1" in fila[0]["razon"])

    # 6) guards de entrada + JSON serializable
    for nombre, kwargs in [("lote vacío aborta", dict(fotos=[], etapa_activa="e")),
                           ("etapa vacía aborta", dict(fotos=["a.jpg"], etapa_activa="  "))]:
        try:
            procesar_lote(tipo_foto_default=None, ejecutar_fn=lambda r, t: None, **kwargs)
            check(nombre, False)
        except ErrorLote:
            check(nombre, True)
    check("resultado JSON-serializable e íntegro",
          json.loads(json.dumps(lote_c, ensure_ascii=False))["meta"]["fotos_totales"] == 5)

    # 7) tipo_foto: "auto"/None pasan None; explícito pasa tal cual
    tipos_vistos = []
    def _espia(ruta, tipo):
        tipos_vistos.append(tipo)
        return _Resultado("CUMPLE", [])
    procesar_lote(["a.jpg"], "e", "auto", _espia)
    procesar_lote(["a.jpg"], "e", None, _espia)
    procesar_lote(["a.jpg"], "e", "focal_show", _espia)
    check("tipo_foto: auto/None -> None; explícito se respeta",
          tipos_vistos == [None, None, "focal_show"])

    print(f"\nAUTOTEST LOTE/RUNNER: {'PASS' if not fallas else 'FAIL'} ({len(fallas)} falla(s))")
    return len(fallas)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "autotest":
        sys.exit(1 if autotest() else 0)
    print("Uso: python -m lote.runner autotest\n"
          "Para correr un lote real usa verificar_lote.py (raíz del repo).")
    sys.exit(2)
