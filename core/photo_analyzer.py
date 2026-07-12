"""
photo_analyzer.py — Pre-análisis de imagen para El Verificador (visual merchandising).
Extrae hechos objetivos antes de pasarlos al modelo.
Sin ML pesado — solo PIL y NumPy.
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageStat

# ──────────────────────────────────────────────────────────────
# Umbrales configurables
#
# OJO (fix doble umbral, Sesión GG): estos valores solo alimentan el campo
# informativo `quality` y los flags del CLI (`analyze_photo`). El VEREDICTO
# de compliance lo decide únicamente `mandatory_engine.ConfigEngine`
# (brillo_minimo=40, etc.) — una sola fuente de verdad para bloquear.
# ──────────────────────────────────────────────────────────────

BRIGHTNESS_MIN = 30          # debajo → imagen muy oscura (solo quality/CLI)
BRIGHTNESS_MAX = 92          # arriba → sobreexpuesta (solo quality/CLI)
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
        img = Image.open(image)
        # EXIF: fotos de celular vienen rotadas por metadato; sin esto el
        # ratio ancho/alto miente y classify_photo_type clasifica mal.
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")
    if isinstance(image, Image.Image):
        return ImageOps.exif_transpose(image).convert("RGB")
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


def _exposicion(img: Image.Image) -> dict:
    """
    Exposición por histograma, no solo media: una foto mitad quemada y mitad
    negra da brillo medio "aceptable" pero es inevaluable. Porcentajes de
    píxeles quemados (>250) y aplastados (<5) + percentiles de luminancia.
    """
    arr = np.array(img.convert("L"), dtype=np.uint8)
    total = arr.size
    return {
        "quemado_pct":   round(float((arr > 250).sum() / total * 100), 1),
        "aplastado_pct": round(float((arr < 5).sum() / total * 100), 1),
        "luminancia_p5":  round(float(np.percentile(arr, 5)) / 255 * 100, 1),
        "luminancia_p95": round(float(np.percentile(arr, 95)) / 255 * 100, 1),
    }


def _contraste(img: Image.Image) -> float:
    """Desviación estándar de luminancia en escala 0-100. Bajo = foto lavada/velada."""
    arr = np.array(img.convert("L"), dtype=float)
    return round(float(arr.std()) / 255 * 100, 1)


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
    Wrapper retrocompatible de classify_photo_type_detallado.
    """
    return classify_photo_type_detallado(image)["tipo"]


# Fronteras de ratio de la heurística. Un ratio pegado a la frontera
# (±10%) clasifica igual, pero con confianza "baja" — el llamador decide
# si se fía o pide el tipo al usuario.
_RATIO_FRONTERAS = (0.75, 1.4, 2.2)
_EMPTY_FRONTERA = 0.35


def classify_photo_type_detallado(image) -> dict:
    """
    {"tipo": str, "confianza": "alta"|"baja", "ratio": float|None}
    Heurística por proporción y densidad visual. confianza=baja cuando el
    ratio cae a menos de 10% de una frontera de decisión (o el empty_ratio
    a menos de 0.05 de la suya en el caso cuadrado).
    """
    try:
        img = _load(image)
        w, h = img.size
        ratio = w / h  # > 1 landscape, < 1 portrait
        empty = _empty_space_ratio(img)

        cerca_frontera = any(abs(ratio - f) / f < 0.10 for f in _RATIO_FRONTERAS)

        if ratio > 2.2:
            tipo = "panoramica"
        elif ratio < 0.75:
            tipo = "focal_show"
        elif ratio <= 1.4:
            # Cuadrado/casi cuadrado: tringla (3 focos, más aire) o focal_show
            tipo = "tringla" if empty > _EMPTY_FRONTERA else "focal_show"
            if abs(empty - _EMPTY_FRONTERA) < 0.05:
                cerca_frontera = True
        else:
            tipo = "mesa_show"

        return {"tipo": tipo,
                "confianza": "baja" if cerca_frontera else "alta",
                "ratio": round(ratio, 3)}

    except Exception:
        return {"tipo": "desconocido", "confianza": "baja", "ratio": None}


def extract_basic_facts(image) -> dict:
    """
    Extrae hechos objetivos medibles de la imagen.
    Cada sub-extracción tiene su propio try/except para no fallar en bloque.

    Contrato honesto (v2, Sesión GG):
      estado = "ok"               → todas las métricas son confiables
      estado = "archivo_invalido" → la imagen no se pudo cargar; `causa` trae
                                    el error real (inexistente, truncada, no
                                    es imagen, bomba de descompresión...).
                                    Las métricas quedan en su valor nulo y NO
                                    deben usarse para veredicto.
      estado = "analisis_parcial" → cargó, pero alguna métrica falló; `causa`
                                    lista cuáles.
    """
    img = None
    load_error = None
    try:
        img = _load(image)
    except Exception as e:
        load_error = f"{type(e).__name__}: {e}"

    facts = {
        "estado": "ok",
        "causa": None,
        "dominant_colors": [],
        "brightness": 0.0,
        "quality": "mala",
        "sharpness_score": 0.0,
        "empty_space_ratio": 0.0,
        "graphics_detected": False,
        "graphics_location": [],
        "quemado_pct": 0.0,
        "aplastado_pct": 0.0,
        "luminancia_p5": 0.0,
        "luminancia_p95": 0.0,
        "contraste": 0.0,
        "ancho_px": 0,
        "alto_px": 0,
    }

    if load_error:
        facts["estado"] = "archivo_invalido"
        facts["causa"] = load_error
        facts["error"] = load_error  # retrocompatibilidad con consumidores previos
        return facts

    fallidas: list[str] = []

    facts["ancho_px"], facts["alto_px"] = img.size

    try:
        facts["dominant_colors"] = _dominant_colors(img, n=3)
    except Exception:
        fallidas.append("dominant_colors")

    try:
        facts["brightness"] = round(_average_brightness(img), 1)
    except Exception:
        fallidas.append("brightness")

    try:
        facts["sharpness_score"] = round(_laplacian_variance(img), 2)
    except Exception:
        fallidas.append("sharpness_score")

    try:
        facts["empty_space_ratio"] = round(_empty_space_ratio(img), 3)
    except Exception:
        fallidas.append("empty_space_ratio")

    try:
        g = _detect_graphics(img)
        facts["graphics_detected"] = g["detectado"]
        facts["graphics_location"] = g["ubicacion"]
    except Exception:
        fallidas.append("graphics")

    try:
        facts.update(_exposicion(img))
    except Exception:
        fallidas.append("exposicion")

    try:
        facts["contraste"] = _contraste(img)
    except Exception:
        fallidas.append("contraste")

    facts["quality"] = _brightness_to_quality(facts["brightness"], facts["sharpness_score"])

    if fallidas:
        facts["estado"] = "analisis_parcial"
        facts["causa"] = "métricas fallidas: " + ", ".join(fallidas)

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
# AUTOTEST — 100% offline, fixtures sintéticos en tmp, cero red.
#   python photo_analyzer.py autotest
# ──────────────────────────────────────────────────────────────

def _autotest() -> int:
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="photo_analyzer_autotest_"))
    fallas: list[str] = []

    def check(nombre: str, cond: bool, detalle: str = ""):
        estado = "PASS" if cond else "FAIL"
        print(f"  [{estado}] {nombre}" + (f" — {detalle}" if detalle and not cond else ""))
        if not cond:
            fallas.append(nombre)

    def img_binaria(blancos_de_10000: int, lado: int = 100) -> Image.Image:
        """Píxeles 0/255 dispersos: brillo EXACTO = blancos/100, nítida."""
        import random
        n = lado * lado
        rng = random.Random(42)
        pos = list(range(n))
        rng.shuffle(pos)
        px = bytearray(n)
        for p in pos[:blancos_de_10000]:
            px[p] = 255
        return Image.frombytes("L", (lado, lado), bytes(px))

    print("== photo_analyzer autotest ==")

    # 1. Contrato ok: imagen sana → estado ok, métricas presentes
    sana = tmp / "sana.png"
    img_binaria(5500).save(sana)
    f = extract_basic_facts(str(sana))
    check("imagen sana → estado=ok", f["estado"] == "ok", f["estado"])
    check("brillo exacto 55.0", f["brightness"] == 55.0, str(f["brightness"]))
    check("resolución reportada", f["ancho_px"] == 100 and f["alto_px"] == 100)
    check("contraste > 0", f["contraste"] > 0)

    # 2. Contrato archivo_invalido: causas reales, no genéricas
    f = extract_basic_facts(str(tmp / "no_existe.webp"))
    check("inexistente → archivo_invalido", f["estado"] == "archivo_invalido")
    check("inexistente → causa con error real", "FileNotFoundError" in (f["causa"] or ""), f["causa"])

    vacio = tmp / "vacio.webp"
    vacio.write_bytes(b"")
    f = extract_basic_facts(str(vacio))
    check("0 bytes → archivo_invalido", f["estado"] == "archivo_invalido")

    texto = tmp / "texto.webp"
    texto.write_text("no soy imagen", encoding="utf-8")
    f = extract_basic_facts(str(texto))
    check("txt renombrado → archivo_invalido", f["estado"] == "archivo_invalido")
    check("txt → brillo queda 0.0 (no confiable)", f["brightness"] == 0.0)

    # 3. Exposición por histograma: la media miente, el histograma no
    quemada = tmp / "quemada.png"
    Image.new("L", (100, 100), 255).save(quemada)
    f = extract_basic_facts(str(quemada))
    check("100% blanca → quemado_pct=100", f["quemado_pct"] == 100.0, str(f["quemado_pct"]))

    mitades = tmp / "mitades.png"
    m = Image.new("L", (100, 100), 0)
    m.paste(255, (0, 0, 100, 50))
    m.save(mitades)
    f = extract_basic_facts(str(mitades))
    check("mitad quemada/mitad negra → brillo medio ~50 PERO quemado ~50 y aplastado ~50",
          abs(f["brightness"] - 50.0) < 1 and f["quemado_pct"] == 50.0 and f["aplastado_pct"] == 50.0,
          f"brillo={f['brightness']} quemado={f['quemado_pct']} aplastado={f['aplastado_pct']}")

    # 4. EXIF: foto rotada por metadato se endereza antes de medir
    exif_img = tmp / "rotada.jpg"
    base = Image.new("RGB", (100, 50), (128, 128, 128))
    exif = Image.Exif()
    exif[274] = 6  # Orientation: Rotate 90 CW
    base.save(exif_img, format="JPEG", exif=exif)
    img_cargada = _load(str(exif_img))
    check("EXIF orientation 6 → 100x50 se carga como 50x100",
          img_cargada.size == (50, 100), str(img_cargada.size))

    # 5. Clasificador con confianza
    d = classify_photo_type_detallado(Image.new("RGB", (250, 100)))  # ratio 2.5
    check("ratio 2.5 → panoramica/alta", d["tipo"] == "panoramica" and d["confianza"] == "alta", str(d))
    d = classify_photo_type_detallado(Image.new("RGB", (145, 100)))  # ratio 1.45, frontera 1.4
    check("ratio 1.45 → mesa_show/BAJA (frontera)", d["tipo"] == "mesa_show" and d["confianza"] == "baja", str(d))
    check("classify_photo_type retrocompatible (str)",
          classify_photo_type(Image.new("RGB", (250, 100))) == "panoramica")

    # 6. analyze_photo nunca lanza y siempre es JSON válido
    r = json.loads(analyze_photo(str(texto)))
    check("analyze_photo con archivo roto → JSON con RECHAZAR", r["pre_verdict"] == "RECHAZAR")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nAUTOTEST PHOTO_ANALYZER: {'PASS' if not fallas else 'FAIL'} ({len(fallas)} falla(s))")
    return 1 if fallas else 0


# ──────────────────────────────────────────────────────────────
# CLI mínimo
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "autotest":
        sys.exit(_autotest())

    if len(sys.argv) < 2:
        print("Uso: python photo_analyzer.py <ruta_imagen> | autotest")
        sys.exit(1)

    result = analyze_photo(sys.argv[1])
    print(result)
