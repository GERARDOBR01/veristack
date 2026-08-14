"""casos.py — genera el ground truth SINTÉTICO del benchmark.

Cada caso es una imagen construida por código con un defecto inyectado a propósito,
más el veredicto que el motor **debería** emitir para las reglas duras.

Por qué sintético: el conocimiento y las fotos reales de un cliente nunca entran a este
repo (regla 1 de CLAUDE.md). Un ground truth generado tiene además una propiedad que uno
real no tiene — **se sabe con certeza qué defecto lleva cada imagen**, porque se inyectó.

Solo se evalúan las reglas que decide el código sin modelo. Los criterios delegados no
entran: su veredicto depende de un proveedor externo y no serían reproducibles.
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

F = lambda n, s: ImageFont.truetype(rf"C:\Windows\Fonts\{n}", s)
COLS = [(58, 78, 110), (128, 62, 66), (86, 96, 88), (176, 168, 150)]

# Veredictos esperados. Ausencia de una clave = "no se evalúa este criterio en este caso".
GRAVE, OBSERVACION, CUMPLE = "GRAVE", "OBSERVACION", "CUMPLE"


def _fuente(nombre, tam):
    try:
        return F(nombre, tam)
    except OSError:                      # CI corre en Linux, sin fuentes de Windows
        return ImageFont.load_default()


def escena(w=1400, h=1000, con_grafico=True, vacio=False, prendas=4):
    img = Image.new("RGB", (w, h), (232, 230, 226))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, int(h * .64)], fill=(238, 236, 232))
    d.rectangle([0, int(h * .64), w, h], fill=(206, 201, 194))
    for x in range(0, w, 180):
        d.line([(x, h * .64), (x - 120, h)], fill=(196, 191, 184), width=2)

    if con_grafico:
        d.rectangle([420, 60, 980, 210], fill=(24, 30, 38), outline=(70, 80, 92), width=3)
        d.text((470, 96), "MERCADEP", font=_fuente("segoeuib.ttf", 54), fill=(245, 245, 245))
        d.text((472, 158), "TEMPORADA DEMO - PV 2026", font=_fuente("segoeui.ttf", 22),
               fill=(180, 186, 196))

    if not vacio:
        d.rectangle([300, 520, 1100, 700], fill=(150, 128, 104))
        d.rectangle([300, 520, 1100, 545], fill=(176, 152, 124))
        x0 = 340
        for i in range(prendas):
            c = COLS[i % 4]
            for k in range(3):
                y = 470 - k * 24
                d.rectangle([x0, y, x0 + 150, y + 22], fill=c, outline=(40, 40, 44))
                d.line([(x0 + 8, y + 11), (x0 + 142, y + 11)], fill=(255, 255, 255), width=1)
            x0 += 185
        for tx in (110, 1180):
            d.rectangle([tx, 240, tx + 120, 700], fill=(214, 210, 204),
                        outline=(120, 118, 114), width=3)
            for k in range(4):
                yy = 270 + k * 105
                d.rectangle([tx + 12, yy, tx + 108, yy + 80], fill=COLS[k % 4],
                            outline=(60, 60, 64))
    return img


def _oscura(factor):
    return lambda: ImageEnhance.Brightness(escena()).enhance(factor)


def _borrosa(radio):
    return lambda: escena().filter(ImageFilter.GaussianBlur(radio))


# (id, generador, veredicto_global_esperado, regla_que_debe_dispararse | None)
CASOS = [
    # correctas: luz y foco normales -> ninguna regla dura debe bloquear
    ("ok_montaje_completo",     lambda: escena(),                  "NO_GRAVE", None),
    ("ok_tres_pilas",           lambda: escena(prendas=3),         "NO_GRAVE", None),
    ("ok_sin_grafico",          lambda: escena(con_grafico=False),  "NO_GRAVE", None),

    # oscuras: por debajo del minimo de brillo (40)
    ("oscura_sin_luz",          _oscura(0.10),                     "GRAVE", "imagen_oscura"),
    ("oscura_penumbra",         _oscura(0.15),                     "GRAVE", "imagen_oscura"),
    ("oscura_limite",           _oscura(0.19),                     "GRAVE", "imagen_oscura"),

    # zona gris declarada: cerca del umbral, se espera que YA no dispare
    ("luz_baja_aceptable",      _oscura(0.30),                     "NO_GRAVE", None),

    # borrosas: por debajo del minimo de nitidez (30)
    ("borrosa_movida",          _borrosa(9),                       "GRAVE", "imagen_borrosa"),
    ("borrosa_fuera_de_foco",   _borrosa(5),                       "GRAVE", "imagen_borrosa"),
    ("borrosa_leve",            _borrosa(3),                       "GRAVE", "imagen_borrosa"),

    # espacio vacio: mueble sin producto, falla de calidad sin bloquear
    ("vacio_mueble_pelon",      lambda: escena(vacio=True),        "OBSERVACION", "espacio_vacio_elevado"),

    # combinada: oscura Y borrosa -> debe frenar en la primera regla dura
    ("combinada_oscura_borrosa",
     lambda: ImageEnhance.Brightness(escena().filter(ImageFilter.GaussianBlur(9))).enhance(0.12),
     "GRAVE", "imagen_oscura"),
]
