# REPORTE DE HALLAZGOS — Stress de código Fase 2 (Sesión HH, 12 Jul 2026)

> 17 casos contra `retrieval_engine` / merge PASO_7 / `confidence_engine` / lotes.
> Cero tokens, cero red (guard verificado: 0 intentos no autorizados), producción intacta.
> Expectativas escritas antes de correr (`EXPECTATIVAS.md`); crudo en `resultados/resultados.json`.

## Resumen ejecutivo

**Los dos peores fallos posibles del sistema existen y se reprodujeron en milisegundos:**

1. 🔴 **CUMPLE fantasma por knowledge muerto (R2a)** — con las 3 capas de knowledge
   corruptas y una foto sana con campaña confirmada, el pipeline emite
   **`VEREDICTO GLOBAL: CUMPLE` con 0 criterios evaluados**. La tienda "pasó" una
   verificación que nunca ocurrió. Es la variante peor de CR-2: la Sesión FF solo vio
   la variante NO_CALIFICA porque su mandatory nunca daba CUMPLE pleno.
2. 🔴 **CUMPLE fantasma por respuesta malformada del modelo (M2)** — si el modelo
   responde un veredicto que no parsea (`"Cumple ✓"`), el `except ValueError: pass` de
   `_merge_veredictos` conserva el CUMPLE preliminar de confidence **y le pega la razón
   del modelo** (`[MODELO] se ve impecable`) — un criterio de juicio visual queda CUMPLE
   sin verificación visual, con apariencia de veredicto real. El caso "modelo no
   respondió" sí degrada a NO_CALIFICA; el caso "respondió basura" no.

El patrón de FF se sostiene y se agrava: **el sistema nunca crashea, pero cuando el
insumo muere (knowledge o modelo), degrada hacia el silencio — y ahora sabemos que en
dos rutas degrada hacia un CUMPLE que no ocurrió.**

## Hallazgos por caso

### Grupo R — knowledge roto (CR-2)

| Caso | Resultado | Clasificación |
|------|-----------|---------------|
| R0 | Baseline: 141 criterios, NO_CALIFICA (por delegados sin modelo — esperado offline) | referencia |
| R1 | Capa2 rota → corrida "normal" con **21 criterios (de 141)**. `traza_visible=False`. Única huella: `versiones_capas["capa2"]=None` (nadie la mira). | 🔴 **CR-2 confirmado — CRÍTICO, fallo silencioso** |
| R2a | 3 capas rotas + mandatory todo CUMPLE → **`CUMPLE` con 0 criterios**. Resumen: `VEREDICTO GLOBAL: CUMPLE | código=0 | modelo=0`. | 🔴 **CR-2b NUEVO — CRÍTICO, CUMPLE fantasma** |
| R2b | 3 capas rotas + etapa E1 → NO_CALIFICA con 0 criterios, causa knowledge invisible (parece problema de gráfico). | 🔴 CR-2 (variante que FF ya vio) |
| R3 | `tipo_foto="x/../../decoy"` → **el path traversal carga `decoy.json` desde FUERA de `knowledge/`** y su criterio entra a la evaluación (`DECOY_CARGADO=True`). Windows resuelve `..` léxicamente aunque `capa3_x/` no exista. | 🟠 **PT-1 NUEVO — bug real** (hoy `tipo_foto` viene de la UI/clasificador, pero cualquier integración externa lo vuelve superficie de ataque de knowledge poisoning) |
| R4 | Capa con entradas basura (id int, texto None, aliases dict, peso inválido, no-dicts) → coerciones aguantan todo, el criterio sano sobrevive, la basura queda fuera. | 🟢 Correcto |

**Detalle de fondo (R1):** `pipeline._leer_capa` (líneas 106-115) es un cargador PROPIO,
distinto de `retrieval_engine._cargar_capa_full`, con `except Exception: return []` **sin
siquiera logger**. Hay DOS cargadores de knowledge con dos niveles de silencio — el fix de
CR-2 debe unificar o cubrir ambos.

### Grupo M — merge PASO_7 (CR-3/H1 + modelo hostil)

| Caso | Resultado | Clasificación |
|------|-----------|---------------|
| M1 | Mandatory emite `grafico_etapa_no_verificable` (NO_CALIFICA) → veredicto_global=NO_CALIFICA pero el criterio **no aparece en `ResultadoFinal.criterios` ni en el resumen**. El usuario ve NO_CALIFICA sin poder saber por qué. Causa: `_criterios_mandatory_solo_codigo` solo promueve GRAVEs. | 🔴 **CR-3/H1 confirmado y cuantificado** |
| M2 | Veredicto malformado del modelo → CUMPLE preliminar conservado + razón del modelo. | 🔴 **MG-1 NUEVO — bug real CRÍTICO** |
| M3 | Criterios inventados por el modelo: ignorados. Intento de pisar un GRAVE de código: bloqueado (no está en `ids_delegados`). | 🟢 Correcto — regla fija #5 aguanta |
| M4 | Evaluaciones duplicadas del mismo criterio: gana la última (determinista, dict overwrite). | 🟢 Documentado, no bug |
| M5 | El modelo puede CREAR un GRAVE de juicio visual sobre un criterio delegado. | 🟢 Diseño confirmado (crear sí, pisar no) |

### Grupo C — confidence_engine

| Caso | Resultado | Clasificación |
|------|-----------|---------------|
| C1 | `ResultadoRetrieval(evidencias=[], sin_evidencia=False)` → **IndexError** en `_aplicar_reglas` (`evidencias[0]`). Hoy inalcanzable desde retrieval (siempre consistente), pero es crash latente ante cualquier caller nuevo. | 🟠 **CE-1 NUEVO — bug real latente (severidad baja)** |
| C2 | Lote mixto (dict/None/int entre válidos) → filtra inválidos, evalúa el válido. | 🟢 Correcto |
| C3 | `no_aplica=True` pasado directo a `evaluar()` se reporta como "Sin evidencia" (NO_CALIFICA) — semántica NO_APLICA ≠ NO_CALIFICA se pierde. Sin ruta de producción hoy (`buscar_lote` los omite antes). | 🟡 Deuda de semántica, documentada |

### Grupo B — lotes contra keys muertas (H3/H5 cuantificado)

| Caso | Resultado |
|------|-----------|
| B1 | 3 lotes × 3 keys muertas = **9 requests + 6 s dormidos** cuando 3 requests bastaban para saberlo. 45/45 criterios degradan a NO_CALIFICA. La razón por-criterio dice "Sin respuesta" (distinguible criterio a criterio), pero **ningún campo global de `ResultadoFinal` dice "modelo no disponible"**. |
| B2 | Keys mueren tras el lote 1 → resultado **PARCIAL** (15 veredictos reales + 30 NO_CALIFICA de cuota) **sin ninguna marca global de parcialidad** — la variante más traicionera de H3: parece una corrida completa. |
| B3 | Escala benchmark: 122 delegados = 9 lotes → **27 requests + 18 s dormidos por foto** contra keys muertas → **~675 requests + ~7.5 min por corrida de 25 fotos**. El número que justifica el circuit breaker. |

## Registro de bugs — movimientos

| ID | Movimiento |
|----|-----------|
| CR-2 | CONFIRMADO + agravado: nueva variante **CR-2b (CUMPLE fantasma con 0 criterios)**. Además: hay DOS cargadores de knowledge (`pipeline._leer_capa` sin logger). |
| CR-3/H1 | CONFIRMADO y cuantificado (M1). |
| H3/H5 | CUANTIFICADOS en código (B1-B3): 675 requests + 7.5 min desperdiciados por corrida; resultado parcial sin marca. |
| MG-1 | **NUEVO — CRÍTICO**: veredicto malformado del modelo → CUMPLE fantasma con razón del modelo (`_merge_veredictos`). |
| PT-1 | **NUEVO — bug real**: path traversal vía `tipo_foto` carga JSON fuera de `knowledge/`. |
| CE-1 | **NUEVO — latente**: IndexError en `confidence_engine._aplicar_reglas` con retrieval inconsistente. |

## Fixes propuestos (Fase B — cirugía)

Sin decisión de Gerardo (fix mecánico con respuesta obvia):
- **MG-1**: veredicto no parseable → degradar a NO_CALIFICA igual que el caso "sin respuesta" (nunca conservar el CUMPLE preliminar de un juicio visual no verificado).
- **CE-1**: en `_aplicar_reglas`, tratar `evidencias=[]` como Regla 5 aunque `sin_evidencia` mienta.
- **PT-1**: validar `tipo_foto` contra `[a-z0-9_]+` antes de formatear la ruta de capa3.
- **CR-2 (guard)**: si el knowledge activo carga 0 criterios → NUNCA CUMPLE; criterio de código visible en el resultado con la causa.

Con decisión de Gerardo (shape/product):
- **CR-3/H1**: cómo se ven los NO_CALIFICA de mandatory en `ResultadoFinal` (¿promoverlos a `criterios` igual que los GRAVEs?).
- **H3**: circuit breaker (cortar lotes al confirmar keys muertas) + campo de parcialidad en `ResultadoFinal` (¿`evaluacion_parcial`/`modelo_no_disponible`?). Agregar campos es retrocompatible con el schema versionado.
- **H2**: bloquear o marcar la evaluación de capa2 cuando la campaña no es confirmable.

---

# ADDENDUM — Re-corrida POST-FIX (misma sesión HH)

Decisiones de Gerardo: CR-3 → promover a `criterios`; H3 → breaker + marca de
parcialidad; H2 → marcar, no bloquear. Fixes aplicados en `pipeline.py`,
`retrieval_engine.py`, `confidence_engine.py` (schema de salida 1.0 → 1.1,
campos nuevos `evaluacion_parcial`/`causa_parcial` — retrocompatible).

| Caso | Antes | Después | Estado |
|------|-------|---------|--------|
| R1 | 141→21 criterios en silencio | `conocimiento_incompleto` VISIBLE en criterios y resumen (`traza_visible=True`) | ✅ CERRADO |
| R2a | **CUMPLE con 0 criterios** | **NO_CALIFICA** + `conocimiento_no_disponible` visible | ✅ CERRADO |
| R2b | Causa invisible | `conocimiento_no_disponible` con detalle por capa | ✅ CERRADO |
| R3 | `DECOY_CARGADO=True` | `DECOY_CARGADO=False` (tipo_foto validado como identificador; capa3 no se consulta) | ✅ CERRADO (PT-1) |
| M1 | NO_CALIFICA de mandatory invisible | Visible en criterios y en resumen | ✅ CERRADO (CR-3/H1) |
| M2 | CUMPLE fantasma con razón del modelo | Degrada a NO_CALIFICA con razón explícita del veredicto malformado | ✅ CERRADO (MG-1) |
| C1 | IndexError | Sin crash (Regla 5 cubre evidencias vacías) | ✅ CERRADO (CE-1) |
| B1 | 9 requests + 6 s | **3 requests + 2 s** (breaker corta tras el lote 1) | ✅ CERRADO |
| B2 | 7 requests, parcial sin marca | 4 requests; E2E: `evaluacion_parcial=True` + causa en `ResultadoFinal` y resumen | ✅ CERRADO |
| B3 | 27 req + 18 s/foto (675 req/benchmark) | **3 req + 2 s/foto (75 req/benchmark)** | ✅ CERRADO |
| C3 / M4 / M5 | — | Sin cambio (deuda de semántica documentada / diseño confirmado) | según lo esperado |

Verificación completa post-fix:
- Autotests: photo_analyzer **16/16**, rotación **10/10**, batching **20/20** (4 checks nuevos del breaker + info).
- Stress FF re-corrido (21 casos): frontera de brillo intacta (39.0/39.9 GRAVE; 40.0+ pasa), A1-A5 GRAVE `archivo_invalido`, P0 con traza, C4 sin crash; **K1/K2 ahora muestran `conocimiento_incompleto` y K3 `conocimiento_no_disponible`** (CR-2 cerrado también contra los fixtures de FF); G1 bajó de 33 a **6** intentos de red (breaker). Guard anti-red: 0 fuera de mocks.
- E2E foto real SF01 offline: NO_CALIFICA como siempre, ahora con `evaluacion_parcial=True — "el modelo no respondió 10 de 10 lote(s)"` y schema 1.1. Baseline pasa de 137 a **138 criterios** (+1 = `grafico_etapa_no_verificable` promovido — es el fix CR-3 visible, no una regresión).
- Nota benchmark: el arnés cuenta como detección solo GRAVE/OBSERVACION — los NO_CALIFICA promovidos NO inflan detecciones.
