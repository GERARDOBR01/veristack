# -*- coding: utf-8 -*-
"""Motor 2 — extractor de criterios con langextract (PILOTO).

Primer uso real de IA en Motor 2. Corre SOLO sobre 4-5 bloques de prueba para
validar el enfoque antes de escalar a los 47.

Reparto de responsabilidad ("código decide, modelo interpreta"):
  - `segmenter.py` + `normalizer.py` ya resolvieron, por CÓDIGO, la página y la
    `seccion_aplicable` de cada bloque. Eso NO se le pregunta al modelo.
  - langextract SOLO decide, por bloque: los criterios (texto literal), su `peso`,
    su `severidad`, la `condicion_libre` y si hay `referencia_no_resuelta`.
  - La página y la sección se PEGAN al armar el JSON final, tomadas del código.

Texto de entrada: se lee con `use_text_flow=True` (ver leer_texto_flow), que
des-intercala las columnas usando el orden del stream interno del PDF. La extracción
por defecto intercala columnas (p10) y rompía el grounding literal; use_text_flow lo
resuelve. (Sesión I: se descartó `layout=True` — solo agrega padding, no des-intercala.)

Grounding: cada criterio extraído se verifica contra el `char_interval` que
devuelve langextract — si el intervalo no reproduce el texto extraído dentro del
bloque, el criterio se marca SIN GROUNDING (no se confía en él).

`referencia_no_resuelta` es de 3 estados: true (remite a doc/liga externa nombrada),
false (criterio normal), null (instrucción vaga sin doc externo — el modelo prefija
el texto con "[AMBIGUO] " en vez de inventar una referencia).

Uso:
    python extractor.py [ruta_al_pdf]

Requiere GEMINI_API_KEY en el .env de la raíz del repo (NUNCA se imprime).
"""
import logging
import os
import re
import sys
import time
from pathlib import Path

import langextract as lx
import pdfplumber

# El ejemplo negativo usa el texto "[AMBIGUO] ..." que a propósito NO existe literal
# en su texto fuente (el prefijo lo agrega el modelo). langextract emite un WARNING
# de alineación por eso; es esperado y benigno, se silencia para no ensuciar la salida.
logging.getLogger("absl").setLevel(logging.ERROR)

from segmenter import PDF_DEFAULT, leer_paginas, segmentar
from normalizer import normalizar

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Modelo alineado al resto del proyecto (CLAUDE.md: GEMINI_MODEL=gemini-3.5-flash).
MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

# Bloques de prueba del piloto (por página), elegidos por complejidad distinta:
#   p29  simple  — 3 indicaciones cortas, sin condición
#   p20  etapas  — focal show con NOTA/excepción de material
#   p43  tabla   — zapatos deportivos: tabla de % + lista larga de mercadeo
#   p10  ref.    — etiquetado: remite a "manual de señalización" (externo)
#   p35  cond.   — diversos: varias condiciones libres (% por tipo de producto)
BLOQUES_PRUEBA = [29, 20, 43, 10, 35]


# --- Prompt e ejemplos few-shot -------------------------------------------------
# El peso se infiere de la etiqueta estructural del manual, que es un patrón real
# y consistente en estos slides (no inventado):
#   INDICACIONES / Pauta / Mercadeo  -> MANDATORY (obligación de montaje)
#   SUGERENCIA                        -> RECOMMENDATION
#   *NOTA / excepción                 -> EXCEPTION
PROMPT_DESCRIPTION = """\
Extrae los CRITERIOS de montaje de un bloque de un manual de retail (Liverpool).
Un criterio es una instrucción accionable y verificable sobre cómo debe quedar la
exhibición. Extrae el texto LITERAL del criterio tal como aparece (no lo parafrasees).

Para cada criterio asigna estos atributos:
- peso: MANDATORY (obligación bajo INDICACIONES / Pauta / Mercadeo / Prioridad),
        RECOMMENDATION (bajo SUGERENCIA o cuando el manual sugiere),
        EXCEPTION (una NOTA, salvedad o "solo/nunca ..." que acota una regla).
- severidad: GRAVE, OBSERVACION o NO_CALIFICA. Es INDEPENDIENTE del peso (no la
        deduzcas del peso). GRAVE = incumplirlo rompe la exhibición o el precio;
        OBSERVACION = detalle de acomodo/orden; NO_CALIFICA = dato informativo que
        no se puede verificar en una foto.
- condicion_libre: si el criterio solo aplica bajo una circunstancia (un tipo de
        mercancía, una zona, un porcentaje de descuento, un horario), ponla como
        texto breve. NUNCA pongas aquí la sección ni la etapa. Si no hay condición,
        déjalo vacío.
- referencia_no_resuelta: "true" SÓLO si el criterio remite a un documento o liga
        externa NOMBRADO (por ejemplo "consulta el manual de señalización", "revisa
        el book de impulsos", "ver la liga"). Usa "null" (y prefija el texto con
        "[AMBIGUO] ") SÓLO cuando el criterio invoca un ESTÁNDAR o material que NO se
        define en este texto y que tampoco es un documento nombrable —el caso típico
        es "cuida tus básicos de Display" (remite a un estándar de Display no enunciado
        aquí)—; sin ese estándar el criterio no se puede verificar. Para CUALQUIER
        instrucción normal y accionable, aunque sea general (por ejemplo "mantén el
        orden de la exhibición", "coloca el producto con mayor descuento", "mercadeo
        por bloqueo de producto"), usa "false" y NO la marques [AMBIGUO].

No extraigas encabezados, nombres de materiales sueltos ni texto decorativo que no
sea una instrucción. No inventes criterios que no estén en el texto.
"""


def _crit(texto, peso, severidad, condicion="", ref="false"):
    return lx.data.Extraction(
        extraction_class="criterio",
        extraction_text=texto,
        attributes={
            "peso": peso,
            "severidad": severidad,
            "condicion_libre": condicion,
            "referencia_no_resuelta": ref,
        },
    )


# Ejemplos anclados en texto REAL del manual (bloques que NO están en el piloto:
# p26 BARRAS Y MANIQUÍES, p31 MASIVOS HARDLINE, p22 FOCAL SHOW HOMBRES) para no
# filtrar respuestas del piloto.
EXAMPLES = [
    lx.data.ExampleData(
        text=(
            "Focal sencillo: Maniquíes + Barra + Cartulina\n"
            "SUGERENCIA:\n"
            "● Da visibilidad al producto con el descuento más alto y corridas completas\n"
            "● Vestir los maniquíes con prendas que estén en la exhibición.\n"
            "*NOTA: Poner etiquetas de descuento a las prendas, no saturar."
        ),
        extractions=[
            _crit("Da visibilidad al producto con el descuento más alto y corridas completas",
                  "RECOMMENDATION", "OBSERVACION"),
            _crit("Vestir los maniquíes con prendas que estén en la exhibición.",
                  "RECOMMENDATION", "OBSERVACION"),
            _crit("Poner etiquetas de descuento a las prendas, no saturar.",
                  "EXCEPTION", "OBSERVACION"),
        ],
    ),
    lx.data.ExampleData(
        text=(
            "Materiales:\n● Cartulinas\n● Carrito Italia\n"
            "Pauta:\n● Colocar alternando a lo largo de la sección\n"
            "Mercadeo:\n● No mezclar marcas\n● Exhibir 1 focal por marca\n"
            "Prioridad Producto:\n● Mesa Fina - caja de vajilla cerrada Narrative y Kostlich."
        ),
        extractions=[
            _crit("Colocar alternando a lo largo de la sección", "MANDATORY", "OBSERVACION"),
            _crit("No mezclar marcas", "MANDATORY", "GRAVE"),
            _crit("Exhibir 1 focal por marca", "MANDATORY", "OBSERVACION"),
            _crit("caja de vajilla cerrada Narrative y Kostlich.",
                  "RECOMMENDATION", "NO_CALIFICA", condicion="Mesa Fina"),
        ],
    ),
    # Ejemplo NEGATIVO: instrucción vaga sin documento externo. Debe salir con
    # referencia_no_resuelta="null" y el texto prefijado "[AMBIGUO] ", NO "true".
    # "Revisa que el producto ... con el mismo descuento" sí es criterio normal.
    lx.data.ExampleData(
        text=(
            "INDICACIONES: Focales fuera de la sección (Entradas, Hueco Central)\n"
            "● Revisa que el producto para este focal sea mercancía con el mismo descuento.\n"
            "● Cuida tus básicos de Display."
        ),
        extractions=[
            _crit("Revisa que el producto para este focal sea mercancía con el mismo descuento.",
                  "MANDATORY", "GRAVE", condicion="Focales fuera de la sección"),
            _crit("[AMBIGUO] Cuida tus básicos de Display.",
                  "MANDATORY", "OBSERVACION", ref="null"),
        ],
    ),
]

# Prefijo que el modelo antepone a un criterio vago (instrucción sin doc externo).
MARCA_AMBIGUO = "[AMBIGUO] "


def _cargar_api_key() -> str:
    """Devuelve la GEMINI_API_KEY sin imprimirla. Busca env y luego el .env raíz."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("LANGEXTRACT_API_KEY")
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for linea in env_path.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea.startswith("GEMINI_API_KEY") and "=" in linea:
                return linea.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("ERROR: falta GEMINI_API_KEY (env o .env de la raíz). No se ejecuta.")


def _norm_ws(s: str) -> str:
    """Colapsa cualquier corrida de espacios/saltos de línea a un solo espacio.

    El PDF parte líneas a mitad de frase, así que el span de la fuente trae saltos
    donde el texto extraído trae espacios. Eso NO es una falla de grounding: hay
    que comparar ignorando el whitespace."""
    return " ".join((s or "").split())


def _verificar_grounding(ext, fuente: str):
    """(ok, span_real) — ¿el char_interval reproduce el texto extraído en la fuente?

    OK sólo si el intervalo alinea EXACTO (ignorando whitespace). Un match_fuzzy /
    match_lesser (típico cuando el texto se reensambla de columnas interleaved) NO
    es exacto y se marca para revisión."""
    ci = ext.char_interval
    if ci is None or ci.start_pos is None or ci.end_pos is None:
        return False, None
    span = fuente[ci.start_pos:ci.end_pos]
    # El prefijo [AMBIGUO] lo agrega el modelo, no está en la fuente: se ignora
    # para comparar el grounding del texto real del criterio.
    texto = ext.extraction_text
    if texto.startswith(MARCA_AMBIGUO):
        texto = texto[len(MARCA_AMBIGUO):]
    ok = _norm_ws(span) == _norm_ws(texto)
    return ok, span


def leer_texto_flow(pdf_path: Path):
    """{numero_pagina: texto} leído con use_text_flow=True (des-intercala columnas).

    `segmenter.leer_paginas` usa la extracción por defecto, que intercala columnas
    (ver p10). Aquí re-leemos con el orden del stream interno del PDF, que respeta
    las columnas — es el texto que se le da al modelo para que el grounding literal
    funcione. La página y la sección siguen viniendo del código (segmenter/normalizer),
    no de esta lectura."""
    textos = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            textos[page.page_number] = page.extract_text(use_text_flow=True) or ""
    return textos


def _retry_delay_seg(exc, default=30):
    """Extrae 'retryDelay' del error 429 de Gemini, o usa el default."""
    m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc)) or \
        re.search(r"'retryDelay': '(\d+)s'", str(exc))
    if m:
        return int(float(m.group(1))) + 2
    return default


def extraer_bloque(texto: str, api_key: str, reintentos=2):
    """Corre langextract sobre el texto de un bloque y devuelve su AnnotatedDocument.

    Reintenta con backoff ante 429 (free tier: 20 req/min). Si se agota la cuota
    diaria, el 429 persiste y se propaga tras los reintentos."""
    for intento in range(reintentos + 1):
        try:
            return lx.extract(
                text_or_documents=texto,
                prompt_description=PROMPT_DESCRIPTION,
                examples=EXAMPLES,
                model_id=MODEL_ID,
                api_key=api_key,
                temperature=0.0,          # piloto determinista
                max_char_buffer=1500,     # > el bloque más largo (p43 ~844) -> 1 chunk
                show_progress=False,
            )
        except Exception as exc:  # noqa: BLE001
            es_429 = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
            if not es_429 or intento == reintentos:
                raise
            espera = _retry_delay_seg(exc)
            print(f"  ⏳ 429 rate limit — esperando {espera}s y reintentando "
                  f"({intento + 1}/{reintentos})...")
            time.sleep(espera)


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PDF_DEFAULT
    if not pdf_path.exists():
        sys.exit(f"ERROR: no existe el PDF: {pdf_path}")

    api_key = _cargar_api_key()
    bloques = segmentar(leer_paginas(pdf_path))
    norm, _ = normalizar(bloques)
    # Índice por página para pegar página+sección (del código) al output del modelo.
    por_pagina = {n.pagina_inicio: (b, n) for b, n in zip(bloques, norm)}
    # Texto des-intercalado (use_text_flow) para dárselo al modelo. Ver leer_texto_flow.
    flow_por_pagina = leer_texto_flow(pdf_path)

    print(f"PDF: {pdf_path.name}")
    print(f"Modelo: {MODEL_ID}  |  Bloques piloto: {BLOQUES_PRUEBA}")
    print(f"Lectura de texto: use_text_flow=True (des-intercala columnas)")
    print("=" * 90)

    for pag in BLOQUES_PRUEBA:
        if pag not in por_pagina:
            print(f"\n[p{pag}] NO ENCONTRADO en el PDF — se omite.")
            continue
        bloque, n = por_pagina[pag]
        # Texto del bloque: páginas del rango, leídas des-intercaladas.
        texto_flow = "\n".join(
            flow_por_pagina.get(p, "")
            for p in range(n.pagina_inicio, n.pagina_fin + 1)
        ).strip()
        print(f"\n{'#' * 90}")
        print(f"# BLOQUE p{n.pagina_inicio}-{n.pagina_fin}  |  seccion_aplicable={n.seccion_aplicable}"
              f"  (fijos por código)")
        print(f"# encabezado: {n.seccion!r}")
        print("#" * 90)

        try:
            doc = extraer_bloque(texto_flow, api_key)
        except Exception as exc:  # noqa: BLE001 — piloto: reportar y seguir
            print(f"  ⚠️  ERROR al extraer p{pag}: {type(exc).__name__}: {exc}")
            continue

        extracciones = list(doc.extractions or [])
        criterios_json = []
        print(f"\n  {len(extracciones)} criterio(s) extraído(s):")
        for i, ext in enumerate(extracciones, 1):
            attrs = ext.attributes or {}
            ok, span = _verificar_grounding(ext, texto_flow)
            estado = "OK" if ok else "SIN GROUNDING"
            align = ext.alignment_status.value if ext.alignment_status else "None"
            print(f"\n  [{i}] grounding={estado} (align={align})")
            print(f"      texto: {ext.extraction_text!r}")
            if not ok and span is not None:
                print(f"      ⚠️  char_interval devuelve: {span!r}")
            print(f"      peso={attrs.get('peso')!r}  severidad={attrs.get('severidad')!r}")
            print(f"      condicion_libre={attrs.get('condicion_libre')!r}"
                  f"  referencia_no_resuelta={attrs.get('referencia_no_resuelta')!r}")

            # Arma el criterio final: página+sección del CÓDIGO, resto del modelo.
            # referencia_no_resuelta es de 3 estados: true / false / null (vago/ambiguo).
            raw_ref = str(attrs.get("referencia_no_resuelta", "false")).strip().lower()
            if raw_ref == "true":
                ref = True
            elif raw_ref in ("null", "none", ""):
                ref = None
            else:
                ref = False
            cond = (attrs.get("condicion_libre") or "").strip() or None
            criterios_json.append({
                "texto": ext.extraction_text,
                "peso": attrs.get("peso"),
                "severidad": attrs.get("severidad"),
                "condicion_libre": cond,
                "referencia_no_resuelta": ref,
                # Pegados por código (el modelo NUNCA los decide):
                "pagina_origen": n.pagina_inicio,
                "seccion_aplicable": n.seccion_aplicable,
                "grounding_ok": ok,
            })

        import json
        print(f"\n  --- JSON armado (p{pag}) para revisión manual ---")
        print(json.dumps(criterios_json, ensure_ascii=False, indent=2))

    print("\n" + "=" * 90)
    print("PILOTO terminado. Revisar a mano antes de escalar a los 47 bloques.")


if __name__ == "__main__":
    main()
