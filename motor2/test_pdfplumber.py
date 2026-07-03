# -*- coding: utf-8 -*-
"""Motor 2 — validación de setup.

Recorre TODAS las páginas del PDF (incluyendo separadores sin criterios)
e imprime el número de página real según pdfplumber + los primeros 100
caracteres del texto extraído. Sirve para verificar a ojo que el número
de página coincide con el slide real del PDF.

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


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PDF_DEFAULT
    if not pdf_path.exists():
        sys.exit(f"ERROR: no existe el PDF: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        print(f"PDF: {pdf_path.name}")
        print(f"Total de páginas: {len(pdf.pages)}")
        print("-" * 80)
        for page in pdf.pages:
            texto = page.extract_text() or ""
            muestra = " ".join(texto.split())[:100]
            if not muestra:
                muestra = "(sin texto extraíble — página gráfica/separador)"
            print(f"[pág {page.page_number:>3}] {muestra}")


if __name__ == "__main__":
    main()
