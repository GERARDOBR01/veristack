# -*- coding: utf-8 -*-
"""Motor 2 — validación de setup + diagnóstico de páginas multicolumna.

Recorre TODAS las páginas del PDF (incluyendo separadores sin criterios) e imprime
el número de página real según pdfplumber + una muestra del texto extraído.

Lectura con `extract_text(use_text_flow=True)`: usa el orden del stream interno del
PDF, que respeta las columnas. NOTA (Sesión I): se probó `layout=True` (lo pedido en
el brief) y NO des-intercala las columnas — solo preserva la posición X con padding,
así que el orden de lectura sigue mezclando columnas (verificado en p10). El que sí
des-intercala es `use_text_flow=True`; por eso es el que se usa aquí y en extractor.py.

Cada página se marca `MULTICOLUMNA` cuando el orden por flujo (use_text_flow) difiere
del orden geométrico por defecto (extract_text) — señal de que la página tiene
columnas que el modo por defecto intercala. Solo se REPORTAN; no se "arreglan" aquí.

Uso:
    python test_pdfplumber.py [ruta_al_pdf]
"""
import sys
from pathlib import Path

import pdfplumber

# Consolas Windows suelen ser cp1252; el texto de los manuales trae viñetas
# y símbolos fuera de ese charset.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PDF_DEFAULT = Path(r"C:\Users\jesus\Downloads\MECÁNICA MONTAJE GRAN BARATA PV 2026 .pdf")


def _lineas(texto: str):
    """Líneas no vacías, con whitespace colapsado (para comparar orden)."""
    return [" ".join(l.split()) for l in (texto or "").splitlines() if l.strip()]


def _es_multicolumna(default: str, flow: str) -> bool:
    """True si ambos modos tienen las MISMAS palabras pero en distinto ORDEN.

    Se compara a nivel de palabra (no de línea) a propósito: cuando hay columnas, el
    modo por defecto no solo reordena sino que a veces funde dos fragmentos de
    columnas distintas en una misma línea (ej. p10, la línea de la NOTA). Comparar
    líneas se perdería esos casos; comparar la secuencia de palabras los detecta.
    Mismas palabras + distinta secuencia = columnas que el modo por defecto intercala."""
    wd = " ".join(default.split()).split()
    wf = " ".join(flow.split()).split()
    return wd != wf and sorted(wd) == sorted(wf)


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PDF_DEFAULT
    if not pdf_path.exists():
        sys.exit(f"ERROR: no existe el PDF: {pdf_path}")

    multicolumna = []
    with pdfplumber.open(pdf_path) as pdf:
        print(f"PDF: {pdf_path.name}")
        print(f"Total de páginas: {len(pdf.pages)}  (lectura: use_text_flow=True)")
        print("-" * 80)
        for page in pdf.pages:
            flow = page.extract_text(use_text_flow=True) or ""
            default = page.extract_text() or ""
            multi = _es_multicolumna(default, flow)
            if multi:
                multicolumna.append(page.page_number)
            muestra = " ".join(flow.split())[:100]
            if not muestra:
                muestra = "(sin texto extraíble — página gráfica/separador)"
            flag = " [MULTICOLUMNA]" if multi else ""
            print(f"[pág {page.page_number:>3}]{flag} {muestra}")

    print("-" * 80)
    if multicolumna:
        print(f"Páginas MULTICOLUMNA (orden por flujo ≠ orden por defecto): {multicolumna}")
        print("  → use_text_flow=True las lee des-intercaladas. Revisar a ojo que el")
        print("    orden de lectura por columna sea el correcto antes de escalar.")
    else:
        print("No se detectaron páginas multicolumna.")


if __name__ == "__main__":
    main()
