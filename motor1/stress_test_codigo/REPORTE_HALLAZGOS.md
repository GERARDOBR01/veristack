# REPORTE DE HALLAZGOS — Stress test de CÓDIGO (sin modelo), Motor 1

**Fecha:** 12 Jul 2026 · **Corrida:** `correr_stress_codigo.py` (21 casos, ~3s total)
**Contraparte de:** `motor1/stress_test/REPORTE_HALLAZGOS.md` (11 Jul, con modelo, H1–H5)
**Cero tokens gastados — verificado por construcción:** guard global sobre `urllib.request.urlopen` registró **0 intentos de red** en todos los casos salvo G1 (donde el guard mismo simuló los HTTP 429). `GEMINI_API_KEY` removida del entorno del proceso.
**Producción intacta:** knowledge corrupto = copias en `fixtures/knowledge_roto/`; `git status` no muestra ningún archivo de `pipeline/`, `core/` ni `knowledge/` modificado.
**Expectativas pre-registradas:** `EXPECTATIVAS.md` (escrito ANTES de correr). Datos crudos: `resultados/resultados.json`.

---

## 🔴 CRÍTICOS — fallos silenciosos (cero tolerancia)

### CR-1 · Excepción en photo_analyzer → la foto rota se evalúa como "perfecta", sin traza — **el peor resultado posible, CONFIRMADO**
- **Caso P0:** se forzó `photo_analyzer.extract_basic_facts` a lanzar `RuntimeError`.
- **Observado:** `pipeline._preparar_metadata` (líneas 220-221) traga la excepción con `except Exception: pass` → metadata cae a defaults `brillo=100.0, nitidez=100.0` → la foto pasa TODAS las reglas duras como si fuera perfecta y el pipeline evalúa los 137 criterios completos. **El `ResultadoFinal` no lleva NINGUNA traza del fallo** (verificado programáticamente: ni en resumen, ni en criterios, ni un warning propio — los únicos warnings son los normales de "sin key").
- **Impacto real:** con modelo activo, una foto cuyo pre-análisis reventó se evaluaría visualmente con metadata falsa "perfecta". Las reglas de brillo/nitidez/espacio quedan desactivadas de facto y nadie se entera.
- **Clasificación: CRÍTICO — bug real, arreglar ya.** El `except: pass` debe al menos marcar `analisis_fallido=True` en metadata y producir un NO_CALIFICA/OBSERVACION visible, nunca defaults optimistas.

### CR-2 · Knowledge JSON corrupto → capa amputada en silencio, el veredicto se emite igual — CONFIRMADO
- **Caso K1:** capa2 con sintaxis JSON inválida (copia corrupta de la real).
- **Observado:** el pipeline NO aborta ni degrada el veredicto: corre con **21 criterios en vez de 137** (capa2 completa desaparece) y emite `NO_CALIFICA` con la misma forma que una corrida sana. La única señal es un `logger.warning` de `retrieval_engine._cargar_capa_full` (193-195) — que en la UI real es invisible (`NullHandler`, mismo mecanismo que ocultó los 429 de la Sesión EE). Además `pipeline._leer_capa` (114-115) —la que decide QUÉ criterios existen— degrada a `[]` sin ni siquiera warning.
- **Caso K3 (las 3 capas corruptas):** el pipeline evalúa con **0 criterios** y emite `VEREDICTO GLOBAL: NO_CALIFICA | código=0 | modelo=0`. Matiz honesto: **NO dio CUMPLE fantasma** (la expectativa temía CUMPLE; el veredicto con 0 criterios resulta NO_CALIFICA) — pero sigue siendo una corrida "exitosa" sobre conocimiento nulo, sin abortar.
- **Clasificación: CRÍTICO — gap arquitectónico.** Es el mismo patrón del bug de rutas relativas del benchmark (Sesión R/CC: 0 criterios → todo NO_CALIFICA sin error visible), ahora demostrado desde el borde de archivo corrupto. El runner del benchmark ya tiene el guard ("aborta si el knowledge carga 0 criterios"); **producción (pipeline/app.py) no lo tiene**. Requiere decisión de diseño: ¿capa ilegible = abortar, o = NO_CALIFICA explícito "knowledge no disponible"?

### CR-3 · `etapa_no_definida` sigue desapareciendo del resultado (H1 re-confirmado desde el borde de config)
- **Casos C2 (`etapa_activa=""`) y C3 (`None`):** mandatory produce `etapa_no_definida` NO_CALIFICA, pero el resultado final trae 21 criterios y **cero mención** de etapa_no_definida (verificado: `menciona_etapa_no_definida=False`). `_criterios_mandatory_solo_codigo` (pipeline.py:154-176) solo expone GRAVEs, y `_calcular_veredicto_global` lo excluye a propósito cuando etapa es None.
- **Clasificación: CRÍTICO ya conocido (es H1)** — esta corrida demuestra que también aplica cuando la etapa falta por completo, no solo con "E1". Sin costo de modelo, reproducible en milisegundos.

---

## 🟠 Bug real — arreglar ya

### BR-1 · `etapa_activa` no-string tumba el pipeline entero (crash sin capturar)
- **Caso C4:** `ejecutar(imagen, etapa_activa=12345, ...)` → **`AttributeError: 'int' object has no attribute 'strip'`** en `pipeline.py:135` (`_extraer_criterios_del_knowledge`). No hay try/except global en `ejecutar()`: la excepción llega cruda al llamador (la UI Streamlit mostraría un traceback).
- Mandatory sí tolera el int (`_to_str` lo coerce); retrieval también (`_norm_etapa`). El único punto frágil es esa línea del pipeline. Fix de una línea: `str(etapa_activa)` o el mismo `_to_str` que ya usan los motores.
- **Clasificación: bug real.** Hoy la UI manda string del selectbox, pero cualquier integración futura (API, batch, CSV) puede mandar int/None y tumba el proceso.

---

## 🟡 Gap de diagnóstico (nuevo)

### GD-1 · Todo archivo roto se diagnostica como "imagen demasiado oscura"
- **Casos A1–A5** (ruta inexistente, 0 bytes, txt renombrado, JPEG truncado, bomba de 256 MP): en TODOS, photo_analyzer captura el error real (`facts["error"]` = "No such file", "cannot identify image file", "image file is truncated", "decompression bomb") y devuelve `brightness=0.0` → mandatory dispara **GRAVE `imagen_oscura`: "La imagen es demasiado oscura para evaluar"**.
- **Lo bueno:** ningún crash, ningún CUMPLE, el pipeline se detiene (bloqueante), la bomba de descompresión se rechaza en 8 ms sin decodificar (PIL protege memoria).
- **Lo malo:** el diagnóstico **miente sobre la causa**. Para el usuario de retail "tu foto está oscura, tómala con más luz" vs "el archivo está corrupto, re-súbelo" son acciones distintas. `photo_analyzer` YA SABE la causa (`facts["error"]`) pero `_preparar_metadata` la descarta (solo mapea brightness/sharpness/ratio).
- **Clasificación: gap arquitectónico nuevo (menor).** Fix natural: mapear `facts["error"]` a metadata y una regla mandatory `archivo_invalido` previa a `imagen_oscura`.

---

## 🟢 Confirmaciones (funciona como se diseñó)

### OK-1 · Frontera de brillo EXACTA — `< 40.0` estricto, sin off-by-one
Fixtures calibrados con la misma `_average_brightness` del motor (brillo medido exacto: 39.0 / 39.9 / 40.0 / 40.1 / 41.0):

| brillo | resultado |
|---|---|
| 39.0 | GRAVE `imagen_oscura`, pipeline bloqueado ✓ |
| 39.9 | GRAVE `imagen_oscura`, pipeline bloqueado ✓ |
| 40.0 | pasa (40.0 NO es < 40.0) ✓ |
| 40.1 | pasa ✓ |
| 41.0 | pasa ✓ |

Nota documental (ya conocido): `photo_analyzer.BRIGHTNESS_MIN=30` es un segundo umbral que NO gobierna el veredicto (sus flags no llegan a mandatory); la verdad operativa es el 40.0 de `ConfigEngine`. Dos umbrales para el mismo concepto = deuda de claridad, no bug.

### OK-2 · `tipo_foto` basura no rompe ni infla (caso T1)
`tipo_foto="foto_rara_xyz"` → OBSERVACION `tipo_foto_invalido` (veredicto global OBSERVACION), capa3 inexistente degrada a 122 criterios, **cero CUMPLE fantasma** (todos los delegados NO_CALIFICA sin modelo). Diseño respetado.

### OK-3 · Las 3 keys agotadas: no cuelga, no lanza, termina — pero es H3 en código (caso G1)
3 keys fake + HTTP 429 simulado en cada intento: `_post_gemini` rotó 1→2→3, agotó, `logging.ERROR`, retornó None; el pipeline terminó y degradó todo a NO_CALIFICA. **Nada en `ResultadoFinal` distingue "cuota agotada" de "NO_CALIFICA real"** (verificado: `cuota_distinguible_en_resultado=False`) — la versión determinista de H3.
Dato nuevo de eficiencia: sin circuit breaker, la corrida quemó **33 requests** (3 por PASO_0 + 3 × 10 lotes) y habría dormido **22 s** en sleeps de rotación, aun sabiendo desde el primer lote que las 3 keys estaban muertas. En una corrida real de 25 fotos eso es ~800 requests desperdiciados contra keys agotadas — coherente con lo vivido en la Sesión EE.

### OK-4 · Guard anti-red: 0 intentos de salida en 20 de 21 casos (el 21º fue el mock). Cero tokens, garantizado por código.

---

## Resumen de clasificación

| ID | Caso | Clasificación | Acción sugerida (NO aplicada — decisión de Gerardo) |
|----|------|---------------|------------------------------------------------------|
| CR-1 | P0 excepción photo_analyzer | **CRÍTICO / bug real** | quitar `except: pass` optimista; marcar fallo en metadata |
| CR-2 | K1/K3 knowledge corrupto | **CRÍTICO / gap arquitectónico** | guard de 0-criterios en producción (ya existe en el runner del benchmark) |
| CR-3 | C2/C3 etapa vacía/None | **CRÍTICO ya conocido (=H1)** | misma decisión pendiente de H1 |
| BR-1 | C4 etapa int | **bug real** | `_to_str` en `pipeline.py:135` |
| GD-1 | A1–A5 archivos rotos | **gap nuevo (diagnóstico falso)** | regla `archivo_invalido` antes de `imagen_oscura` |
| GC | K2 capa vacía, C1 E99 | gap conocido, confirmado | — |
| OK | B1–B5, T1, G1-terminación, A5-bomba | diseño confirmado | — |

**Balance honesto:** el motor NO se cae (0 crashes salvo el buscado C4) y nunca inventa CUMPLE — eso es real y es la mitad buena. La mitad mala es sistemática: **cuando algo falla, Motor 1 degrada siempre hacia el silencio** (foto rota → "perfecta", knowledge roto → corrida "normal" con menos criterios, cuota muerta → NO_CALIFICA anónimo, causa real del archivo → diagnóstico falso). Para ser "la herramienta" del retail, la regla que falta no es de robustez sino de honestidad interna: *todo fallo debe dejar traza en el resultado que ve el usuario.*

---

## ADDENDUM — Re-corrida post-fix (12 Jul, Sesión GG: photo_analyzer v2)

Tras el endurecimiento de contrato (photo_analyzer v2 + `_preparar_metadata` + reglas mandatory nuevas), los 21 casos se re-corrieron. Cambios verificados:

| ID | Antes | Después |
|----|-------|---------|
| CR-1 (P0) | foto "perfecta" brillo=100, sin traza | **GRAVE `archivo_invalido`**, `traza_del_fallo_en_resultado=True`, causa en log ERROR → **CERRADO** |
| GD-1 (A1–A5) | GRAVE `imagen_oscura` (diagnóstico falso) | **GRAVE `archivo_invalido`** con la causa real en evidencia/log (FileNotFound / UnidentifiedImage / truncated / DecompressionBomb) → **CERRADO** |
| BR-1 (C4) | AttributeError, pipeline muerto | coerción en la entrada de `ejecutar()`; corre y evalúa (etapa "12345" = no normalizable → no filtra) → **CERRADO** |
| B1–B5 | frontera exacta | intacta (39.9 GRAVE / 40.0 pasa) ✓ |
| C2/C3 (CR-3=H1), K1–K3 (CR-2), G1 (H3) | fallos silenciosos | **sin cambio — siguen ABIERTOS** (fuera del alcance de photo_analyzer v2) |

Hallazgo colateral de la re-corrida: la regla nueva `imagen_sobreexpuesta` (quemado_pct>50) bloqueó el fixture `base_valida` original (55% píxeles blancos PUROS = foto quemada de verdad) — la regla hizo su trabajo; el fixture se regeneró con grises realistas 40/210. Las 5 fotos reales del stress del 11 Jul pasan todas las reglas nuevas sin falsos positivos (quemado 0–0.1%, ver `motor1/calibracion_photo_v2/`).
