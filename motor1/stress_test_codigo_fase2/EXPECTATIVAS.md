# EXPECTATIVAS — Stress de código Fase 2 (retrieval / merge / confidence / lotes)

> Escrito ANTES de correr `correr_stress_fase2.py`, como manda el protocolo de Sesión FF.
> Cero modelo, cero red (guard anti-red global), cero cambios a producción.
> Objetivo: mapear con precisión los módulos que la Fase FF nunca tocó — donde viven
> CR-2 (retrieval/knowledge), CR-3/H1 (merge PASO_7) y H3/H5 (lotes/keys) — ANTES de
> la cirugía de fixes. Cada caso declara la conducta esperada según lectura del código.

Fecha: 12 Jul 2026 · Sesión HH · Módulos: `retrieval_engine.py`, `pipeline.py`
(`_calcular_veredicto_global`, `_merge_veredictos`, `_evaluar_delegados_en_lotes`,
`_post_gemini`), `confidence_engine.py`.

Leyenda de lo que se mide en cada caso:
- `crash`: ¿lanza excepción no controlada?
- `traza_visible`: ¿el fallo deja señal en el `ResultadoFinal` que ve el usuario
  (criterios / resumen_ejecutivo / veredicto), no solo en un logger con NullHandler?
- `veredicto`: veredicto_global resultante.

---

## Grupo R — Knowledge roto (CR-2, `retrieval_engine` + `pipeline._leer_capa`)

Contexto de código: `pipeline._leer_capa` (líneas 106-115) tiene su PROPIO cargador con
`except Exception: return []` **sin siquiera un logger** — más silencioso aún que
`retrieval_engine._cargar_capa_full`, que al menos loggea WARNING (invisible por NullHandler).
`ResultadoConfianza` no transporta `capas_vacias`; la única traza candidata en
`ResultadoFinal` es `versiones_capas` (queda `None` para la capa rota).

| Caso | Setup | Esperado |
|------|-------|----------|
| R0 (baseline) | Copias INTACTAS del knowledge real, etapa=E1, tipo=focal_show, metadata sana inyectada | Corrida normal: N≈137 criterios, sin GRAVE. Referencia para comparar conteos. |
| R1 | capa2 con sintaxis JSON rota (mismas condiciones que R0) | **Fallo silencioso confirmado (CRÍTICO, es CR-2)**: corrida "normal" con muchos menos criterios (solo capa1+capa3, ≈15-20). `traza_visible=False` salvo `versiones_capas["capa2"]=None`. Sin crash. |
| R2a | Las 3 capas rotas + mandatory TODO CUMPLE (etapa=ID de campaña real, grafico inyectado correcto, tipo válido, foto sana) | ⚠️ Predicción de lectura de código: `criterios=[]` → `severidades=∅` → se agrega `mandatory.veredicto_final=CUMPLE` → **veredicto_global=CUMPLE con 0 criterios evaluados**. Si se confirma: **CUMPLE FANTASMA — peor variante de CR-2** (FF solo vio la variante NO_CALIFICA porque su mandatory no daba CUMPLE pleno). |
| R2b | Las 3 capas rotas + etapa=E1 (mandatory da NO_CALIFICA por `grafico_etapa_no_verificable`) | veredicto=NO_CALIFICA con 0 criterios (la variante que FF ya vio). Honesto a medias: no inventa CUMPLE, pero la causa real (knowledge muerto) es invisible — parece problema de gráfico. |
| R3 | `tipo_foto="../capa2_campana_activa"` (path traversal en `ruta_capa3_template.format()`) | El template produce `knowledge/capa3_../capa2_campana_activa.json` → lo más probable es que el path NO resuelva y capa3=[] (degradación graceful). Si el SO normaliza el path y carga capa2 como capa3: bug real (knowledge equivocado activado por input). Verificar cuál de los dos ocurre. |
| R4 | Capa con entradas basura: id=int, texto=None, aliases=dict, peso="MUYGRAVE", etapa_aplicable="foo", criterios=string | Sin crash: `_to_str/_to_list/_coerce_peso` cubren todo; entradas basura se ignoran o degradan a RECOMMENDATION. Esperado: graceful, 0 crash. |

## Grupo M — Merge PASO_7 y veredicto global (CR-3/H1 + respuesta del modelo hostil)

Contexto: `_criterios_mandatory_solo_codigo` SOLO promueve GRAVEs del mandatory a
`ResultadoFinal.criterios`; los NO_CALIFICA de mandatory (etapa_no_definida,
grafico_no_detectado, grafico_etapa_no_verificable, tipo_foto_desconocido) no aparecen
nunca en la lista, aunque SÍ pueden teñir el veredicto_global. En `_merge_veredictos`,
un veredicto malformado del modelo cae en `except ValueError: pass` → conserva el
CUMPLE preliminar de confidence.

| Caso | Setup | Esperado |
|------|-------|----------|
| M1 | etapa=E1 + grafico inyectado (dispara `grafico_etapa_no_verificable` NO_CALIFICA en mandatory), knowledge intacto | **CR-3 cuantificado**: veredicto_global=NO_CALIFICA pero `grafico_etapa_no_verificable` NO aparece en `ResultadoFinal.criterios` ni en el resumen — el usuario ve NO_CALIFICA sin poder saber por qué. `traza_visible=False`. |
| M2 | Modelo (mockeado) responde veredicto malformado `"Cumple ✓"` para un criterio delegado | ⚠️ Predicción: `Severidad("CUMPLE ✓")` → ValueError → `pass` → **el criterio conserva el CUMPLE preliminar de confidence + razón "[MODELO] ..."** → **CUMPLE fantasma de juicio visual no verificado**. Si se confirma: **bug real nuevo** (el caso "modelo no respondió" sí degrada a NO_CALIFICA; el caso "respondió basura" no). |
| M3 | Modelo responde evaluaciones para criterios NO delegados / inventados (`criterio_inventado_por_modelo`) | Ignorados (`if rc.criterio not in ids_delegados: continue`). Correcto — verificar que ni el veredicto ni el conteo cambian. |
| M4 | Modelo responde 2 evaluaciones para el MISMO criterio (CUMPLE y luego GRAVE) | Última gana (dict overwrite). Documentar el orden — no es bug si es determinista. |
| M5 | Modelo responde veredicto=GRAVE para criterio delegado | El merge lo acepta (diseño: el modelo puede CREAR un GRAVE de juicio visual; lo que no puede es PISAR un GRAVE del código — esos nunca se delegan). Verificar y documentar como diseño, no bug. |

## Grupo C — confidence_engine (sin stress previo)

| Caso | Setup | Esperado |
|------|-------|----------|
| C1 | `ResultadoRetrieval` inconsistente: `evidencias=[]` pero `sin_evidencia=False` | ⚠️ Predicción: `top = retrieval.evidencias[0]` → **IndexError** (línea 140). Hoy inalcanzable desde `retrieval_engine` (siempre consistente), pero es un crash latente ante cualquier caller nuevo. Bug real de severidad baja. |
| C2 | `evaluar_lote` con lista mixta (ResultadoRetrieval válido + dict + None + int) | Los inválidos se filtran (`isinstance`), los válidos se evalúan. Graceful. |
| C3 | `no_aplica=True` pasado directo a `evaluar()` (buscar_lote los omite, pero `buscar()` unitario los retorna) | Se evalúa como Regla 5 (sin_evidencia=True) → NO_CALIFICA "Sin evidencia". Semántica dudosa (NO_APLICA ≠ NO_CALIFICA) pero sin ruta de producción que lo alcance hoy. Documentar. |

## Grupo B — Lotes contra keys muertas (H3/H5 en código)

Contexto: `intentos_max = max(3, n_claves)`; cada lote llama `_llamar_modelo` →
`_post_gemini` desde cero, sin memoria de que las keys ya murieron en el lote anterior.
Con rotación entre claves la espera es `sleep(1)`; el último intento no duerme.

| Caso | Setup | Esperado |
|------|-------|----------|
| B1 | 3 keys todas en 429 permanente (mock), 45 criterios delegados → 3 lotes de 15, sin imagen | **H3 cuantificado**: 3 lotes × 3 intentos = **9 requests** contra keys que se sabían muertas desde el intento 3 del lote 1, + ~6 s de sleeps (2 rotaciones × 1 s × 3 lotes). Un circuit breaker habría cortado tras el lote 1 (3 requests). Todos los criterios degradan a NO_CALIFICA **indistinguible** de un NO_CALIFICA real en `ResultadoFinal` (ni un campo lo dice). |
| B2 | Keys mueren DESPUÉS del lote 1 (lote 1 OK, lotes 2-3 en 429) | Lote 1 mergea normal; lotes 2-3 queman 6 requests + sleeps. El `ResultadoFinal` mezcla veredictos reales con NO_CALIFICA de cuota sin distinguirlos — variante más traicionera de H3 (resultado PARCIAL que parece completo). |
| B3 | Escala: 122 delegados (9 lotes) todas las keys muertas — solo contar, sin correr los sleeps reales (sleep mockeado) | 9 lotes × 3 intentos = **27 requests + ~18 s dormidos** por foto. × 25 fotos del benchmark = ~675 requests desperdiciados. El número que justifica el circuit breaker. |

## Guard global

- `urllib.request.urlopen` interceptado TODO el run: cualquier intento de red fuera de
  los mocks del Grupo B → contador `intentos_red_no_autorizados` (esperado: 0).
- `time.sleep` mockeado en Grupo B (contador, no espera real).
- Producción intacta: `pipeline/`, `core/`, `knowledge/*.json` solo se LEEN;
  las copias rotas viven en `fixtures/` de esta carpeta.
