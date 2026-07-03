# -*- coding: utf-8 -*-
"""Motor 2 — volcado de texto crudo de páginas multicolumna (SIN IA, SIN costo API).

Imprime el texto completo, extraído con `use_text_flow=True`, de las páginas que
`test_pdfplumber.py` marca como multicolumna (orden por flujo ≠ orden por defecto).
Sirve para que Gerardo compare a ojo, página por página, el texto des-intercalado
contra el PDF real antes de escalar la extracción a los 47 bloques.

NO llama a langextract/Gemini: solo pdfplumber. La lista de páginas NO se hardcodea:
se recalcula con el mismo detector de `test_pdfplumber.py` para no desincronizarse.

Uso:
    python revisar_multicolumna.py [ruta_al_pdf]
"""
import sys
from pathlib import Path

import pdfplumber

# Se reutiliza el detector de test_pdfplumber (importar NO ejecuta su main()).
from test_pdfplumber import PDF_DEFAULT, _es_multicolumna

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PDF_DEFAULT
    if not pdf_path.exists():
        sys.exit(f"ERROR: no existe el PDF: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        # 1) Detecta las páginas multicolumna (mismo criterio que test_pdfplumber).
        flows = {}
        multicolumna = []
        for page in pdf.pages:
            flow = page.extract_text(use_text_flow=True) or ""
            default = page.extract_text() or ""
            flows[page.page_number] = flow
            if _es_multicolumna(default, flow):
                multicolumna.append(page.page_number)

    print(f"PDF: {pdf_path.name}")
    print(f"Lectura: use_text_flow=True  |  Páginas multicolumna: {len(multicolumna)}")
    print(f"Lista: {multicolumna}")
    print("Revisión a ojo: comparar cada volcado contra el slide real del PDF.")

    # 2) Vuelca el texto completo de cada página multicolumna.
    for pag in multicolumna:
        print("\n" + "=" * 90)
        print(f"PÁGINA {pag}")
        print("=" * 90)
        texto = flows[pag].strip()
        print(texto if texto else "(sin texto extraíble — página gráfica/separador)")

    print("\n" + "=" * 90)
    print(f"FIN — {len(multicolumna)} páginas volcadas. Sin llamadas a IA.")


if __name__ == "__main__":
    main()
