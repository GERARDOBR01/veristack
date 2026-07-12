# -*- coding: utf-8 -*-
"""
correr_stress_test.py — Maltrato exploratorio de Motor 1 (SIN ground truth).

NO es el benchmark oficial. Objetivo: encontrar comportamiento raro/silencioso
del pipeline real (con imagen + modelo) bajo configuraciones adversariales.

Corridas:
  A — 5 fotos con etapa_activa="E1" forzado (fotos de OTRA campaña).
  B — las mismas 5 con etapa_activa=None (sin forzar).
  C — determinismo: SF03 corrida 2 veces con la MISMA config (E1).
  D — tipo_foto forzado mal: SF05 con tipo_foto="focal_show" (no lo es), E1.

Salida: motor1/stress_test/resultados/corrida_<X>.json con el ResultadoFinal
COMPLETO por foto (no solo detecciones), tiempo por foto, y cualquier excepción
capturada (una foto que crashea NO aborta el resto — el crash ES un hallazgo).

Uso:  python correr_stress_test.py [A B C D]   (default: las 4)
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

AQUI          = Path(__file__).resolve().parent
RAIZ_REPO     = AQUI.parents[1]
KNOWLEDGE_DIR = RAIZ_REPO / "pipeline" / "knowledge"
FOTOS_DIR     = AQUI / "fotos"
SALIDA_DIR    = AQUI / "resultados"

FOTOS = ["SF01.png", "SF02.png", "SF03.png", "SF04.png", "SF05.jpeg"]
FOTO_DETERMINISMO = "SF03.png"   # la más rica en contenido (piso de venta)
FOTO_TIPO_MAL     = "SF05.jpeg"  # sala de muebles — claramente NO focal_show


def _cargar_env(raiz: Path) -> None:
    ruta = raiz / ".env"
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _serializar(obj):
    """dataclass/Enum → estructuras JSON. Nunca lanza: repr() como último recurso."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serializar(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _serializar(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serializar(v) for v in obj]
    if hasattr(obj, "value") and not isinstance(obj, (str, int, float, bool)):
        return obj.value
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


def main(argv: list[str]) -> int:
    corridas = [c.upper() for c in argv] or ["A", "B", "C", "D"]

    _cargar_env(RAIZ_REPO)
    sys.path.insert(0, str(RAIZ_REPO / "pipeline"))
    sys.path.insert(0, str(RAIZ_REPO / "core"))
    import pipeline as motor1                     # noqa: E402
    from retrieval_engine import ConfigRetrieval  # noqa: E402

    if not os.environ.get("GEMINI_API_KEY"):
        print("ABORTADO: GEMINI_API_KEY ausente — sin modelo todo saldría NO_CALIFICA.")
        return 1

    faltan = [f for f in FOTOS if not (FOTOS_DIR / f).exists()]
    if faltan:
        print(f"ABORTADO: fotos faltantes en {FOTOS_DIR}: {faltan}")
        return 1

    # Logging del pipeline VISIBLE (lección del 9 Jul: sin esto los 429/503 son invisibles)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s | %(message)s")

    def _config(etapa_activa):
        return motor1.ConfigPipeline(
            config_retrieval=ConfigRetrieval(
                ruta_capa1          = str(KNOWLEDGE_DIR / "capa1_display_basics.json"),
                ruta_capa2          = str(KNOWLEDGE_DIR / "capa2_campana_activa.json"),
                ruta_capa3_template = str(KNOWLEDGE_DIR / "capa3_{tipo_foto}.json"),
                etapa_activa        = etapa_activa,
            ))

    n_base = len(motor1._extraer_criterios_del_knowledge(
        _config("E1").config_retrieval, None, "E1"))
    if n_base == 0:
        print("ABORTADO: knowledge cargó 0 criterios.")
        return 1
    print(f"Knowledge OK: {n_base} criterios base (E1).")

    # Pre-flight de cuota — 1 llamada mínima, aborta si todas las keys caídas
    cuerpo_min = {"contents": [{"role": "user", "parts": [{"text": "di ok"}]}],
                  "generationConfig": {"maxOutputTokens": 5}}
    if motor1._post_gemini(cuerpo_min, 20, "PREFLIGHT-STRESS") is None:
        print("ABORTADO: pre-flight de cuota falló — ninguna key responde.")
        return 1
    print("Pre-flight de cuota OK.\n")

    def correr_foto(archivo: str, etapa, tipo_foto):
        ruta = str(FOTOS_DIR / archivo)
        t0 = time.perf_counter()
        registro = {"archivo": archivo, "etapa_activa": etapa, "tipo_foto_forzado": tipo_foto}
        try:
            r = motor1.ejecutar(imagen_path=ruta, etapa_activa=etapa,
                                tipo_foto=tipo_foto, config=_config(etapa))
            registro["excepcion"] = None
            registro["resultado"] = _serializar(r)
        except Exception:
            registro["excepcion"] = traceback.format_exc()
            registro["resultado"] = None
        registro["tiempo_segundos"] = round(time.perf_counter() - t0, 2)
        res = registro.get("resultado") or {}
        print(f"  {archivo} [etapa={etapa} tipo={tipo_foto}]: "
              f"{registro['tiempo_segundos']}s, veredicto={res.get('veredicto_global')}, "
              f"criterios={len(res.get('criterios') or [])}, "
              f"excepcion={'SI' if registro['excepcion'] else 'no'}", flush=True)
        return registro

    PLAN = {
        "A": ("etapa E1 forzada, fotos de otra campana",
              [(f, "E1", None) for f in FOTOS]),
        "B": ("etapa None (sin forzar)",
              [(f, None, None) for f in FOTOS]),
        "C": ("determinismo: misma foto+config 2 veces",
              [(FOTO_DETERMINISMO, "E1", None), (FOTO_DETERMINISMO, "E1", None)]),
        "D": ("tipo_foto=focal_show forzado mal",
              [(FOTO_TIPO_MAL, "E1", "focal_show")]),
    }

    SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    for c in corridas:
        desc, plan = PLAN[c]
        print(f"── CORRIDA {c}: {desc}", flush=True)
        registros = [correr_foto(*args) for args in plan]
        datos = {"meta": {"corrida": c, "descripcion": desc,
                          "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "nota": "STRESS TEST EXPLORATORIO — sin ground truth, no es benchmark"},
                 "corridas": registros}
        ruta = SALIDA_DIR / f"corrida_{c}.json"
        ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  → {ruta}\n", flush=True)
    print("Stress test completado.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
