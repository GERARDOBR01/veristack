# -*- coding: utf-8 -*-
"""Motor 2 — segmentador de secciones (100% heurística, SIN IA).

Agrupa el texto por página (extraído con pdfplumber, misma lógica de lectura
que test_pdfplumber.py) en bloques por sección. Los encabezados se detectan
por patrón de texto: primera línea de la página, corta, en mayúsculas o con
formato "PREFIJO: ..." / "PREFIJO - ...".

NO normaliza el nombre de sección (eso es un paso posterior): conserva el
texto crudo del encabezado tal como aparece en el PDF.

Uso:
    python segmenter.py [ruta_al_pdf]
"""
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

# Consolas Windows suelen ser cp1252; el texto de los manuales trae viñetas.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PDF_DEFAULT = Path(r"C:\Users\jesus\Downloads\MECÁNICA MONTAJE GRAN BARATA PV 2026 .pdf")

# Un encabezado del manual es una línea corta; ninguno observado supera ~44.
MAX_LEN_ENCABEZADO = 60
# Títulos full mayúsculas ("MONTAJE SOFTLINE", "DIVERSOS", "SOFTLINE: ...").
MIN_RATIO_MAYUS = 0.6
# Títulos mixtos que no alcanzan el ratio pero llevan prefijo de sección en
# mayúsculas y un separador: "HOGAR - Muebles", "DEPORTES - Zapatos", etc.
RE_PREFIJO_SECCION = re.compile(r"^[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ0-9 ]{2,}\s*[:\-]")


@dataclass
class Bloque:
    seccion: str          # texto crudo del encabezado detectado (sin normalizar)
    pagina_inicio: int
    pagina_fin: int
    texto: str = ""       # contenido bajo el encabezado, sin la línea de título


def _ratio_mayus(texto: str) -> float:
    letras = [c for c in texto if c.isalpha()]
    if not letras:
        return 0.0
    return sum(1 for c in letras if c.isupper()) / len(letras)


def es_encabezado(linea: str) -> bool:
    """True si la línea parece un encabezado de sección del manual."""
    linea = linea.strip()
    if not linea or len(linea) > MAX_LEN_ENCABEZADO:
        return False
    if _ratio_mayus(linea) >= MIN_RATIO_MAYUS:
        return True
    return bool(RE_PREFIJO_SECCION.match(linea))


def leer_paginas(pdf_path: Path):
    """Devuelve [(numero_real, texto)] por página.

    Misma lógica de lectura que test_pdfplumber.py; se replica aquí en vez de
    importarla porque ese script no expone una función reutilizable (todo vive
    dentro de su main()) y el alcance de esta sesión es no tocarlo.
    """
    paginas = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            paginas.append((page.page_number, page.extract_text() or ""))
    return paginas


def segmentar(paginas):
    """Agrupa páginas en bloques por sección hasta el próximo encabezado."""
    bloques = []
    actual = None
    for num, texto in paginas:
        lineas = [l.strip() for l in texto.splitlines() if l.strip()]
        primera = lineas[0] if lineas else ""
        resto = lineas[1:]
        if es_encabezado(primera):
            actual = Bloque(
                seccion=primera,
                pagina_inicio=num,
                pagina_fin=num,
                texto="\n".join(resto),
            )
            bloques.append(actual)
        elif actual is not None:
            # Página sin encabezado propio: es continuación del bloque previo.
            actual.pagina_fin = num
            cuerpo = "\n".join(lineas)
            actual.texto = f"{actual.texto}\n{cuerpo}".strip()
        else:
            # Página sin encabezado antes de cualquier bloque: huérfana.
            actual = Bloque(
                seccion="(sin encabezado)",
                pagina_inicio=num,
                pagina_fin=num,
                texto="\n".join(lineas),
            )
            bloques.append(actual)
    return bloques


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PDF_DEFAULT
    if not pdf_path.exists():
        sys.exit(f"ERROR: no existe el PDF: {pdf_path}")

    paginas = leer_paginas(pdf_path)
    bloques = segmentar(paginas)

    print(f"PDF: {pdf_path.name}")
    print(f"Páginas: {len(paginas)}  |  Bloques detectados: {len(bloques)}")
    print("-" * 80)
    for b in bloques:
        rango = (
            f"p{b.pagina_inicio}"
            if b.pagina_inicio == b.pagina_fin
            else f"p{b.pagina_inicio}-{b.pagina_fin}"
        )
        muestra = " ".join(b.texto.split())[:80]
        if not muestra:
            muestra = "(separador sin contenido)"
        print(f"[{rango:>8}] {b.seccion}")
        print(f"           {muestra}")


if __name__ == "__main__":
    main()
