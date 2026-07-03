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

## Estado actual (3 Jul 2026 — Sesión I: Motor 2, fix multicolumna + fix referencia_no_resuelta)

✅ Completado y en repo remoto (verificado con `git log origin/main`, working tree limpio):
- **Motor 2 — 2 fixes del piloto** (`motor2/extractor.py` + `motor2/test_pdfplumber.py`, sigue en PILOTO):
  - **Fix multicolumna (el hallazgo grande de Sesión H):** la lectura por defecto de pdfplumber intercala columnas (p10 salía revuelto → 3 criterios SIN GROUNDING). Se probó `layout=True` (lo pedido en el brief) y **NO des-intercala** — solo agrega padding X, el orden de lectura sigue mezclado. El que sí funciona es **`extract_text(use_text_flow=True)`** (orden del stream interno del PDF): un solo parámetro, sin heurística propia frágil. Se descartó un declusterizador por posición X porque salió frágil (sobre-dividía p35, una sola columna). `extractor.py` ahora lee el texto de cada bloque con use_text_flow; **página y `seccion_aplicable` siguen viniendo del código** (segmenter/normalizer, extracción por defecto) — no se tocaron. **Resultado: p10 pasó de 3 SIN GROUNDING a 4/4 grounding exacto**; sin regresión en las demás
  - **`test_pdfplumber.py`** ahora lee con use_text_flow y **detecta+reporta páginas multicolumna** comparando el orden de palabras flujo-vs-default. Reportadas (orden difiere): **p1, 2, 3, 5, 6, 7, 10, 11, 12, 13, 16, 18, 26, 27, 28, 31, 32, 34, 35, 42** (20/48). use_text_flow las lee des-intercaladas; el piloto verifica p10 y p35 de ese set (limpias), el resto queda para revisión a ojo antes de escalar (por brief: reportar, no arreglar)
  - **Fix `referencia_no_resuelta` (falso positivo de Sesión H):** ahora es de **3 estados** — `true` (doc/liga externa nombrada), `false` (criterio normal), `null` (instrucción que invoca un estándar externo NO nombrado, ej. "básicos de Display"; el modelo prefija el texto con `[AMBIGUO] ` en vez de inventar una referencia). Ejemplo few-shot negativo anclado en texto real de p22 (fuera del piloto). **Validado**: p20 "Cuida tus básicos de Display." → `[AMBIGUO]`/`null` (ya no `true`); p10 "manual de señalización" → `true` correcto. Se acotó el prompt tras una 1ª iteración que sobre-disparó (marcaba `[AMBIGUO]` a "Mantén el orden"); ahora esas instrucciones normales quedan `false`
  - Robustez: reintento con backoff ante 429. **Límite real del free tier: 20 requests/DÍA por key** (el `.env` tiene **1 sola key**, no 3 como decía una nota vieja). La corrida final combinada validó p29/p20/p10 (ambos fixes); **p43 y p35 quedaron cortadas por cuota diaria agotada** — ya se habían validado limpias esta sesión bajo use_text_flow (p43 5/5, p35 8/8) y no contienen "básicos de Display", así que el cambio de prompt no las altera. Re-correr los 5 juntos requiere cuota fresca (otro día u otra key)
- **Motor 2 — extractor de criterios, PILOTO** (`motor2/extractor.py`, PRIMER uso real de IA/langextract):
  - Corre SOLO sobre 5 bloques de prueba (págs 29, 20, 43, 10, 35 — elegidos por complejidad distinta: simple / con NOTA-excepción / tabla larga / referencia externa / condiciones múltiples). NO se escaló a los 47 (Gerardo revisa a mano primero, por brief)
  - Reparto de responsabilidad respetado: `segmenter.py`+`normalizer.py` fijan página y `seccion_aplicable` por CÓDIGO; langextract SOLO decide `texto`(literal)/`peso`/`severidad`/`condicion_libre`/`referencia_no_resuelta`. Página y sección se PEGAN del código al armar el JSON — el modelo nunca las decide (p10 quedó `seccion_aplicable=null`, no inventó sección)
  - `model_id=gemini-3.5-flash`, `temperature=0.0`, `max_char_buffer=1500` (>bloque más largo → 1 chunk). API key leída de `.env` raíz sin imprimirla. Few-shot (2 ejemplos) anclados en texto REAL de bloques fuera del piloto (p26, p31) para no filtrar respuestas — regla #1 respetada
  - **Verificación de grounding por `char_interval`**: cada criterio se compara contra el span real de la fuente (normalizando whitespace, porque el PDF parte frases a media línea). Solo `match_exact` = OK; `match_fuzzy`/`match_lesser` = SIN GROUNDING para revisión
  - **Resultado**: 24 criterios extraídos, **21 con grounding exacto, 3 sin grounding — los 3 en p10**. peso siguió el patrón estructural real (INDICACIONES→MANDATORY, SUGERENCIA→RECOMMENDATION, NOTA→EXCEPTION); severidad independiente del peso y variada; condicion_libre capturó circunstancias reales (Mascotas, Artículos de viaje, en mesa, muebles de focal) sin meter sección/etapa; sin duplicados
  - **🔴 2 hallazgos para revisión de Gerardo antes de escalar**: (1) **p10 es layout de 2 columnas** → pdfplumber intercala las columnas y revuelve el texto fuente; el modelo reensambla la frase correcta pero deja de ser span literal contiguo (los 3 SIN GROUNDING). No es falla del extractor ni del modelo — es del texto de origen; las páginas multicolumna necesitan tratamiento antes del run completo. (2) **falso positivo en `referencia_no_resuelta`**: "Cuida tus básicos de Display." (p20) salió `true` (concepto interno, no doc externo); en contraste "manual de señalización" (p10) → `true` correcto
- **Motor 2 — normalizador de secciones** (`motor2/normalizer.py`, 100% código, SIN IA):
  - Consume los bloques de `segmenter.py` (import directo, no lo toca) y mapea el encabezado crudo de cada bloque a `seccion_aplicable`: uno de `Softline · Hardline · Diversos · Multimedia · Deportes · Niño/Niña · Hogar` o `None` (null). **`seccion_aplicable` es campo NUEVO** — no existe en el knowledge (que solo tiene `etapa_aplicable`); el vocabulario lo definió Gerardo en el brief de sesión
  - Mapeo por diccionario explícito con precedencia: (1) bloque sin contenido = separador → null; (2) keyword de departamento en el encabezado → su valor (orden fijo, el prefijo gana: `DEPORTES` antes que `NIÑO/NIÑA`); (3) allowlist de genéricos sin depto (portada, materiales, planogramas, exteriores) → null; (4) nada matchea → REPORTA en consola, no fuerza. Umbral duro: >3 sin match → `sys.exit`
  - `COCINA Y ELECTRO` (p34) → Hardline (sub-depto de línea dura sin valor propio, bajo el separador MONTAJE HARDLINE). `Niño/Niña` queda en el vocabulario pero SIN uso en este PDF: la p44 "DEPORTES - DEPORTES Y DEPORTIVO NIÑO/NIÑA" va a Deportes por prefijo
  - **Títulos truncados reparados**: págs 24 y 44 (el título del PDF se parte en 2 líneas). Reparación por conjunto explícito `PAGINAS_TITULO_PARTIDO = {24, 44}` — NO por heurística: un detector genérico de "línea corta en mayúsculas" disparaba en 9 páginas (capturaba primeras palabras de contenido como "BARRAS", "ZAPATERÍAS") y corrompía encabezados; se descartó por la regla de no inventar reglas frágiles
  - **Criterio de éxito cumplido**: 47/47 bloques con `seccion_aplicable` correcta o null explícito, 0 sin match, exactamente 2 títulos reparados (p24, p44), sin encabezados truncados. Reparto: Softline 10 (p20-29), Hardline p31-34+38, Diversos p35, Hogar p36/37/39/40, Multimedia p41/42, Deportes p43/44, resto null. langextract sigue SIN usarse
- **Motor 2 — segmentador de secciones** (`motor2/segmenter.py`, 100% heurística, SIN IA):
  - Lee el texto por página con pdfplumber (misma lógica de lectura que `test_pdfplumber.py`, replicada porque ese script no expone función importable y el alcance era no tocarlo) y agrupa en bloques por sección hasta el próximo encabezado. Cada `Bloque` conserva: `seccion` (texto crudo del encabezado, SIN normalizar), `pagina_inicio`, `pagina_fin`, `texto`
  - Heurística de encabezado (`es_encabezado`): primera línea de la página, `len ≤ 60` y (`ratio_mayúsculas ≥ 0.6` **o** prefijo en mayúsculas seguido de `:`/`-`, ej. "HOGAR - Muebles", "SOFTLINE: FOCAL SHOW..."). Patrón confirmado inspeccionando el PDF real antes de codificar: la primera línea de CADA página del manual es un encabezado
  - **Criterio de éxito cumplido** (revisión a ojo vs Gran Barata): 47 bloques de 48 páginas. Los 6 separadores de una línea (9 PAUTA GENERAL, 15 DESARROLLOS, 17 PDV IMPULSO VIVE, 19 MONTAJE SOFTLINE, 30 MONTAJE HARDLINE, 45 EXTERIORES) se detectan y marcan `(separador sin contenido)`; la pág 48 "¡gracias!" (cierre, sin mayúsculas) NO se toma como sección y se fusiona con APARADORES → bloque `p47-48`. Rangos de página todos correctos
  - **2 imperfecciones conocidas (no fallos de segmentación)**: en págs 24 y 44 el título del PDF se parte en 2 líneas en el origen, así que el encabezado crudo sale truncado ("SOFTLINE: FOCAL SHOW INFANTILES (1a y 2da", "DEPORTES - DEPORTES Y DEPORTIVO") y el resto ("ETAPA)", "NIÑO/NIÑA") cae al inicio del contenido. Bajo el umbral de 2-3 casos; se resuelve al normalizar el nombre de sección (siguiente sesión). langextract sigue SIN usarse
- **Motor 2 — setup validado** (`motor2/`, aislado; pipeline/ y core/ intactos):
  - Entorno virtual en `motor2/venv/` (git-ignored por la regla `venv/`), Python 3.13.3, con `pdfplumber 0.11.10` y `langextract 1.6.0` instalados — import limpio verificado, langextract NO se usó todavía (solo instalación)
  - `motor2/test_pdfplumber.py`: recorre TODAS las páginas del PDF (incluye separadores sin criterios) e imprime número de página real + primeros 100 caracteres. Acepta ruta por argumento; default: `Downloads\MECÁNICA MONTAJE GRAN BARATA PV 2026 .pdf` (48 páginas, confirmado por Gerardo como fuente)
  - **Criterio de éxito cumplido**: verificación visual de 4 páginas al azar (9, 22, 35, 43) renderizadas con pypdfium2 vs salida de pdfplumber — los números de página coinciden exactos con el slide real (pág 9 "PAUTA GENERAL" separador, pág 22 "FOCAL SHOW HOMBRES 1a y 2a ETAPA", pág 35 "DIVERSOS", pág 43 "DEPORTES – Zapatos Deportivos")
  - GEMINI_API_KEY confirmada presente en `.env` local (no se tocó)
  - Nota: el PDF vive en Downloads, NO en el repo (`.gitignore` no bloquea PDFs, pero es material de Liverpool — decidir si se versiona). El venv es local: en otra máquina se recrea con `python -m venv motor2/venv` + `pip install pdfplumber langextract`
- **UI → filtro de etapa activo en producción** (`d59b08e`, 3 líneas en `app.py`): `_config_pipeline(etapa_activa)` recibe el valor del selectbox "Etapa activa" y lo pone en `ConfigRetrieval.etapa_activa`. El filtro de Sesión C ya no está dormido
- **UI → filtro de etapa activo en producción** (`d59b08e`, 3 líneas en `app.py`): `_config_pipeline(etapa_activa)` recibe el valor del selectbox "Etapa activa" y lo pone en `ConfigRetrieval.etapa_activa`. El filtro de Sesión C ya no está dormido
  - **Probado en la UI real** (Streamlit + Playwright, no solo script): subir `simulation.jpeg`, E1 + focal_show, click Verificar → tabla/CSV con **116 criterios** (antes 123), los 7 de etapas 2/3 ausentes (`barras_segunda_tercera_etapa`, `columnas_segunda_etapa`, `columnas_tercera_etapa`, `agregar_puntos_verdes`, `focal_show_mujeres_etapa3`, `prohibicion_graficos_barata_etapa3`, `colocar_atriles_marca_etapa3`), los de E1 presentes, GRAVE global por `grafico_etapa_incorrecta`, delegados 83→76. CSV verificado contra los IDs (misma fuente que la tabla, por construcción)
- **Filtro por `etapa_aplicable` en `retrieval_engine.py`** (`22f28f0`) — único archivo de motor tocado, según límite de sesión:
  - Criterio cuyo `etapa_aplicable` excluye la etapa activa → **NO_APLICA**: `buscar_lote` lo omite del resultado, así que no llega a `confidence_engine`, no se delega al modelo y no aparece en `ResultadoFinal` (ni como NO_CALIFICA ni como CUMPLE fantasma). Cada omisión se loggea
  - `etapa_aplicable` null/[] o etapa activa desconocida/no normalizable → el criterio aplica (comportamiento histórico intacto; nunca se descarta en silencio por datos ambiguos). Normalización acepta "E1" (UI) y "1" (schema)
  - La etapa entra por parámetro `etapa_activa` de `buscar`/`buscar_lote` o por el campo nuevo `ConfigRetrieval.etapa_activa` (default None = sin filtro). También acepta `schema_version` 1.0 y 1.1 sin WARNING; `ResultadoRetrieval` ganó el flag `no_aplica`
  - **⚠️ El filtro aún NO se activa desde la UI**: `pipeline.py` no pasa `etapa_activa` a `buscar_lote` y `app.py` no llena `ConfigRetrieval.etapa_activa` — ambos archivos estaban fuera del límite de esta sesión. Falta 1 línea (en `app.py` `_config_pipeline()` o en `pipeline.py` PASO 2) que requiere autorización → Sesión D
  - **Validado E2E** (config con `etapa_activa="E1"`, `simulation.jpeg`, focal_show): 116 criterios (antes 123) — desaparecen exactamente los 7 de etapas 2/3, cero fugas como NO_CALIFICA, los de E1 permanecen, GRAVE global por `grafico_etapa_incorrecta` se mantiene; delegaciones al modelo 83→76. Retrocompatibilidad: sin etapa, 122/122 criterios del knowledge se comportan igual que antes; E2 omite 8, E3 omite 9 (conteos verificados contra el mapeo). Tests internos de `retrieval_engine.py` (`__main__`) ampliados con 3 casos de filtro por etapa
- **Schema v1.1 + capa2 con 101 criterios reales** (`be0baf1`):
  - `schema_conocimiento_v1.md` **creado** en la raíz (no existía como archivo — la regla fija #4 lo referenciaba pero estaba en "pendiente de diseño"). Documenta el schema v1.0 de facto (extraído de los JSONs reales y del contrato de `retrieval_engine.py`) y agrega 3 campos v1.1: `etapa_aplicable` (array o null), `condicion_libre` (texto libre), `referencia_no_resuelta` (bool). Cero cambios a campos existentes
  - `capa2_campana_activa.json` regenerado: los 5 criterios genéricos reemplazados por los **101 criterios reales de Gran Barata** (fuente: `Gran barata 101 criterios · JSON` en la raíz del repo, subido por Gerardo). Mapeo: 15 criterios con `etapa_aplicable`, 11 con `condicion_libre`, 2 con `referencia_no_resuelta: true` (manual de señalización Hardline y Book de impulsos). Generado por script con verificaciones (101 únicos, pesos válidos, guarda anti-condición-de-etapa sin mapear)
  - Se conservaron campos de proveniencia de la extracción en cada criterio (`pagina_origen`, `confianza_extraccion`, `referencia_cruzada`) — NO son parte del schema v1.1; los motores los ignoran. Decidir si se formalizan en el schema o se eliminan
  - **Validado sin tocar motores**: pipeline completo con `simulation.jpeg` + E1 + focal_show (config idéntica a app.py). Sin excepciones; `versiones_capas` reporta capa2 `1.1`; 123 criterios evaluados (40 por código, 83 delegados); veredicto global GRAVE por `grafico_etapa_incorrecta` (E1 vs foto Gran Barata), consistente con Sesión A
- **Fix .env + export CSV** (`e8c3051`, Sesión A, push verificado en origin/main):
  - `app.py` carga `.env` con `load_dotenv()` al inicio (antes de los imports del pipeline y de cualquier `os.environ.get`). Ya no se necesita `$env:GEMINI_API_KEY` manual en PowerShell. `python-dotenv` agregado a `requirements.txt`
  - Export CSV: **no existía función de export previa** (se auditó main y la rama remota) — se creó `_df_criterios()` como única fuente de filas para la tabla en pantalla Y el CSV (`st.download_button` con `on_click="ignore"`, sin rerun al descargar). Imposible desincronizarse por construcción
  - Probado end-to-end con `simulation.jpeg` (Downloads) + modelo real: 27 criterios, CSV == tabla 1:1 (comparación programática), `grafico_etapa_incorrecta` presente como GRAVE/MANDATORY (etapa activa E1 vs foto Gran Barata → veredicto global GRAVE, correcto)
- Pipeline determinista 4 módulos + 4 mejoras empresariales + `app.py` (histórico, ver commits)
- Fix Capa2 (`936b21f`, `3238769`) y detección de etapa por visión en PASO 0 (`f1a084f`)
- **Verificación visual real** (`2e2dff4`) — fix arquitectónico validado con `simulation.jpeg`:
  - `confidence_engine`: `delegar_si_mandatory=True` default. Juicio visual (planchado, tags, props, colorización, triangulación) siempre pasa por modelo con imagen. Guarda de regla fija #5: lo que `mandatory_engine` midió en píxeles nunca se delega
  - PASO 6 adjunta la imagen (base64) al modelo; timeout 90s con imagen; prompt instruye evaluar contra la foto
  - Normalización canónica nombre visible → ID de etapa ("Gran Barata" → `gran_barata_pv2026`) en PASO 0, sin tocar `mandatory_engine` ni el schema JSON
  - `_merge_veredictos`: delegado sin respuesta del modelo → NO_CALIFICA (nunca CUMPLE fantasma)
  - Backoff 30s para HTTP 429 (ventana free tier por minuto, límite 20 req/min con gemini-3.5-flash)
- **Test con foto real**: ya NO da 26/26 CUMPLE. El modelo detectó la etiqueta con 40% vs beneficio de etapa (50%/50+20%) y punto verde ausente en torres slim → OBSERVACION (3 criterios)
- GEMINI_API_KEY en `.env` local (git-ignored, jamás en historial ni logs). `GEMINI_MODEL = gemini-3.5-flash`
- 9 casos: unitarios 1-6 sin key (deterministas — delegados quedan NO_CALIFICA sin modelo, por diseño), integración 3/7/8/9 con modelo real
- **`props_decoracion` con ejemplos concretos** (`e07d1ed`) en `capa3_focal_show.json` — el modelo ahora marca la planta y la mochila sobre pedestales (OBSERVACION). Corrida con simulation.jpeg: 6 OBSERVACION (props, materiales ajenos, punto verde, beneficio, mezcla, gráficos)

🟡 Observaciones operativas:
- Quota free tier (20 req/min) se agota rápido — hay 3 GEMINI_API_KEY en `.env` local, pero las 3 líneas usan el mismo nombre: el loader solo lee la primera. Para rotación automática hay que renombrarlas (`GEMINI_API_KEY_2`...) y agregar lógica de rotación en 429 (no implementada — decidir si vale la pena)

🔴 Gaps conocidos (sin resolver):
- Faltan `capa3_tringla.json` y `capa3_mesa_show.json` en `pipeline/knowledge/`
- README desactualizado (dice v0.1)

⏳ Pendiente de diseño (decidido, sin implementar):
- Schema versionado de conocimiento v1.0
- Extractor híbrido de PDFs (código extrae texto/tablas, modelo solo interpreta zonas visuales)
- Cola de consenso `pendientes_revision.json`

## Próximos pasos (orden de prioridad)
1. **Motor 2 — siguiente sesión: escalar la extracción a los 47 bloques** (piloto validado en Sesiones H–I; los 2 bloqueadores —multicolumna y falso positivo de referencia— ya están resueltos en Sesión I). Pendientes antes/durante el escalado: (a) **conseguir cuota** — el free tier es 20 req/día por key y solo hay 1 key; 47 bloques necesitan plan de pago o varias keys con rotación; (b) revisar a ojo el orden de lectura de las 20 páginas multicolumna reportadas por `test_pdfplumber.py` antes de confiar en su extracción; (c) completar la corrida combinada de p43/p35 con cuota fresca (ya validadas por separado). `condicion_libre` y `referencia_no_resuelta` siguen siendo solo datos, sin lógica en el motor
2. Resolver las 2 referencias no resueltas de capa2 (`etiquetado_hogar_diversos` → manual señalización Hardline; `exhibicion_book_impulsos` → Book de impulsos) cuando Gerardo consiga esos documentos
3. Decidir si los campos de proveniencia (`pagina_origen`, `confianza_extraccion`, `referencia_cruzada`) se formalizan en el schema o se eliminan del JSON
4. Validar `app.py` en navegador (la lógica ya está probada end-to-end por script; falta el click manual en la UI)
5. Decidir: ¿rotación automática de API keys en 429? (hay 3 keys en `.env`, solo se usa la primera)
6. Agregar `capa3_tringla.json` y `capa3_mesa_show.json`
7. Actualizar README a estado real
8. Implementar extractor híbrido de PDFs

---

## Protocolo de cierre de sesión
Usar `/cerrar-sesion` al final de cada sesión de trabajo. El comando:
1. Verifica estado real del repo remoto (no confía en el reporte de la sesión)
2. Actualiza esta sección "Estado actual"
3. Hace commit de este CLAUDE.md
4. Entrega resumen de 3-5 líneas

## Estructura del proyecto
```
veristack/
├── CLAUDE.md               ← este archivo (fuente de verdad)
├── AGENTS.md               → symlink a CLAUDE.md (para OpenCode)
├── app.py                  ← UI Streamlit
├── requirements.txt
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
│   ├── venv/               ← git-ignored (pdfplumber + langextract)
│   ├── test_pdfplumber.py  ← validación de setup (Sesión E)
│   ├── segmenter.py        ← segmentador de secciones por heurística (Sesión F)
│   ├── normalizer.py       ← mapea encabezado crudo → seccion_aplicable (Sesión G)
│   └── extractor.py        ← langextract: criterios+peso+severidad por bloque (Sesión H, piloto)
├── core/
│   └── photo_analyzer.py
├── brains/
└── prompts/
```
