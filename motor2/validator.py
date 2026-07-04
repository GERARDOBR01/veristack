# -*- coding: utf-8 -*-
"""Motor 2 — validador de criterios extraídos (Sesión P).

Es el filtro que decide si un criterio es confiable. Cero tolerancia a bugs
silenciosos: el AUTOTEST (fixtures propios del validator, NO conocimiento real)
corre SIEMPRE antes de tocar datos reales; si un solo caso no se detecta,
aborta sin procesar nada.

INPUT: motor2/criterios_extraidos.json (output real de extractor.py, Sesión O).

Qué hace (en orden, cada paso una función separada y testeable):
  1. validar_schema(criterio)      → lista de motivos (vacía = válido).
       Campos obligatorios, tipos, catálogos (peso/severidad/etapa/sección/
       grounding/fuente). peso según schema_conocimiento_v1.md:
       MANDATORY | RECOMMENDATION | EXCEPTION.
       DECISIÓN DOCUMENTADA: seccion_aplicable=null ES válido — el contrato de
       normalizer.py es "una de las 7 secciones o None" y en Sesión O los null
       quedaron "reportados, no forzados" (p1, GRAN, PLANOGRAMA ZAPATERÍAS,
       OUTPOS). Se cuentan aparte en el reporte, no se esconden.
  2. detectar_contaminacion_fewshot(criterio) → nº de ejemplo o None.
       Substring-test (verbatim módulo whitespace y puntuación final . , ; : —
       el PDF parte líneas y el modelo a veces agrega/quita el punto; fix
       Sesión Q: "No mezclar marcas" p31 y "No mezclar marcas." p34 son el
       mismo caso y deben flagear igual)
       contra los 3 bloques few-shot del prompt, importados de extractor.py
       (una sola fuente de verdad — extractor.py NO se toca). Los bloques
       vienen de texto real de p26/p31/p20, así que en ESAS páginas el match
       es circular-por-construcción (Sesión O). Por eso NO rechaza: solo marca
       posible_herencia_fewshot=true. NO usa el alignment_status de langextract
       (produce falsos "failed" con el prefijo [AMBIGUO] — hallazgo Sesión O).
  3. filtrar_failed(criterios)     → grounding=failed va a revision_manual.json,
       no entra al JSON validado.
  4. detectar_duplicados(criterios) → difflib.SequenceMatcher, umbral fijo 0.85,
       sobre texto normalizado (whitespace colapsado, casefold, sin prefijo
       [AMBIGUO]). Determinista, sin embeddings ni librerías nuevas. Reporta
       pares sospechosos — NO borra nada.

OUTPUT (en motor2/, respaldo .bak-<timestamp> si ya existían — nunca se pisa):
  - capa2_<slug_del_manual>_validado.json → criterios que pasaron 1 y 3
    (con el flag del paso 2). OJO: aún NO es una capa de knowledge v1.1
    (faltan id/aliases/aplica_a — paso posterior); es extracción v1.2 validada.
  - validator_report.json  → conteos exactos por categoría + pares duplicados.
  - revision_manual.json   → failed + rechazados por schema, con motivo explícito.

NO hace: no resuelve referencia_no_resuelta ni [AMBIGUO], no borra duplicados,
no toca extractor/normalizer/segmenter/consolidar ni nada de pipeline/.

Uso:
    python validator.py [ruta_criterios_extraidos.json] [--autotest]
    (--autotest corre solo los fixtures y termina)
"""
import difflib
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

MOTOR2 = Path(__file__).resolve().parent
sys.path.insert(0, str(MOTOR2))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Solo para EXAMPLES y MARCA_AMBIGUO (una sola fuente de verdad con el prompt
# real). Importar extractor NO ejecuta nada: main() está protegido.
import extractor as ex  # noqa: E402

ENTRADA_DEFAULT = MOTOR2 / "criterios_extraidos.json"
CONSOLIDADO = MOTOR2 / "manual_consolidado.json"
SALIDA_REPORTE = MOTOR2 / "validator_report.json"
SALIDA_REVISION = MOTOR2 / "revision_manual.json"

# --- Catálogos del contrato (schema_conocimiento_v1.md + schema v1.2 Sesión O) --
PESOS_VALIDOS = {"MANDATORY", "RECOMMENDATION", "EXCEPTION"}
SEVERIDADES_VALIDAS = {"GRAVE", "OBSERVACION", "NO_CALIFICA"}
ETAPAS_VALIDAS = {"E1", "E2", "E3"}
SECCIONES_VALIDAS = {"Softline", "Hardline", "Diversos", "Multimedia",
                     "Deportes", "Niño/Niña", "Hogar"}
FUENTES_VALIDAS = {"pdfplumber_text_flow", "gemini_vision"}
GROUNDINGS_VALIDOS = {"exact", "lesser", "failed"}
CAMPOS_OBLIGATORIOS = ("texto", "peso", "severidad", "condicion_libre",
                       "referencia_no_resuelta", "pagina_origen",
                       "seccion_aplicable", "etapa_aplicable",
                       "fuente_pagina", "grounding")

UMBRAL_DUPLICADOS = 0.85  # fijo por brief — determinista, sin calibración

def _norm_ws(s: str) -> str:
    return " ".join((s or "").split())


def _norm_fewshot(s: str) -> str:
    """Normalización del substring-test: whitespace colapsado + sin puntuación
    final (. , ; :). Fix Sesión Q — el mismo texto con/sin punto final debe dar
    el mismo resultado. Se aplica IGUAL al criterio y a los bloques EXAMPLES."""
    return _norm_ws(s).rstrip(".,;:")


# Bloques few-shot literales del prompt real (anclados en texto de p26/p31/p20).
BLOQUES_FEWSHOT = [(i, _norm_fewshot(e.text)) for i, e in enumerate(ex.EXAMPLES, 1)]


def _sin_ambiguo(texto: str) -> str:
    """El prefijo [AMBIGUO] lo agrega el modelo — no es contenido del manual."""
    if isinstance(texto, str) and texto.startswith(ex.MARCA_AMBIGUO):
        return texto[len(ex.MARCA_AMBIGUO):]
    return texto if isinstance(texto, str) else ""


# --- 1. Schema -------------------------------------------------------------------
def validar_schema(criterio) -> list:
    """Lista de motivos de rechazo. Vacía = criterio válido.

    Cada campo se revisa solo si está presente (la ausencia ya se reporta sola,
    para que un criterio con varios defectos liste TODOS sus motivos)."""
    if not isinstance(criterio, dict):
        return [f"el criterio no es un objeto JSON: {type(criterio).__name__}"]
    motivos = []
    faltan = [k for k in CAMPOS_OBLIGATORIOS if k not in criterio]
    if faltan:
        motivos.append(f"campos obligatorios ausentes: {faltan}")

    if "texto" in criterio and (not isinstance(criterio["texto"], str)
                                or not criterio["texto"].strip()):
        motivos.append(f"texto: debe ser string no vacío, vino {criterio['texto']!r}")

    if "peso" in criterio and criterio["peso"] not in PESOS_VALIDOS:
        motivos.append(f"peso fuera del rango de schema_conocimiento_v1.md: "
                       f"{criterio['peso']!r} (válidos: {sorted(PESOS_VALIDOS)})")

    if "severidad" in criterio and criterio["severidad"] not in SEVERIDADES_VALIDAS:
        motivos.append(f"severidad fuera de catálogo: {criterio['severidad']!r} "
                       f"(válidas: {sorted(SEVERIDADES_VALIDAS)})")

    if "condicion_libre" in criterio:
        v = criterio["condicion_libre"]
        if not (v is None or (isinstance(v, str) and v.strip())):
            motivos.append(f"condicion_libre: debe ser null o string no vacío, vino {v!r}")

    if "referencia_no_resuelta" in criterio:
        v = criterio["referencia_no_resuelta"]
        if not (v is None or isinstance(v, bool)):  # ojo: 1 == True en Python — tipo, no valor
            motivos.append(f"referencia_no_resuelta: debe ser true/false/null, vino {v!r}")

    if "pagina_origen" in criterio:
        v = criterio["pagina_origen"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            motivos.append(f"pagina_origen: debe ser entero ≥ 1, vino {v!r}")

    if "seccion_aplicable" in criterio:
        v = criterio["seccion_aplicable"]
        if not (v is None or v in SECCIONES_VALIDAS):
            motivos.append(f"seccion_aplicable fuera del set fijo: {v!r} "
                           f"(válidas: {sorted(SECCIONES_VALIDAS)} o null)")

    if "etapa_aplicable" in criterio:
        v = criterio["etapa_aplicable"]
        if v is not None:
            if (not isinstance(v, list) or not v
                    or not set(v) <= ETAPAS_VALIDAS or len(set(v)) != len(v)):
                motivos.append(f"etapa_aplicable: debe ser null o lista no vacía sin "
                               f"repetidos con valores de {sorted(ETAPAS_VALIDAS)}, vino {v!r}")

    if "fuente_pagina" in criterio and criterio["fuente_pagina"] not in FUENTES_VALIDAS:
        motivos.append(f"fuente_pagina desconocida: {criterio['fuente_pagina']!r}")

    if "grounding" in criterio and criterio["grounding"] not in GROUNDINGS_VALIDOS:
        motivos.append(f"grounding desconocido: {criterio['grounding']!r}")

    return motivos


# --- 2. Contaminación few-shot ---------------------------------------------------
def detectar_contaminacion_fewshot(criterio):
    """Nº del bloque ejemplo (1-3) si el texto del criterio aparece VERBATIM
    (módulo whitespace y puntuación final) dentro de un bloque few-shot del
    prompt; None si no. Solo marca — el rechazo no es asunto de esta función."""
    t = _norm_fewshot(_sin_ambiguo(criterio.get("texto")))
    if not t:
        return None
    for i, bloque in BLOQUES_FEWSHOT:
        if t in bloque:
            return i
    return None


# --- 3. Filtro de grounding failed ------------------------------------------------
def filtrar_failed(criterios):
    """(pasan, failed) — failed va a revisión manual, no al JSON validado."""
    pasan = [c for c in criterios if c.get("grounding") != "failed"]
    failed = [c for c in criterios if c.get("grounding") == "failed"]
    return pasan, failed


# --- 4. Duplicados ----------------------------------------------------------------
def detectar_duplicados(criterios, umbral=UMBRAL_DUPLICADOS):
    """Pares (i<j) con similitud ≥ umbral sobre texto normalizado (whitespace
    colapsado + casefold + sin prefijo [AMBIGUO]). Solo reporta — no borra."""
    textos = [_norm_ws(_sin_ambiguo(c.get("texto"))).casefold() for c in criterios]
    pares = []
    for i in range(len(criterios)):
        for j in range(i + 1, len(criterios)):
            sm = difflib.SequenceMatcher(None, textos[i], textos[j])
            if (sm.real_quick_ratio() < umbral or sm.quick_ratio() < umbral):
                continue  # cotas superiores estándar de difflib — mismo resultado, menos costo
            r = sm.ratio()
            if r >= umbral:
                pares.append({
                    "ratio": round(r, 4),
                    "a": {"pagina": criterios[i].get("pagina_origen"),
                          "texto": criterios[i].get("texto")},
                    "b": {"pagina": criterios[j].get("pagina_origen"),
                          "texto": criterios[j].get("texto")},
                })
    return pares


# --- PASO 0: autotest con fixtures propios (NO conocimiento real) ------------------
def _fixture(**overrides):
    base = {
        "texto": "FIXTURE: texto de prueba del validator, no es conocimiento real.",
        "peso": "MANDATORY", "severidad": "OBSERVACION",
        "condicion_libre": None, "referencia_no_resuelta": False,
        "pagina_origen": 999, "seccion_aplicable": "Softline",
        "etapa_aplicable": None, "fuente_pagina": "pdfplumber_text_flow",
        "grounding": "exact",
    }
    base.update(overrides)
    for k in [k for k, v in base.items() if v is Ellipsis]:  # Ellipsis = quitar campo
        del base[k]
    return base


def autotest() -> bool:
    """Fixtures a mano cubriendo cada defecto que el validator debe atrapar.
    Devuelve True solo si TODOS los casos se detectan correctamente."""
    f_incompleto = _fixture(texto="FIXTURE 1: le falta el campo severidad.",
                            severidad=Ellipsis)
    f_severidad = _fixture(texto="FIXTURE 2: severidad fuera de catálogo.",
                           severidad="CRITICA")
    f_peso = _fixture(texto="FIXTURE 3: peso fuera de rango del schema.",
                      peso="OBLIGATORIO")
    f_dup_a = _fixture(texto="FIXTURE 4: colocar el material de prueba en la zona A.",
                       pagina_origen=998)
    f_dup_b = _fixture(texto="FIXTURE 4: colocar el material de prueba en la zona A.")
    f_contaminado = _fixture(texto="No mezclar marcas")  # verbatim del ejemplo 2 del prompt
    f_failed = _fixture(texto="FIXTURE 5: schema válido pero grounding failed.",
                        grounding="failed")
    f_limpio = _fixture(texto="FIXTURE 6: criterio íntegro que debe pasar todo.")

    casos = [
        ("schema incompleto (sin severidad) → rechazado", f_incompleto,
         lambda: any("severidad" in m and "ausentes" in m for m in validar_schema(f_incompleto))),
        ("severidad fuera de catálogo (CRITICA) → rechazado", f_severidad,
         lambda: any("severidad fuera de catálogo" in m for m in validar_schema(f_severidad))),
        ("peso fuera de rango (OBLIGATORIO) → rechazado", f_peso,
         lambda: any("peso fuera del rango" in m for m in validar_schema(f_peso))),
        ("duplicado exacto a propósito → par detectado (ratio 1.0)", f_dup_a,
         lambda: [(p["a"]["pagina"], p["b"]["pagina"]) for p in
                  detectar_duplicados([f_dup_a, f_dup_b, f_limpio])] == [(998, 999)]),
        ("contaminación few-shot a propósito ('No mezclar marcas') → flag ej2", f_contaminado,
         lambda: detectar_contaminacion_fewshot(f_contaminado) == 2),
        ("grounding=failed → filtrado a revisión manual", f_failed,
         lambda: (filtrar_failed([f_failed, f_limpio])[1] == [f_failed]
                  and filtrar_failed([f_failed, f_limpio])[0] == [f_limpio])),
        ("criterio 100% limpio → pasa schema, sin flags, no duplicado", f_limpio,
         lambda: (validar_schema(f_limpio) == []
                  and detectar_contaminacion_fewshot(f_limpio) is None
                  and f_limpio in filtrar_failed([f_limpio])[0])),
    ]

    print("PASO 0 — AUTOTEST del validator (fixtures propios, no conocimiento real)")
    print("-" * 88)
    ok = True
    for descripcion, fixture, check in casos:
        paso = bool(check())
        ok = ok and paso
        print(f"  [{'PASS' if paso else 'FAIL'}] {descripcion}")
        if not paso:
            print(f"         fixture: {fixture!r}")
            print(f"         motivos schema: {validar_schema(fixture)!r}")
    print("-" * 88)
    print(f"AUTOTEST: {'7/7 OK' if ok else 'FALLÓ — NO se tocan los datos reales'}")
    return ok


# --- Persistencia (misma convención .bak-<ts> del resto de Motor 2) ---------------
def _guardar(ruta: Path, data: dict) -> None:
    if ruta.exists():
        respaldo = ruta.with_suffix(f"{ruta.suffix}.bak-{datetime.now():%Y%m%d-%H%M%S}")
        ruta.rename(respaldo)
        print(f"(anterior respaldado en {respaldo.name})")
    ruta.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _slug_manual() -> str:
    """Nombre del manual para el archivo de salida, desde el consolidado (campo
    pdf). Determinista: minúsculas, sin acentos, no-alfanumérico → '_'."""
    nombre = "manual"
    if CONSOLIDADO.exists():
        nombre = json.loads(CONSOLIDADO.read_text(encoding="utf-8")).get("pdf", nombre)
    nombre = Path(nombre).stem
    sin_acentos = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", sin_acentos.lower())).strip("_")


# --- Corrida sobre datos reales -----------------------------------------------------
def main() -> None:
    solo_autotest = "--autotest" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a != "--autotest"]
    entrada = Path(args[0]) if args else ENTRADA_DEFAULT

    # PASO 0: si el autotest no detecta cada caso, no se avanza. Sin excepciones.
    if not autotest():
        sys.exit(1)
    if solo_autotest:
        return
    print()

    if not entrada.exists():
        sys.exit(f"ERROR: no existe el input: {entrada}")
    data = json.loads(entrada.read_text(encoding="utf-8"))

    paginas = data.get("paginas", {})
    estados = {}
    criterios = []
    for num in sorted(paginas, key=int):
        pd = paginas[num]
        estados[pd.get("estado")] = estados.get(pd.get("estado"), 0) + 1
        criterios.extend(pd.get("criterios", []))

    # Campos no contemplados en el contrato: se reportan (no rechazan) — un campo
    # inesperado puede ser síntoma de un bug upstream, no se esconde.
    desconocidos = sorted({k for c in criterios if isinstance(c, dict)
                           for k in c if k not in CAMPOS_OBLIGATORIOS})

    # 1. Schema  +  2. flag de contaminación (se marca ANTES de filtrar, para que
    # también los que van a revisión lleven el flag — los 8 contaminados de
    # p1/p5/p8 deben salir failed Y flageados, doble evidencia).
    rechazados, schema_ok = [], []
    for c in criterios:
        motivos = validar_schema(c)
        ej = detectar_contaminacion_fewshot(c) if isinstance(c, dict) else None
        if isinstance(c, dict):
            c = {**c, "posible_herencia_fewshot": ej is not None,
                 **({"fewshot_ejemplo": ej} if ej is not None else {})}
        if motivos:
            rechazados.append({**(c if isinstance(c, dict) else {"criterio_crudo": repr(c)}),
                               "motivos_revision": [f"schema: {m}" for m in motivos]})
        else:
            schema_ok.append(c)

    # 3. failed → revisión manual
    validados, failed = filtrar_failed(schema_ok)
    a_revision = rechazados + [{**c, "motivos_revision": ["grounding=failed — sin span en la fuente, no se confía (los contaminados de few-shot de p1/p5/p8 caen aquí)"]}
                               for c in failed]

    # Conservación exacta — si esto no cuadra hay un bug del validator, se aborta.
    if len(validados) + len(a_revision) != len(criterios):
        sys.exit(f"ERROR interno: {len(validados)} validados + {len(a_revision)} a revisión "
                 f"≠ {len(criterios)} de entrada. NO se guarda nada.")

    # 4. duplicados sobre los validados — reporte, sin borrar
    pares_dup = detectar_duplicados(validados)

    # --- Salidas -----------------------------------------------------------------
    slug = _slug_manual()
    salida_validado = MOTOR2 / f"capa2_{slug}_validado.json"
    generado = datetime.now().isoformat(timespec="seconds")

    flag_validados = sum(1 for c in validados if c["posible_herencia_fewshot"])
    flag_revision = sum(1 for c in a_revision if c.get("posible_herencia_fewshot"))
    motivos_conteo = {}
    for r in rechazados:
        for m in r["motivos_revision"]:
            motivos_conteo[m] = motivos_conteo.get(m, 0) + 1

    reporte = {
        "generado": generado,
        "input": entrada.name,
        "umbral_duplicados": UMBRAL_DUPLICADOS,
        "paginas_por_estado": estados,
        "criterios_entrada": len(criterios),
        "schema": {
            "validos": len(schema_ok),
            "rechazados": len(rechazados),
            "motivos": motivos_conteo,
        },
        "grounding_failed_filtrados": len(failed),
        "contaminacion_fewshot": {
            "flag_en_validados": flag_validados,
            "flag_en_revision": flag_revision,
            "nota": ("solo marca, no rechaza. En p20/26/31 el match es circular por "
                     "construcción: los few-shot del prompt citan texto real de esas "
                     "páginas (Sesión O) — el texto es legítimo pero sus atributos "
                     "peso/severidad no son juicio independiente del modelo"),
        },
        "duplicados": {"pares_sospechosos": len(pares_dup), "detalle": pares_dup},
        "resultado": {
            "validados": len(validados),
            "a_revision_manual": len(a_revision),
        },
        "advertencias": {
            "seccion_aplicable_null_en_validados":
                sum(1 for c in validados if c.get("seccion_aplicable") is None),
            "campos_fuera_de_contrato": desconocidos,
            "nota_seccion_null": ("null es válido por contrato del normalizer "
                                  "(encabezado sin match, reportado en Sesión O) — "
                                  "se cuenta, no se rechaza"),
        },
    }

    validado_json = {
        "meta": {
            "generado": generado,
            "input": entrada.name,
            "manual": slug,
            "schema": data.get("meta", {}).get("schema"),
            "validador": "validator.py (Sesión P): schema v1.2 + filtro grounding=failed; "
                         "posible_herencia_fewshot solo marca; duplicados solo reportados "
                         "en validator_report.json",
            "nota_formato": "extracción v1.2 validada — AÚN NO es capa de knowledge v1.1 "
                            "(faltan id/aliases/aplica_a; se asignan en un paso posterior)",
        },
        "criterios": validados,
    }
    revision_json = {"generado": generado, "input": entrada.name,
                     "total": len(a_revision), "criterios": a_revision}

    _guardar(salida_validado, validado_json)
    _guardar(SALIDA_REPORTE, reporte)
    _guardar(SALIDA_REVISION, revision_json)

    # --- Reporte en consola (números exactos) --------------------------------------
    print("VALIDACIÓN SOBRE DATOS REALES")
    print("=" * 88)
    print(f"  Input:                        {entrada.name} "
          f"(páginas por estado: {estados})")
    print(f"  Criterios de entrada:         {len(criterios)}")
    print(f"  1. Schema  → válidos:         {len(schema_ok)}   rechazados: {len(rechazados)}")
    for m, n in sorted(motivos_conteo.items()):
        print(f"       {n} × {m}")
    print(f"  2. Flag posible_herencia_fewshot: {flag_validados} en validados, "
          f"{flag_revision} en revisión (marca, no rechaza)")
    print(f"  3. grounding=failed → revisión:   {len(failed)}")
    print(f"  4. Duplicados (≥ {UMBRAL_DUPLICADOS}):          {len(pares_dup)} pares "
          f"(reportados, NO borrados)")
    print(f"  seccion_aplicable=null en validados: "
          f"{reporte['advertencias']['seccion_aplicable_null_en_validados']} (válido por contrato)")
    if desconocidos:
        print(f"  🟡 campos fuera de contrato (se conservan, no rechazan): {desconocidos}")
    print("-" * 88)
    print(f"  VALIDADOS: {len(validados)}  →  {salida_validado.name}")
    print(f"  A REVISIÓN MANUAL: {len(a_revision)}  →  {SALIDA_REVISION.name}")
    print(f"  Reporte: {SALIDA_REPORTE.name}")
    print(f"  Conservación: {len(validados)} + {len(a_revision)} = {len(criterios)} ✓")


if __name__ == "__main__":
    main()
