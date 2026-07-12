# EXPECTATIVAS — Stress test de código (sin modelo), Motor 1

> Escrito ANTES de ejecutar `correr_stress_codigo.py`, para no reinterpretar
> resultados después. Fecha: 12 Jul 2026. Contraparte sin-modelo del stress
> test con IA del 11 Jul (`motor1/stress_test/REPORTE_HALLAZGOS.md`, H1–H5).
> Cero llamadas de red: guard-rail global sobre `urllib.request.urlopen` +
> `GEMINI_API_KEY` removida del entorno del proceso.

Anclas de código (verificadas por lectura antes de correr):

- `mandatory_engine.py:122` — `if brillo < config.brillo_minimo` con `brillo_minimo=40.0` (línea 72). Estricto `<`.
- `mandatory_engine.py:121` — `brillo` ausente/None → default **100.0** (no dispara).
- `core/photo_analyzer.py:17` — `BRIGHTNESS_MIN = 30` (umbral PROPIO, distinto del de mandatory).
- `core/photo_analyzer.py:220-237` — fallo de carga → `facts["error"]`, `brightness=0.0`, `quality="mala"`. No lanza.
- `pipeline.py:209-221` — `_preparar_metadata`: si `photo_analyzer` lanza → `except Exception: pass` → defaults `brillo=100.0, nitidez=100.0` (foto "perfecta").
- `pipeline.py:135` — `if etapa_activa and etapa_activa.strip()` — un no-string con truthiness (int) llama `.strip()` → AttributeError.
- `retrieval_engine.py:186-213` — `_cargar_capa_full`: JSON corrupto/no-dict → `logger.warning` + `([], {})`. Nunca lanza.
- `pipeline.py:106-115` — `_leer_capa` (usada por `_extraer_criterios_del_knowledge`): `except Exception: return []` — ni siquiera warning.
- `pipeline.py:499-574` — `_post_gemini`: 401/403/429/RESOURCE_EXHAUSTED rota clave; agotados los intentos → `logging.ERROR` + `return None`. Nunca lanza.
- `pipeline.py:1208-1224` — mandatory bloqueante → retorna GRAVE con `criterios=[]`.
- `mandatory_engine.py:300-326` — `tipo_foto` None → NO_CALIFICA; no reconocido → OBSERVACION (no bloquea).

## Tabla de expectativas por caso

| # | Caso | Expectativa exacta (antes de correr) |
|---|------|--------------------------------------|
| B1 | Fixture brillo **39.0** | `imagen_oscura` GRAVE, pipeline bloqueado (`puede_continuar=False`, `criterios=[]`). |
| B2 | Fixture brillo **39.9** | Igual que B1 — GRAVE (39.9 < 40.0). |
| B3 | Fixture brillo **40.0** | `imagen_oscura` NO dispara (40.0 no es < 40.0). El pipeline sigue a la regla 2 (`imagen_borrosa`) — si el fixture es nítido, continúa. |
| B4 | Fixture brillo **40.1** | Igual que B3 — pasa brillo. |
| B5 | Fixture brillo **41.0** | Igual que B3 — pasa brillo. |
| B6 | Doble umbral | Documentar: photo_analyzer marcaría `IMAGEN_MUY_OSCURA` solo <30 (sus flags NO llegan a mandatory por el mapeo de `_preparar_metadata`; mandatory decide con 40). Dos verdades sobre el mismo número — gap arquitectónico conocido, se confirma. |
| A1 | Ruta de imagen inexistente | photo_analyzer captura el error → `brightness=0.0` → `brillo=0.0` → **GRAVE `imagen_oscura`**. Diagnóstico EQUIVOCADO: el sistema dice "foto oscura", la verdad es "archivo no existe". No crashea. Gap de diagnóstico. |
| A2 | Archivo 0 bytes `.webp` | Igual que A1 — PIL lanza al abrir, capturado → brillo 0.0 → GRAVE `imagen_oscura` con diagnóstico equivocado. |
| A3 | `.txt` renombrado `.webp` | Igual que A1/A2 — `UnidentifiedImageError` capturado → GRAVE `imagen_oscura`. |
| A4 | JPEG truncado al 50% | `Image.open` es lazy; `.convert("RGB")` fuerza la decodificación → OSError "truncated" → capturado → brillo 0.0 → GRAVE `imagen_oscura`. Mismo diagnóstico equivocado. (Si PIL tolera el truncado y decodifica parcial, el brillo será el de la mitad decodificada — se documenta lo observado.) |
| A5 | Imagen gigante (16000×16000 = 256 MP) | PIL `DecompressionBombError` (límite ~178 MP) al abrir → capturado → brillo 0.0 → GRAVE `imagen_oscura`. No debe colgarse ni agotar memoria (el error salta ANTES de decodificar). Medir tiempo. |
| C1 | `etapa_activa="E99"` | No crashea. Mandatory: `grafico_no_detectado` NO_CALIFICA (sin modelo no hay gráfico). Retrieval: capa2 SÍ se carga (etapa definida); criterios con `etapa_aplicable` que excluye "99" se omiten; los null aplican. El sistema evalúa contra una etapa QUE NO EXISTE sin ninguna señal de alarma — versión config de H1/H2. |
| C2 | `etapa_activa=""` | `_extraer_criterios_del_knowledge` no carga capa2 (string vacío es falsy). Mandatory: `etapa_no_definida` NO_CALIFICA — que por H1 (`pipeline.py:154-176` solo expone GRAVEs extra) **desaparece del JSON final**. Confirmar la invisibilidad. |
| C3 | `etapa_activa=None` | Igual que C2. Además `_calcular_veredicto_global` excluye ese NO_CALIFICA a propósito cuando etapa es None (pipeline.py:258-260). |
| C4 | `etapa_activa=12345` (int) | **CRASH esperado**: `pipeline.py:135` hace `12345.strip()` → AttributeError sin capturar → `ejecutar()` lanza. Bug real (la capa de entrada no valida tipo). |
| K1 | Knowledge capa2 corrupto (sintaxis inválida) | NO aborta ni avisa en el resultado: `_leer_capa` y `_cargar_capa_full` degradan a `[]` → capa2 aporta 0 criterios. El veredicto se calcula sobre un knowledge amputado **en silencio** (solo un `logger.warning` que la UI no enseña). Candidato a CRÍTICO. Comparar nº de criterios vs corrida sana. |
| K2 | Knowledge capa2 vacío (`{"criterios": []}`) | 0 criterios de capa2, sin siquiera warning (es JSON válido). Gap conocido (Sesión R: "0 criterios en silencio"). Confirmar. |
| K3 | Las 3 capas corrutas a la vez | Pipeline corre igual: 0 criterios totales del knowledge → solo reglas mandatory. Si mandatory pasa, veredicto sobre 0 criterios — probablemente CUMPLE global con `criterios` casi vacíos. Si sale CUMPLE: **CRÍTICO** (aprobación con conocimiento nulo). |
| T1 | `tipo_foto="foto_rara_xyz"` | No crashea. Mandatory: OBSERVACION `tipo_foto_invalido` (no bloquea). Capa3 `capa3_foto_rara_xyz.json` no existe → `[]`. Sin CUMPLE fantasma en delegados (sin modelo → NO_CALIFICA). Veredicto esperado: OBSERVACION o NO_CALIFICA, nunca CUMPLE. |
| P0 | `photo_analyzer.extract_basic_facts` lanza RuntimeError | `pipeline.py:220-221` lo traga con `pass` → metadata queda en defaults `brillo=100/nitidez=100` → la foto rota pasa TODAS las reglas duras como si fuera perfecta. **CRÍTICO esperado** (fallo silencioso hacia el resultado optimista). El ResultadoFinal no llevará NINGUNA traza del fallo. |
| G1 | 3 keys inválidas (mock 429 RESOURCE_EXHAUSTED en urlopen) | `_post_gemini` rota FAKE1→FAKE2→FAKE3, agota `max(3, 3)=3` intentos, loggea ERROR, retorna None. No cuelga, no lanza. Todos los delegados → NO_CALIFICA. **En ResultadoFinal nada distingue "cuota agotada" de "NO_CALIFICA real"** (versión en-código de H3). Medir: nº de requests interceptados y sleep total solicitado (con 3 keys: 1s por rotación). |
| G2 | Guard anti-red | En TODOS los demás casos el contador de intentos de red debe terminar en **0** (la key se removió del entorno → `_cargar_claves_api()` retorna `[]` antes de tocar la red). Si algún caso registra un intento, es un hallazgo aparte. |

## Clasificación prevista

- **CRÍTICO (fallo silencioso)** si se confirma: P0 (foto rota → "perfecta"), K1/K3 (knowledge corrupto → evaluación amputada sin señal), y la invisibilidad del NO_CALIFICA en C2/C3 (ya conocida como H1, se re-confirma desde el borde de config).
- **Bug real**: C4 (crash por int).
- **Gap de diagnóstico** (no silencioso, pero miente sobre la causa): A1–A5 ("archivo roto" reportado como "imagen oscura").
- **Gap conocido**: K2, T1, G1 (H3 en código), B6 (doble umbral 30/40).

## Reglas de esta corrida

- Producción solo lectura. Knowledge corrupto = COPIAS en `fixtures/knowledge_roto/`, apuntadas vía `ConfigRetrieval` — los originales de `pipeline/knowledge/` no se tocan.
- `time.sleep` parcheado a un contador (no duerme): se reporta el sleep que el código HABRÍA pedido.
- Cada caso corre en try/except propio; una excepción se registra como observación (en C4 es el resultado esperado), nunca aborta la corrida completa.
