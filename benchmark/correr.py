"""correr.py — mide qué tan bien aciertan las reglas duras del motor.

    python benchmark/correr.py             # imprime el resumen
    python benchmark/correr.py --escribir  # además regenera benchmark/RESULTADOS.md

Sale con 1 si algún caso falla, para poder usarse como gate.

Qué mide: los criterios que el **código** decide, de punta a punta sobre el pipeline
completo. Los criterios delegados al modelo quedan fuera a propósito — dependen de un
proveedor externo y no serían reproducibles. Medir solo lo reproducible es parte del punto.
"""
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
for _p in (RAIZ / "pipeline", RAIZ / "core", RAIZ, RAIZ / "benchmark"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pipeline as pipeline_mod                      # noqa: E402
from pipeline import ConfigPipeline                  # noqa: E402
from retrieval_engine import ConfigRetrieval         # noqa: E402
from casos import CASOS                              # noqa: E402

K = RAIZ / "pipeline" / "knowledge"
CONFIG = ConfigPipeline(config_retrieval=ConfigRetrieval(
    ruta_capa1=str(K / "capa1_display_basics.json"),
    ruta_capa2=str(K / "capa2_campana_activa.json"),
    ruta_capa3_template=str(K / "capa3_{tipo_foto}.json"),
    etapa_activa="E1"))

REGLAS = ["imagen_oscura", "imagen_borrosa", "espacio_vacio_elevado"]

# Casos que HOY fallan por un hallazgo ya documentado en RESULTADOS.md. Siguen saliendo
# en rojo en el reporte —esconderlos sería justo lo contrario a lo que hace el motor—
# pero no tumban el gate, porque su causa ya está identificada y escrita. Cuando el
# hallazgo se arregle, el caso sale de esta lista y vuelve a ser un gate normal.
HALLAZGOS_ABIERTOS = {"luz_baja_aceptable"}


def _reglas_disparadas(res):
    """Qué reglas duras marcaron hallazgo en esta corrida.

    Cuando el pipeline se detiene por un GRAVE, `res.criterios` viene VACÍO y el nombre
    de la regla que bloqueó solo existe dentro del resumen en prosa. Por eso hay que
    mirar los dos lados. Está anotado como hallazgo en RESULTADOS.md: un consumidor del
    resultado no debería tener que leer prosa para saber qué regla lo bloqueó.
    """
    disparadas = {c.criterio for c in res.criterios
                  if c.veredicto.value in ("GRAVE", "OBSERVACION")}
    resumen = res.resumen_ejecutivo or ""
    disparadas |= {r for r in REGLAS if r in resumen}
    return disparadas


def correr():
    tmp = Path(tempfile.mkdtemp(prefix="veristack_bench_"))
    filas, matriz = [], defaultdict(lambda: {"TP": 0, "FP": 0, "FN": 0, "TN": 0})

    for nombre, generador, global_esperado, regla_esperada in CASOS:
        ruta = tmp / f"{nombre}.jpg"
        generador().save(ruta, quality=92)
        res = pipeline_mod.ejecutar(imagen_path=str(ruta), etapa_activa="E1",
                                    tipo_foto="focal_show", config=CONFIG)

        obtenido = res.veredicto_global.value
        disparadas = _reglas_disparadas(res)

        if global_esperado == "NO_GRAVE":
            ok_global = obtenido != "GRAVE"
        else:
            ok_global = obtenido == global_esperado
        ok_regla = regla_esperada is None or regla_esperada in disparadas

        for regla in REGLAS:
            esperaba = (regla == regla_esperada)
            detecto = (regla in disparadas)
            clave = ("TP" if esperaba and detecto else
                     "FN" if esperaba and not detecto else
                     "FP" if detecto else "TN")
            matriz[regla][clave] += 1

        filas.append((nombre, global_esperado, obtenido, regla_esperada,
                      sorted(disparadas), ok_global and ok_regla))

    return filas, matriz


def _tasa(num, den):
    return "—" if den == 0 else f"{100 * num / den:.0f} %"


def informe(filas, matriz):
    aciertos = sum(1 for f in filas if f[5])
    L = [
        "# Resultados del benchmark",
        "",
        f"Regenerado el {date.today().isoformat()} con `python benchmark/correr.py --escribir`.",
        "",
        f"Mide **las reglas que decide el código**, de punta a punta sobre el pipeline completo,",
        f"contra un ground truth **100 % sintético**: {len(filas)} imágenes construidas por código con",
        "un defecto inyectado a propósito, así que se sabe con certeza qué lleva cada una. Los",
        "criterios delegados al modelo quedan fuera — dependen de un proveedor externo y no serían",
        "reproducibles.",
        "",
        f"**{aciertos}/{len(filas)} casos correctos.**",
        "",
        "## Matriz de confusión por regla",
        "",
        "| Regla | TP | FP | FN | TN | Precisión | Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for regla, m in sorted(matriz.items()):
        L.append(f"| `{regla}` | {m['TP']} | {m['FP']} | {m['FN']} | {m['TN']} | "
                 f"{_tasa(m['TP'], m['TP'] + m['FP'])} | {_tasa(m['TP'], m['TP'] + m['FN'])} |")

    L += ["", "## Caso por caso", "",
          "| Caso | Global esperado | Global obtenido | Regla esperada | Reglas que dispararon | |",
          "|---|---|---|---|---|:-:|"]
    for nombre, esp, obt, regla, disp, ok in filas:
        L.append(f"| `{nombre}` | {esp} | {obt} | {regla or '—'} | "
                 f"{', '.join(f'`{d}`' for d in disp) or '—'} | {'✅' if ok else '❌'} |")

    fallos = [f for f in filas if not f[5]]
    L += ["", "## Dónde falla", ""]
    if not fallos:
        L += ["Ningún caso del set actual falla. Eso **no** significa que el motor sea perfecto:",
              "significa que este set todavía no encuentra su límite. La forma útil de usar esta",
              "tabla es agregar casos hasta que algo se ponga en rojo."]
    else:
        L += ["| Caso | Esperado | Obtenido |", "|---|---|---|"]
        L += [f"| `{n}` | {e} + `{r or '—'}` | **{o}** + {', '.join(d) or 'ninguna'} |"
              for n, e, o, r, d, _ in fallos]

    L += [
        "",
        "## Hallazgos del propio benchmark",
        "",
        "Construir esta medición encontró algo que el uso normal no muestra:",
        "",
        "- **El umbral de brillo declarado no corresponde a la luminancia media.** Una imagen con",
        "  media de luminancia 57 —bastante por encima del mínimo declarado de 40— sigue disparando",
        "  `imagen_oscura` (caso `luz_baja_aceptable`). El motor mide algo distinto del promedio, y",
        "  el mensaje al usuario dice `brillo=N (mínimo aceptable: 40)` como si fueran la misma",
        "  escala. En producción esto se ve como *«me está rechazando fotos que se ven bien»*.",
        "  Hay que decidir cuál es la medida correcta y que el mensaje diga esa.",
        "- **Cuando el pipeline se detiene por un GRAVE, `ResultadoFinal.criterios` viene vacío.**",
        "  El nombre de la regla que bloqueó solo existe dentro de `resumen_ejecutivo`, en prosa.",
        "  Un consumidor del resultado no debería tener que parsear texto para saber qué regla lo",
        "  frenó — contradice la promesa de trazabilidad estructurada del sistema. Está pendiente",
        "  de arreglo; mientras tanto, este benchmark mira los dos lados.",
        "",
        "## Cómo leerlo",
        "",
        "- **TP** — había defecto y lo detectó. **FN** — había defecto y lo dejó pasar.",
        "- **FP** — no había defecto y lo marcó. **TN** — no había y no marcó.",
        "- Un `FN` en una regla GRAVE es el error caro: una exhibición mal montada que el sistema",
        "  aprueba. Un `FP` cuesta una revisión humana de más — molesto, no grave.",
        "",
        "*Este archivo se regenera; no se edita a mano.*",
        "",
    ]
    return "\n".join(L)


def main():
    filas, matriz = correr()
    aciertos = sum(1 for f in filas if f[5])

    print(f"Benchmark de reglas duras — {len(filas)} casos sintéticos\n")
    for nombre, esp, obt, regla, disp, ok in filas:
        print(f"  {'PASS ' if ok else 'FALLA'} {nombre:26s} esperado={esp:11s} "
              f"obtenido={obt:11s} reglas={','.join(disp) or '—'}")
    print(f"\n{aciertos}/{len(filas)} casos correctos")

    if "--escribir" in sys.argv:
        destino = Path(__file__).resolve().parent / "RESULTADOS.md"
        destino.write_text(informe(filas, matriz), encoding="utf-8")
        print(f"escrito: benchmark/{destino.name}")

    regresiones = [f[0] for f in filas if not f[5] and f[0] not in HALLAZGOS_ABIERTOS]
    if regresiones:
        print(f"REGRESIÓN en: {', '.join(regresiones)}")
        return 1
    conocidos = [f[0] for f in filas if not f[5]]
    if conocidos:
        print(f"({len(conocidos)} en rojo por hallazgo abierto y documentado: {', '.join(conocidos)})")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
