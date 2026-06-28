"""
photo_analyzer.py — Pre-análisis de imagen para El Verificador (visual merchandising).
Extrae hechos objetivos antes de pasarlos al modelo.
Sin ML pesado — solo PIL y NumPy.
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageStat

# ──────────────────────────────────────────────────────────────
# Umbrales configurables
# ──────────────────────────────────────────────────────────────

BRIGHTNESS_MIN = 30          # debajo → imagen muy oscura
BRIGHTNESS_MAX = 92          # arriba → sobreexpuesta
EMPTY_SPACE_GRAVE = 0.60     # ratio espacio vacío → GRAVE
SHARPNESS_BUENA = 100        # varianza Laplaciana
SHARPNESS_REGULAR = 30
EDGE_DENSITY_GLOBAL = 0.07   # umbral global para "hay gráficos"
EDGE_DENSITY_QUADRANT = 0.10 # umbral por cuadrante para ubicación

# Tabla hue (0-360) → nombre de color
_HUE_TABLE = [
    (0,   15,  "rojo"),
    (15,  30,  "naranja"),
    (30,  60,  "amarillo"),
    (60,  90,  "verde amarillo"),
    (90,  150, "verde"),
    (150, 180, "verde azul"),
    (180, 210, "cian"),
    (210, 255, "azul"),
    (255, 285, "azul violeta"),
    (285, 330, "violeta"),
    (330, 360, "rosa"),
]


# ──────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────

def _load(image) -> Image.Image:
    if isinstance(image, (str, Path)):
        return Image.open(image).convert("RGB")
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    raise TypeError(f"Se esperaba path o PIL.Image, recibido: {type(image)}")


def _hex(r, g, b) -> str:
    return "#{:02X}{:02X}{:02X}".format(int(r), int(g), int(b))


def _color_name(r, g, b) -> str:
    r_, g_, b_ = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(r_, g_, b_), min(r_, g_, b_)
    v = mx
    s = 0.0 if mx == 0 else (mx - mn) / mx

    if v < 0.15:
        return "negro"
    if v > 0.85 and s < 0.15:
        return "blanco"
    if s < 0.15:
        return "gris"

    if mx == mn:
        h = 0.0
    elif mx == r_:
        h = 60 * ((g_ - b_) / (mx - mn) % 6)
    elif mx == g_:
        h = 60 * ((b_ - r_) / (mx - mn) + 2)
    else:
        h = 60 * ((r_ - g_) / (mx - mn) + 4)

    for lo, hi, name in _HUE_TABLE:
        if lo <= h < hi:
            return name
    return "rojo"  # wrap 330-360


def _dominant_colors(img: Image.Image, n: int = 3) -> list:
    """Colores dominantes por cuantización mediana."""
    small = img.resize((150, 150), Image.LANCZOS)
    quantized = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette()  # 256*3 valores; los primeros n*3 son los usados

    arr = np.array(quantized)
    counts = np.bincount(arr.flatten(), minlength=n)[:n]
    order = np.argsort(counts)[::-1]  # más frecuente primero

    colors = []
    for i in order:
        r, g, b = palette[i * 3], palette[i * 3 + 1], palette[i * 3 + 2]
        colors.append({
            "hex": _hex(r, g, b),
            "nombre": _color_name(r, g, b),
            "rgb": [int(r), int(g), int(b)],
        })
    return colors


def _laplacian_variance(img: Image.Image) -> float:
    """Varianza del filtro Laplaciano — proxy de nitidez. Mayor = más nítido."""
    gray = np.array(img.convert("L"), dtype=float)
    # Laplaciano discrego: L[i,j] = vecinos_suma - 4*centro
    lap = (
        gray[:-2, 1:-1]   # arriba
        + gray[2:, 1:-1]  # abajo
        + gray[1:-1, :-2] # izquierda
        + gray[1:-1, 2:]  # derecha
        - 4 * gray[1:-1, 1:-1]
    )
    return float(np.var(lap))


def _empty_space_ratio(img: Image.Image) -> float:
    """
    Fracción de píxeles considerados 'espacio vacío'.
    Proxy: píxeles muy claros y poco saturados (fondo blanco, estante vacío).
    """
    arr = np.array(img.resize((200, 200), Image.LANCZOS), dtype=float)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    brightness = r * 0.299 + g * 0.587 + b * 0.114
    chan_max = arr.max(axis=2)
    chan_min = arr.min(axis=2)
    saturation = (chan_max - chan_min) / (chan_max + 1e-5)
    empty_mask = (brightness > 220) & (saturation < 0.15)
    return float(empty_mask.sum() / empty_mask.size)


def _detect_graphics(img: Image.Image) -> dict:
    """
    Detecta presencia de texto/gráficos por densidad de bordes.
    Retorna si hay gráficos y su ubicación aproximada (cuadrante).
    """
    small = img.resize((300, 300), Image.LANCZOS).convert("L")
    edges = np.array(small.filter(ImageFilter.FIND_EDGES), dtype=float)
    h, w = edges.shape

    global_density = float((edges > 50).sum() / edges.size)

    quadrants = {
        "superior": edges[:h // 2, :],
        "inferior": edges[h // 2:, :],
        "izquierda": edges[:, :w // 2],
        "derecha": edges[:, w // 2:],
    }
    locations = [
        name for name, q in quadrants.items()
        if float((q > 50).sum() / q.size) > EDGE_DENSITY_QUADRANT
    ]

    detected = global_density > EDGE_DENSITY_GLOBAL
    return {
        "detectado": detected,
        "ubicacion": locations if detected else [],
        "densidad_bordes": round(global_density, 3),
    }


def _brightness_to_quality(brightness: float, sharpness: float) -> str:
    too_dark = brightness < BRIGHTNESS_MIN
    too_bright = brightness > BRIGHTNESS_MAX
    blurry = sharpness < SHARPNESS_REGULAR

    if too_dark or too_bright or blurry:
        return "mala"
    if sharpness < SHARPNESS_BUENA or brightness < 45 or brightness > 82:
        return "regular"
    return "buena"


# ──────────────────────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────────────────────

def classify_photo_type(image) -> str:
    """
    Clasifica el tipo de foto de visual merchandising.
    Retorna: "focal_show" | "tringla" | "mesa_show" | "panoramica" | "desconocido"
    Heurística basada en proporción y densidad visual.
    """
    try:
        img = _load(image)
        w, h = img.size
        ratio = w / h  # > 1 landscape, < 1 portrait

        empty = _empty_space_ratio(img)

        if ratio > 2.2:
            return "panoramica"

        if ratio < 0.75:
            return "focal_show"

        if 0.75 <= ratio <= 1.4:
            # Cuadrado/casi cuadrado: tringla (3 focos, más aire) o focal_show
            return "tringla" if empty > 0.35 else "focal_show"

        if 1.4 < ratio <= 2.2:
            return "mesa_show"

        return "desconocido"

    except Exception:
        return "desconocido"


def extract_basic_facts(image) -> dict:
    """
    Extrae hechos objetivos medibles de la imagen.
    Cada sub-extracción tiene su propio try/except para no fallar en bloque.
    """
    img = None
    load_error = None
    try:
        img = _load(image)
    except Exception as e:
        load_error = str(e)

    facts = {
        "dominant_colors": [],
        "brightness": 0.0,
        "quality": "mala",
        "sharpness_score": 0.0,
        "empty_space_ratio": 0.0,
        "graphics_detected": False,
        "graphics_location": [],
    }

    if load_error:
        facts["error"] = load_error
        return facts

    try:
        facts["dominant_colors"] = _dominant_colors(img, n=3)
    except Exception:
        pass

    try:
        facts["brightness"] = round(_average_brightness(img), 1)
    except Exception:
        pass

    try:
        facts["sharpness_score"] = round(_laplacian_variance(img), 2)
    except Exception:
        pass

    try:
        facts["empty_space_ratio"] = round(_empty_space_ratio(img), 3)
    except Exception:
        pass

    try:
        g = _detect_graphics(img)
        facts["graphics_detected"] = g["detectado"]
        facts["graphics_location"] = g["ubicacion"]
    except Exception:
        pass

    facts["quality"] = _brightness_to_quality(facts["brightness"], facts["sharpness_score"])

    return facts


def _average_brightness(img: Image.Image) -> float:
    stat = ImageStat.Stat(img.convert("L"))
    return stat.mean[0] / 255.0 * 100


def check_hard_rules(image, facts: dict) -> list:
    """
    Reglas duras que el código determina automáticamente, sin intervención del modelo.
    El parámetro image se reserva para reglas futuras que requieran datos de píxel.
    Retorna lista de flags: [{rule, severity, description}]
    """
    flags = []

    try:
        brightness = facts.get("brightness", 50.0)
        empty_ratio = facts.get("empty_space_ratio", 0.0)
        quality = facts.get("quality", "regular")

        if brightness < BRIGHTNESS_MIN:
            flags.append({
                "rule": "IMAGEN_MUY_OSCURA",
                "severity": "GRAVE",
                "description": f"Brillo promedio {brightness:.1f}/100 - imagen ilegible",
            })

        if brightness > BRIGHTNESS_MAX:
            flags.append({
                "rule": "IMAGEN_SOBREEXPUESTA",
                "severity": "GRAVE",
                "description": f"Brillo promedio {brightness:.1f}/100 - perdida de detalle por sobreexposicion",
            })

        if empty_ratio > EMPTY_SPACE_GRAVE:
            flags.append({
                "rule": "ESPACIO_VACIO_EXCESIVO",
                "severity": "GRAVE",
                "description": f"Espacio vacío estimado en {empty_ratio * 100:.0f}% — supera el límite de 60%",
            })

        # Calidad mala no cubierta por los flags anteriores (ej. solo borrosidad)
        if quality == "mala" and brightness >= BRIGHTNESS_MIN and brightness <= BRIGHTNESS_MAX:
            flags.append({
                "rule": "CALIDAD_IMAGEN_BAJA",
                "severity": "OBSERVACION",
                "description": "Imagen borrosa o de baja nitidez",
            })

    except Exception as e:
        flags.append({
            "rule": "ERROR_EVALUACION_REGLAS",
            "severity": "OBSERVACION",
            "description": f"No se pudieron evaluar reglas duras: {e}",
        })

    return flags


def build_context_report(photo_type: str, facts: dict, hard_rule_flags: list) -> dict:
    """
    Ensambla el reporte JSON listo para pasar al modelo como contexto estructurado.
    """
    try:
        has_grave = any(f.get("severity") == "GRAVE" for f in hard_rule_flags)
        has_obs = any(f.get("severity") == "OBSERVACION" for f in hard_rule_flags)

        if has_grave:
            pre_verdict = "RECHAZAR"
        elif has_obs:
            pre_verdict = "OBSERVACION"
        else:
            pre_verdict = "PROCEDER"

        empty_pct = facts.get("empty_space_ratio", 0.0)
        occupied_pct = 1.0 - empty_pct

        return {
            "photo_type": photo_type,
            "quality": facts.get("quality", "desconocido"),
            "brightness": facts.get("brightness", 0.0),
            "dominant_colors": facts.get("dominant_colors", []),
            "space_usage": f"{occupied_pct * 100:.0f}%",
            "empty_space": f"{empty_pct * 100:.0f}%",
            "graphics_detected": facts.get("graphics_detected", False),
            "graphics_location": facts.get("graphics_location", []),
            "hard_rule_flags": hard_rule_flags,
            "pre_verdict": pre_verdict,
        }

    except Exception as e:
        return {
            "photo_type": "desconocido",
            "quality": "mala",
            "brightness": 0.0,
            "dominant_colors": [],
            "space_usage": "0%",
            "empty_space": "0%",
            "graphics_detected": False,
            "graphics_location": [],
            "hard_rule_flags": [{"rule": "ERROR_REPORTE", "severity": "GRAVE", "description": str(e)}],
            "pre_verdict": "RECHAZAR",
        }


def analyze_photo(image_path: str) -> str:
    """
    Punto de entrada principal.
    Carga la imagen, ejecuta el pipeline completo y retorna JSON string.
    Siempre retorna JSON válido, aunque la imagen falle.
    """
    try:
        img = _load(image_path)
    except Exception as e:
        fallback = build_context_report("desconocido", {}, [
            {"rule": "ERROR_CARGA", "severity": "GRAVE", "description": str(e)}
        ])
        return json.dumps(fallback, ensure_ascii=False, indent=2)

    photo_type = classify_photo_type(img)
    facts = extract_basic_facts(img)
    flags = check_hard_rules(img, facts)
    report = build_context_report(photo_type, facts, flags)

    return json.dumps(report, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────────────────────
# CLI mínimo
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python photo_analyzer.py <ruta_imagen>")
        sys.exit(1)

    result = analyze_photo(sys.argv[1])
    print(result)
