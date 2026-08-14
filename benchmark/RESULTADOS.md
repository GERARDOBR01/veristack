# Resultados del benchmark

Regenerado el 2026-08-13 con `python benchmark/correr.py --escribir`.

Mide **las reglas que decide el código**, de punta a punta sobre el pipeline completo,
contra un ground truth **100 % sintético**: 12 imágenes construidas por código con
un defecto inyectado a propósito, así que se sabe con certeza qué lleva cada una. Los
criterios delegados al modelo quedan fuera — dependen de un proveedor externo y no serían
reproducibles.

**11/12 casos correctos.**

## Matriz de confusión por regla

| Regla | TP | FP | FN | TN | Precisión | Recall |
|---|---:|---:|---:|---:|---:|---:|
| `espacio_vacio_elevado` | 1 | 3 | 0 | 8 | 25 % | 100 % |
| `imagen_borrosa` | 3 | 0 | 0 | 9 | 100 % | 100 % |
| `imagen_oscura` | 4 | 1 | 0 | 7 | 80 % | 100 % |

## Caso por caso

| Caso | Global esperado | Global obtenido | Regla esperada | Reglas que dispararon | |
|---|---|---|---|---|:-:|
| `ok_montaje_completo` | NO_GRAVE | OBSERVACION | — | `espacio_vacio_elevado` | ✅ |
| `ok_tres_pilas` | NO_GRAVE | OBSERVACION | — | `espacio_vacio_elevado` | ✅ |
| `ok_sin_grafico` | NO_GRAVE | OBSERVACION | — | `espacio_vacio_elevado` | ✅ |
| `oscura_sin_luz` | GRAVE | GRAVE | imagen_oscura | `imagen_oscura` | ✅ |
| `oscura_penumbra` | GRAVE | GRAVE | imagen_oscura | `imagen_oscura` | ✅ |
| `oscura_limite` | GRAVE | GRAVE | imagen_oscura | `imagen_oscura` | ✅ |
| `luz_baja_aceptable` | NO_GRAVE | GRAVE | — | `imagen_oscura` | ❌ |
| `borrosa_movida` | GRAVE | GRAVE | imagen_borrosa | `imagen_borrosa` | ✅ |
| `borrosa_fuera_de_foco` | GRAVE | GRAVE | imagen_borrosa | `imagen_borrosa` | ✅ |
| `borrosa_leve` | GRAVE | GRAVE | imagen_borrosa | `imagen_borrosa` | ✅ |
| `vacio_mueble_pelon` | OBSERVACION | OBSERVACION | espacio_vacio_elevado | `espacio_vacio_elevado` | ✅ |
| `combinada_oscura_borrosa` | GRAVE | GRAVE | imagen_oscura | `imagen_oscura` | ✅ |

## Dónde falla

| Caso | Esperado | Obtenido |
|---|---|---|
| `luz_baja_aceptable` | NO_GRAVE + `—` | **GRAVE** + imagen_oscura |

## Hallazgos del propio benchmark

Construir esta medición encontró algo que el uso normal no muestra:

- **El umbral de brillo declarado no corresponde a la luminancia media.** Una imagen con
  media de luminancia 57 —bastante por encima del mínimo declarado de 40— sigue disparando
  `imagen_oscura` (caso `luz_baja_aceptable`). El motor mide algo distinto del promedio, y
  el mensaje al usuario dice `brillo=N (mínimo aceptable: 40)` como si fueran la misma
  escala. En producción esto se ve como *«me está rechazando fotos que se ven bien»*.
  Hay que decidir cuál es la medida correcta y que el mensaje diga esa.
- **Cuando el pipeline se detiene por un GRAVE, `ResultadoFinal.criterios` viene vacío.**
  El nombre de la regla que bloqueó solo existe dentro de `resumen_ejecutivo`, en prosa.
  Un consumidor del resultado no debería tener que parsear texto para saber qué regla lo
  frenó — contradice la promesa de trazabilidad estructurada del sistema. Está pendiente
  de arreglo; mientras tanto, este benchmark mira los dos lados.

## Cómo leerlo

- **TP** — había defecto y lo detectó. **FN** — había defecto y lo dejó pasar.
- **FP** — no había defecto y lo marcó. **TN** — no había y no marcó.
- Un `FN` en una regla GRAVE es el error caro: una exhibición mal montada que el sistema
  aprueba. Un `FP` cuesta una revisión humana de más — molesto, no grave.

*Este archivo se regenera; no se edita a mano.*
