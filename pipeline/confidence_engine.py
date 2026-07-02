"""
confidence_engine.py
Motor de Calibración de Confianza — visual-lv

Recibe ResultadoPipeline (mandatory) + ResultadoRetrieval (retrieval) por criterio.
Produce un veredicto calibrado con nivel de confianza y señal de delegación al modelo.

Jerarquía de reglas (orden estricto, primera que aplica gana):
  Regla 1 — Mandatory bloqueó        → GRAVE,        ALTO,  no delegar
  Regla 2 — Evidencia MANDATORY+ALTO  → del mandatory, ALTO,  delegar (configurable;
            NUNCA delega si mandatory_engine ya midió el criterio en píxeles —
            el modelo no puede sobreescribir lo que el código ya determinó)
  Regla 3 — Evidencia REC+ALTO        → del mandatory, MEDIO, delegar
  Regla 4 — Solo BAJO o EXCEPTION     → del mandatory, BAJO,  delegar
  Regla 5 — Sin evidencia             → NO_CALIFICA,   ALTO,  no delegar

El modelo NO participa aquí. Solo calibra; no evalúa la imagen.
Input:  list[ResultadoRetrieval] + ResultadoPipeline
Output: list[ResultadoConfianza] ordenada por severidad desc → confianza desc
"""

from dataclasses import dataclass, field
from typing import Optional

from mandatory_engine import ResultadoPipeline, Severidad
from retrieval_engine import Confianza, EvidenciaRetrieved, Peso, ResultadoRetrieval


# ──────────────────────────────────────────────
# TIPOS
# ──────────────────────────────────────────────

@dataclass
class ResultadoConfianza:
    criterio:         str
    veredicto:        Severidad
    confianza:        Confianza
    fuente_dominante: str       # "CAPA1" | "CAPA2" | "CAPA3" | "MANDATORY" | "NINGUNA"
    peso_dominante:   Peso
    delegar_a_modelo: bool
    razon:            str


# ──────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────

@dataclass
class ConfigConfianza:
    # Regla 2: los criterios de juicio visual (planchado, tags, props,
    # colorización, triangulación...) requieren que el modelo VEA la imagen.
    # El código solo decide lo que mide en píxeles (mandatory_engine) —
    # esos criterios nunca se delegan, sin importar este flag.
    delegar_si_mandatory:     bool = True
    delegar_si_recomendacion: bool = True   # Regla 3: RECOMMENDATION necesita modelo
    delegar_si_bajo:          bool = True   # Regla 4: evidencia débil necesita modelo


# ──────────────────────────────────────────────
# TABLAS DE ORDENAMIENTO
# ──────────────────────────────────────────────

_SEVERIDAD_RANK: dict[Severidad, int] = {
    Severidad.GRAVE:       4,
    Severidad.OBSERVACION: 3,
    Severidad.NO_CALIFICA: 2,
    Severidad.CUMPLE:      1,
}

_CONFIANZA_RANK: dict[Confianza, int] = {
    Confianza.ALTO:  3,
    Confianza.MEDIO: 2,
    Confianza.BAJO:  1,
}


# ──────────────────────────────────────────────
# COERCIÓN DE TIPOS
# ──────────────────────────────────────────────

def _to_str(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


# ──────────────────────────────────────────────
# LÓGICA INTERNA
# ──────────────────────────────────────────────

def _veredicto_desde_mandatory(criterio: str, mandatory: ResultadoPipeline) -> Severidad:
    """
    Busca el veredicto del criterio en la lista del mandatory.
    Si el criterio no fue evaluado por mandatory (es solo de retrieval),
    retorna CUMPLE — mandatory no tiene objeción sobre este criterio.
    mandatory.veredicto_final es un agregado global y no debe propagarse
    a criterios independientes que mandatory no evaluó.
    """
    match = next((c for c in mandatory.criterios if c.criterio == criterio), None)
    return match.severidad if match else Severidad.CUMPLE


def _fuente(capa: int) -> str:
    return f"CAPA{capa}"


def _aplicar_reglas(
    retrieval: ResultadoRetrieval,
    mandatory: ResultadoPipeline,
    config:    ConfigConfianza,
) -> ResultadoConfianza:
    criterio = retrieval.criterio

    # ── Regla 1: mandatory bloqueó — ninguna evaluación es válida ──
    if not mandatory.puede_continuar:
        return ResultadoConfianza(
            criterio         = criterio,
            veredicto        = Severidad.GRAVE,
            confianza        = Confianza.ALTO,
            fuente_dominante = "MANDATORY",
            peso_dominante   = Peso.MANDATORY,
            delegar_a_modelo = False,
            razon            = "Mandatory bloqueó el pipeline. Foto no evaluable para este criterio.",
        )

    # ── Regla 5: sin evidencia — evaluada aquí para evitar acceder ──
    #    a evidencias[] vacío en las reglas siguientes.
    if retrieval.sin_evidencia:
        return ResultadoConfianza(
            criterio         = criterio,
            veredicto        = Severidad.NO_CALIFICA,
            confianza        = Confianza.ALTO,
            fuente_dominante = "NINGUNA",
            peso_dominante   = Peso.RECOMMENDATION,
            delegar_a_modelo = False,
            razon            = "Sin evidencia en ninguna capa de conocimiento. No es posible calificar el criterio.",
        )

    top = retrieval.evidencias[0]

    # ── Regla 2: evidencia MANDATORY con confianza ALTO ────────────
    ev_mandatory_alto = [
        e for e in retrieval.evidencias
        if e.peso == Peso.MANDATORY and e.confianza == Confianza.ALTO
    ]
    if ev_mandatory_alto:
        best = ev_mandatory_alto[0]
        # Regla fija #5 del proyecto: si mandatory_engine ya midió este
        # criterio en píxeles, su veredicto es definitivo — el modelo no
        # puede sobreescribirlo. Solo se delegan criterios de juicio visual
        # que el código no midió.
        medido_por_codigo = any(c.criterio == criterio for c in mandatory.criterios)
        delegar = config.delegar_si_mandatory and not medido_por_codigo
        if medido_por_codigo:
            detalle = "Veredicto medido por código (píxeles) — definitivo."
        elif delegar:
            detalle = "Criterio de juicio visual — evaluación delegada al modelo con la imagen."
        else:
            detalle = "Criterio evaluable sin intervención del modelo."
        return ResultadoConfianza(
            criterio         = criterio,
            veredicto        = _veredicto_desde_mandatory(criterio, mandatory),
            confianza        = Confianza.ALTO,
            fuente_dominante = _fuente(best.capa),
            peso_dominante   = Peso.MANDATORY,
            delegar_a_modelo = delegar,
            razon            = f"Evidencia MANDATORY con confianza ALTO en Capa{best.capa}. {detalle}",
        )

    # ── Regla 3: evidencia RECOMMENDATION con confianza ALTO ───────
    ev_rec_alto = [
        e for e in retrieval.evidencias
        if e.peso == Peso.RECOMMENDATION and e.confianza == Confianza.ALTO
    ]
    if ev_rec_alto:
        best = ev_rec_alto[0]
        return ResultadoConfianza(
            criterio         = criterio,
            veredicto        = _veredicto_desde_mandatory(criterio, mandatory),
            confianza        = Confianza.MEDIO,
            fuente_dominante = _fuente(best.capa),
            peso_dominante   = Peso.RECOMMENDATION,
            delegar_a_modelo = config.delegar_si_recomendacion,
            razon            = (
                f"Evidencia RECOMMENDATION con confianza ALTO en Capa{best.capa}. "
                "Evaluación final delegada al modelo."
            ),
        )

    # ── Regla 4: resto — BAJO confianza o solo EXCEPTION ───────────
    #    Cubre: MANDATORY+MEDIO, MANDATORY+BAJO, REC+MEDIO, REC+BAJO,
    #           EXCEPTION+cualquier confianza.
    return ResultadoConfianza(
        criterio         = criterio,
        veredicto        = _veredicto_desde_mandatory(criterio, mandatory),
        confianza        = Confianza.BAJO,
        fuente_dominante = _fuente(top.capa),
        peso_dominante   = top.peso,
        delegar_a_modelo = config.delegar_si_bajo,
        razon            = (
            f"Mejor evidencia disponible: {top.peso.value} con confianza {top.confianza.value} "
            f"en Capa{top.capa}. Alta incertidumbre — evaluación delegada al modelo."
        ),
    )


# ──────────────────────────────────────────────
# ENGINE PRINCIPAL
# ──────────────────────────────────────────────

def evaluar(
    resultado_retrieval: ResultadoRetrieval,
    resultado_mandatory: ResultadoPipeline,
    config:              Optional[ConfigConfianza] = None,
) -> ResultadoConfianza:
    """
    Calibra la confianza para un único criterio.
    """
    if not isinstance(resultado_retrieval, ResultadoRetrieval):
        return ResultadoConfianza(
            criterio         = _to_str(getattr(resultado_retrieval, "criterio", None)) or "desconocido",
            veredicto        = Severidad.NO_CALIFICA,
            confianza        = Confianza.BAJO,
            fuente_dominante = "NINGUNA",
            peso_dominante   = Peso.RECOMMENDATION,
            delegar_a_modelo = True,
            razon            = f"ResultadoRetrieval inválido: se esperaba ResultadoRetrieval, recibido {type(resultado_retrieval).__name__}",
        )

    if not isinstance(resultado_mandatory, ResultadoPipeline):
        resultado_mandatory = ResultadoPipeline(
            veredicto_final = Severidad.NO_CALIFICA,
            resumen         = "ResultadoPipeline inválido — contexto mandatory ausente",
        )

    if config is None:
        config = ConfigConfianza()

    return _aplicar_reglas(resultado_retrieval, resultado_mandatory, config)


def evaluar_lote(
    resultados_retrieval: list[ResultadoRetrieval],
    resultado_mandatory:  ResultadoPipeline,
    config:               Optional[ConfigConfianza] = None,
) -> list[ResultadoConfianza]:
    """
    Calibra la confianza para una lista de criterios.
    Retorna ordenado por severidad desc → confianza desc.
    """
    if not isinstance(resultados_retrieval, list):
        return []

    if not isinstance(resultado_mandatory, ResultadoPipeline):
        resultado_mandatory = ResultadoPipeline(
            veredicto_final = Severidad.NO_CALIFICA,
            resumen         = "ResultadoPipeline inválido — contexto mandatory ausente",
        )

    if config is None:
        config = ConfigConfianza()

    resultados = [
        evaluar(r, resultado_mandatory, config)
        for r in resultados_retrieval
        if isinstance(r, ResultadoRetrieval)
    ]

    return sorted(
        resultados,
        key=lambda r: (
            _SEVERIDAD_RANK.get(r.veredicto, 0),
            _CONFIANZA_RANK.get(r.confianza, 0),
        ),
        reverse=True,
    )


def _generar_resumen(resultados: list[ResultadoConfianza]) -> str:
    if not resultados:
        return "CONFIANZA: sin criterios evaluados"

    graves    = sum(1 for r in resultados if r.veredicto == Severidad.GRAVE)
    delegados = sum(1 for r in resultados if r.delegar_a_modelo)
    no_cal    = sum(1 for r in resultados if r.veredicto == Severidad.NO_CALIFICA)

    partes = [f"CONFIANZA: {len(resultados)} criterio(s)"]
    if graves:
        partes.append(f"{graves} GRAVE(S)")
    if no_cal:
        partes.append(f"{no_cal} NO_CALIFICA")
    partes.append(f"{delegados} delegado(s) al modelo")

    return " | ".join(partes)


# ──────────────────────────────────────────────
# TESTS RÁPIDOS
# Construye ResultadoRetrieval y ResultadoPipeline directamente
# sin cargar archivos — confidence_engine no hace IO.
# ──────────────────────────────────────────────

if __name__ == "__main__":
    from mandatory_engine import Fuente, ResultadoCriterio

    # ── Builders de evidencia ────────────────────────────────────
    def ev(capa: int, peso: Peso, confianza: Confianza) -> EvidenciaRetrieved:
        return EvidenciaRetrieved(
            criterio  = "test",
            evidencia = f"Texto de prueba — Capa{capa} {peso.value} {confianza.value}",
            capa      = capa,
            peso      = peso,
            confianza = confianza,
        )

    def retrieval(criterio: str, evidencias: list, sin_evidencia: bool = False) -> ResultadoRetrieval:
        return ResultadoRetrieval(
            criterio          = criterio,
            evidencias        = evidencias,
            capas_consultadas = [1, 2, 3],
            capas_vacias      = [],
            sin_evidencia     = sin_evidencia or not evidencias,
            resumen           = f"mock:{criterio}",
        )

    # ── Mandatory fixtures ───────────────────────────────────────
    mandatory_ok = ResultadoPipeline(
        veredicto_final = Severidad.CUMPLE,
        puede_continuar = True,
        criterios       = [
            ResultadoCriterio(
                criterio    = "grafico_etapa",
                severidad   = Severidad.GRAVE,
                fuente      = Fuente.CODIGO,
                descripcion = "Gráfico incorrecto",
            ),
        ],
        resumen = "Todo revisado",
    )

    mandatory_bloqueado = ResultadoPipeline(
        veredicto_final = Severidad.GRAVE,
        puede_continuar = False,
        resumen         = "Imagen oscura — pipeline detenido",
    )

    # ── Casos de prueba ──────────────────────────────────────────
    casos = [
        {
            "nombre":   "Regla 1 — Mandatory bloqueó",
            "retrieval": retrieval("triangulacion", [ev(1, Peso.MANDATORY, Confianza.ALTO)]),
            "mandatory": mandatory_bloqueado,
        },
        {
            "nombre":   "Regla 2 — Evidencia MANDATORY+ALTO (criterio en mandatory)",
            "retrieval": retrieval("grafico_etapa", [ev(1, Peso.MANDATORY, Confianza.ALTO)]),
            "mandatory": mandatory_ok,
        },
        {
            "nombre":   "Regla 2 — Evidencia MANDATORY+ALTO (criterio solo en retrieval)",
            "retrieval": retrieval("triangulacion", [ev(1, Peso.MANDATORY, Confianza.ALTO)]),
            "mandatory": mandatory_ok,
        },
        {
            "nombre":   "Regla 3 — Evidencia RECOMMENDATION+ALTO",
            "retrieval": retrieval("limpieza_area", [ev(1, Peso.RECOMMENDATION, Confianza.ALTO)]),
            "mandatory": mandatory_ok,
        },
        {
            "nombre":   "Regla 4 — Solo MANDATORY+MEDIO (no llega a Regla 2)",
            "retrieval": retrieval("distribucion", [ev(1, Peso.MANDATORY, Confianza.MEDIO)]),
            "mandatory": mandatory_ok,
        },
        {
            "nombre":   "Regla 4 — Solo EXCEPTION+ALTO",
            "retrieval": retrieval("criterio_excepcional", [ev(3, Peso.EXCEPTION, Confianza.ALTO)]),
            "mandatory": mandatory_ok,
        },
        {
            "nombre":   "Regla 4 — RECOMMENDATION+BAJO (no llega a Regla 3)",
            "retrieval": retrieval("surtido", [ev(2, Peso.RECOMMENDATION, Confianza.BAJO)]),
            "mandatory": mandatory_ok,
        },
        {
            "nombre":   "Regla 5 — Sin evidencia",
            "retrieval": retrieval("criterio_inexistente", [], sin_evidencia=True),
            "mandatory": mandatory_ok,
        },
        {
            "nombre":   "Input inválido — ResultadoRetrieval no es del tipo correcto",
            "retrieval": {"criterio": "falso"},
            "mandatory": mandatory_ok,
        },
        {
            "nombre":   "Input inválido — ResultadoPipeline no es del tipo correcto",
            "retrieval": retrieval("triangulacion", [ev(1, Peso.MANDATORY, Confianza.ALTO)]),
            "mandatory": {"no_es": "un_pipeline"},
        },
    ]

    for caso in casos:
        print(f"\n{'='*65}")
        print(f"CASO: {caso['nombre']}")
        print(f"{'='*65}")
        r = evaluar(caso["retrieval"], caso["mandatory"])
        print(f"  criterio:         {r.criterio}")
        print(f"  veredicto:        {r.veredicto.value}")
        print(f"  confianza:        {r.confianza.value}")
        print(f"  fuente_dominante: {r.fuente_dominante}")
        print(f"  peso_dominante:   {r.peso_dominante.value}")
        print(f"  delegar_a_modelo: {r.delegar_a_modelo}")
        print(f"  razon:            {r.razon}")

    # ── Test evaluar_lote + ordenamiento ─────────────────────────
    print(f"\n{'='*65}")
    print("LOTE — ordenado por severidad desc → confianza desc")
    print(f"{'='*65}")

    lote_retrieval = [
        retrieval("limpieza_area",      [ev(1, Peso.RECOMMENDATION, Confianza.ALTO)]),  # MEDIO
        retrieval("triangulacion",      [ev(1, Peso.MANDATORY,      Confianza.ALTO)]),  # ALTO / CUMPLE
        retrieval("sin_evidencia",      [], sin_evidencia=True),                         # NO_CALIFICA
        retrieval("grafico_etapa",      [ev(1, Peso.MANDATORY,      Confianza.ALTO)]),  # ALTO / GRAVE
        retrieval("surtido",            [ev(2, Peso.RECOMMENDATION, Confianza.BAJO)]),  # BAJO
    ]

    lote = evaluar_lote(lote_retrieval, mandatory_ok)
    print(_generar_resumen(lote))
    print()
    for r in lote:
        delegado = "→ modelo" if r.delegar_a_modelo else "→ código"
        print(f"  [{r.veredicto.value:<12}][{r.confianza.value:<5}] {r.criterio:<22} {delegado}  fuente={r.fuente_dominante}")
