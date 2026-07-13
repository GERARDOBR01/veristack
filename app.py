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
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

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

# Modo lote (N fotos -> reporte consolidado). El paquete lote/ vive en la raíz.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from lote import runner as lote_runner                # noqa: E402
from lote import reporte as lote_reporte              # noqa: E402


# ──────────────────────────────────────────────────────────────
# CONFIG: knowledge base con rutas absolutas
# ConfigRetrieval por defecto apunta a "knowledge/..." relativo al cwd.
# Streamlit corre desde la raíz del proyecto, pero los JSON viven en
# pipeline/knowledge/, así que fijamos rutas absolutas aquí.
# ──────────────────────────────────────────────────────────────

def _config_pipeline(etapa_activa: str | None = None) -> ConfigPipeline:
    return ConfigPipeline(
        config_retrieval=ConfigRetrieval(
            ruta_capa1          = str(KNOWLEDGE / "capa1_display_basics.json"),
            ruta_capa2          = str(KNOWLEDGE / "capa2_campana_activa.json"),
            ruta_capa3_template = str(KNOWLEDGE / "capa3_{tipo_foto}.json"),
            etapa_activa        = etapa_activa,
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


def _df_criterios(criterios):
    """
    DataFrame con las filas de criterios, en el mismo orden que la tabla en
    pantalla. Única fuente para la tabla Y el CSV exportado: ambos salen de
    aquí, así no pueden desincronizarse. Devuelve None si no hay criterios.
    """
    if not criterios:
        return None

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
    return pd.DataFrame(filas, columns=["criterio", "veredicto", "confianza", "fuente", "delegado_a_modelo"])


def _tabla_criterios(df) -> None:
    """
    Tabla con columnas: criterio | veredicto | confianza | fuente | delegado_a_modelo.
    Primero los criterios que NO cumplen (ordenados por severidad), luego los
    CUMPLE al final, mostrados en gris. Recibe el DataFrame de _df_criterios().
    """
    if df is None:
        st.caption("El pipeline no devolvió criterios individuales para este caso.")
        return

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

    fotos_subidas = st.file_uploader(
        "Subir foto(s) — varias fotos activan el modo lote",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
    )

    etapa_activa = st.selectbox("Etapa activa", ["E1", "E2", "E3"])

    # Honestidad ANTES del click: un tipo sin capa3 en knowledge/ dará
    # NO_CALIFICA en sus criterios específicos (gap GC-capa3) — se avisa aquí.
    def _etiqueta_tipo(t: str) -> str:
        if t == "auto":
            return "auto (detección del sistema)"
        return t if (KNOWLEDGE / f"capa3_{t}.json").exists() else f"{t} (sin knowledge aún)"

    tipo_foto = st.selectbox("Tipo de foto",
                             ["auto", "focal_show", "tringla", "mesa_show"],
                             format_func=_etiqueta_tipo)

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

_tipo_efectivo = None if tipo_foto == "auto" else tipo_foto


def _banner_parcial(es_parcial: bool, causa: str | None) -> None:
    """Fix del gap de honestidad (schema 1.1): una corrida parcial se dice
    ARRIBA del veredicto, nunca se presenta como completa."""
    if es_parcial:
        st.error(f"⚠️ EVALUACIÓN PARCIAL — {causa or 'ver resumen'}. "
                 "El resultado mezcla veredictos reales con NO_CALIFICA de "
                 "infraestructura y NO debe leerse como una corrida completa.",
                 icon="⚠️")


# ══════════════════════════════════════════════════════════════
# MODO LOTE (2+ fotos): procesar_lote + reporte consolidado
# ══════════════════════════════════════════════════════════════
if fotos_subidas and len(fotos_subidas) > 1:
    import shutil

    tmp_dir = tempfile.mkdtemp(prefix="lote_verificador_")
    try:
        # Conservar los nombres originales (el reporte los muestra); si dos
        # archivos se llaman igual, se desambiguan con sufijo _2, _3, …
        rutas, usados = [], set()
        for f in fotos_subidas:
            nombre = Path(f.name).name or "foto.jpg"
            base, ext = os.path.splitext(nombre)
            k = 1
            while nombre.lower() in usados:
                k += 1
                nombre = f"{base}_{k}{ext}"
            usados.add(nombre.lower())
            destino = Path(tmp_dir) / nombre
            destino.write_bytes(f.getbuffer())
            rutas.append(str(destino))

        ejecutar_fn, cuota_fn, n_base = lote_runner.crear_ejecutor_real(etapa_activa)
        if n_base == 0:
            st.error(f"El knowledge cargó 0 criterios para la etapa '{etapa_activa}' — "
                     "todo saldría NO_CALIFICA. Revisa pipeline/knowledge/.")
            st.stop()

        barra = st.progress(0.0, text=f"Procesando lote de {len(rutas)} fotos…")

        def _prog(i, total, nombre):
            barra.progress(i / total, text=f"{i}/{total} — {nombre}")

        with st.spinner("Ejecutando pipeline por foto…"):
            lote = lote_runner.procesar_lote(
                rutas, etapa_activa, _tipo_efectivo, ejecutar_fn,
                cuota_agotada_fn=cuota_fn, progreso_cb=_prog)

        # Generar los reportes ANTES de borrar los temporales: las miniaturas
        # del HTML se leen de disco en este punto.
        html_reporte = lote_reporte.generar_html(lote)
        xlsx         = lote_reporte.generar_excel(lote)
        csv_detalle  = lote_reporte.generar_csv_detalle(lote)
        import json as _json
        json_lote    = _json.dumps(lote, ensure_ascii=False, indent=2).encode("utf-8")
    except Exception as exc:  # el lote no debe tumbar la UI
        st.error("El modo lote lanzó un error y no pudo completar la corrida.")
        st.exception(exc)
        st.stop()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    r  = lote["resumen"]
    pv = r["por_veredicto"]
    _banner_parcial(r["lote_parcial"], r["causa_lote_parcial"])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("GRAVE",       pv["GRAVE"])
    c2.metric("OBSERVACION", pv["OBSERVACION"])
    c3.metric("NO_CALIFICA", pv["NO_CALIFICA"])
    c4.metric("CUMPLE",      pv["CUMPLE"])
    c5.metric("% cumplimiento",
              f"{r['pct_cumplimiento']}%" if r["pct_cumplimiento"] is not None else "—")

    st.subheader(f"Lote: {lote['meta']['fotos_procesadas']}/{lote['meta']['fotos_totales']} "
                 f"fotos procesadas — campaña {etapa_activa}")

    import pandas as pd
    filas = [{
        "foto":       f["nombre"],
        "estado":     f["estado"],
        "veredicto":  f["veredicto_global"] or "—",
        "graves":     f["n_graves"],
        "obs.":       f["n_observaciones"],
        "no_califica": f["n_no_califica"],
        "parcial":    "sí" if f["evaluacion_parcial"] else "no",
    } for f in sorted(lote["fotos"],
                      key=lambda x: (lote_reporte._ORDEN_REPORTE.get(x["veredicto_global"], 3),
                                     x["nombre"]))]
    st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)

    # on_click="ignore": la descarga no dispara rerun (mismo patrón del CSV single)
    d1, d2, d3 = st.columns(3)
    d1.download_button("Descargar reporte HTML", data=html_reporte.encode("utf-8"),
                       file_name="reporte_lote.html", mime="text/html", on_click="ignore")
    if xlsx is not None:
        d2.download_button("Descargar Excel", data=xlsx, file_name="datos_lote.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           on_click="ignore")
    else:
        d2.download_button("Descargar CSV (detalle)", data=csv_detalle,
                           file_name="datos_lote_detalle.csv", mime="text/csv",
                           on_click="ignore")
    d3.download_button("Descargar JSON", data=json_lote, file_name="resultados_lote.json",
                       mime="application/json", on_click="ignore")
    st.stop()

# ══════════════════════════════════════════════════════════════
# MODO 1 FOTO (o ninguna): vista original
# ══════════════════════════════════════════════════════════════
foto = fotos_subidas[0] if fotos_subidas else None

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
            tipo_foto    = _tipo_efectivo,
            config       = _config_pipeline(etapa_activa),
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
    # Honestidad primero: si la corrida fue parcial, se dice ANTES del veredicto.
    _banner_parcial(getattr(resultado, "evaluacion_parcial", False),
                    getattr(resultado, "causa_parcial", None))

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
    df_criterios = _df_criterios(resultado.criterios)
    _tabla_criterios(df_criterios)

    if df_criterios is not None:
        # on_click="ignore": la descarga no dispara rerun, así el CSV servido
        # es exactamente el de la corrida que está en pantalla.
        st.download_button(
            "Descargar CSV",
            data=df_criterios.to_csv(index=False).encode("utf-8-sig"),
            file_name="criterios_verificacion.csv",
            mime="text/csv",
            on_click="ignore",
        )
