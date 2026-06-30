"""
app.py — UI mínima del Pipeline de Verificación Visual (visual-lv / Veristack)

Una sola pantalla, Streamlit nativo puro. La UI NO tiene lógica de evaluación:
solo recoge inputs, llama a pipeline.ejecutar() y muestra el ResultadoFinal.

Uso:
    pip install -r requirements.txt    (o: pip install streamlit pillow numpy)
    streamlit run app.py

La API key de Gemini se toma de la variable de entorno GEMINI_API_KEY
(nunca se pide en la UI). Si no está, el pipeline degrada de forma controlada.
"""

import os
import sys
import tempfile
import traceback
from pathlib import Path

import streamlit as st

# ──────────────────────────────────────────────────────────────
# IMPORTS DEL PIPELINE
# El paquete pipeline/ usa imports planos (import mandatory_engine, ...),
# así que su carpeta debe ir al frente del sys.path. core/ se agrega para
# que photo_analyzer quede disponible (el pipeline lo importa de forma
# opcional; si falta, usa defaults seguros).
# ──────────────────────────────────────────────────────────────

ROOT         = Path(__file__).resolve().parent
PIPELINE_DIR = ROOT / "pipeline"
CORE_DIR     = ROOT / "core"
KNOWLEDGE    = PIPELINE_DIR / "knowledge"

for _p in (str(PIPELINE_DIR), str(CORE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pipeline as pipeline_mod                       # pipeline/pipeline.py
from pipeline import ConfigPipeline                   # dataclass agregador
from mandatory_engine import Severidad
from retrieval_engine import ConfigRetrieval


# ──────────────────────────────────────────────────────────────
# CONFIG: knowledge base con rutas absolutas
# ConfigRetrieval por defecto apunta a "knowledge/..." relativo al cwd.
# Streamlit corre desde la raíz del proyecto, pero los JSON viven en
# pipeline/knowledge/, así que fijamos rutas absolutas aquí.
# ──────────────────────────────────────────────────────────────

def _config_pipeline() -> ConfigPipeline:
    return ConfigPipeline(
        config_retrieval=ConfigRetrieval(
            ruta_capa1          = str(KNOWLEDGE / "capa1_display_basics.json"),
            ruta_capa2          = str(KNOWLEDGE / "capa2_campana_activa.json"),
            ruta_capa3_template = str(KNOWLEDGE / "capa3_{tipo_foto}.json"),
        )
    )


# ──────────────────────────────────────────────────────────────
# HELPERS DE PRESENTACIÓN
# ──────────────────────────────────────────────────────────────

_RANK_SEVERIDAD = {
    Severidad.GRAVE:       4,
    Severidad.OBSERVACION: 3,
    Severidad.NO_CALIFICA: 2,
    Severidad.CUMPLE:      1,
}


def _mostrar_veredicto_global(veredicto: Severidad) -> None:
    """Veredicto global con color: CUMPLE verde, OBSERVACION amarillo, GRAVE rojo."""
    texto = f"VEREDICTO GLOBAL: {veredicto.value}"
    if veredicto == Severidad.GRAVE:
        st.error(texto, icon="🛑")
    elif veredicto == Severidad.OBSERVACION:
        st.warning(texto, icon="⚠️")
    elif veredicto == Severidad.CUMPLE:
        st.success(texto, icon="✅")
    else:  # NO_CALIFICA u otro
        st.info(texto, icon="ℹ️")


def _tabla_criterios(criterios) -> None:
    """
    Tabla con columnas: criterio | veredicto | confianza | fuente | delegado_a_modelo.
    Primero los criterios que NO cumplen (ordenados por severidad), luego los
    CUMPLE al final, mostrados en gris.
    """
    if not criterios:
        st.caption("El pipeline no devolvió criterios individuales para este caso.")
        return

    ordenados = sorted(
        criterios,
        key=lambda c: (
            c.veredicto == Severidad.CUMPLE,          # CUMPLE al final
            -_RANK_SEVERIDAD.get(c.veredicto, 0),     # más grave primero
            c.criterio,
        ),
    )

    filas = [
        {
            "criterio":          c.criterio,
            "veredicto":         c.veredicto.value,
            "confianza":         c.confianza.value,
            "fuente":            c.fuente_dominante,
            "delegado_a_modelo": "sí" if c.delegar_a_modelo else "no",
        }
        for c in ordenados
    ]

    import pandas as pd
    df = pd.DataFrame(filas, columns=["criterio", "veredicto", "confianza", "fuente", "delegado_a_modelo"])

    def _gris_si_cumple(row):
        return ["color: gray" if row["veredicto"] == "CUMPLE" else "" for _ in row]

    estilo = df.style.apply(_gris_si_cumple, axis=1)
    st.dataframe(estilo, width="stretch", hide_index=True)


# ──────────────────────────────────────────────────────────────
# PÁGINA
# ──────────────────────────────────────────────────────────────

st.set_page_config(page_title="Verificador Visual", layout="wide")
st.title("Verificador Visual — visual-lv")

# ── SIDEBAR: inputs ───────────────────────────────────────────
with st.sidebar:
    st.header("Inputs")

    foto = st.file_uploader("Subir foto", type=["jpg", "jpeg", "png"])

    etapa_activa = st.selectbox("Etapa activa", ["E1", "E2", "E3"])

    tipo_foto = st.selectbox("Tipo de foto", ["focal_show", "tringla", "mesa_show"])

    verificar = st.button("Verificar", type="primary", width="stretch")

    st.divider()
    if os.environ.get("GEMINI_API_KEY"):
        st.caption("GEMINI_API_KEY: detectada ✅")
    else:
        st.caption("GEMINI_API_KEY: ausente — los criterios delegados "
                   "conservan el veredicto del código.")

# ── ÁREA PRINCIPAL: output ────────────────────────────────────
if not verificar:
    st.info("Configura los inputs en la barra lateral y presiona **Verificar**.")
    st.stop()

# Guardar la foto subida a un archivo temporal y pasar su ruta como imagen_path.
# Sin foto → imagen_path=None (el pipeline ya lo maneja).
imagen_path = None
tmp_path    = None
try:
    if foto is not None:
        sufijo = Path(foto.name).suffix or ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=sufijo) as tmp:
            tmp.write(foto.getbuffer())
            tmp_path = tmp.name
        imagen_path = tmp_path

    with st.spinner("Ejecutando pipeline…"):
        resultado = pipeline_mod.ejecutar(
            imagen_path  = imagen_path,
            etapa_activa = etapa_activa,
            tipo_foto    = tipo_foto,
            config       = _config_pipeline(),
        )
except Exception as exc:  # el pipeline no debe tumbar la UI
    st.error("El pipeline lanzó un error y no pudo completar la evaluación.")
    st.exception(exc)
    st.code("".join(traceback.format_exc()))
    resultado = None
finally:
    if tmp_path:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

if resultado is not None:
    # Veredicto global con color
    _mostrar_veredicto_global(resultado.veredicto_global)

    # Métricas en 3 columnas
    col1, col2, col3 = st.columns(3)
    col1.metric("Decididos por código", resultado.criterios_decididos_por_codigo)
    col2.metric("Delegados a modelo",   resultado.criterios_delegados_a_modelo)
    col3.metric("Duración (ms)",        resultado.duracion_ms)

    if resultado.resumen_ejecutivo:
        st.caption(resultado.resumen_ejecutivo)

    st.subheader("Criterios")
    _tabla_criterios(resultado.criterios)
