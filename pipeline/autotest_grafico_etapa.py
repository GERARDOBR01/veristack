"""
autotest_grafico_etapa.py — gate del fix de `grafico_etapa_incorrecta`
(sesión 7 Jul 2026: la comparación estricta != disparaba GRAVE en toda foto
con gráfico porque visión responde el nombre de campaña y la UI manda "E1").

3 casos obligatorios del gate + regresiones. Exit 1 si cualquiera falla.
Correr:  python pipeline/autotest_grafico_etapa.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mandatory_engine import ConfigEngine, Severidad, _regla_grafico_etapa

BASE = {"brillo": 80.0, "nitidez": 90.0, "espacio_vacio": 10.0, "tipo_foto": "focal_show"}


def caso(nombre, etapa, grafico, criterio_esperado, severidad_esperada):
    meta = dict(BASE, etapa_activa=etapa, grafico_detectado=grafico)
    r = _regla_grafico_etapa(meta, ConfigEngine())
    ok = r.criterio == criterio_esperado and r.severidad == severidad_esperada
    estado = "PASS" if ok else "FAIL"
    print(f"[{estado}] {nombre}: etapa={etapa!r} grafico={grafico!r} "
          f"-> {r.criterio}/{r.severidad.value} (esperado {criterio_esperado}/{severidad_esperada.value})")
    return ok


resultados = [
    # ── Los 3 casos del gate ──────────────────────────────────────────
    # (a) gráfico genérico correcto → NO dispara
    caso("(a) genérico correcto, ID de campaña", "gran_barata_pv2026", "Gran Barata",
         "grafico_etapa", Severidad.CUMPLE),
    # (b) gráfico con % correcto → NO dispara
    caso("(b) con % correcto, ID de campaña", "gran_barata_pv2026", "Gran Barata 40%",
         "grafico_etapa", Severidad.CUMPLE),
    # (c) gráfico real incorrecto (sintético) → SÍ dispara
    caso("(c) gráfico incorrecto sintético", "gran_barata_pv2026", "Día del Padre",
         "grafico_etapa_incorrecta", Severidad.GRAVE),

    # ── Regresiones / variantes de producción ─────────────────────────
    # UI manda etiqueta de etapa "E1": no comparable por código → NO_CALIFICA
    # honesto, nunca GRAVE falso (era el 0/5 real).
    caso("UI E1 + gráfico correcto (foto real 2)", "E1", "Gran Barata",
         "grafico_etapa_no_verificable", Severidad.NO_CALIFICA),
    caso("UI E1 + gráfico con %", "E1", "Gran Barata 40%",
         "grafico_etapa_no_verificable", Severidad.NO_CALIFICA),
    # Slogan completo del gráfico real
    caso("slogan completo correcto", "gran_barata_pv2026", "Vive la GRAN BARATA",
         "grafico_etapa", Severidad.CUMPLE),
    # Etiquetas de etapa comparables entre sí (selftest histórico del engine)
    caso("E2 activa vs gráfico E1", "E2", "E1",
         "grafico_etapa_incorrecta", Severidad.GRAVE),
    caso("E1 activa vs gráfico E1", "E1", "E1",
         "grafico_etapa", Severidad.CUMPLE),
    # IDs históricos de los tests de pipeline.py
    caso("verano_2025 idéntico", "verano_2025", "verano_2025",
         "grafico_etapa", Severidad.CUMPLE),
    caso("primavera_2024 vs verano_2025", "verano_2025", "primavera_2024",
         "grafico_etapa_incorrecta", Severidad.GRAVE),
    # Guards intactos
    caso("sin gráfico detectado", "gran_barata_pv2026", None,
         "grafico_no_detectado", Severidad.NO_CALIFICA),
    caso("sin etapa activa", None, "Gran Barata",
         "etapa_no_definida", Severidad.NO_CALIFICA),
]

total, ok = len(resultados), sum(resultados)
print(f"\n{ok}/{total} PASS")
sys.exit(0 if ok == total else 1)
