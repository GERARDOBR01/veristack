# -*- coding: utf-8 -*-
"""
verificar_lote.py — CLI del modo lote: barre una carpeta de fotos de UNA
campaña, corre el pipeline completo por foto y escribe el reporte consolidado.

Uso:
  python verificar_lote.py <carpeta> --etapa <id_campaña>
                           [--tipo focal_show|tringla|mesa_show|auto]
                           [--salida <dir>]

Salidas (en --salida, default <carpeta>/reporte_verificacion/):
  reporte_lote_<timestamp>.html   ← reporte visual (abrir en navegador)
  datos_lote_<timestamp>.xlsx     ← datos (o .csv ×2 si falta openpyxl)
  resultados_lote.json            ← lote completo, schema_lote 1.0

Gate obligatorio: los autotests de lote/runner y lote/reporte deben pasar
antes de tocar una sola foto. Pre-flight: el knowledge debe cargar >0
criterios para la etapa (si no, todo saldría NO_CALIFICA sin causa útil).

Sin GEMINI_API_KEY el lote SÍ corre, pero se avisa por adelantado: los
criterios delegados al modelo saldrán NO_CALIFICA y el reporte quedará
marcado como EVALUACIÓN PARCIAL (honestidad antes que apariencia).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from lote import runner, reporte  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("carpeta", type=Path, help="carpeta con las fotos del lote")
    parser.add_argument("--etapa", required=True, help="id de la campaña vigente (ej. gran_barata_pv2026)")
    parser.add_argument("--tipo", default="auto",
                        choices=["focal_show", "tringla", "mesa_show", "auto"],
                        help="tipo de foto para todo el lote (default: detección automática)")
    parser.add_argument("--salida", type=Path, default=None,
                        help="carpeta de salida (default: <carpeta>/reporte_verificacion)")
    args = parser.parse_args(argv)

    # PASO 0 — autotests como gate (patrón del runner de benchmark)
    print("PASO 0 — autotests de lote (gate obligatorio):")
    if runner.autotest() or reporte.autotest():
        print("ABORTADO: un autotest falló — no se corre el lote.")
        return 1

    try:
        fotos = runner.listar_fotos_carpeta(args.carpeta)
    except runner.ErrorLote as e:
        print(f"ABORTADO: {e}")
        return 1

    # .env + avisos honestos ANTES de correr
    runner.cargar_env()
    if not os.environ.get("GEMINI_API_KEY"):
        print("AVISO: GEMINI_API_KEY ausente — los criterios delegados al modelo "
              "saldrán NO_CALIFICA y el reporte quedará marcado como PARCIAL.")

    # Logging del pipeline visible (a stderr) — sin esto los 429/503 mueren en
    # el NullHandler y una corrida degradada parece normal (lección del 9 Jul).
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s | %(message)s")

    ejecutar_fn, cuota_agotada_fn, n_base = runner.crear_ejecutor_real(args.etapa)
    if n_base == 0:
        print(f"ABORTADO: el knowledge cargó 0 criterios para la etapa '{args.etapa}' "
              "— todo saldría NO_CALIFICA. Revisa pipeline/knowledge/.")
        return 1
    print(f"Knowledge OK: {n_base} criterios base para '{args.etapa}'. "
          f"Lote: {len(fotos)} foto(s), tipo={args.tipo}.")

    def _progreso(i, total, nombre):
        print(f"  [{i}/{total}] {nombre}")

    lote = runner.procesar_lote(fotos, args.etapa, args.tipo, ejecutar_fn,
                                cuota_agotada_fn=cuota_agotada_fn, progreso_cb=_progreso)

    # ── salidas ──
    salida = args.salida or (args.carpeta / "reporte_verificacion")
    salida.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    ruta_html = salida / f"reporte_lote_{ts}.html"
    ruta_html.write_text(reporte.generar_html(lote), encoding="utf-8")

    xlsx = reporte.generar_excel(lote)
    if xlsx is not None:
        ruta_datos = salida / f"datos_lote_{ts}.xlsx"
        ruta_datos.write_bytes(xlsx)
    else:
        print("AVISO: openpyxl/pandas no instalados — datos en CSV (pip install openpyxl).")
        (salida / f"datos_lote_{ts}_resumen.csv").write_bytes(reporte.generar_csv_resumen(lote))
        ruta_datos = salida / f"datos_lote_{ts}_detalle.csv"
        ruta_datos.write_bytes(reporte.generar_csv_detalle(lote))

    import json
    (salida / "resultados_lote.json").write_text(
        json.dumps(lote, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── resumen de 5 líneas ──
    r = lote["resumen"]
    pv = r["por_veredicto"]
    print(f"\nLote terminado: {lote['meta']['fotos_procesadas']}/{lote['meta']['fotos_totales']} "
          f"fotos procesadas (campaña {args.etapa}).")
    print(f"Veredictos: {pv['GRAVE']} GRAVE | {pv['OBSERVACION']} OBSERVACION | "
          f"{pv['NO_CALIFICA']} NO_CALIFICA | {pv['CUMPLE']} CUMPLE "
          f"({r['pct_cumplimiento'] if r['pct_cumplimiento'] is not None else '—'}% cumplimiento).")
    if r["lote_parcial"]:
        print(f"⚠️ EVALUACIÓN PARCIAL: {r['causa_lote_parcial']}")
    else:
        print("Corrida completa — sin parcialidad.")
    print(f"Reporte visual: {ruta_html}")
    print(f"Datos: {ruta_datos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
