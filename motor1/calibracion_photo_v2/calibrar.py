"""
calibrar.py — Corrida de calibración de photo_analyzer v2 sobre fotos REALES.

Mide todas las métricas v2 (brillo, nitidez, exposición por histograma,
contraste, resolución, tipo+confianza) sobre un directorio de fotos y
produce una tabla para revisión humana. NO cambia ningún umbral: la
calibración PROPONE, Gerardo decide.

Cero modelo, cero red — solo photo_analyzer (PIL+NumPy).

Uso:
  python calibrar.py [directorio_de_fotos]
  (default: motor1/stress_test/fotos — las 5 reales del stress del 11 Jul;
   cuando las 25 del benchmark estén en esta máquina, apuntar ahí)

Salida: calibracion_resultados.csv + calibracion_resultados.md (junto al script)
"""

import csv
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent.parent
sys.path.insert(0, str(REPO / "core"))

from photo_analyzer import classify_photo_type_detallado, extract_basic_facts  # noqa: E402

EXTENSIONES = {".webp", ".jpg", ".jpeg", ".png"}

# Umbrales VIGENTES (solo para marcar en la tabla qué dispararía hoy)
BRILLO_MIN = 40.0        # ConfigEngine.brillo_minimo
NITIDEZ_MIN = 30.0       # ConfigEngine.nitidez_minima
QUEMADO_MAX = 50.0       # ConfigEngine.quemado_maximo_pct (v2)


def main() -> int:
    directorio = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "motor1" / "stress_test" / "fotos"
    fotos = sorted(p for p in directorio.iterdir() if p.suffix.lower() in EXTENSIONES)
    if not fotos:
        print(f"Sin fotos en {directorio}")
        return 1

    filas = []
    for foto in fotos:
        f = extract_basic_facts(str(foto))
        t = classify_photo_type_detallado(str(foto))
        dispara = []
        if f["estado"] != "ok":
            dispara.append(f"estado={f['estado']}")
        if f["brightness"] < BRILLO_MIN:
            dispara.append("imagen_oscura")
        if f["quemado_pct"] > QUEMADO_MAX:
            dispara.append("imagen_sobreexpuesta")
        if f["sharpness_score"] < NITIDEZ_MIN:
            dispara.append("imagen_borrosa")
        filas.append({
            "foto":        foto.name,
            "estado":      f["estado"],
            "brillo":      f["brightness"],
            "nitidez":     f["sharpness_score"],
            "quemado_pct": f["quemado_pct"],
            "aplastado_pct": f["aplastado_pct"],
            "p5":          f["luminancia_p5"],
            "p95":         f["luminancia_p95"],
            "contraste":   f["contraste"],
            "resolucion":  f"{f['ancho_px']}x{f['alto_px']}",
            "lado_menor":  min(f["ancho_px"], f["alto_px"]),
            "espacio_vacio": f["empty_space_ratio"],
            "tipo":        t["tipo"],
            "tipo_conf":   t["confianza"],
            "ratio":       t["ratio"],
            "dispararia_hoy": " + ".join(dispara) or "-",
        })

    columnas = list(filas[0].keys())
    with open(AQUI / "calibracion_resultados.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)

    with open(AQUI / "calibracion_resultados.md", "w", encoding="utf-8") as fh:
        fh.write(f"# Calibración photo_analyzer v2 — {directorio}\n\n")
        fh.write(f"{len(filas)} foto(s). Los umbrales vigentes NO se cambiaron; "
                 "esta tabla es insumo para decidirlos con Gerardo.\n\n")
        fh.write("| " + " | ".join(columnas) + " |\n")
        fh.write("|" + "---|" * len(columnas) + "\n")
        for fila in filas:
            fh.write("| " + " | ".join(str(fila[c]) for c in columnas) + " |\n")

    for fila in filas:
        print(f"{fila['foto']:<28} brillo={fila['brillo']:<6} nitidez={fila['nitidez']:<9} "
              f"quemado={fila['quemado_pct']:<5} contraste={fila['contraste']:<5} "
              f"res={fila['resolucion']:<11} tipo={fila['tipo']}/{fila['tipo_conf']:<5} "
              f"dispara={fila['dispararia_hoy']}")
    print(f"\n{len(filas)} fotos -> calibracion_resultados.csv / .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
