# -*- coding: utf-8 -*-
"""Motor 2 — consolidado de TODAS las páginas del manual en un solo JSON (Sesión N).

Ojo con el conteo: el PDF Gran Barata tiene 48 páginas reales. El "47" que
aparece en otros scripts del proyecto se refiere a los 47 BLOQUES de
conocimiento (ver extractor.py), no a páginas del PDF. Aquí mandan las
páginas físicas del PDF: len(pdf.pages), sin números mágicos.

Une en un solo JSON, ordenado por número de página real y sin huecos:
  - Las páginas DIAGRAMA (según `clasificador_layout.py`) → toman el resultado
    ya generado por `vision_fallback.py` en resultados_vision/pagina_N.json.
    Este script NO llama a Gemini: si falta un JSON o vino con error, ABORTA
    y lo dice explícito — nunca rellena en silencio.
  - Las páginas restantes → texto plano de pdfplumber con use_text_flow=True
    (mismo criterio validado en revisar_multicolumna.py). Cero gasto de API.

La lista de páginas diagrama NO se hardcodea: se recalcula importando el
clasificador (misma regla que vision_fallback.py — no desincronizarse).

Este consolidado es el insumo base para el paso siguiente (extractor.py /
LangExtract). Aquí NO se decide criterio/peso/severidad de nada.

Salida: motor2/manual_consolidado.json. Si ya existe uno de una corrida
anterior, se renombra a .bak-<timestamp> — nunca se pisa sin dejar rastro.

Uso:
    python consolidar_manual.py [ruta_al_pdf]
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pdfplumber

from clasificador_layout import PDF_DEFAULT, clasificar_pdf

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTADOS_VISION_DIR = Path(__file__).resolve().parent / "resultados_vision"
SALIDA = Path(__file__).resolve().parent / "manual_consolidado.json"

# Umbral de sospecha para páginas de texto plano: menos caracteres que esto
# se reporta para revisión a ojo (portadas/separadores gráficos son legítimos,
# pero hay que decirlo, no esconderlo).
MIN_CHARS_TEXTO = 60


def _cargar_vision(pagina: int) -> dict:
    """Carga y valida el JSON de vision_fallback para una página diagrama."""
    ruta = RESULTADOS_VISION_DIR / f"pagina_{pagina}.json"
    if not ruta.exists():
        sys.exit(
            f"ERROR: la página {pagina} está marcada DIAGRAMA pero no existe {ruta.name}. "
            "Corre vision_fallback.py antes de consolidar."
        )
    payload = json.loads(ruta.read_text(encoding="utf-8"))
    if not payload.get("parseo_ok") or "resultado" not in payload:
        sys.exit(
            f"ERROR: {ruta.name} existe pero no trae resultado válido "
            f"(parseo_ok={payload.get('parseo_ok')}). No se consolida con datos rotos."
        )
    return payload


def _guardar(consolidado: dict) -> None:
    if SALIDA.exists():  # nunca pisar la corrida anterior sin rastro
        respaldo = SALIDA.with_suffix(f".json.bak-{datetime.now():%Y%m%d-%H%M%S}")
        SALIDA.rename(respaldo)
        print(f"(corrida anterior respaldada en {respaldo.name})")
    SALIDA.write_text(json.dumps(consolidado, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PDF_DEFAULT
    if not pdf_path.exists():
        sys.exit(f"ERROR: no existe el PDF: {pdf_path}")

    # El clasificador decide qué páginas son diagrama — aquí no se re-decide nada.
    _, scores, umbral = clasificar_pdf(pdf_path)
    paginas_diagrama = sorted(p for p, s in scores.items() if s >= umbral)

    paginas = []
    sospechosas = []  # (pagina, motivo) para revisión a ojo de Gerardo
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        print(f"PDF: {pdf_path.name} ({total} páginas)")
        print(f"Páginas DIAGRAMA (umbral {umbral:.3f}): {paginas_diagrama}")
        print("-" * 80)

        for page in pdf.pages:
            num = page.page_number
            texto = (page.extract_text(use_text_flow=True) or "").strip()

            if num in paginas_diagrama:
                vision = _cargar_vision(num)
                entrada = {
                    "pagina": num,
                    "fuente": "gemini_vision",
                    "texto_crudo": texto,
                    "estructura": vision["resultado"],
                    "vision_meta": {
                        "modelo": vision.get("modelo"),
                        "timestamp": vision.get("timestamp"),
                        "archivo": f"resultados_vision/pagina_{num}.json",
                    },
                }
                if not vision["resultado"].get("secciones"):
                    sospechosas.append((num, "resultado de visión sin secciones"))
            else:
                entrada = {
                    "pagina": num,
                    "fuente": "pdfplumber_text_flow",
                    "texto": texto,
                }
                if not texto:
                    sospechosas.append((num, "sin texto extraíble (¿página 100% gráfica/separador?)"))
                elif len(texto) < MIN_CHARS_TEXTO:
                    sospechosas.append((num, f"texto muy corto ({len(texto)} chars): {texto[:80]!r}"))

            paginas.append(entrada)

    # --- Validación de integridad (antes de reportar "listo") ---
    numeros = [e["pagina"] for e in paginas]
    esperados = list(range(1, total + 1))
    if numeros != esperados:
        faltan = sorted(set(esperados) - set(numeros))
        dobles = sorted({n for n in numeros if numeros.count(n) > 1})
        sys.exit(f"ERROR de integridad: faltan {faltan}, duplicadas {dobles}. NO se guarda.")

    n_vision = sum(1 for e in paginas if e["fuente"] == "gemini_vision")
    n_texto = total - n_vision

    consolidado = {
        "pdf": pdf_path.name,
        "generado": datetime.now().isoformat(timespec="seconds"),
        "total_paginas": total,
        "paginas_vision": paginas_diagrama,
        "n_vision": n_vision,
        "n_texto_plano": n_texto,
        "paginas": paginas,
    }
    _guardar(consolidado)

    print(f"✅ Integridad: {total}/{total} páginas presentes, sin huecos ni duplicados.")
    print(f"   Desde Gemini Vision:  {n_vision} → {paginas_diagrama}")
    print(f"   Desde texto plano:    {n_texto}")
    print(f"   Guardado en: {SALIDA}")
    print("-" * 80)
    if sospechosas:
        print(f"🟡 PÁGINAS PARA REVISAR A OJO ({len(sospechosas)}):")
        for num, motivo in sospechosas:
            print(f"   [pág {num:>3}] {motivo}")
    else:
        print("Sin páginas sospechosas.")


if __name__ == "__main__":
    main()
