"""pruebas.py — corre toda la suite de autotests de Veristack en una sola pasada.

    python pruebas.py

Ninguna de estas pruebas gasta una llamada de API: el modelo está stubbeado y el
knowledge es la capa sintética de demo. Una prueba que cuesta dinero es una
prueba que se deja de correr.

Sale con código 1 si alguna falla, para que sirva de gate en CI.
"""
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

# (nombre legible, comando). El orden va de lo más básico a lo más integrado.
SUITE = [
    ("photo_analyzer — metadata objetiva",   [sys.executable, "core/photo_analyzer.py", "autotest"]),
    ("mandatory_engine — reglas duras",      [sys.executable, "pipeline/mandatory_engine.py"]),
    ("retrieval_engine — evidencia",         [sys.executable, "pipeline/retrieval_engine.py"]),
    ("confidence_engine — delegación",       [sys.executable, "pipeline/confidence_engine.py"]),
    ("pipeline — rotación de claves",        [sys.executable, "pipeline/pipeline.py", "autotest-rotacion"]),
    ("pipeline — batching del paso 4",       [sys.executable, "pipeline/pipeline.py", "autotest-batching"]),
    ("pipeline — fallback de proveedor",     [sys.executable, "pipeline/pipeline.py", "autotest-fallback"]),
    ("gate gráfico ↔ etapa (14 casos)",      [sys.executable, "pipeline/autotest_grafico_etapa.py"]),
    ("lote — runner",                        [sys.executable, "-m", "lote.runner", "autotest"]),
    ("lote — reporte HTML/Excel/CSV",        [sys.executable, "-m", "lote.reporte", "autotest"]),
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print(f"Veristack — suite completa ({len(SUITE)} bloques, cero llamadas de API)\n")
    fallos, t0 = [], time.time()

    for nombre, cmd in SUITE:
        inicio = time.time()
        res = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        ms = int((time.time() - inicio) * 1000)
        if res.returncode == 0:
            print(f"  PASS  {nombre:42s} {ms:>6} ms")
        else:
            print(f"  FALLA {nombre:42s} {ms:>6} ms")
            fallos.append((nombre, res))

    total_ms = int((time.time() - t0) * 1000)
    print()

    for nombre, res in fallos:
        print(f"--- salida de «{nombre}» (código {res.returncode}) ---")
        cola = (res.stdout or "") + (res.stderr or "")
        print("\n".join(cola.strip().splitlines()[-15:]) or "(sin salida)")
        print()

    if fallos:
        print(f"SUITE: {len(SUITE) - len(fallos)}/{len(SUITE)} en verde — "
              f"{len(fallos)} FALLA(S) en {total_ms} ms")
        return 1

    print(f"SUITE: {len(SUITE)}/{len(SUITE)} en verde — {total_ms} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
