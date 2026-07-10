# -*- coding: utf-8 -*-
"""
arnes_benchmark.py — Arnés de benchmark de Motor 1 contra ground truth humano.

Reconstrucción desde cero (Sesión Z, 8 Jul 2026) — el arnés del 7 Jul nunca
llegó al remoto. Regla nueva: commit + push INMEDIATO en cuanto el autotest
pase, antes de seguir iterando.

Compara las detecciones de Motor 1 contra el ground truth de revisión humana
(46 hallazgos reales de piso) en 4 categorías por (foto, criterio):

  ACIERTO         — el sistema detecta lo mismo que el ground truth.
  HALLAZGO        — el sistema detecta algo que el ground truth NO tiene.
                    Queda PENDIENTE_REVISION hasta que un humano lo clasifique
                    (archivo de revisión) como HALLAZGO_REAL (detección válida
                    que el humano no anotó) o FALSO_POSITIVO.
  FALSO_POSITIVO  — hallazgo del sistema revisado por humano como no-aplica.
  FALSO_NEGATIVO  — el ground truth lo tiene y el sistema no lo detectó.
                    (Esperado en la mayoría de los gaps de capa1 — no es bug,
                    por eso el resumen desglosa por `gap`.)

Reglas especiales del ground truth real:
  - gap=YA_CUBIERTO: si el sistema lo detecta es ACIERTO (no "hallazgo nuevo");
    si NO lo detecta es FALSO_NEGATIVO con bug_esperado=true (el sistema ya
    debería cubrirlo — es bug a reportar, no conocimiento faltante).
  - gap=CUMPLE_ESPERADO (ej. F13 brillo, corregido Sesión CC): CONTROL NEGATIVO
    — lo correcto es que el sistema NO detecte nada ahí (el criterio se cumple
    de verdad). Si NO detecta = CUMPLE_CORRECTO (no cuenta ni como ACIERTO ni
    como FALSO_NEGATIVO; queda fuera del denominador de ambos %). Si SÍ detecta
    (marcó un problema donde no lo hay) = FALSO_POSITIVO.
  - severidad CONDICIONAL (ej. F10 tallaje): se preserva el string tal cual
    y se marca severidad_condicional=true en el detalle. No rompe nada.

Entradas (rutas explícitas, sin defaults a datos reales — mismo principio que
swap_capa2_produccion.mjs):
  ground truth CSV : foto_id,criterio_id,criterio,familia,severidad,
                     tipo_evaluacion,gap
                     (criterio_id puede ir vacío → el match cae a texto
                     normalizado de `criterio`)
  resultados JSON  : {"fotos": [{"foto_id", "tiempo_segundos",
                     "detecciones": [{"criterio_id","criterio","veredicto",
                     "razon"}]}]}
                     (lo produce correr_motor1_benchmark.py)
  revisión CSV opt.: foto_id,criterio_id,clasificacion
                     clasificacion ∈ {FALSO_POSITIVO, HALLAZGO_REAL}

Salidas:
  benchmark_detalle.json / benchmark_detalle.csv — fila por (foto, criterio)
  benchmark_resumen.json — conteos, porcentajes (numerador/denominador
  explícitos), tiempo total del sistema vs. estimado humano (6-10 min/foto).

Uso:
  python arnes_benchmark.py autotest
  python arnes_benchmark.py comparar --ground-truth GT.csv --resultados R.json
         [--revision REV.csv] --salida-dir DIR

Sin IA, sin dependencias fuera de stdlib. PASO 0 obligatorio: `autotest`
corre SIEMPRE como gate dentro de `comparar` — si un caso falla, no se
procesa nada real (mismo patrón que validator.py / swap_capa2_produccion.mjs).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from pathlib import Path

# ── Constantes de categorías y reglas ──────────────────────────────

CAT_ACIERTO         = "ACIERTO"
CAT_HALLAZGO        = "HALLAZGO"
CAT_FALSO_POSITIVO  = "FALSO_POSITIVO"
CAT_FALSO_NEGATIVO  = "FALSO_NEGATIVO"
CAT_CUMPLE_CORRECTO = "CUMPLE_CORRECTO"   # control negativo: correcto NO detectar

SUB_PENDIENTE     = "PENDIENTE_REVISION"
SUB_HALLAZGO_REAL = "HALLAZGO_REAL"

GAP_YA_CUBIERTO     = "YA_CUBIERTO"
GAP_CUMPLE_ESPERADO = "CUMPLE_ESPERADO"

CLASIFICACIONES_REVISION = {CAT_FALSO_POSITIVO, SUB_HALLAZGO_REAL}

COLUMNAS_GT = ["foto_id", "criterio_id", "criterio", "familia",
               "severidad", "tipo_evaluacion", "gap"]
COLUMNAS_REVISION = ["foto_id", "criterio_id", "clasificacion"]

MINUTOS_HUMANO_MIN = 6
MINUTOS_HUMANO_MAX = 10


class ErrorArnes(Exception):
    """Error de datos de entrada — aborta sin escribir nada (nunca silencioso)."""


# ── Normalización para matching ────────────────────────────────────

def _normalizar(texto: str) -> str:
    """Minúsculas, sin acentos, whitespace colapsado, sin puntuación en bordes.

    Misma filosofía que _canonizar de pipeline.py / _norm_fewshot de
    validator.py: comparar contenido, no tipografía.
    """
    if texto is None:
        return ""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = " ".join(t.lower().split())
    return t.strip(" .,;:!?\"'")


def _clave_match(criterio_id: str, criterio_texto: str) -> str:
    """Clave de matching: id normalizado si existe, si no texto normalizado."""
    cid = _normalizar(criterio_id)
    if cid:
        return f"id::{cid}"
    txt = _normalizar(criterio_texto)
    if txt:
        return f"txt::{txt}"
    raise ErrorArnes("Fila sin criterio_id NI texto de criterio — no hay clave de match posible.")


# ── Carga y validación de entradas ─────────────────────────────────

def cargar_ground_truth(ruta: Path) -> list[dict]:
    """Lee el CSV de ground truth. Valida columnas y duplicados. Aborta si algo no calza."""
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        columnas = [c.strip() for c in (lector.fieldnames or [])]
        faltantes = [c for c in COLUMNAS_GT if c not in columnas]
        if faltantes:
            raise ErrorArnes(f"Ground truth sin columnas requeridas: {faltantes}. "
                             f"Esperadas: {COLUMNAS_GT}")
        filas = [dict(r) for r in lector]

    if not filas:
        raise ErrorArnes("Ground truth vacío — no hay nada que comparar.")

    vistos: set[tuple[str, str]] = set()
    for i, fila in enumerate(filas, start=2):   # línea real del CSV (1 = header)
        foto = _normalizar(fila.get("foto_id"))
        if not foto:
            raise ErrorArnes(f"Ground truth línea {i}: foto_id vacío.")
        clave = (foto, _clave_match(fila.get("criterio_id", ""), fila.get("criterio", "")))
        if clave in vistos:
            raise ErrorArnes(f"Ground truth línea {i}: duplicado exacto de "
                             f"(foto_id, criterio) = {clave}. Resolver antes de correr.")
        vistos.add(clave)
    return filas


def cargar_resultados(ruta: Path) -> list[dict]:
    """Lee el JSON de resultados del sistema. Valida estructura y duplicados."""
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)

    fotos = datos.get("fotos")
    if not isinstance(fotos, list):
        raise ErrorArnes('Resultados sin lista "fotos" — formato inválido.')

    fotos_vistas: set[str] = set()
    for foto in fotos:
        fid = _normalizar(foto.get("foto_id"))
        if not fid:
            raise ErrorArnes("Resultados: foto sin foto_id.")
        if fid in fotos_vistas:
            raise ErrorArnes(f"Resultados: foto_id duplicado '{foto.get('foto_id')}'.")
        fotos_vistas.add(fid)
        tiempo = foto.get("tiempo_segundos")
        if not isinstance(tiempo, (int, float)) or tiempo < 0:
            raise ErrorArnes(f"Resultados foto {foto.get('foto_id')}: tiempo_segundos "
                             f"inválido ({tiempo!r}) — debe ser número >= 0.")
        detecciones = foto.get("detecciones", [])
        if not isinstance(detecciones, list):
            raise ErrorArnes(f"Resultados foto {foto.get('foto_id')}: detecciones no es lista.")
        claves: set[str] = set()
        for det in detecciones:
            clave = _clave_match(det.get("criterio_id", ""), det.get("criterio", ""))
            if clave in claves:
                raise ErrorArnes(f"Resultados foto {foto.get('foto_id')}: detección "
                                 f"duplicada {clave}.")
            claves.add(clave)
    return fotos


def cargar_revision(ruta: Path | None) -> dict[tuple[str, str], str]:
    """Lee el CSV de revisión humana de hallazgos (opcional).

    Devuelve {(foto_id_norm, clave_match): clasificacion}.
    """
    if ruta is None:
        return {}
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        columnas = [c.strip() for c in (lector.fieldnames or [])]
        faltantes = [c for c in COLUMNAS_REVISION if c not in columnas]
        if faltantes:
            raise ErrorArnes(f"Revisión sin columnas requeridas: {faltantes}.")
        revision: dict[tuple[str, str], str] = {}
        for i, fila in enumerate(lector, start=2):
            clasif = (fila.get("clasificacion") or "").strip().upper()
            if clasif not in CLASIFICACIONES_REVISION:
                raise ErrorArnes(f"Revisión línea {i}: clasificacion '{clasif}' fuera de "
                                 f"catálogo {sorted(CLASIFICACIONES_REVISION)}.")
            clave = (_normalizar(fila.get("foto_id")),
                     _clave_match(fila.get("criterio_id", ""), ""))
            if clave in revision:
                raise ErrorArnes(f"Revisión línea {i}: entrada duplicada {clave}.")
            revision[clave] = clasif
    return revision


# ── Comparación núcleo ─────────────────────────────────────────────

def _es_condicional(severidad: str) -> bool:
    return "CONDICIONAL" in (severidad or "").upper()


def comparar(ground_truth: list[dict],
             resultados_fotos: list[dict],
             revision: dict[tuple[str, str], str] | None = None) -> dict:
    """Compara GT vs. detecciones del sistema. Devuelve {"detalle": [...], "resumen": {...}}.

    Matching determinista por (foto_id, clave) donde clave = criterio_id
    normalizado o, en su ausencia, texto normalizado. 1-a-1: cada fila de GT
    matchea a lo sumo una detección y viceversa.
    """
    revision = revision or {}

    # Índice de detecciones por (foto, clave)
    det_por_clave: dict[tuple[str, str], dict] = {}
    tiempos: dict[str, float] = {}
    for foto in resultados_fotos:
        fid = _normalizar(foto["foto_id"])
        tiempos[fid] = float(foto["tiempo_segundos"])
        for det in foto.get("detecciones", []):
            clave = (fid, _clave_match(det.get("criterio_id", ""), det.get("criterio", "")))
            det_por_clave[clave] = det

    detalle: list[dict] = []
    claves_matcheadas: set[tuple[str, str]] = set()

    # 1) Recorrer ground truth → ACIERTO / FALSO_NEGATIVO / CUMPLE_CORRECTO / FP
    for fila in ground_truth:
        fid = _normalizar(fila["foto_id"])
        clave = (fid, _clave_match(fila.get("criterio_id", ""), fila.get("criterio", "")))
        gap = (fila.get("gap") or "").strip()
        gap_u = gap.upper()
        ya_cubierto     = gap_u == GAP_YA_CUBIERTO
        cumple_esperado = gap_u == GAP_CUMPLE_ESPERADO
        det = det_por_clave.get(clave)
        bug_esperado = False

        if cumple_esperado:
            # Control negativo: lo CORRECTO es que el sistema NO detecte nada.
            # Se matchea la clave en ambas ramas para que una detección aquí no
            # caiga además a HALLAZGO en el paso 2.
            claves_matcheadas.add(clave)
            if det is not None:
                categoria, subcategoria = CAT_FALSO_POSITIVO, ""   # marcó un no-problema
            else:
                categoria, subcategoria = CAT_CUMPLE_CORRECTO, ""  # correcto no detectar
        elif det is not None:
            claves_matcheadas.add(clave)
            categoria, subcategoria = CAT_ACIERTO, ""
        else:
            categoria, subcategoria = CAT_FALSO_NEGATIVO, ""
            # YA_CUBIERTO no detectado = el sistema ya debía cubrirlo → bug, no gap.
            bug_esperado = ya_cubierto

        detalle.append({
            "foto_id":               fila["foto_id"].strip(),
            "criterio_id":           (fila.get("criterio_id") or "").strip(),
            "criterio":              (fila.get("criterio") or "").strip(),
            "familia":               (fila.get("familia") or "").strip(),
            "severidad":             (fila.get("severidad") or "").strip(),
            "tipo_evaluacion":       (fila.get("tipo_evaluacion") or "").strip(),
            "gap":                   gap,
            "categoria":             categoria,
            "subcategoria":          subcategoria,
            "severidad_condicional": _es_condicional(fila.get("severidad", "")),
            "bug_esperado":          bug_esperado,
            "detalle":               (det.get("razon", "") if det else ""),
            "origen":                "ground_truth",
        })

    # 2) Detecciones sin match en GT → HALLAZGO (o su revisión humana)
    for (fid, clave_det), det in det_por_clave.items():
        if (fid, clave_det) in claves_matcheadas:
            continue
        clasif = revision.get((fid, clave_det))
        if clasif == CAT_FALSO_POSITIVO:
            categoria, subcategoria = CAT_FALSO_POSITIVO, ""
        elif clasif == SUB_HALLAZGO_REAL:
            categoria, subcategoria = CAT_HALLAZGO, SUB_HALLAZGO_REAL
        else:
            categoria, subcategoria = CAT_HALLAZGO, SUB_PENDIENTE

        detalle.append({
            "foto_id":               det.get("foto_id", "") or fid.upper(),
            "criterio_id":           (det.get("criterio_id") or "").strip(),
            "criterio":              (det.get("criterio") or "").strip(),
            "familia":               "",
            "severidad":             (det.get("veredicto") or "").strip(),
            "tipo_evaluacion":       "",
            "gap":                   "",
            "categoria":             categoria,
            "subcategoria":          subcategoria,
            "severidad_condicional": False,
            "bug_esperado":          False,
            "detalle":               (det.get("razon") or "").strip(),
            "origen":                "sistema",
        })

    # ── Resumen ────────────────────────────────────────────────────
    conteo = {c: 0 for c in (CAT_ACIERTO, CAT_HALLAZGO, CAT_FALSO_POSITIVO,
                             CAT_FALSO_NEGATIVO, CAT_CUMPLE_CORRECTO)}
    fn_por_gap: dict[str, int] = {}
    bugs_esperados = []
    for fila in detalle:
        conteo[fila["categoria"]] += 1
        if fila["categoria"] == CAT_FALSO_NEGATIVO:
            g = fila["gap"] or "(sin gap)"
            fn_por_gap[g] = fn_por_gap.get(g, 0) + 1
            if fila["bug_esperado"]:
                bugs_esperados.append(f"{fila['foto_id']}:{fila['criterio_id'] or fila['criterio']}")

    total_gt = len(ground_truth)
    # Los controles CUMPLE_ESPERADO no esperan detección: quedan fuera del
    # denominador de acierto y falso_negativo (no son "hallazgos a encontrar").
    n_cumple_esperado = sum(1 for f in ground_truth
                            if (f.get("gap") or "").strip().upper() == GAP_CUMPLE_ESPERADO)
    total_esperan_deteccion = total_gt - n_cumple_esperado
    total_detecciones = len(det_por_clave)
    hallazgos_pendientes = sum(1 for f in detalle
                               if f["categoria"] == CAT_HALLAZGO
                               and f["subcategoria"] == SUB_PENDIENTE)

    def pct(num: int, den: int) -> float:
        return round(100.0 * num / den, 1) if den else 0.0

    tiempo_total_s = round(sum(tiempos.values()), 2)
    n_fotos = len(tiempos)

    resumen = {
        "totales": {
            "hallazgos_ground_truth":       total_gt,
            "hallazgos_esperan_deteccion":  total_esperan_deteccion,
            "controles_cumple_esperado":    n_cumple_esperado,
            "detecciones_sistema":          total_detecciones,
            "fotos_sistema":                n_fotos,
            **conteo,
            "hallazgos_pendientes_de_revision": hallazgos_pendientes,
        },
        "porcentajes": {
            "acierto":        {"valor": pct(conteo[CAT_ACIERTO], total_esperan_deteccion),
                               "numerador": conteo[CAT_ACIERTO],
                               "denominador": total_esperan_deteccion,
                               "base": "hallazgos del ground truth que esperan detección"},
            "falso_negativo": {"valor": pct(conteo[CAT_FALSO_NEGATIVO], total_esperan_deteccion),
                               "numerador": conteo[CAT_FALSO_NEGATIVO],
                               "denominador": total_esperan_deteccion,
                               "base": "hallazgos del ground truth que esperan detección"},
            "falso_positivo": {"valor": pct(conteo[CAT_FALSO_POSITIVO], total_detecciones),
                               "numerador": conteo[CAT_FALSO_POSITIVO],
                               "denominador": total_detecciones,
                               "base": "detecciones del sistema"},
        },
        "falsos_negativos_por_gap": dict(sorted(fn_por_gap.items())),
        "bugs_esperados_no_detectados": bugs_esperados,
        "tiempo": {
            "sistema_total_segundos":    tiempo_total_s,
            "sistema_promedio_segundos": round(tiempo_total_s / n_fotos, 2) if n_fotos else 0.0,
            "humano_estimado_minutos":   {"min": n_fotos * MINUTOS_HUMANO_MIN,
                                          "max": n_fotos * MINUTOS_HUMANO_MAX,
                                          "supuesto": f"{MINUTOS_HUMANO_MIN}-{MINUTOS_HUMANO_MAX} min/foto × {n_fotos} fotos"},
        },
    }
    return {"detalle": detalle, "resumen": resumen}


# ── Salidas ────────────────────────────────────────────────────────

def escribir_salidas(resultado: dict, salida_dir: Path) -> list[Path]:
    salida_dir.mkdir(parents=True, exist_ok=True)
    rutas = []

    ruta_json = salida_dir / "benchmark_detalle.json"
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(resultado["detalle"], f, ensure_ascii=False, indent=2)
    rutas.append(ruta_json)

    ruta_csv = salida_dir / "benchmark_detalle.csv"
    campos = ["foto_id", "criterio_id", "criterio", "familia", "severidad",
              "tipo_evaluacion", "gap", "categoria", "subcategoria",
              "severidad_condicional", "bug_esperado", "detalle", "origen"]
    with open(ruta_csv, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(resultado["detalle"])
    rutas.append(ruta_csv)

    ruta_resumen = salida_dir / "benchmark_resumen.json"
    with open(ruta_resumen, "w", encoding="utf-8") as f:
        json.dump(resultado["resumen"], f, ensure_ascii=False, indent=2)
    rutas.append(ruta_resumen)
    return rutas


# ── AUTOTEST — gate obligatorio ────────────────────────────────────
# Todos los fixtures son 100% FICTICIOS ("FIXTURE AUTOTEST"), sin ningún
# criterio real de Liverpool — regla fija #1 del proyecto.

def _gt_fixture() -> list[dict]:
    def fila(foto, cid, texto, gap="capa1", severidad="OBSERVACION", tipo="binario"):
        return {"foto_id": foto, "criterio_id": cid, "criterio": texto,
                "familia": "familia_ficticia", "severidad": severidad,
                "tipo_evaluacion": tipo, "gap": gap}
    return [
        # FX1: un acierto + un falso negativo capa1
        fila("FX1", "criterio_ficticio_a", "FIXTURE AUTOTEST criterio a"),
        fila("FX1", "criterio_ficticio_b", "FIXTURE AUTOTEST criterio b"),
        # FX2: severidad CONDICIONAL (caso F10 tallaje) — detectado
        fila("FX2", "criterio_ficticio_c", "FIXTURE AUTOTEST criterio c",
             severidad="CONDICIONAL (escala con hueco visible = GRAVE)", tipo="escala"),
        # FX3: YA_CUBIERTO detectado → ACIERTO (caso F13 brillo)
        fila("FX3", "criterio_ficticio_brillo", "FIXTURE AUTOTEST brillo bajo",
             gap="YA_CUBIERTO", severidad="N/A", tipo="N/A"),
        # FX4: YA_CUBIERTO NO detectado → FALSO_NEGATIVO + bug_esperado
        fila("FX4", "criterio_ficticio_nitidez", "FIXTURE AUTOTEST nitidez",
             gap="YA_CUBIERTO", severidad="N/A", tipo="N/A"),
        # FX5: match por TEXTO (sin criterio_id)
        fila("FX5", "", "FIXTURE AUTOTEST solo texto, Sin ID."),
        # FX6: foto donde el sistema no detecta NADA → todo FALSO_NEGATIVO
        fila("FX6", "criterio_ficticio_d", "FIXTURE AUTOTEST criterio d"),
        fila("FX6", "criterio_ficticio_e", "FIXTURE AUTOTEST criterio e"),
    ]


def _resultados_fixture() -> list[dict]:
    def det(cid, texto="", veredicto="GRAVE", razon="FIXTURE AUTOTEST razon"):
        return {"criterio_id": cid, "criterio": texto,
                "veredicto": veredicto, "razon": razon}
    return [
        {"foto_id": "FX1", "tiempo_segundos": 10.0, "detecciones": [
            det("criterio_ficticio_a"),                     # acierto
            det("criterio_ficticio_extra1"),                # hallazgo → revisado FALSO_POSITIVO
            det("criterio_ficticio_extra2"),                # hallazgo → revisado HALLAZGO_REAL
        ]},
        {"foto_id": "FX2", "tiempo_segundos": 12.5, "detecciones": [
            det("criterio_ficticio_c"),                     # acierto CONDICIONAL
        ]},
        {"foto_id": "FX3", "tiempo_segundos": 8.0, "detecciones": [
            det("criterio_ficticio_brillo"),                # acierto YA_CUBIERTO
        ]},
        {"foto_id": "FX4", "tiempo_segundos": 9.0, "detecciones": []},   # FN + bug_esperado
        {"foto_id": "FX5", "tiempo_segundos": 7.5, "detecciones": [
            # sin id — matchea por texto normalizado (tipografía distinta a propósito)
            det("", texto="  fixture autotest solo texto,  sin id"),
        ]},
        {"foto_id": "FX6", "tiempo_segundos": 11.0, "detecciones": []},  # sistema no detecta nada
        # FX7: foto con 0 hallazgos en GT — toda detección es HALLAZGO pendiente
        {"foto_id": "FX7", "tiempo_segundos": 6.0, "detecciones": [
            det("criterio_ficticio_extra3"),
        ]},
    ]


def _revision_fixture() -> dict[tuple[str, str], str]:
    return {
        (_normalizar("FX1"), "id::criterio_ficticio_extra1"): CAT_FALSO_POSITIVO,
        (_normalizar("FX1"), "id::criterio_ficticio_extra2"): SUB_HALLAZGO_REAL,
    }


def autotest() -> int:
    """Casos borde explícitos. Devuelve nº de fallas (0 = PASS)."""
    fallas: list[str] = []

    def check(nombre: str, condicion: bool, detalle: str = ""):
        estado = "PASS" if condicion else "FAIL"
        print(f"  [{estado}] {nombre}" + (f" — {detalle}" if not condicion and detalle else ""))
        if not condicion:
            fallas.append(nombre)

    r = comparar(_gt_fixture(), _resultados_fixture(), _revision_fixture())
    detalle = {(_normalizar(f["foto_id"]),
                _clave_match(f["criterio_id"], f["criterio"])): f
               for f in r["detalle"]}

    def cat(foto, clave):
        return detalle[(_normalizar(foto), clave)]["categoria"]

    # 1. Caso mixto básico
    check("acierto simple",        cat("FX1", "id::criterio_ficticio_a") == CAT_ACIERTO)
    check("falso negativo capa1",  cat("FX1", "id::criterio_ficticio_b") == CAT_FALSO_NEGATIVO)
    # 2. Revisión humana de hallazgos
    check("hallazgo revisado como falso positivo",
          cat("FX1", "id::criterio_ficticio_extra1") == CAT_FALSO_POSITIVO)
    fila_hr = detalle[(_normalizar("FX1"), "id::criterio_ficticio_extra2")]
    check("hallazgo revisado como hallazgo real",
          fila_hr["categoria"] == CAT_HALLAZGO and fila_hr["subcategoria"] == SUB_HALLAZGO_REAL)
    # 3. Severidad CONDICIONAL: categoriza normal + flag
    fila_cond = detalle[(_normalizar("FX2"), "id::criterio_ficticio_c")]
    check("condicional categoriza como acierto", fila_cond["categoria"] == CAT_ACIERTO)
    check("condicional flageado", fila_cond["severidad_condicional"] is True)
    check("condicional preserva severidad textual",
          fila_cond["severidad"].startswith("CONDICIONAL"))
    # 4. YA_CUBIERTO
    check("ya_cubierto detectado es ACIERTO (no hallazgo nuevo)",
          cat("FX3", "id::criterio_ficticio_brillo") == CAT_ACIERTO)
    fila_bug = detalle[(_normalizar("FX4"), "id::criterio_ficticio_nitidez")]
    check("ya_cubierto no detectado es FALSO_NEGATIVO",
          fila_bug["categoria"] == CAT_FALSO_NEGATIVO)
    check("ya_cubierto no detectado marca bug_esperado", fila_bug["bug_esperado"] is True)
    check("bug esperado listado en resumen",
          r["resumen"]["bugs_esperados_no_detectados"] == ["FX4:criterio_ficticio_nitidez"])
    # 5. Match por texto sin criterio_id (tipografía distinta)
    check("match por texto normalizado",
          cat("FX5", "txt::fixture autotest solo texto, sin id") == CAT_ACIERTO)
    # 6. Foto donde el sistema no detecta nada → todos FN
    check("sistema sin detecciones: todo FN",
          cat("FX6", "id::criterio_ficticio_d") == CAT_FALSO_NEGATIVO
          and cat("FX6", "id::criterio_ficticio_e") == CAT_FALSO_NEGATIVO)
    # 7. Foto con 0 hallazgos en GT → detección es HALLAZGO pendiente
    fila_fx7 = detalle[(_normalizar("FX7"), "id::criterio_ficticio_extra3")]
    check("foto sin GT: deteccion es HALLAZGO pendiente",
          fila_fx7["categoria"] == CAT_HALLAZGO and fila_fx7["subcategoria"] == SUB_PENDIENTE)
    # 8. Conteos y porcentajes exactos (calculados a mano sobre el fixture)
    t = r["resumen"]["totales"]
    # Fixture a mano: GT = 8 filas (aciertos: a, c, brillo, texto → 4; FN: b,
    # nitidez, d, e → 4). Detecciones = 7 (a, extra1, extra2, c, brillo,
    # texto, extra3): FP = 1 (extra1), HALLAZGO = 2 (extra2 real + extra3).
    check("conteo acierto = 4",        t[CAT_ACIERTO] == 4)
    check("conteo falso_negativo = 4", t[CAT_FALSO_NEGATIVO] == 4)
    check("conteo falso_positivo = 1", t[CAT_FALSO_POSITIVO] == 1)
    check("conteo hallazgo = 2",       t[CAT_HALLAZGO] == 2)
    check("hallazgos pendientes = 1",  t["hallazgos_pendientes_de_revision"] == 1)
    check("total detecciones = 7",     t["detecciones_sistema"] == 7)
    p = r["resumen"]["porcentajes"]
    check("% acierto = 4/8 = 50.0",    p["acierto"]["valor"] == 50.0)
    check("% FN = 4/8 = 50.0",         p["falso_negativo"]["valor"] == 50.0)
    check("% FP = 1/7 = 14.3",         p["falso_positivo"]["valor"] == 14.3)
    # 9. FN por gap desglosado (capa1=3, YA_CUBIERTO=1)
    check("FN por gap desglosado",
          r["resumen"]["falsos_negativos_por_gap"] == {"YA_CUBIERTO": 1, "capa1": 3})
    # 10. Tiempos: suma exacta + estimado humano
    tiempo = r["resumen"]["tiempo"]
    check("tiempo total = suma exacta", tiempo["sistema_total_segundos"] == 64.0)
    check("humano estimado 6-10 min/foto",
          tiempo["humano_estimado_minutos"] == {"min": 42, "max": 70,
                                                "supuesto": "6-10 min/foto × 7 fotos"})
    # 11. Guards de entrada — deben ABORTAR, no pasar de largo
    def espera_error(nombre, fn):
        try:
            fn()
            check(nombre, False, "no abortó")
        except ErrorArnes:
            check(nombre, True)

    gt_dup = _gt_fixture() + [_gt_fixture()[0]]
    espera_error("GT duplicado aborta", lambda: _validar_gt_en_memoria(gt_dup))
    espera_error("GT vacío aborta",     lambda: _validar_gt_en_memoria([]))
    espera_error("fila sin id ni texto aborta",
                 lambda: _clave_match("", "   "))
    espera_error("revisión con clasificación inválida aborta",
                 lambda: _validar_revision_en_memoria(
                     [{"foto_id": "FX1", "criterio_id": "x", "clasificacion": "OTRA_COSA"}]))
    espera_error("resultados con tiempo negativo aborta",
                 lambda: _validar_resultados_en_memoria(
                     [{"foto_id": "FX1", "tiempo_segundos": -1, "detecciones": []}]))
    espera_error("resultados con foto duplicada aborta",
                 lambda: _validar_resultados_en_memoria(
                     [{"foto_id": "FX1", "tiempo_segundos": 1, "detecciones": []},
                      {"foto_id": "fx1", "tiempo_segundos": 1, "detecciones": []}]))

    # 12. gap=CUMPLE_ESPERADO — control negativo (caso F13 brillo, Sesión CC).
    #     Fixture propio y aislado para no tocar los conteos del fixture principal.
    gt_ce = [{"foto_id": "FCE", "criterio_id": "imagen_oscura",
              "criterio": "FIXTURE AUTOTEST brillo aceptable", "familia": "tecnico",
              "severidad": "N/A", "tipo_evaluacion": "N/A", "gap": "CUMPLE_ESPERADO"}]
    # 12a. sistema NO detecta → CUMPLE_CORRECTO, no cuenta como acierto ni FN
    r_ok = comparar(gt_ce, [{"foto_id": "FCE", "tiempo_segundos": 1.0, "detecciones": []}])
    t_ok = r_ok["resumen"]["totales"]
    check("cumple_esperado no detectado = CUMPLE_CORRECTO",
          r_ok["detalle"][0]["categoria"] == CAT_CUMPLE_CORRECTO)
    check("cumple_esperado no cuenta como acierto ni FN",
          t_ok[CAT_ACIERTO] == 0 and t_ok[CAT_FALSO_NEGATIVO] == 0)
    check("cumple_esperado fuera del denominador de acierto/FN",
          r_ok["resumen"]["porcentajes"]["acierto"]["denominador"] == 0
          and t_ok["controles_cumple_esperado"] == 1
          and t_ok["hallazgos_esperan_deteccion"] == 0)
    # 12b. sistema SÍ detecta (marca un no-problema) → FALSO_POSITIVO, no HALLAZGO
    r_fp = comparar(gt_ce, [{"foto_id": "FCE", "tiempo_segundos": 1.0, "detecciones": [
        {"criterio_id": "imagen_oscura", "criterio": "", "veredicto": "GRAVE",
         "razon": "FIXTURE marcó oscura una foto que no lo está"}]}])
    check("cumple_esperado detectado = FALSO_POSITIVO",
          r_fp["detalle"][0]["categoria"] == CAT_FALSO_POSITIVO)
    check("cumple_esperado detectado no genera HALLAZGO duplicado",
          r_fp["resumen"]["totales"][CAT_HALLAZGO] == 0)

    print(f"\nAUTOTEST: {'PASS' if not fallas else 'FAIL'} "
          f"({len(fallas)} falla(s) de {_contar_checks()} casos)")
    return len(fallas)


_N_CHECKS = 0


def _contar_checks() -> str:
    return "todos los"   # informativo; el conteo exacto sale línea por línea


# Validadores en memoria (mismos guards que cargar_*, sin tocar disco) —
# los usa el autotest para probar los aborts sin fixtures en archivos.

def _validar_gt_en_memoria(filas: list[dict]) -> None:
    if not filas:
        raise ErrorArnes("Ground truth vacío — no hay nada que comparar.")
    vistos = set()
    for fila in filas:
        clave = (_normalizar(fila.get("foto_id")),
                 _clave_match(fila.get("criterio_id", ""), fila.get("criterio", "")))
        if clave in vistos:
            raise ErrorArnes(f"Duplicado {clave}")
        vistos.add(clave)


def _validar_revision_en_memoria(filas: list[dict]) -> None:
    for fila in filas:
        clasif = (fila.get("clasificacion") or "").strip().upper()
        if clasif not in CLASIFICACIONES_REVISION:
            raise ErrorArnes(f"clasificacion '{clasif}' fuera de catálogo")


def _validar_resultados_en_memoria(fotos: list[dict]) -> None:
    vistas = set()
    for foto in fotos:
        fid = _normalizar(foto.get("foto_id"))
        if fid in vistas:
            raise ErrorArnes(f"foto_id duplicado {fid}")
        vistas.add(fid)
        tiempo = foto.get("tiempo_segundos")
        if not isinstance(tiempo, (int, float)) or tiempo < 0:
            raise ErrorArnes(f"tiempo inválido {tiempo!r}")


# ── CLI ────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("autotest", help="corre los casos borde (gate obligatorio)")

    p_cmp = sub.add_parser("comparar", help="compara GT vs resultados del sistema")
    p_cmp.add_argument("--ground-truth", required=True, type=Path)
    p_cmp.add_argument("--resultados",   required=True, type=Path)
    p_cmp.add_argument("--revision",     type=Path, default=None)
    p_cmp.add_argument("--salida-dir",   required=True, type=Path)

    args = parser.parse_args(argv)

    if args.comando == "autotest":
        return 1 if autotest() else 0

    # comparar: PASO 0 — autotest como gate, igual que validator.py
    print("PASO 0 — autotest (gate obligatorio):")
    if autotest():
        print("ABORTADO: el autotest falló — no se procesa ningún dato real.")
        return 1

    try:
        gt         = cargar_ground_truth(args.ground_truth)
        resultados = cargar_resultados(args.resultados)
        revision   = cargar_revision(args.revision)
        resultado  = comparar(gt, resultados, revision)
        rutas      = escribir_salidas(resultado, args.salida_dir)
    except ErrorArnes as e:
        print(f"ABORTADO: {e}")
        return 1

    t = resultado["resumen"]["totales"]
    p = resultado["resumen"]["porcentajes"]
    print(f"\nComparación completada: GT={t['hallazgos_ground_truth']}, "
          f"sistema={t['detecciones_sistema']} detecciones en {t['fotos_sistema']} fotos.")
    print(f"  ACIERTO={t['ACIERTO']} ({p['acierto']['valor']}%)  "
          f"FN={t['FALSO_NEGATIVO']} ({p['falso_negativo']['valor']}%)  "
          f"FP={t['FALSO_POSITIVO']} ({p['falso_positivo']['valor']}%)  "
          f"HALLAZGO={t['HALLAZGO']} (pendientes: {t['hallazgos_pendientes_de_revision']})  "
          f"CUMPLE_CORRECTO={t['CUMPLE_CORRECTO']} (controles: {t['controles_cumple_esperado']})")
    for ruta in rutas:
        print(f"  -> {ruta}")   # ASCII a propósito: consolas Windows cp1252
    return 0


if __name__ == "__main__":
    sys.exit(main())
