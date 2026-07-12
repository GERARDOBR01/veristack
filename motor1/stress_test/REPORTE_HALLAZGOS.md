# Stress test exploratorio Motor 1 — 5 fotos adversariales (11 Jul 2026)

> NO es el benchmark oficial. Sin ground truth. Objetivo: encontrar comportamiento
> raro/silencioso con fotos reales de OTRA campaña (no Gran Barata).
> Fotos: SF01/SF02 (Haus vajilla), SF03 (Softline niños, cartulina 30%),
> SF04 (Hogar muebles), SF05 (Haus sala exterior). Artefactos: `resultados/corrida_{A,B,C,D}.json`
> (ResultadoFinal COMPLETO por foto) + `stress_test_run.log`.

## Advertencia de validez — la cuota murió a media corrida A

El pre-flight de cuota PASÓ al inicio, pero las 3 GEMINI_API_KEY entraron en 429
(cuota diaria) durante la corrida A (~50-60 requests). **Datos con modelo real:
solo SF01, SF03 y SF04 de la corrida A** (SF02/SF05 parcialmente degradadas).
**Las corridas B, C y D corrieron degradadas por 429 → NO probaron lo que debían
probar.** Re-correrlas con cuota fresca cuesta ~50 requests (B=15, C=22, D=11).

## Resultados por corrida

### Corrida A — etapa_activa=E1 forzada, fotos de otra campaña (LA CORRIDA CON SEÑAL)

| Foto | t (s) | Global | Veredictos | ¿grafico_etapa_incorrecta? |
|------|-------|--------|-----------|---------------------------|
| SF01 (sala Haus) | 247 | **GRAVE** | 6 GRAVE / 10 CUMPLE / 121 NC | **NO — ausente** |
| SF02 (vajilla) | 212 | NO_CALIFICA | 15 CUMPLE / 122 NC (cuota parcial) | NO — ausente |
| SF03 (niños 30%) | 250 | **GRAVE** | 3 GRAVE / 13 OBS / 50 CUMPLE / 71 NC | **NO — ausente** |
| SF04 (muebles) | 258 | **GRAVE** | 4 GRAVE / 1 OBS / 20 CUMPLE / 112 NC | **NO — ausente** |
| SF05 (sala ext.) | 191 | NO_CALIFICA | 18 CUMPLE / 119 NC (cuota parcial) | NO — ausente |

Todas: 137 criterios (capa1=7, capa2=100, capa3=30), `criterios_decididos_por_codigo=0`,
137 delegados. Cero excepciones/crashes en las 13 ejecuciones del día.

### Corrida B — etapa=None: estructuralmente sensato, veredictos inválidos por cuota
Sin etapa la capa2 NO se carga → 21 criterios (capa1+capa3), como diseñado: la
caída 137→21 es el comportamiento correcto de "sin etapa no se evalúa campaña".
Pero los veredictos (todo NO_CALIFICA) son basura de 429 — comparación A vs B
de veredictos NO concluyente.

### Corrida C — determinismo (SF03 ×2, misma config): NO CONCLUYENTE
Ambas corridas salieron 137/137 NO_CALIFICA por 429. Lo único observable: la
degradación por cuota es determinista y el shape del JSON es idéntico. El
determinismo real del modelo queda SIN probar.

### Corrida D — tipo_foto=focal_show forzado sobre sala de muebles: NO CONCLUYENTE
No crasheó: cargó capa3_focal_show (137 criterios) y corrió. Pero los veredictos
son basura de 429 — no se puede ver si el modelo degrada con sentido.

## HALLAZGOS

### 🔴 H1 — El mismatch de campaña es ESTRUCTURALMENTE INDETECTABLE con etapa "E1"
Lo esperado por el brief ("el sistema debe reconocer el mismatch") NO ocurre, y
no es el modelo: es diseño. `_regla_grafico_etapa` (mandatory_engine.py:270)
con `etapa_activa="E1"` (etiqueta, no ID de campaña) devuelve
`grafico_etapa_no_verificable`/`grafico_no_detectado` = **NO_CALIFICA**, y
`_criterios_mandatory_solo_codigo` (pipeline.py:165) **solo expone al resultado
final los mandatory GRAVE** → el "no pude verificar la campaña" desaparece del
JSON final sin dejar rastro visible. Consecuencia: la UI actual (que manda
"E1"/"E2"/"E3") NUNCA puede disparar `grafico_etapa_incorrecta`; solo funcionaría
pasando el ID de campaña ("gran_barata_pv2026"). Es la secuela conocida del fix
del 7 Jul (0/5 precisión), pero el stress test muestra el costo real: el guard
anti-campaña-equivocada está apagado en el flujo real de la UI, en silencio.

### 🔴 H2 — Con el guard apagado, el sistema evalúa EN FALSO los criterios de Gran Barata
SF01 (sala Haus, cero relación con Gran Barata) salió **GRAVE global** con 6
GRAVEs de capa2 tipo `colocar_cartulinas`, `coloca_material_grafico_forma_alternada`
— el modelo penaliza la AUSENCIA de material de Gran Barata en una foto donde
Gran Barata no aplica. SF04 (muebles): GRAVE por `columnas_etapa1_40_60`
("no se observa la presencia de columnas"). Es exactamente el "evaluar en falso"
que el brief temía: para un usuario que dejó el dropdown en Gran Barata, una
foto perfecta de otra campaña sale reprobada con GRAVEs concretos y creíbles.

### 🔴 H3 — Criterios de etapa 2/3 con `etapa_aplicable=null`: el filtro de código no los ve y los decide el MODELO
`barras_etapa2_100`, `barras_etapa3_100`, `columnas_etapa2_100`,
`columnas_etapa3_parches_20` (p6) tienen `etapa_aplicable=null` en la capa2
activa (126/148 son null; solo 22 tienen etapa). Bajo E1 el filtro determinista
no los omite → se delegan y el MODELO razona "la campaña activa es E1, no
aplica" → NO_CALIFICA. Funcionó "bien" por suerte, pero viola "código decide,
modelo interpreta": la aplicabilidad de etapa la está decidiendo el modelo en
texto libre. Peor: en SF03 el modelo usó el mismo razonamiento al revés y marcó
**GRAVE `columnas_etapa1_40_60`** porque "el gráfico muestra 30%... no se alinea
con la Etapa 1" — inventó una regla de dosificación por etapa. Origen: la
extracción de Sesión O solo detectó etapas por encabezado de bloque (p7, p20-25);
los textos de p6 ("2da etapa 100%...") quedaron sin tag.

### 🟡 H4 — Inconsistencia del modelo ante la misma situación
La misma ausencia de material gráfico en fotos equivalentes salió GRAVE en SF01
(`coloca_material_grafico_forma_alternada`: "No se visualiza ningún tipo de
material gráfico") y NO_CALIFICA en SF02/SF05 ("no hay material que evaluar").
Sin determinismo probado (corrida C caída), pero la variación criterio-a-criterio
dentro de la misma corrida ya muestra que la frontera GRAVE-por-ausencia vs
NO_CALIFICA-por-ausencia la traza el modelo, no una regla.

### 🟡 H5 — El pre-flight de cuota protege el ARRANQUE, no la corrida
Pasó el pre-flight y aun así 10 de 13 ejecuciones salieron degradadas por 429.
El pipeline degrada por lote (correcto, visible en logs), pero el registro por
foto no marca "degradado por cuota" — en el JSON una foto asfixiada por 429 es
indistinguible de una foto genuinamente NO_CALIFICA salvo por `tokens_modelo_usados`
(0 o bajo). Para el benchmark oficial de 25: un corte de cuota a media corrida
produciría fotos-basura contadas como FALSO_NEGATIVO. Mitigación barata: abortar
(o marcar la foto) cuando PASO_4 termina con 0 lotes exitosos.

### 🟢 Lo que se comportó bien
- **Cero crashes** en 13 ejecuciones, incluidas config adversariales (tipo_foto
  falso, etapa None, cuota agotada, 503 intermitente). Nunca lanzó excepción.
- **Sin CUMPLE fantasma**: los lotes sin respuesta degradan a NO_CALIFICA y el
  global queda NO_CALIFICA (SF02/SF05/B/C/D) — nunca aprueba por falta de datos.
- **Etapa None → capa2 fuera** (137→21 criterios): la semántica es coherente.
- **Rotación de keys + batching**: rotó 1→2→3 correctamente; lotes fallidos
  aislados sin contaminar a los demás; logging visible funcionó (los 429 se VEN).
- El modelo, cuando respondió, distinguió bien el CONTENIDO de la foto (SF03:
  "exhibición de moda infantil, no de caballeros/damas"; SF02: "montaje de mesa
  HAUS, no focal de moda") — el problema no es visión, es qué se le pregunta.

## Nota del runner (no del pipeline)
El primer intento crasheó por encoding de consola Windows (cp1252 vs "──" en un
print). Se corre con `PYTHONIOENCODING=utf-8`. Costó 1 request de pre-flight.

## Pendiente si se quiere cerrar el experimento
Re-correr B, C y D con cuota fresca (~50 requests) para tener la comparación
E1-vs-None con veredictos reales, el diff de determinismo y la degradación de
tipo_foto forzado. La corrida A no necesita repetirse: su señal (H1/H2/H3) es
de diseño, no de muestreo.
