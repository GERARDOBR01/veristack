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

## Estado actual (12 Jul 2026 — Sesión II: **MODO LOTE DE PRODUCCIÓN + REPORTE CONSOLIDADO + UI HONESTA — "la herramienta del retail" v1, todo offline, cero tokens.**)

**Resumen honesto: se construyó lo que faltaba entre el motor y la herramienta que reemplaza la revisión manual masiva. Módulo nuevo `lote/` (runner + reportería), CLI `verificar_lote.py` (carpeta → reporte), y `app.py` con multi-upload, banner de EVALUACIÓN PARCIAL (la UI ignoraba los campos 1.1 — una corrida parcial se veía completa) y dropdown que avisa "(sin knowledge aún)" para tringla/mesa_show. Decisiones de Gerardo: HTML visual + Excel de datos; UI y CLI; benchmark de 25 + calibración quedan como Fase 2 con cuota fresca.**

- **`lote/runner.py`** — `procesar_lote()`: una etapa por lote (un lote = una campaña), `tipo_foto` por lote con opción auto; una foto que revienta queda `estado=error` CON traza y el lote sigue (cero fallos silenciosos); **corte de lote por cuota** (extiende el breaker por-foto de HH: foto parcial + `_ESTADO_CUOTA` agotado → las restantes se marcan `no_procesada_por_cuota` sin gastar un request). Contrato `schema_lote 1.0`. Autotest 15/15 (corte por cuota con mock, foto-error, bloqueo mandatory, guards).
- **`lote/reporte.py`** — HTML auto-contenido (miniaturas base64 240px, GRAVES arriba, semáforo, banner rojo de parcialidad; todo texto del pipeline pasa por `html.escape` — las razones del modelo son texto no confiable) + Excel 2 hojas (openpyxl, fallback CSV con BOM — el reporte nunca tumba el lote). Autotest 15/15.
- **`verificar_lote.py`** — CLI: gate de autotests obligatorio, pre-flight de knowledge >0 criterios, aviso honesto sin key ANTES de correr, logging del pipeline visible (lección del 9 Jul).
- **Verificación (offline, sin gastar cuota — keys forzadas a vacío):** autotests nuevos 30/30; E2E CLI sobre las 5 fotos reales de `motor1/stress_test/fotos/` → 5/5 procesadas, NO_CALIFICA + parcial honesto, HTML con 5 miniaturas embebidas y cero recursos externos, xlsx Resumen(5)+Detalle(690), JSON íntegro; AppTest de Streamlit → render OK, dropdown honesto, banner parcial visible en vista single; los 3 autotests del pipeline PASS; re-corrida stress FF (21) + fase 2 (17), guard anti-red 0 — sin regresión (no se tocó `pipeline/`).
- `requirements.txt` +pandas +openpyxl. README actualizado a estado real (**GC-readme CERRADO**). `CLAUDE.md` adelgazado: el historial de sesiones vive en `HISTORIAL_SESIONES.md` (no se carga en contexto; el protocolo de cierre lo alimenta).
- **Pendiente de Gerardo:** click manual en navegador (single y lote) — la lógica está verificada por script. **Fase 2 (con cuota fresca):** benchmark de 25 + calibración (gate de credibilidad antes de mostrar a su jefa). **Fase 3 (bloqueado en manuales):** capa3 tringla/mesa_show.

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
| H2 | Con etapa etiqueta ("E1") el sistema evalúa capa2 de una campaña que no puede confirmar (evaluación en falso) | pipeline PASO 2 + knowledge | Gap arquitectónico | CERRADO (Sesión HH: decisión Gerardo "marcar, no bloquear" — `grafico_etapa_no_verificable` visible en criterios + línea "CAMPAÑA NO CONFIRMADA POR CÓDIGO" en el resumen) | Stress IA 11 Jul |
| H3 | Cuota agotada (429 en todas las keys) indistinguible de NO_CALIFICA real; sin circuit breaker quema todos los lotes contra keys muertas (medido: 27 requests + 18 s/foto = ~675 requests/benchmark) | `_post_gemini` / `_evaluar_delegados_en_lotes` | Gap arquitectónico | CERRADO (Sesión HH: circuit breaker `_ESTADO_CUOTA` corta lotes restantes — 27→3 requests/foto — + `evaluacion_parcial`/`causa_parcial` en ResultadoFinal, schema 1.1) | Stress IA 11 Jul + código 12 Jul + fase 2 |
| H4 | Inconsistencia del modelo entre corridas idénticas | PASO_4 (modelo) | Gap conocido (inherente al modelo) | ABIERTO | Stress IA 11 Jul |
| H5 | Pre-flight de cuota protege el arranque, no la corrida | runner benchmark | Gap conocido | CERRADO (Sesión HH: el breaker + `evaluacion_parcial` cubren la mitad de corrida; el pre-flight del runner queda como optimización de arranque) | Stress IA 11 Jul |
| MG-1 | Veredicto malformado del modelo ("Cumple ✓") → `except ValueError: pass` conservaba el CUMPLE preliminar CON la razón del modelo pegada — CUMPLE fantasma de juicio visual no verificado | `pipeline._merge_veredictos` | CRÍTICO / bug real | CERRADO (Sesión HH: basura del modelo degrada a NO_CALIFICA igual que ausencia de respuesta) | Stress fase 2 (12 Jul) |
| PT-1 | Path traversal vía `tipo_foto` ("x/../../otro") cargaba un JSON FUERA de `knowledge/` como capa3 (Windows resuelve `..` léxicamente) | `retrieval_engine._ruta_capa3` + `pipeline._extraer_criterios_del_knowledge` | Bug real (superficie de knowledge poisoning) | CERRADO (Sesión HH: tipo_foto validado como identificador `[A-Za-z0-9_-]+`; el pipeline reutiliza `_ruta_capa3` — una sola ruta de construcción) | Stress fase 2 (12 Jul) |
| CE-1 | `ResultadoRetrieval` inconsistente (evidencias=[] + sin_evidencia=False) → IndexError latente | `confidence_engine._aplicar_reglas` | Bug real latente (baja) | CERRADO (Sesión HH: Regla 5 cubre evidencias vacías) | Stress fase 2 (12 Jul) |
| GC-noaplica | `no_aplica=True` evaluado directo por `confidence_engine.evaluar()` se reporta como "Sin evidencia" (NO_CALIFICA) — semántica NO_APLICA ≠ NO_CALIFICA se pierde. Sin ruta de producción hoy (`buscar_lote` los omite antes) | `confidence_engine` | Deuda de semántica | ABIERTO | Stress fase 2 (12 Jul) |
| GC-umbral | Doble umbral de brillo (photo_analyzer 30 vs ConfigEngine 40) — dos verdades sobre el mismo número | `photo_analyzer.BRIGHTNESS_MIN` vs `ConfigEngine.brillo_minimo` | Deuda de claridad | CERRADO (Sesión GG: documentado en el código — BRIGHTNESS_MIN/MAX solo alimentan `quality`/CLI; el veredicto lo decide únicamente ConfigEngine) | Sesión BB + stress código 12 Jul |
| GC-capa3 | Faltan `capa3_tringla.json` y `capa3_mesa_show.json` | `pipeline/knowledge/` | Gap conocido | ABIERTO | Histórico |
| GC-readme | README desactualizado (dice v0.1) | `README.md` | Deuda documental | CERRADO (Sesión II: README a estado real — uso UI/CLI, arquitectura, honestidad sin key) | Histórico |

## Próximos pasos (orden de prioridad)
1. **Motor 2 — siguiente sesión: revisión manual de Gerardo sobre `capa2_validado_con_candidatos.json`** (Sesión S ya generó los candidatos de `id`/`aliases`/`aplica_a` — falta aprobarlos/editarlos criterio por criterio, probablemente en tandas, y resolver los 18 grupos en colisión de `candidatos_id_colisiones.json` antes de marcar `revisado_por_gerardo: true`). En paralelo: decidir qué hacer con los 76 pares duplicados reportados por `validator.py` (los clusters de páginas hermanas son repetición real del manual — ¿consolidar con `etapa_aplicable`/`condicion_libre` o conservar por página?), revisar a mano los 11 de `revision_manual.json` (el `[AMBIGUO]` de p20 es falso-failed: su texto sí está en la página), y corregir los 3 casos sub-marcados de `referencia_no_resuelta` (p10 manual de señalización, p39/p40 Book de impulsos). Revisar los 2 pendientes documentados en Sesión Q: duplicados intra-página en p6 (Gerardo revisa el slide a ojo) y scope de criterios descriptivos en páginas Vision (p44)
2. Resolver las 2 referencias no resueltas de capa2 (`etiquetado_hogar_diversos` → manual señalización Hardline; `exhibicion_book_impulsos` → Book de impulsos) cuando Gerardo consiga esos documentos
3. Decidir si los campos de proveniencia (`pagina_origen`, `confianza_extraccion`, `referencia_cruzada`) se formalizan en el schema o se eliminan del JSON
4. **Fase 2 de "la herramienta del retail" (con cuota fresca): benchmark de las 25 fotos + calibración** — gate de credibilidad antes de mostrar a la jefa; la calibración PROPONE umbrales, nunca aplica; incluye el pendiente `resolucion_minima_px`
5. Validar `app.py` en navegador (single y modo lote; la lógica ya está probada por script/AppTest; falta el click manual en la UI)
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
