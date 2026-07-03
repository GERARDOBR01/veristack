# -*- coding: utf-8 -*-
"""Motor 2 — clasificador determinista de layout por página (Sesión L).

Distingue, para cada página del manual, si su layout es "prosa" (columnas
normales, `use_text_flow=True` ya la lee bien — ver `revisar_multicolumna.py`)
o "diagrama/matriz" (planogramas, líneas de tiempo, cuadrículas — pdfplumber
aplana la relación espacial 2D del gráfico y el texto extraído pierde el
significado, aunque a veces siga leyéndose "bonito" como texto suelto).

SIN IA, SIN API: solo geometría de `pdfplumber` (cajas de palabras). No se
usa DBSCAN/sklearn: se evaluó en la exploración de calibración y no separaba
mejor que la densidad/dispersión simple de abajo — se descarta por la regla
del proyecto de no meter maquinaria que no compra nada (ver CLAUDE.md, casos
previos: layout=True y el declusterizador por posición X).

Cómo se calibró (Sesión J + QA revisaron a ojo las 20 páginas "multicolumna"
de `test_pdfplumber.py` contra el PDF real):
  - 5 confirmadas DIAGRAMA real con fallas bloqueantes: 5, 10, 11, 18, 35
  - 12 confirmadas limpias (de las 20): 1, 2, 3, 6, 7, 26, 27, 28, 31, 32, 34, 42
    (las 3 restantes de las 20 no se usaron como ground truth por brief)

Score por página = z(cv_nn) + z(ratio_biggap) - z(mediana_palabras_por_línea),
con z-scores contra la media/desvest de las 12 páginas limpias de calibración:
  - cv_nn: coeficiente de variación de la distancia al vecino más cercano entre
    centros de cajas de palabra — texto disperso/irregular (diagrama) da CV alto;
    texto en flujo de lectura (prosa) da CV más parejo.
  - ratio_biggap: fracción de espacios horizontales > 25pt entre palabras
    consecutivas de una misma línea visual — típico de etiquetas aisladas de un
    gráfico, no de una oración.
  - mediana_palabras_por_línea: las líneas de un diagrama suelen ser etiquetas
    cortas (1-5 palabras); se resta porque más palabras/línea = más "prosa".

Umbral = el score mínimo entre las 5 páginas DIAGRAMA de calibración (garantiza
capturar las 5 conocidas). Esto es deliberadamente favorable a RECALL sobre
precisión: una página limpia marcada de más solo cuesta una llamada extra al
fallback de Gemini Vision (siguiente sesión); una página diagrama NO detectada
se extraería mal en silencio. El resultado real (abajo, sección REPORTE) deja
explícito cuántos falsos positivos produce este umbral sobre las 12 limpias.

Uso:
    python clasificador_layout.py [ruta_al_pdf]
"""
import statistics
import sys
from math import hypot
from pathlib import Path

import pdfplumber

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PDF_DEFAULT = Path(r"C:\Users\jesus\Downloads\MECÁNICA MONTAJE GRAN BARATA PV 2026 .pdf")

CALIBRACION_DIAGRAMA = {5, 10, 11, 18, 35}
CALIBRACION_LIMPIA = {1, 2, 3, 6, 7, 26, 27, 28, 31, 32, 34, 42}

GAP_GRANDE_PT = 25  # separación horizontal (pt) que ya no es espaciado normal de palabra
TOLERANCIA_LINEA_PT = 3  # palabras con `top` a esta distancia se agrupan en la misma línea visual


def _agrupar_lineas(words, tol=TOLERANCIA_LINEA_PT):
    """Agrupa palabras en líneas visuales por proximidad vertical (`top`)."""
    words = sorted(words, key=lambda w: w["top"])
    lineas, actual, top_actual = [], [], None
    for w in words:
        if top_actual is None or abs(w["top"] - top_actual) <= tol:
            actual.append(w)
            top_actual = top_actual if top_actual is not None else w["top"]
        else:
            lineas.append(actual)
            actual, top_actual = [w], w["top"]
    if actual:
        lineas.append(actual)
    return lineas


def _cv_vecino_cercano(centros):
    """Coeficiente de variación de la distancia al vecino más cercano (2D)."""
    n = len(centros)
    if n < 3:
        return 0.0
    distancias = []
    for i in range(n):
        mejor = min(
            hypot(centros[i][0] - centros[j][0], centros[i][1] - centros[j][1])
            for j in range(n)
            if j != i
        )
        distancias.append(mejor)
    media = statistics.mean(distancias)
    return statistics.pstdev(distancias) / media if media else 0.0


def extraer_features(page) -> dict | None:
    """Calcula las 3 métricas de dispersión espacial de una página. None si no hay texto suficiente."""
    words = page.extract_words(use_text_flow=True)
    if len(words) < 5:
        return None

    lineas = _agrupar_lineas(words)
    palabras_por_linea = [len(l) for l in lineas]

    gaps, grandes = [], 0
    for linea in lineas:
        linea = sorted(linea, key=lambda w: w["x0"])
        for a, b in zip(linea, linea[1:]):
            gap = b["x0"] - a["x1"]
            if 0 <= gap < 1000:  # descarta artefactos de coordenadas corruptas
                gaps.append(gap)
                if gap > GAP_GRANDE_PT:
                    grandes += 1
    ratio_biggap = grandes / len(gaps) if gaps else 0.0

    centros = [((w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2) for w in words]
    cv_nn = _cv_vecino_cercano(centros)

    mediana_wpl = statistics.median(palabras_por_linea)

    return {
        "nwords": len(words),
        "nlineas": len(lineas),
        "cv_nn": cv_nn,
        "ratio_biggap": ratio_biggap,
        "mediana_wpl": mediana_wpl,
    }


def _z(valores, x):
    media = statistics.mean(valores)
    desv = statistics.pstdev(valores) or 1.0
    return (x - media) / desv


def clasificar_pdf(pdf_path: Path):
    """Devuelve (features_por_pagina, baseline_limpia, umbral)."""
    features = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            f = extraer_features(page)
            if f is not None:
                features[page.page_number] = f

    faltantes_calibracion = (CALIBRACION_DIAGRAMA | CALIBRACION_LIMPIA) - set(features)
    if faltantes_calibracion:
        sys.exit(
            f"ERROR: páginas de calibración sin texto extraíble (no se puede calibrar): {sorted(faltantes_calibracion)}"
        )

    base_cv = [features[p]["cv_nn"] for p in CALIBRACION_LIMPIA]
    base_biggap = [features[p]["ratio_biggap"] for p in CALIBRACION_LIMPIA]
    base_wpl = [features[p]["mediana_wpl"] for p in CALIBRACION_LIMPIA]

    def score(f):
        return _z(base_cv, f["cv_nn"]) + _z(base_biggap, f["ratio_biggap"]) - _z(base_wpl, f["mediana_wpl"])

    scores = {p: score(f) for p, f in features.items()}
    umbral = min(scores[p] for p in CALIBRACION_DIAGRAMA)  # garantiza recall 5/5 en calibración

    return features, scores, umbral


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PDF_DEFAULT
    if not pdf_path.exists():
        sys.exit(f"ERROR: no existe el PDF: {pdf_path}")

    features, scores, umbral = clasificar_pdf(pdf_path)
    diagrama = sorted(p for p, s in scores.items() if s >= umbral)

    print(f"PDF: {pdf_path.name}")
    print(f"Páginas con texto evaluado: {len(features)} / umbral calibrado: {umbral:.3f}")
    print("-" * 80)
    for p in sorted(features):
        marca = " [DIAGRAMA]" if scores[p] >= umbral else ""
        cal = ""
        if p in CALIBRACION_DIAGRAMA:
            cal = "  (calibración: DIAGRAMA)"
        elif p in CALIBRACION_LIMPIA:
            cal = "  (calibración: limpia)"
        print(f"[pág {p:>3}] score={scores[p]:6.2f}{marca}{cal}")

    print("-" * 80)
    print(f"Total clasificadas DIAGRAMA: {len(diagrama)} de {len(features)}")
    print(f"Páginas: {diagrama}")

    print("-" * 80)
    print("VALIDACIÓN CONTRA GROUND TRUTH (Sesión J + QA):")
    faltan = sorted(p for p in CALIBRACION_DIAGRAMA if scores[p] < umbral)
    if faltan:
        print(f"  ⚠️  FALLO: el heurístico NO detectó como diagrama {len(faltan)} de las 5 páginas confirmadas: {faltan}")
    else:
        print("  ✅ Las 5 páginas confirmadas como diagrama (5, 10, 11, 18, 35) SÍ caen en la categoría DIAGRAMA.")
    falsos_positivos = sorted(p for p in CALIBRACION_LIMPIA if scores[p] >= umbral)
    if falsos_positivos:
        print(f"  🟡 Falsos positivos entre las 12 limpias de calibración: {falsos_positivos}")
    else:
        print("  ✅ Cero falsos positivos entre las 12 páginas limpias de calibración.")


if __name__ == "__main__":
    main()
