# CLAUDE.md — Veristack / El Verificador
> Fuente de verdad en tiempo real del estado del proyecto.
> Code actualiza la sección "Estado actual" al cerrar cada sesión.
> La página de Notion "🤖 Claude Code — Configuración & Estado" se sincroniza **desde** este archivo, no al revés.

## Rol
Claude Code es el **ingeniero arquitecto y ejecutor** de Veristack. No es un asistente que prueba a ver qué funciona — es el ejecutor técnico de una empresa seria. Cada entrega debe ser robusta, verificable y exacta. Si algo no está claro, pregunta o lo marca como pendiente — **nunca inventa ni asume "razonable"**.

## Reglas fijas — no negociables
1. **Nunca generar JSONs de prueba/fixtures genéricos** cuando se trate de conocimiento real (criterios de Liverpool u otro cliente). Si no tiene los datos reales adjuntos, debe decirlo explícitamente — no inventar contenido plausible. *(Ya pasó una vez, 28 Jun — costó una sesión completa de detección y corrección.)*
2. **"Hecho" significa que está en el repo remoto y corre**, no que terminó de programarlo en la sesión local. Toda entrega debe ser explícita sobre si ya hizo push o si Gerardo necesita descargarlo manualmente.
3. **Nunca pegar API keys** en código ni en chat. Solo `.env` local, nunca se commitea.
4. Cualquier criterio o JSON de conocimiento debe seguir el **schema_conocimiento_v1.md** — no cambiar ese formato sin aprobación explícita de Gerardo.
5. `mandatory_engine.py` ejecuta reglas duras y bloquea — el modelo nunca puede sobreescribir un GRAVE que el código ya determinó.

## Decisión fundacional
**"Código decide, modelo interpreta."** El modelo (Gemini/GPT) nunca decide compliance. Solo contextualiza y redacta criterios que el código ya marcó como ambiguos (confianza MEDIO/BAJO).
Filosofía: **"Reloj suizo, no cohete espacial"** — robusto, seguro, confiable, duradero. Simplicidad antes que complejidad. Cero mediocridad.

---

## Estado actual (25 Jul 2026 — Sesión LL: **FIX del mapeo campaña↔gráfico — el falso NO_CALIFICA de `grafico_etapa_no_verificable` cerrado; en remoto (`8d00e81`).**)

**Resumen honesto: sesión corta y quirúrgica. Se corrigió el input mal armado de la comparación gráfico↔etapa: la UI/manifest manda `etapa_activa="E1"` (etiqueta pura, sin nombre de campaña), así que TODA foto con gráfico caía a `grafico_etapa_no_verificable` (NO_CALIFICA) aunque el knowledge de capa2 SÍ tenía la campaña cargada — verificado en vivo en el benchmark_mini (las 5 fotos con "Gran Barata"/"Preventa Gran Barato" bajo E1 disparaban el falso NO_CALIFICA). El fix inyecta el nombre canónico de la campaña desde capa2 y lo usa para la comparación cuando la etapa es etiqueta pura; sin ese dato conserva el NO_CALIFICA honesto de siempre. Gate 14/14 PASS antes de push. Todo en remoto.**

- **Fix (4 archivos, solo se corrige el INPUT — la lógica de comparación probada NO se toca):**
  - `pipeline/knowledge/capa2_campana_activa.json`: nuevo top-level `nombre_campana: "gran_barata_pv2026"`.
  - `pipeline/pipeline.py`: helper `_nombre_campana_capa2()` + inyección de `metadata["nombre_campana"]` antes de mandatory (solo cuando hay etapa activa → capa2 se carga; no pisa `metadata_extra`).
  - `pipeline/mandatory_engine.py`: `_regla_grafico_etapa` usa `nombre_campana` como input de comparación cuando la etapa es etiqueta pura (`_ETIQUETA_ETAPA_RE`). **NO toca** `_corresponde_grafico_etapa`/`_canon_grafico`/`_nucleo_campana`. Fallback preservado: sin `nombre_campana` → `grafico_etapa_no_verificable` (NO_CALIFICA), idéntico a hoy.
  - `pipeline/autotest_grafico_etapa.py`: +2 casos (E1+nombre_campana→CUMPLE; E1+nombre_campana+gráfico ajeno→GRAVE). **14/14 PASS.**
- **Verificado:** `autotest_grafico_etapa.py` 14/14 PASS; autotest interno de `mandatory_engine.py` PASS; integración desde `pipeline/` → el falso NO_CALIFICA desaparece y un gráfico ajeno sigue dando GRAVE.
- 🔴 **NO re-corrido el benchmark de 5 fotos** (consume cuota Gemini; el gate real son los autotests, que pasaron). Cuando Gerardo lo corra, las fotos "Gran Barata" bajo E1 deben mostrar CUMPLE en PASO_1 en vez de `grafico_etapa_no_verificable`.
- **NO tocado:** los JSON candidatos de `motor2/` (para el swap futuro) no recibieron el campo — el swap está gated y es aparte.
- ⏳ **Pendientes de Motor 2 (heredados de Sesión KK, sin cambio):** lotes 9-10 de aplicabilidad (28 criterios) → `aplicar_aplicabilidad.py aplicar` + validator + swap con autorización; decidir el mapeo mueble↔tipo_foto ANTES del swap (el filtro compara literal). GITHUB_API_KEY 401 pendiente de renovar.

**Tracking (sin cambio — se decide junto con Gerardo): Motor 1: 100% | Motor 2: 100% | Listo-para-mostrar: 45%.**

## Historial de sesiones
El historial completo de sesiones anteriores (secciones “Estado previo”, Sesiones I–GG) vive en `HISTORIAL_SESIONES.md` (raíz del repo). No se carga en contexto automáticamente — consultarlo solo cuando se necesite el detalle de una sesión pasada.

## Registro de bugs y gaps abiertos
> Tabla viva. Toda sesión que encuentre o cierre un bug la actualiza (además de su sección de sesión).
> Estados: `ABIERTO` / `EN_FIX` / `CERRADO(commit)`.

| ID | Descripción corta | Dónde | Clasificación | Estado | Origen |
|----|-------------------|-------|---------------|--------|--------|
| CR-1 | Excepción en photo_analyzer → foto evaluada como "perfecta" (brillo=100) sin traza | `pipeline._preparar_metadata` | CRÍTICO / fallo silencioso | CERRADO (Sesión GG: `analisis_fallido` + regla `archivo_invalido` bloqueante; verificado con re-corrida del stress) | Stress código 12 Jul |
| CR-2 | Knowledge JSON corrupto → capa amputada en silencio; 3 capas rotas → corrida con 0 criterios. **Agravante encontrado en Sesión HH (CR-2b): con mandatory todo CUMPLE, las 3 capas muertas daban `CUMPLE` con 0 criterios — CUMPLE fantasma.** | `retrieval_engine._cargar_capa_full` + `pipeline._leer_capa` (había DOS cargadores con dos niveles de silencio) | CRÍTICO / gap arquitectónico | CERRADO (Sesión HH: `_diagnostico_knowledge` + criterio visible `conocimiento_incompleto`/`conocimiento_no_disponible`; verificado en stress fase 2 y re-corrida FF) | Stress código 12 Jul + fase 2 |
| CR-3 / H1 | `etapa_no_definida` y todo NO_CALIFICA de mandatory desaparece del resultado final (solo se exponen GRAVEs) — mismatch de campaña indetectable | `pipeline._criterios_mandatory_solo_codigo` | CRÍTICO / gap arquitectónico | CERRADO (Sesión HH: se promueve todo lo no-CUMPLE del mandatory a `criterios`; sin etapa, `etapa_no_definida` es visible pero no tiñe el veredicto — decisión Gerardo 12 Jul) | Stress IA 11 Jul + código 12 Jul |
| BR-1 | `etapa_activa` no-string (int) tumba `ejecutar()` con AttributeError | `pipeline.py:135` y `:293` | Bug real | CERRADO (Sesión GG: coerción a str en la entrada de `ejecutar()`; había DOS `.strip()` frágiles, no uno) | Stress código 12 Jul |
| GD-1 | Todo archivo roto (inexistente/0 bytes/truncado/no-imagen) se diagnostica como "imagen oscura" — la causa real se descarta | `photo_analyzer` (la sabe) → `_preparar_metadata` (la tira) | Gap de diagnóstico | CERRADO (Sesión GG: contrato `estado/causa` en photo_analyzer + GRAVE `archivo_invalido` con causa real) | Stress código 12 Jul |
| H2 | Con etapa etiqueta ("E1") el sistema evalúa capa2 de una campaña que no puede confirmar (evaluación en falso) | pipeline PASO 2 + knowledge | Gap arquitectónico | CERRADO (Sesión HH: "marcar, no bloquear" — `grafico_etapa_no_verificable` visible + "CAMPAÑA NO CONFIRMADA POR CÓDIGO". **Sesión LL (`8d00e81`): la campaña ahora SÍ se confirma por código cuando el knowledge de capa2 declara `nombre_campana` — la etiqueta pura "E1" se mapea al nombre canónico para la comparación de gráfico; sin ese dato conserva el NO_CALIFICA honesto**) | Stress IA 11 Jul |
| H3 | Cuota agotada (429 en todas las keys) indistinguible de NO_CALIFICA real; sin circuit breaker quema todos los lotes contra keys muertas (medido: 27 requests + 18 s/foto = ~675 requests/benchmark) | `_post_gemini` / `_evaluar_delegados_en_lotes` | Gap arquitectónico | CERRADO (Sesión HH: circuit breaker `_ESTADO_CUOTA` corta lotes restantes — 27→3 requests/foto — + `evaluacion_parcial`/`causa_parcial` en ResultadoFinal, schema 1.1) | Stress IA 11 Jul + código 12 Jul + fase 2 |
| H4 | Inconsistencia del modelo entre corridas idénticas | PASO_4 (modelo) | Gap conocido (inherente al modelo) | ABIERTO | Stress IA 11 Jul |
| H5 | Pre-flight de cuota protege el arranque, no la corrida | runner benchmark | Gap conocido | CERRADO (Sesión HH: el breaker + `evaluacion_parcial` cubren la mitad de corrida; el pre-flight del runner queda como optimización de arranque) | Stress IA 11 Jul |
| MG-1 | Veredicto malformado del modelo ("Cumple ✓") → `except ValueError: pass` conservaba el CUMPLE preliminar CON la razón del modelo pegada — CUMPLE fantasma de juicio visual no verificado | `pipeline._merge_veredictos` | CRÍTICO / bug real | CERRADO (Sesión HH: basura del modelo degrada a NO_CALIFICA igual que ausencia de respuesta) | Stress fase 2 (12 Jul) |
| PT-1 | Path traversal vía `tipo_foto` ("x/../../otro") cargaba un JSON FUERA de `knowledge/` como capa3 (Windows resuelve `..` léxicamente) | `retrieval_engine._ruta_capa3` + `pipeline._extraer_criterios_del_knowledge` | Bug real (superficie de knowledge poisoning) | CERRADO (Sesión HH: tipo_foto validado como identificador `[A-Za-z0-9_-]+`; el pipeline reutiliza `_ruta_capa3` — una sola ruta de construcción) | Stress fase 2 (12 Jul) |
| CE-1 | `ResultadoRetrieval` inconsistente (evidencias=[] + sin_evidencia=False) → IndexError latente | `confidence_engine._aplicar_reglas` | Bug real latente (baja) | CERRADO (Sesión HH: Regla 5 cubre evidencias vacías) | Stress fase 2 (12 Jul) |
| GC-noaplica | `no_aplica=True` evaluado directo por `confidence_engine.evaluar()` se reporta como "Sin evidencia" (NO_CALIFICA) — semántica NO_APLICA ≠ NO_CALIFICA se pierde. Sin ruta de producción hoy (`buscar_lote` los omite antes) | `confidence_engine` | Deuda de semántica | ABIERTO | Stress fase 2 (12 Jul) |
| GC-umbral | Doble umbral de brillo (photo_analyzer 30 vs ConfigEngine 40) — dos verdades sobre el mismo número | `photo_analyzer.BRIGHTNESS_MIN` vs `ConfigEngine.brillo_minimo` | Deuda de claridad | CERRADO (Sesión GG: documentado en el código — BRIGHTNESS_MIN/MAX solo alimentan `quality`/CLI; el veredicto lo decide únicamente ConfigEngine) | Sesión BB + stress código 12 Jul |
| H6 | `evaluacion_parcial` mentía por diseño: el runner re-derivaba el flag con señal gruesa (tokens==0 = degradación TOTAL) e ignoraba el flag por-lote que el pipeline SÍ expone desde Sesión HH → benchmark_mini 19 Jul reportó "completa" 5 fotos con 1-3 lotes caídos c/u; además no existía % de degradación ni corte temprano por % de fallo acumulado | `correr_motor1_benchmark._metadata_parcial` + `pipeline._evaluar_delegados_en_lotes` | CRÍTICO / gap de honestidad | CERRADO (Sesión KK: runner lee el flag real del pipeline; ResultadoFinal 1.2 expone `criterios_degradados_por_cuota`/`pct_degradado_por_cuota` — solo delegados AUSENTES de la respuesta, NC respondidos no cuentan; corte temprano al 50% de lotes fallidos tras muestra de 4 — umbral decidido por Gerardo; autotest 5 casos borde) | benchmark_mini 19 Jul |
| H7 | Rotación de claves NO persistente: `idx=0` local a cada `_post_gemini` → TODA llamada quemaba 1 request + 1s en la key #1 muerta (medido: 50/50 rotaciones salieron de #1) y las keys #4/#5 jamás se usaron; agravante: Google aplica cuota POR PROYECTO, no por key (verificar mapeo key→proyecto en AI Studio) | `pipeline._post_gemini` | CRÍTICO / bug real | CERRADO (Sesión KK: `_ROTACION` a nivel módulo — arranca en la última key viva; + respeta `retryDelay` del 429; + el log ya nombra la cuota excedida `quotaId` y `finishReason`/snippet en JSON inválido) | Diagnóstico IA 19 Jul |
| GC-delegacion | Delegación masiva: se delegan ~137 criterios/foto y el modelo responde "no verificable" a ~2/3 → 10 lotes + 10 reenvíos de imagen por foto para NO_CALIFICA en masa (~275-375 requests por benchmark de 25). Filtrar por `aplica_a` bajaría a ~3-4 lotes/foto — depende del pendiente #1 de Motor 2. **Verificado 19 Jul: NO requiere código — el filtro ya existe y opera en `retrieval_engine` (`_aplica_a_tipo`/`_aplica_a_etapa`/`no_aplica`); el problema es dato: 126/148 criterios de capa2 con `etapa_aplicable=null` y 138/148 con `aplica_a=null` → todo pasa. Se cierra con la curación de Motor 2 + swap, sin tocar pipeline** | `pipeline` PASO 3/4 + knowledge capa2 | Gap arquitectónico / costo | EN_FIX (Sesión KK: curación 120/148, lotes 9-10 pendientes; ⚠️ mapeo mueble↔tipo_foto a decidir ANTES del swap — el filtro compara literal) | Diagnóstico IA 19 Jul |
| H8 | Gemini emite el array de evaluaciones con `finishReason=STOP` pero SIN el `]` de cierre (JSON válido truncado al final) → `json.loads` revienta y el lote ENTERO degradaba a NO_CALIFICA aunque 14/15 evaluaciones venían completas (7/50 lotes en benchmark_mini 19 Jul fallaron así — 0 por cuota) | `pipeline._normalizar_respuesta` | Bug real (del proveedor; el código lo amplificaba) | CERRADO (Sesión KK: `_rescatar_array_truncado` decodifica objeto por objeto y conserva los completos; objeto cortado a la mitad se descarta; basura real sigue degradando; ausentes cuentan en `pct_degradado_por_cuota`; autotest 4 casos) | Instrumentación Sesión KK (corrida 19 Jul) |
| GC-capa3 | Faltan `capa3_tringla.json` y `capa3_mesa_show.json` | `pipeline/knowledge/` | Gap conocido | ABIERTO | Histórico |
| GC-readme | README desactualizado (dice v0.1) | `README.md` | Deuda documental | CERRADO (Sesión II: README a estado real — uso UI/CLI, arquitectura, honestidad sin key) | Histórico |

## Próximos pasos (orden de prioridad)
1. **Motor 2 — terminar la curación de aplicabilidad (Sesión KK dejó 120/148):** revisar lotes 9-10 de `motor2/candidatos_aplicabilidad.json` (28 criterios, mismo flujo en chat) → `aplicar_aplicabilidad.py aplicar` + validator → **decidir el mapeo mueble↔tipo_foto** (el filtro compara literal — ver hallazgo en Estado actual) → swap con `swap_capa2_produccion.mjs` SOLO con autorización explícita. Sub-pendientes históricos aún vigentes: 76 pares duplicados de `validator.py` (¿consolidar o conservar por página?), los 11 de `revision_manual.json`, los 3 sub-marcados de `referencia_no_resuelta`, y los 2 de Sesión Q (duplicados intra-página p6, scope descriptivos p44)
2. Resolver las 2 referencias no resueltas de capa2 (`etiquetado_hogar_diversos` → manual señalización Hardline; `exhibicion_book_impulsos` → Book de impulsos) cuando Gerardo consiga esos documentos
3. Decidir si los campos de proveniencia (`pagina_origen`, `confianza_extraccion`, `referencia_cruzada`) se formalizan en el schema o se eliminan del JSON
4. **Fase 2 de "la herramienta del retail" (con cuota fresca): benchmark de las 25 fotos + calibración** — gate de credibilidad antes de mostrar a la jefa; la calibración PROPONE umbrales, nunca aplica; incluye el pendiente `resolucion_minima_px`
5. Validar `app.py` en navegador — **single VALIDADO 13 Jul** (banner parcial + aviso sin key + degradación honesta, con foto real); falta: modo lote en navegador, dropdown "(sin knowledge aún)" a ojo, y corrida con key real
6. Agregar `capa3_tringla.json` y `capa3_mesa_show.json` (bloqueado en los manuales reales — mientras, la UI los marca "(sin knowledge aún)")
7. Implementar extractor híbrido de PDFs

---

## Protocolo de cierre de sesión
Usar `/cerrar-sesion` al final de cada sesión de trabajo. El comando:
1. Verifica estado real del repo remoto (no confía en el reporte de la sesión)
2. Actualiza esta sección "Estado actual"
3. Hace commit de este CLAUDE.md
4. Entrega resumen de 3-5 líneas
5. Al degradar el “Estado actual” anterior, la sección degradada se MUEVE a `HISTORIAL_SESIONES.md` (no se acumula en este archivo).

## Estructura del proyecto
```
veristack/
├── CLAUDE.md               ← este archivo (fuente de verdad)
├── AGENTS.md               → symlink a CLAUDE.md (para OpenCode)
├── app.py                  ← UI Streamlit (1 foto o modo lote con multi-upload)
├── verificar_lote.py       ← CLI modo lote: carpeta → reporte HTML+Excel (Sesión II)
├── lote/
│   ├── runner.py           ← procesar_lote(): núcleo del lote, corte por cuota
│   └── reporte.py          ← HTML auto-contenido + Excel/CSV
├── requirements.txt        ← +pandas +openpyxl (Sesión II)
├── pipeline/
│   ├── pipeline.py         ← orquestador
│   ├── mandatory_engine.py ← reglas duras, sin modelo
│   ├── retrieval_engine.py ← evidencia del knowledge base
│   ├── confidence_engine.py← calibra confianza por criterio
│   └── knowledge/
│       ├── capa1_display_basics.json
│       ├── capa2_campana_activa.json
│       └── capa3_focal_show.json
├── motor2/                 ← extractor de manuales (aislado del pipeline)
│   ├── venv/               ← git-ignored (pdfplumber + langextract + openai)
│   ├── requirements.txt    ← deps de Motor 2, incluye openai (Sesión K)
│   ├── test_pdfplumber.py  ← validación de setup (Sesión E)
│   ├── segmenter.py        ← segmentador de secciones por heurística (Sesión F)
│   ├── normalizer.py       ← mapea encabezado crudo → seccion_aplicable (Sesión G)
│   ├── extractor.py        ← langextract: criterios+peso+severidad (Sesión H piloto; backend GitHub Models Sesión K; corrida completa sobre el consolidado + etapa_aplicable v1.2 Sesión O)
│   ├── revisar_multicolumna.py ← vuelca texto crudo de páginas multicolumna (Sesión J, sin IA)
│   ├── clasificador_layout.py  ← detecta layout prosa vs diagrama/matriz por página (Sesión L, sin IA)
│   ├── vision_fallback.py      ← Gemini Vision SOLO para las páginas que el clasificador marcó (Sesión M)
│   ├── resultados_vision/      ← pagina_N.json × 14 (estructura reconstruida por Vision, Sesión M)
│   ├── consolidar_manual.py    ← une Vision (14) + texto plano (34) en un solo JSON (Sesión N)
│   ├── manual_consolidado.json ← las 48 páginas consolidadas, insumo base para extractor.py (Sesión N)
│   ├── criterios_extraidos.json ← 167 criterios schema v1.2 con grounding por criterio (Sesión O)
│   ├── validator.py            ← filtro de confiabilidad: schema + contaminación few-shot + failed + duplicados; autotest obligatorio (Sesión P; fix puntuación final en substring-test Sesión Q)
│   ├── capa2_mecanica_montaje_gran_barata_pv_2026_validado.json ← 156 criterios validados (aún sin id/aliases/aplica_a)
│   ├── validator_report.json   ← conteos exactos + 76 pares duplicados (Sesión P)
│   ├── revision_manual.json    ← 11 criterios para revisión manual, con motivo (Sesión P)
│   └── swap_capa2_produccion.mjs ← swap a producción: validar/swap/rollback con gate de autotest 19/19 (Sesión W; swap real pendiente de autorización)
├── core/
│   └── photo_analyzer.py
├── brains/
└── prompts/
```
