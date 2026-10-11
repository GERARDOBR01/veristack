"""mapa_evidencia.py — lo que midió el código, pintado sobre la foto.

El veredicto dice CUMPLE u OBSERVACIÓN, y la tabla dice qué criterio salió de
dónde. Lo que no se veía era POR QUÉ: qué parte de la foto el código contó como
espacio vacío, qué zonas están quemadas o sin detalle, dónde encontró gráficos.
Este módulo lo dibuja encima de la foto con las MISMAS medidas y los MISMOS
umbrales de photo_analyzer —no hay una segunda opinión—, así que la imagen y el
número del veredicto no pueden contradecirse.

Capas:
  · azul     espacio vacío (claro y poco saturado: estante o muro sin producto)
  · rojo     quemado (luminancia > 250): sin detalle por exceso de luz
  · ámbar    aplastado (luminancia < 5): sin detalle por sombra
  · verde    celdas con densidad de bordes de gráfico/texto

Uso:
    python core/mapa_evidencia.py <foto> [salida.png]
    python core/mapa_evidencia.py autotest
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import unicodedata

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import photo_analyzer as pa  # noqa: E402

ANCHO_MAX = 900          # ancho del mapa; la foto original no se toca
REJILLA = 6              # celdas por lado para ubicar gráficos
LEYENDA_ALTO = 64

AZUL = (59, 130, 246)
ROJO = (229, 72, 77)
AMBAR = (245, 165, 36)
VERDE = (48, 164, 108)


def _fuente(tam: int):
    """Una fuente con acentos: DejaVu (Linux, Streamlit Cloud) o Arial (Windows).
    Sin ninguna, la de Pillow, que no trae acentos: entonces el texto va sin
    ellos en vez de con cuadritos."""
    for nombre in ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "arial.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(nombre, tam), True
        except OSError:
            continue
    return ImageFont.load_default(size=tam), False


def _sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def _mascara_vacio(img: Image.Image, tam: tuple[int, int]) -> np.ndarray:
    """La misma regla que pa._empty_space_ratio (brillo > 220 y saturación < 0.15),
    calculada a 200×200 como allá y llevada al tamaño del mapa."""
    arr = np.array(img.resize((200, 200), Image.LANCZOS), dtype=float)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    brillo = r * 0.299 + g * 0.587 + b * 0.114
    sat = (arr.max(axis=2) - arr.min(axis=2)) / (arr.max(axis=2) + 1e-5)
    m = ((brillo > 220) & (sat < 0.15)).astype(np.uint8) * 255
    return np.array(Image.fromarray(m).resize(tam, Image.NEAREST)) > 0


def _celdas_graficos(img: Image.Image) -> list[tuple[int, int, float]]:
    """Densidad de bordes por celda, con el mismo filtro y el mismo umbral por
    zona que pa._detect_graphics. Devuelve (fila, columna, densidad) de las que
    pasan el umbral."""
    small = img.resize((300, 300), Image.LANCZOS).convert("L")
    edges = np.array(small.filter(ImageFilter.FIND_EDGES), dtype=float)
    lado = 300 // REJILLA
    out = []
    for i in range(REJILLA):
        for j in range(REJILLA):
            celda = edges[i * lado:(i + 1) * lado, j * lado:(j + 1) * lado]
            d = float((celda > 50).sum() / celda.size)
            if d > pa.EDGE_DENSITY_QUADRANT:
                out.append((i, j, round(d, 3)))
    return out


def generar(image) -> tuple[Image.Image, dict]:
    """Devuelve (mapa, leyenda). La leyenda trae las cifras que se pintaron,
    sacadas de las mismas funciones que usa el veredicto."""
    img = pa._load(image)
    k = min(1.0, ANCHO_MAX / img.width)
    w, h = max(1, round(img.width * k)), max(1, round(img.height * k))
    base = img.resize((w, h), Image.LANCZOS)

    # La foto, con autocontraste (una foto oscura también se ve) y luego apagada
    # y casi en gris: el color queda para lo que se midió. Las capas se miden
    # sobre la foto original, no sobre esta.
    visible = ImageOps.autocontrast(base, cutoff=1)
    fondo = Image.blend(visible, ImageOps.grayscale(visible).convert("RGB"), 0.6)
    fondo = Image.eval(fondo, lambda v: int(v * 0.8))
    capa = np.zeros((h, w, 4), dtype=np.uint8)

    def pintar(mask: np.ndarray, color: tuple[int, int, int], alfa: int):
        capa[mask] = (*color, alfa)

    pintar(_mascara_vacio(img, (w, h)), AZUL, 120)
    lum = np.array(base.convert("L"))
    pintar(lum > 250, ROJO, 150)
    pintar(lum < 5, AMBAR, 150)

    mapa = Image.alpha_composite(fondo.convert("RGBA"), Image.fromarray(capa, "RGBA"))
    dibujo = ImageDraw.Draw(mapa)
    celdas = _celdas_graficos(img)
    cw, ch = w / REJILLA, h / REJILLA
    for i, j, _ in celdas:
        dibujo.rectangle([j * cw + 2, i * ch + 2, (j + 1) * cw - 3, (i + 1) * ch - 3], outline=VERDE, width=3)

    expo = pa._exposicion(img)
    graf = pa._detect_graphics(img)
    leyenda = {
        "vacio_pct": round(pa._empty_space_ratio(img) * 100, 1),
        "quemado_pct": expo["quemado_pct"],
        "aplastado_pct": expo["aplastado_pct"],
        "graficos_detectados": graf["detectado"],
        "graficos_ubicacion": graf["ubicacion"],
        "celdas_graficos": len(celdas),
        "fuente": "CODIGO",
    }

    # Tira de leyenda debajo: el mapa se entiende solo, también fuera de la app.
    lienzo = Image.new("RGB", (w, h + LEYENDA_ALTO), (13, 17, 23))
    lienzo.paste(mapa.convert("RGB"), (0, 0))
    d = ImageDraw.Draw(lienzo)
    fuente, con_acentos = _fuente(15)
    txt = (lambda t: t) if con_acentos else _sin_acentos
    x, y = 14, h + 22
    for color, texto in (
        (AZUL, f"vacío {leyenda['vacio_pct']}%"),
        (ROJO, f"quemado {leyenda['quemado_pct']}%"),
        (AMBAR, f"sin detalle {leyenda['aplastado_pct']}%"),
        (VERDE, f"gráficos: {len(celdas)} celdas"),
    ):
        d.rectangle([x, y, x + 16, y + 16], fill=color)
        d.text((x + 22, y), txt(texto), fill=(230, 237, 243), font=fuente)
        x += 22 + int(d.textlength(txt(texto), font=fuente)) + 26
    marca = txt("fuente: CÓDIGO")
    if x + d.textlength(marca, font=fuente) < w - 14:
        d.text((w - 14 - d.textlength(marca, font=fuente), y), marca, fill=(139, 148, 158), font=fuente)
    return lienzo, leyenda


# ──────────────────────────────────────────────────────────────
# Autotest
# ──────────────────────────────────────────────────────────────

def _autotest() -> int:
    fallas: list[str] = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        print(f"  [{'PASS' if cond else 'FAIL'}] {nombre}" + (f" — {detalle}" if detalle and not cond else ""))
        if not cond:
            fallas.append(nombre)

    print("== mapa_evidencia autotest ==")

    # 1. Mitad clara (vacío) y mitad gris con rayas (producto): la cifra del mapa
    #    es la misma que la del veredicto, y el azul cae en la mitad blanca.
    img = Image.new("RGB", (400, 300), (238, 238, 238))   # pared clara: vacío, no quemado
    dr = ImageDraw.Draw(img)
    dr.rectangle([200, 0, 399, 299], fill=(90, 70, 60))
    for xx in range(205, 400, 8):
        dr.line([xx, 0, xx, 299], fill=(200, 180, 40), width=2)
    mapa, ley = generar(img)
    check("la cifra de vacío es la de photo_analyzer", ley["vacio_pct"] == round(pa._empty_space_ratio(img) * 100, 1), str(ley))
    check("mitad clara ≈ 50 % de vacío", 40 <= ley["vacio_pct"] <= 60, str(ley["vacio_pct"]))
    px_izq = mapa.getpixel((50, 150))
    px_der = mapa.getpixel((300, 150))
    check("el azul cae en la mitad vacía", px_izq[2] > px_izq[0] + 30, str(px_izq))
    check("la mitad con producto no se pinta de azul", not (px_der[2] > px_der[0] + 30), str(px_der))
    check("las rayas de la derecha cuentan como gráfico", ley["celdas_graficos"] >= 3, str(ley["celdas_graficos"]))
    check("el mapa trae su tira de leyenda", mapa.size == (400, 300 + LEYENDA_ALTO), str(mapa.size))
    check("la fuente es el código", ley["fuente"] == "CODIGO")

    # 2. Quemado y aplastado: coinciden con _exposicion.
    img2 = Image.new("RGB", (300, 200), (128, 128, 128))
    ImageDraw.Draw(img2).rectangle([0, 0, 99, 199], fill=(255, 255, 255))
    ImageDraw.Draw(img2).rectangle([200, 0, 299, 199], fill=(0, 0, 0))
    _, ley2 = generar(img2)
    expo = pa._exposicion(img2)
    check("quemado = _exposicion", ley2["quemado_pct"] == expo["quemado_pct"], f"{ley2['quemado_pct']} vs {expo['quemado_pct']}")
    check("aplastado = _exposicion", ley2["aplastado_pct"] == expo["aplastado_pct"])
    check("un tercio quemado", 30 <= ley2["quemado_pct"] <= 37, str(ley2["quemado_pct"]))

    # 3. Una foto grande se reduce al ancho del mapa; la original no se toca.
    grande = Image.new("RGB", (3000, 2000), (120, 110, 100))
    m3, _ = generar(grande)
    check("se reduce a ANCHO_MAX", m3.size[0] == ANCHO_MAX, str(m3.size))
    check("la original sigue igual", grande.size == (3000, 2000))

    print(f"\nAUTOTEST MAPA_EVIDENCIA: {'PASS' if not fallas else 'FAIL'} ({len(fallas)} falla(s))")
    return 1 if fallas else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) >= 2 and sys.argv[1] == "autotest":
        sys.exit(_autotest())
    if len(sys.argv) < 2:
        print("Uso: python core/mapa_evidencia.py <foto> [salida.png] | autotest")
        sys.exit(1)
    m, ley = generar(sys.argv[1])
    salida = sys.argv[2] if len(sys.argv) > 2 else "mapa_evidencia.png"
    m.save(salida)
    print(salida, ley)
