# Resultados del benchmark

Regenerado el 2026-10-11 con `python benchmark/correr.py --escribir`.

Mide **las reglas que decide el código**, de punta a punta sobre el pipeline completo,
contra un ground truth **100 % sintético**: 12 imágenes construidas por código con
un defecto inyectado a propósito, así que se sabe con certeza qué lleva cada una. Los
criterios delegados al modelo quedan fuera — dependen de un proveedor externo y no serían
reproducibles.

**12/12 casos correctos.**

## Matriz de confusión por regla

| Regla | TP | FP | FN | TN | Precisión | Recall |
|---|---:|---:|---:|---:|---:|---:|
| `espacio_vacio_elevado` | 1 | 3 | 0 | 8 | 25 % | 100 % |
| `imagen_borrosa` | 3 | 0 | 0 | 9 | 100 % | 100 % |
| `imagen_oscura` | 5 | 0 | 0 | 7 | 100 % | 100 % |

## Caso por caso

| Caso | Global esperado | Global obtenido | Regla esperada | Reglas que dispararon | |
|---|---|---|---|---|:-:|
| `ok_montaje_completo` | NO_GRAVE | OBSERVACION | — | `espacio_vacio_elevado` | ✅ |
| `ok_tres_pilas` | NO_GRAVE | OBSERVACION | — | `espacio_vacio_elevado` | ✅ |
| `ok_sin_grafico` | NO_GRAVE | OBSERVACION | — | `espacio_vacio_elevado` | ✅ |
| `oscura_sin_luz` | GRAVE | GRAVE | imagen_oscura | `imagen_oscura` | ✅ |
| `oscura_penumbra` | GRAVE | GRAVE | imagen_oscura | `imagen_oscura` | ✅ |
| `oscura_limite` | GRAVE | GRAVE | imagen_oscura | `imagen_oscura` | ✅ |
| `oscura_intermedia` | GRAVE | GRAVE | imagen_oscura | `imagen_oscura` | ✅ |
| `borrosa_movida` | GRAVE | GRAVE | imagen_borrosa | `imagen_borrosa` | ✅ |
| `borrosa_fuera_de_foco` | GRAVE | GRAVE | imagen_borrosa | `imagen_borrosa` | ✅ |
| `borrosa_leve` | GRAVE | GRAVE | imagen_borrosa | `imagen_borrosa` | ✅ |
| `vacio_mueble_pelon` | OBSERVACION | OBSERVACION | espacio_vacio_elevado | `espacio_vacio_elevado` | ✅ |
| `combinada_oscura_borrosa` | GRAVE | GRAVE | imagen_oscura | `imagen_oscura` | ✅ |

## Dónde falla

Ningún caso del set actual falla. Eso **no** significa que el motor sea perfecto:
significa que este set todavía no encuentra su límite. La forma útil de usar esta
tabla es agregar casos hasta que algo se ponga en rojo.

## Hallazgos del propio benchmark

Construir esta medición encontró algo que el uso normal no muestra:

- **Corregida la expectativa del caso de luz baja, no el motor.** El brillo es la media
  de luminancia dividida entre 255 y multiplicada por 100. El informe anterior comparó
  una media de píxeles en escala 0-255 contra el umbral 40 en escala 0-100. La escena
  atenuada por 0.30 está por debajo del umbral: su GRAVE era correcto. Se conserva la
  misma imagen como `oscura_intermedia`, con la expectativa corregida; ningún umbral
  de producción cambió. El comando también comprueba la regla con grises 101, 102 y
  103: por debajo de 40 bloquea; exactamente en 40 y por encima no bloquea por brillo.
- **NO_GRAVE no equivale a ausencia de observaciones.** Los tres montajes normales
  siguen disparando `espacio_vacio_elevado`: son falsos positivos visibles en la matriz,
  aunque el veredicto global cumpla la expectativa de no bloquear. Un 12/12 global
  no significa precisión perfecta por regla ni mide la interpretación del modelo.
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
