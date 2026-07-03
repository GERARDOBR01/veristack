# -*- coding: utf-8 -*-
"""Motor 2 — fallback de Gemini Vision para páginas diagrama/matriz (Sesión M).

"Código decide, modelo interpreta": el clasificador determinista
(`clasificador_layout.py`, sin IA) ya decidió QUÉ páginas necesitan visión.
Este script NO decide nada — solo interpreta esas páginas ya marcadas.
Las demás páginas siguen por pdfplumber normal, cero gasto de API.

Qué hace, por cada página marcada DIAGRAMA:
  1. Renderiza la página a imagen (~1024 px de ancho) con pdfplumber/pypdfium2
     (ya en el venv — no se instaló nada nuevo) y la comprime a JPEG.
  2. Llama a Gemini Vision con la imagen + el texto crudo que pdfplumber ya
     extrajo de esa misma página (use_text_flow=True). El texto va como
     contexto: ya tiene las palabras correctas, al modelo solo se le pide
     reconstruir la relación espacial/estructural que la extracción plana pierde.
  3. Guarda el JSON estructurado en resultados_vision/pagina_N.json. Si ya
     existe un resultado de una corrida anterior, se renombra a
     pagina_N.json.bak-<timestamp> — nunca se sobreescribe sin dejar rastro.

La lista de páginas NO se hardcodea: se recalcula importando el clasificador
(misma regla que revisar_multicolumna.py — no desincronizarse del detector).

Claves: el .env de la raíz trae varias GEMINI_API_KEY (mismo nombre, separadas
por retorno de carro). Se parsean TODAS y se rota a la siguiente si una
devuelve error de cuota (429/RESOURCE_EXHAUSTED). Las claves nunca se imprimen.

Uso:
    python vision_fallback.py [ruta_al_pdf]
"""
import io
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pdfplumber
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from clasificador_layout import PDF_DEFAULT, clasificar_pdf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
RESULTADOS_DIR = Path(__file__).resolve().parent / "resultados_vision"

MODELO = "gemini-2.5-flash"
ANCHO_PX = 1024          # ancho objetivo del render; ajustar solo si Gemini rechaza calidad
JPEG_CALIDAD = 85
PAUSA_ENTRE_PAGINAS_S = 7  # respeta el rate limit del tier gratuito (~10 RPM)

# Schema mínimo, consistente entre todas las páginas. Se pide vía prompt +
# response_mime_type=application/json (sin response_schema estricto: los
# diagramas varían — planograma, timeline, prioridades — y un schema rígido
# forzaría al modelo a inventar campos que no aplican).
PROMPT = """Eres un analista de visual merchandising de retail. Recibes:
1. La IMAGEN de una página (slide) de un manual de montaje de campaña.
2. El TEXTO CRUDO que un extractor de PDF ya sacó de esa misma página.

El texto crudo tiene las palabras correctas, pero la extracción plana perdió \
la relación espacial: no se sabe qué texto pertenece a qué eje, columna, nivel \
de mueble, celda de matriz o punto de una línea de tiempo. Tu única tarea es \
reconstruir esa estructura mirando la imagen. NO inventes texto que no esté en \
la imagen; usa las palabras del texto crudo siempre que puedas.

Responde SOLO con un JSON válido con exactamente esta forma:
{
  "tipo_layout": "planograma" | "timeline" | "matriz" | "lista_prioridades" | "mixto" | "otro",
  "titulo": "título principal de la página, o null",
  "descripcion_general": "1-3 frases: qué comunica este diagrama y cómo está organizado",
  "secciones": [
    {
      "nombre": "nombre de la sección/eje/columna/nivel tal como aparece, o descriptivo si no tiene rótulo",
      "rol": "qué es dentro del diagrama (ej: 'columna izquierda: mesa 1', 'eje temporal', 'nivel superior del mueble', 'fila de la matriz')",
      "elementos": ["cada texto/instrucción que pertenece a esta sección, en orden de lectura"]
    }
  ],
  "relaciones": ["relaciones estructurales que el texto plano pierde, en frases explícitas (ej: 'PRIORIDAD 1 corresponde a la zona frontal de la mesa', 'la fecha 15 mayo aplica solo a tiendas AAA')"],
  "texto_no_ubicado": ["fragmentos del texto crudo que NO pudiste ubicar en ninguna sección de la imagen"]
}

Reglas:
- "secciones" debe cubrir todo el contenido visible; ninguna sección vacía.
- Si un dato aparece ligado visualmente a otro (flecha, celda, posición), esa \
liga va en "relaciones".
- Si la imagen es ilegible o no coincide con el texto crudo, dilo en \
"descripcion_general" y deja el resto lo más honesto posible; no rellenes.

TEXTO CRUDO DE LA PÁGINA:
---
{TEXTO_CRUDO}
---
"""


def _cargar_claves() -> list[str]:
    """Extrae TODAS las GEMINI_API_KEY del .env (hay varias con el mismo nombre)."""
    raw = ENV_PATH.read_text(encoding="utf-8", errors="replace")
    claves = re.findall(r"GEMINI_API_KEY\s*=\s*([^\s\r\n]+)", raw)
    if not claves:
        sys.exit(f"ERROR: no hay GEMINI_API_KEY en {ENV_PATH}")
    return claves


def _render_jpeg(page) -> bytes:
    """Renderiza la página a JPEG de ~ANCHO_PX px de ancho."""
    resolucion = int(ANCHO_PX / float(page.width) * 72)
    imagen = page.to_image(resolution=resolucion).original.convert("RGB")
    buf = io.BytesIO()
    imagen.save(buf, format="JPEG", quality=JPEG_CALIDAD)
    return buf.getvalue()


class PoolGemini:
    """Rota entre las claves disponibles cuando una agota su cuota."""

    def __init__(self, claves: list[str]):
        self._claves = claves
        self._idx = 0
        self._cliente = genai.Client(api_key=claves[0])
        self.requests = 0
        self.tokens_prompt = 0
        self.tokens_respuesta = 0

    def _rotar(self):
        self._idx = (self._idx + 1) % len(self._claves)
        self._cliente = genai.Client(api_key=self._claves[self._idx])
        print(f"    (cuota agotada — rotando a la clave #{self._idx + 1} de {len(self._claves)})")

    def generar(self, jpeg: bytes, texto_crudo: str) -> str:
        prompt = PROMPT.replace("{TEXTO_CRUDO}", texto_crudo or "(sin texto extraíble)")
        intentos_max = len(self._claves) * 2
        for intento in range(intentos_max):
            try:
                self.requests += 1
                resp = self._cliente.models.generate_content(
                    model=MODELO,
                    contents=[
                        genai_types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
                        prompt,
                    ],
                    config=genai_types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                    ),
                )
                uso = resp.usage_metadata
                if uso:
                    self.tokens_prompt += uso.prompt_token_count or 0
                    self.tokens_respuesta += (uso.candidates_token_count or 0) + (
                        uso.thoughts_token_count or 0
                    )
                return resp.text or ""
            except genai_errors.APIError as e:
                # Rota tanto por cuota agotada como por clave inválida (hay varias
                # claves en el .env y no todas tienen por qué estar vivas).
                rotable = (
                    e.code in (401, 403, 429)
                    or "RESOURCE_EXHAUSTED" in str(e)
                    or "API key not valid" in str(e)
                )
                if rotable and intento < intentos_max - 1:
                    self._rotar()
                    time.sleep(10)
                    continue
                raise
        raise RuntimeError("agotados los reintentos con todas las claves")


def _guardar(pagina: int, payload: dict) -> Path:
    RESULTADOS_DIR.mkdir(exist_ok=True)
    destino = RESULTADOS_DIR / f"pagina_{pagina}.json"
    if destino.exists():  # nunca pisar la corrida anterior sin rastro
        respaldo = destino.with_suffix(f".json.bak-{datetime.now():%Y%m%d-%H%M%S}")
        destino.rename(respaldo)
        print(f"    (corrida anterior respaldada en {respaldo.name})")
    destino.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destino


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PDF_DEFAULT
    if not pdf_path.exists():
        sys.exit(f"ERROR: no existe el PDF: {pdf_path}")

    pool = PoolGemini(_cargar_claves())

    # El clasificador decide las páginas — aquí no se re-decide nada.
    _, scores, umbral = clasificar_pdf(pdf_path)
    paginas_diagrama = sorted(p for p, s in scores.items() if s >= umbral)
    print(f"PDF: {pdf_path.name}")
    print(f"Páginas DIAGRAMA según clasificador_layout (umbral {umbral:.3f}): {paginas_diagrama}")
    print(f"Modelo: {MODELO} | render ~{ANCHO_PX}px | claves disponibles: {len(pool._claves)}")
    print("-" * 80)

    ok, con_error = [], []
    with pdfplumber.open(pdf_path) as pdf:
        for i, num in enumerate(paginas_diagrama):
            page = pdf.pages[num - 1]
            assert page.page_number == num
            print(f"[pág {num:>3}] renderizando + llamando a Gemini…")
            jpeg = _render_jpeg(page)
            texto_crudo = page.extract_text(use_text_flow=True) or ""

            payload = {
                "pagina": num,
                "pdf": pdf_path.name,
                "modelo": MODELO,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "render_px_ancho": ANCHO_PX,
                "render_kb": round(len(jpeg) / 1024, 1),
                "texto_crudo_chars": len(texto_crudo),
            }
            try:
                bruto = pool.generar(jpeg, texto_crudo)
                try:
                    payload["resultado"] = json.loads(bruto)
                    payload["parseo_ok"] = True
                    ok.append(num)
                except json.JSONDecodeError as e:
                    payload["parseo_ok"] = False
                    payload["error_parseo"] = str(e)
                    payload["respuesta_cruda"] = bruto
                    con_error.append(num)
                    print(f"    ⚠️ respuesta NO es JSON válido — guardada cruda para revisión")
            except Exception as e:
                payload["parseo_ok"] = False
                payload["error_api"] = f"{type(e).__name__}: {e}"
                con_error.append(num)
                print(f"    ❌ error de API: {type(e).__name__}: {e}")

            destino = _guardar(num, payload)
            print(f"    → {destino.relative_to(destino.parents[2])}")

            if i < len(paginas_diagrama) - 1:
                time.sleep(PAUSA_ENTRE_PAGINAS_S)

    print("-" * 80)
    print("RESUMEN DE LA CORRIDA:")
    print(f"  Páginas OK (JSON válido): {len(ok)} → {ok}")
    print(f"  Páginas con error:        {len(con_error)} → {con_error}")
    print(f"  Requests a la API:        {pool.requests}")
    print(f"  Tokens prompt:            {pool.tokens_prompt}")
    print(f"  Tokens respuesta (+razonamiento): {pool.tokens_respuesta}")
    print(f"  Resultados en: {RESULTADOS_DIR}")


if __name__ == "__main__":
    main()
