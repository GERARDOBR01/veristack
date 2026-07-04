# -*- coding: utf-8 -*-
"""Motor 2 — extractor de criterios con langextract (corrida COMPLETA, Sesión O).

Evolución del piloto de Sesión K (5 bloques) a la corrida completa sobre el
manual consolidado. La lógica de extracción, prompt, few-shot y grounding NO
cambió respecto al piloto validado — cambió el INPUT y se agregó etapa_aplicable.

INPUT: motor2/manual_consolidado.json (Sesión N) — NO el PDF directo.
  - Páginas de texto plano → su `texto` (ya use_text_flow, des-intercalado).
  - Páginas diagrama (Gemini Vision) → la `estructura` reconstruida, serializada
    a texto legible (título + secciones con elementos + relaciones + texto no
    ubicado). El texto plano de esas páginas está roto por diseño — ese fue el
    motivo del fallback de Vision. `descripcion_general` NO se incluye (es meta
    del modelo de visión, no contenido del manual).

Reparto de responsabilidad ("código decide, modelo interpreta"):
  - `segmenter.py` + `normalizer.py` (importados, SIN tocar) resuelven por
    CÓDIGO los bloques y la `seccion_aplicable`, alimentados con las páginas
    del consolidado (no con el PDF).
  - `etapa_aplicable` (NUEVO, schema v1.2 según brief de Gerardo) también la
    decide CÓDIGO: regex sobre el encabezado del bloque ("(1a y 2a ETAPA)",
    "(3a ETAPA)", "(ETAPA 2 Y 3)"). Valores fijos: ["E1"|"E2"|"E3"] o null.
  - langextract SOLO decide, por página: criterios (texto literal), `peso`,
    `severidad`, `condicion_libre` y `referencia_no_resuelta`.
  - página + sección + etapa se PEGAN al armar el JSON final, del código.

Grounding por criterio (mismo indicador que el piloto de Sesión K):
  - exact  → el char_interval reproduce el texto extraído (ignorando whitespace)
  - lesser → hay intervalo pero no alinea exacto (match_lesser/fuzzy) — revisar
  - failed → sin intervalo — no se confía
En páginas Vision el grounding es contra la estructura reconstruida (el texto
plano de esas páginas está roto — no hay fuente literal mejor).

Páginas que NO se extraen (documentado, no silencioso):
  - p47 (APARADORES): excluida por decisión de Gerardo — solo imagen/link,
    sin criterio verificable.
  - Páginas de <5 palabras y sin estructura Vision (portadas de sección:
    p9, p15, p17, p19, p30, p45, p48) — no hay nada accionable que extraer.

Reanudación: el output se guarda página a página en criterios_extraidos.json.
Si la corrida muere (rate limit agotado), el script reporta en qué página quedó;
al relanzarlo retoma desde ahí (salta las páginas ya extraídas OK). Con
--desde-cero se respalda el archivo anterior a .bak-<timestamp> y se reinicia.

Backend (sin cambios desde Sesión K): MOTOR2_BACKEND = github (default,
openai/gpt-4o-mini vía GitHub Models con GITHUB_API_KEY) o gemini (fallback).

Uso:
    python extractor.py [ruta_manual_consolidado.json] [--desde-cero]
"""
import json
import logging
import os
import re
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import langextract as lx

# El ejemplo negativo usa el texto "[AMBIGUO] ..." que a propósito NO existe literal
# en su texto fuente (el prefijo lo agrega el modelo). langextract emite un WARNING
# de alineación por eso; es esperado y benigno, se silencia para no ensuciar la salida.
logging.getLogger("absl").setLevel(logging.ERROR)

# Al usar `config=`, langextract avisa que las restricciones de esquema se aplican
# vía ejemplos (no vía output_schema). Es el comportamiento buscado; se silencia.
warnings.filterwarnings("ignore", message="With 'config', schema constraints")

from segmenter import segmentar
from normalizer import normalizar

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONSOLIDADO_DEFAULT = Path(__file__).resolve().parent / "manual_consolidado.json"
SALIDA = Path(__file__).resolve().parent / "criterios_extraidos.json"

# p47 (APARADORES): solo imagen/link de outfits, sin criterio verificable.
# Decisión de Gerardo (Sesión O) — exclusión deliberada, no bug.
PAGINAS_EXCLUIDAS = {47: "excluida por decisión: solo imagen/link, sin criterio verificable"}

# Una página de texto con menos palabras que esto y sin estructura Vision es una
# portada de sección ("MONTAJE SOFTLINE") — no se gasta un request en ella.
MIN_PALABRAS_PAGINA = 5

PAUSA_ENTRE_PAGINAS_S = 5  # respeta el RPM del free tier de GitHub Models

ETAPAS_VALIDAS = {"E1", "E2", "E3"}

# --- Backend / proveedor de IA (sin cambios desde Sesión K) ---------------------
BACKEND = os.environ.get("MOTOR2_BACKEND", "github").strip().lower()
GITHUB_MODEL = os.environ.get("GITHUB_MODEL", "openai/gpt-4o-mini")
GITHUB_BASE_URL = os.environ.get("GITHUB_BASE_URL", "https://models.github.ai/inference")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
MODEL_ID = GITHUB_MODEL if BACKEND == "github" else GEMINI_MODEL


# --- Prompt e ejemplos few-shot (SIN cambios desde el piloto de Sesión K) --------
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

MARCA_AMBIGUO = "[AMBIGUO] "


# --- Utilidades (sin cambios desde el piloto) ------------------------------------
def _leer_env(nombre: str):
    """Devuelve el valor de una variable, del entorno o del .env raíz. Sin imprimirla."""
    if os.environ.get(nombre):
        return os.environ[nombre]
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for linea in env_path.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea.startswith(nombre) and "=" in linea:
                return linea.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _cargar_api_key() -> str:
    if BACKEND == "github":
        key = _leer_env("GITHUB_API_KEY")
        if key:
            return key
        sys.exit("ERROR: falta GITHUB_API_KEY (env o .env de la raíz). No se ejecuta.")
    key = _leer_env("GEMINI_API_KEY") or _leer_env("LANGEXTRACT_API_KEY")
    if key:
        return key
    sys.exit("ERROR: falta GEMINI_API_KEY (env o .env de la raíz). No se ejecuta.")


def _construir_config(api_key: str, temperature: float = 0.0):
    if BACKEND == "github":
        return lx.factory.ModelConfig(
            model_id=GITHUB_MODEL,
            provider="OpenAILanguageModel",
            provider_kwargs={
                "api_key": api_key,
                "base_url": GITHUB_BASE_URL,
                "temperature": temperature,
            },
        )
    return lx.factory.ModelConfig(
        model_id=GEMINI_MODEL,
        provider_kwargs={"api_key": api_key, "temperature": temperature},
    )


def _norm_ws(s: str) -> str:
    return " ".join((s or "").split())


def _grounding(ext, fuente: str):
    """('exact'|'lesser'|'failed', span) — mismo indicador que el piloto de Sesión K."""
    ci = ext.char_interval
    if ci is None or ci.start_pos is None or ci.end_pos is None:
        return "failed", None
    span = fuente[ci.start_pos:ci.end_pos]
    texto = ext.extraction_text
    if texto.startswith(MARCA_AMBIGUO):  # prefijo del modelo, no está en la fuente
        texto = texto[len(MARCA_AMBIGUO):]
    return ("exact" if _norm_ws(span) == _norm_ws(texto) else "lesser"), span


def _retry_delay_seg(exc, default=30):
    m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc)) or \
        re.search(r"'retryDelay': '(\d+)s'", str(exc))
    if m:
        return int(float(m.group(1))) + 2
    return default


def _es_429(exc) -> bool:
    s = str(exc)
    return "429" in s or "RESOURCE_EXHAUSTED" in s or "RateLimit" in type(exc).__name__


def extraer_pagina(texto: str, config, reintentos=2):
    """Corre langextract sobre el texto de UNA página. Reintenta ante 429."""
    for intento in range(reintentos + 1):
        try:
            return lx.extract(
                text_or_documents=texto,
                prompt_description=PROMPT_DESCRIPTION,
                examples=EXAMPLES,
                config=config,
                max_char_buffer=max(1500, len(texto) + 100),  # 1 página = 1 chunk = 1 request
                show_progress=False,
            )
        except Exception as exc:  # noqa: BLE001
            if not _es_429(exc) or intento == reintentos:
                raise
            espera = _retry_delay_seg(exc)
            print(f"  ⏳ 429 rate limit — esperando {espera}s y reintentando "
                  f"({intento + 1}/{reintentos})...")
            time.sleep(espera)


# --- Input: manual consolidado ---------------------------------------------------
def _texto_pagina_vision(entrada: dict) -> str:
    """Serializa la estructura reconstruida por Vision a texto extraíble.

    Formato con viñetas ● (mismo patrón que los few-shot). descripcion_general
    NO se incluye: es prosa meta del modelo de visión, no contenido del manual.
    Las relaciones SÍ: son exactamente el valor que Vision agregó (condiciones
    y ligas espaciales que el texto plano perdía)."""
    est = entrada["estructura"]
    crudo = entrada.get("texto_crudo", "")
    titulo = est.get("titulo") or (crudo.splitlines() or ["(sin título)"])[0]
    lineas = [titulo]
    for sec in est.get("secciones", []):
        rol = f" ({sec['rol']})" if sec.get("rol") else ""
        lineas.append(f"{sec.get('nombre', '(sin nombre)')}{rol}:")
        for el in sec.get("elementos", []):
            lineas.append(f"● {el}")
    if est.get("relaciones"):
        lineas.append("Relaciones:")
        lineas.extend(f"● {r}" for r in est["relaciones"])
    if est.get("texto_no_ubicado"):
        lineas.append("Texto no ubicado:")
        lineas.extend(f"● {t}" for t in est["texto_no_ubicado"])
    return "\n".join(lineas)


def cargar_paginas(ruta: Path):
    """[(num, texto_para_modelo, fuente)] desde manual_consolidado.json."""
    data = json.loads(ruta.read_text(encoding="utf-8"))
    paginas = []
    for e in data["paginas"]:
        if e["fuente"] == "gemini_vision":
            texto = _texto_pagina_vision(e)
        else:
            texto = e.get("texto", "")
        paginas.append((e["pagina"], texto, e["fuente"]))
    return paginas


# --- etapa_aplicable (schema v1.2) — decidida por CÓDIGO, no por el modelo -------
def detectar_etapas(encabezado: str):
    """["E1".."E3"] desde el encabezado del bloque, o None si no nombra etapas.

    Patrones reales del manual: "(1a y 2a ETAPA)", "(1a y 2da ETAPA)",
    "(3a ETAPA)", "(ETAPA 2 Y 3)". None = aplica a todas (semántica v1.1)."""
    up = encabezado.upper()
    m = re.search(r"ETAPA\s*(\d)\s*Y\s*(\d)", up)
    if m:
        etapas = [f"E{m.group(1)}", f"E{m.group(2)}"]
    else:
        m = re.search(r"(\d)[AªERA]*\s*Y\s*(\d)[DA]*\s*ETAPA", up)
        if m:
            etapas = [f"E{m.group(1)}", f"E{m.group(2)}"]
        else:
            m = re.search(r"(\d)[AªERA]*\s*ETAPA", up)
            etapas = [f"E{m.group(1)}"] if m else None
    if etapas and not set(etapas) <= ETAPAS_VALIDAS:
        print(f"  ⚠️ etapa fuera de vocabulario en {encabezado!r}: {etapas} — se deja null")
        return None
    return etapas


# --- Persistencia con reanudación -------------------------------------------------
def _cargar_estado(desde_cero: bool) -> dict:
    if SALIDA.exists():
        if desde_cero:
            respaldo = SALIDA.with_suffix(f".json.bak-{datetime.now():%Y%m%d-%H%M%S}")
            SALIDA.rename(respaldo)
            print(f"(--desde-cero: corrida anterior respaldada en {respaldo.name})")
            return {}
        estado = json.loads(SALIDA.read_text(encoding="utf-8"))
        hechas = [p for p, v in estado.get("paginas", {}).items() if v.get("estado") == "ok"]
        print(f"(reanudando: {len(hechas)} páginas ya extraídas OK se saltan; "
              f"--desde-cero para reiniciar)")
        return estado
    return {}


def _guardar_estado(estado: dict) -> None:
    SALIDA.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


# --- Corrida completa --------------------------------------------------------------
def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--desde-cero"]
    desde_cero = "--desde-cero" in sys.argv[1:]
    ruta = Path(args[0]) if args else CONSOLIDADO_DEFAULT
    if not ruta.exists():
        sys.exit(f"ERROR: no existe el consolidado: {ruta}")

    api_key = _cargar_api_key()
    config = _construir_config(api_key, temperature=0.0)

    paginas = cargar_paginas(ruta)

    # Bloques y seccion_aplicable por CÓDIGO (segmenter/normalizer, sin tocar),
    # alimentados con las páginas del consolidado — no con el PDF.
    bloques = segmentar([(num, texto) for num, texto, _ in paginas])
    norm, no_matchean = normalizar(bloques)
    seccion_por_pagina, etapa_por_pagina, encabezado_por_pagina = {}, {}, {}
    for n in norm:
        etapas = detectar_etapas(n.seccion)
        for p in range(n.pagina_inicio, n.pagina_fin + 1):
            seccion_por_pagina[p] = n.seccion_aplicable
            etapa_por_pagina[p] = etapas
            encabezado_por_pagina[p] = n.seccion

    estado = _cargar_estado(desde_cero)
    estado.setdefault("meta", {})
    estado["meta"].update({
        "schema": "v1.2 (v1.1 + seccion_aplicable + etapa_aplicable E1/E2/E3/null)",
        "consolidado": ruta.name,
        "backend": BACKEND,
        "modelo": MODEL_ID,
        "ultima_corrida": datetime.now().isoformat(timespec="seconds"),
    })
    estado.setdefault("paginas", {})

    print(f"Input: {ruta.name} ({len(paginas)} páginas)")
    print(f"Backend: {BACKEND}  |  Modelo: {MODEL_ID}  |  Schema: v1.2")
    if no_matchean:
        print(f"🟡 Encabezados sin match en normalizer ({len(no_matchean)}) — quedan "
              f"seccion_aplicable=null: {no_matchean}")
    print("=" * 90)

    requests_hechos = 0
    for num, texto, fuente in paginas:
        clave = str(num)
        if estado["paginas"].get(clave, {}).get("estado") == "ok":
            continue  # ya extraída en una corrida anterior — reanudación

        if num in PAGINAS_EXCLUIDAS:
            estado["paginas"][clave] = {"estado": "excluida",
                                        "motivo": PAGINAS_EXCLUIDAS[num], "criterios": []}
            print(f"[pág {num:>2}] EXCLUIDA — {PAGINAS_EXCLUIDAS[num]}")
            _guardar_estado(estado)
            continue

        if fuente != "gemini_vision" and len(texto.split()) < MIN_PALABRAS_PAGINA:
            estado["paginas"][clave] = {"estado": "sin_contenido",
                                        "motivo": f"portada/separador ({len(texto.split())} palabras)",
                                        "criterios": []}
            print(f"[pág {num:>2}] SIN CONTENIDO accionable ({texto.strip()[:40]!r}) — se salta")
            _guardar_estado(estado)
            continue

        print(f"[pág {num:>2}] {fuente:<22} seccion={seccion_por_pagina.get(num)!r} "
              f"etapa={etapa_por_pagina.get(num)!r} ({len(texto)} chars)…")
        try:
            doc = extraer_pagina(texto, config)
            requests_hechos += 1
        except Exception as exc:  # noqa: BLE001
            estado["paginas"][clave] = {"estado": "error",
                                        "error": f"{type(exc).__name__}: {exc}", "criterios": []}
            _guardar_estado(estado)
            if _es_429(exc):
                print(f"  ❌ 429 persistente — cuota agotada. LA CORRIDA QUEDÓ EN LA PÁGINA {num}.")
                print(f"     Relanza `python extractor.py` para retomar desde aquí (estado guardado).")
                break
            print(f"  ⚠️ ERROR en p{num}: {type(exc).__name__}: {exc} — se continúa")
            continue

        criterios = []
        for ext in (doc.extractions or []):
            attrs = ext.attributes or {}
            g, _span = _grounding(ext, texto)
            raw_ref = str(attrs.get("referencia_no_resuelta", "false")).strip().lower()
            ref = True if raw_ref == "true" else (None if raw_ref in ("null", "none", "") else False)
            cond = (attrs.get("condicion_libre") or "").strip() or None
            criterios.append({
                "texto": ext.extraction_text,
                "peso": attrs.get("peso"),
                "severidad": attrs.get("severidad"),
                "condicion_libre": cond,
                "referencia_no_resuelta": ref,
                # Pegados por código (el modelo NUNCA los decide):
                "pagina_origen": num,
                "seccion_aplicable": seccion_por_pagina.get(num),
                "etapa_aplicable": etapa_por_pagina.get(num),
                # Proveniencia/QA (no son schema; el validator los usará):
                "fuente_pagina": fuente,
                "grounding": g,
            })

        estado["paginas"][clave] = {
            "estado": "ok",
            "fuente": fuente,
            "encabezado_bloque": encabezado_por_pagina.get(num),
            "criterios": criterios,
        }
        _guardar_estado(estado)
        resumen_g = {k: sum(1 for c in criterios if c["grounding"] == k)
                     for k in ("exact", "lesser", "failed")}
        print(f"  → {len(criterios)} criterio(s)  grounding: {resumen_g}")
        time.sleep(PAUSA_ENTRE_PAGINAS_S)

    # --- Reporte final -------------------------------------------------------------
    todas = [v for v in estado["paginas"].values()]
    criterios_todos = [c for v in todas for c in v.get("criterios", [])]
    print("\n" + "=" * 90)
    print("RESUMEN DE LA CORRIDA:")
    print(f"  Páginas en estado ok:        {sum(1 for v in todas if v['estado'] == 'ok')}")
    print(f"  Páginas sin contenido:       {sum(1 for v in todas if v['estado'] == 'sin_contenido')}")
    print(f"  Páginas excluidas:           {sum(1 for v in todas if v['estado'] == 'excluida')}")
    print(f"  Páginas con error:           "
          f"{sorted(int(k) for k, v in estado['paginas'].items() if v['estado'] == 'error')}")
    print(f"  Requests hechos esta corrida: {requests_hechos}")
    print(f"  Criterios totales:           {len(criterios_todos)}")
    for k in ("exact", "lesser", "failed"):
        n = sum(1 for c in criterios_todos if c["grounding"] == k)
        print(f"    grounding {k:<7}: {n}")
    n_amb = sum(1 for c in criterios_todos if c["referencia_no_resuelta"] is None)
    n_ref = sum(1 for c in criterios_todos if c["referencia_no_resuelta"] is True)
    print(f"  [AMBIGUO] (ref=null):        {n_amb}")
    print(f"  referencia_no_resuelta=true: {n_ref}")
    print(f"  Output: {SALIDA}")


if __name__ == "__main__":
    main()
