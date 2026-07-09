# -*- coding: utf-8 -*-
"""
preparar_gt_para_arnes.py — Adapta el ground truth sellado al formato del arnés.

Lee ground_truth/benchmark_ground_truth.csv (sellado por Gerardo, NO se toca)
y produce ground_truth/ground_truth_arnes.csv con las columnas que consume
arnes_benchmark.py: foto_id,criterio_id,criterio,familia,severidad,
tipo_evaluacion,gap.

Transformaciones (todas documentadas, cero juicio nuevo):
1. hallazgo → criterio; capa_gap → gap. seccion/campana/notas no viajan.
2. criterio_id se llena SOLO donde existe un id real del sistema que cubre el
   hallazgo (EQUIVALENCIAS abajo — confirmadas en la verificación del 8 Jul).
   El resto queda vacío → matching por texto (fallará contra ids del sistema
   = FALSO_NEGATIVO, que es el resultado esperado para los gaps de capa1).
3. Se EXCLUYEN las filas de fotos que no corren en el benchmark (F02 categoría
   c, F06 duda, F28 fuera hasta que Gerardo la verifique — ver
   preparar_fotos_benchmark.py) para no inflar los FN con fotos que el sistema
   nunca vio. Conteo guardado y verificado.

Guard: cada equivalencia debe matchear EXACTAMENTE una fila; si no, aborta.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

AQUI    = Path(__file__).resolve().parent
ENTRADA = AQUI / "ground_truth" / "benchmark_ground_truth.csv"
SALIDA  = AQUI / "ground_truth" / "ground_truth_arnes.csv"

# Fotos que NO corren (no hay imagen limpia utilizable, o quedan fuera por
# decisión de Gerardo) — sus filas de GT no entran a la comparación, si no,
# quedarían como FALSO_NEGATIVO fantasma (el sistema nunca vio esa foto).
# F02 categoría c, F06 duda, F28 fuera hasta que Gerardo la verifique. Todas
# ausentes del manifest — esta lista debe seguir al manifest. Ver
# clasificación a/b/c en preparar_fotos_benchmark.py.
FOTOS_EXCLUIDAS = {"F02", "F06", "F28"}

# (foto_id, fragmento único del hallazgo) → criterio_id del sistema.
# Verificados contra capa2_validado_final.json / capa3_focal_show.json /
# mandatory_engine.py en la sesión del 8 Jul.
EQUIVALENCIAS: dict[tuple[str, str], str] = {
    ("F13", "Foto oscura"):                    "imagen_oscura",             # mandatory (photo_analyzer PASO 0)
    ("F03", "Falta cartulina de descuento"):   "identificar_cartulina_descuento",   # capa2 p13/p14
    ("F05", "Falta etiqueta de descuento 1"):  "2_maniquies_1_etiqueta",    # capa2 p10 (proporción)
    ("F11", "Maniquíes sin etiqueta"):         "etiqueta_ausente_maniqui",  # capa3 focal_show
}


def preparar() -> int:
    with open(ENTRADA, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))

    usadas = {clave: 0 for clave in EQUIVALENCIAS}
    salida = []
    excluidas = 0
    for fila in filas:
        foto = fila["foto_id"].strip()
        if foto in FOTOS_EXCLUIDAS:
            excluidas += 1
            continue
        criterio_id = ""
        for (f_eq, fragmento), cid in EQUIVALENCIAS.items():
            if foto == f_eq and fila["hallazgo"].startswith(fragmento):
                criterio_id = cid
                usadas[(f_eq, fragmento)] += 1
        salida.append({
            "foto_id":         foto,
            "criterio_id":     criterio_id,
            "criterio":        fila["hallazgo"],
            "familia":         fila["familia"],
            "severidad":       fila["severidad"],
            "tipo_evaluacion": fila["tipo_evaluacion"],
            "gap":             fila["capa_gap"],
        })

    errores = [f"{clave} matcheó {n} veces (esperado 1)"
               for clave, n in usadas.items() if n != 1]
    if errores:
        print("ABORTADO — equivalencias sin match exacto:")
        for e in errores:
            print(f"  {e}")
        return 1

    with open(SALIDA, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["foto_id", "criterio_id", "criterio",
                                          "familia", "severidad",
                                          "tipo_evaluacion", "gap"])
        w.writeheader()
        w.writerows(salida)

    print(f"OK: {len(filas)} filas leidas -> {len(salida)} al arnes "
          f"({excluidas} excluidas de {sorted(FOTOS_EXCLUIDAS)}), "
          f"{sum(usadas.values())} con criterio_id de sistema -> {SALIDA.name}")
    return 0


if __name__ == "__main__":
    sys.exit(preparar())
