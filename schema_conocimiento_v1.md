# Schema de conocimiento — v1.1

> Fuente de verdad del formato de los JSONs de `pipeline/knowledge/`.
> Regla fija #4 de CLAUDE.md: ningún JSON de conocimiento cambia de formato sin aprobación explícita de Gerardo.
>
> **Nota de origen (2 Jul 2026, Sesión B):** este documento no existía como archivo antes de v1.1
> (figuraba como "pendiente de diseño" en CLAUDE.md). La sección v1.0 documenta el schema *de facto*
> ya vigente en los JSONs reales y en el contrato de lectura de `retrieval_engine.py` — no se inventó
> ni se modificó ningún campo existente. Lo nuevo en v1.1 son únicamente los 3 campos marcados.

## Estructura de archivo (por capa)

```json
{
  "version": "1.0",
  "criterios": [ ... ],
  "schema_version": "1.1",
  "fecha_actualizacion": "YYYY-MM-DD",
  "hash_contenido": "md5 del contenido"
}
```

Metadatos adicionales según la capa:

| Campo | Capa | Tipo | Descripción |
|---|---|---|---|
| `descripcion` | Capa1 | string | Descripción de la capa de básicos permanentes |
| `etapa` | Capa2 | string | ID canónico de la campaña activa (ej. `gran_barata_pv2026`) |
| `vigencia_inicio` / `vigencia_fin` | Capa2 | string `YYYY-MM-DD` | Ventana de vigencia de la campaña |
| `tipo_foto` | Capa3 | string | Tipo de foto al que aplica la capa (ej. `focal_show`) |

## Spec de criterio

Campos existentes desde v1.0 (sin cambios):

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | string | Identificador único del criterio, snake_case |
| `aliases` | array de strings | Sinónimos/formas coloquiales para retrieval por keyword |
| `texto` | string | Texto del criterio, fiel al manual oficial |
| `peso` | string | `MANDATORY` \| `RECOMMENDATION` \| `EXCEPTION` |
| `aplica_a` | array de strings \| null | Tipos de foto donde aplica (ej. `["focal_show"]`); `null` = aplica a todos |

Campos nuevos en **v1.1**:

| Campo | Tipo | Descripción |
|---|---|---|
| `etapa_aplicable` | array de strings \| null | Etapas de la campaña donde aplica el criterio (ej. `["1"]`, `["2","3"]`). `null` = aplica a todas las etapas |
| `condicion_libre` | string \| null | Texto libre — fallback para cualquier condición del manual que no sea de etapa (horarios, tipos de mercancía, zonas, etc.) |
| `referencia_no_resuelta` | bool | `true` si el criterio remite a otro documento o sección que no se resolvió automáticamente (ej. manual Hardline, Book de impulsos). Requiere resolución manual posterior |

### Ejemplo v1.1

```json
{
  "id": "beneficio_segunda_etapa",
  "aliases": ["descuento etapa 2", "rebaja adicional"],
  "texto": "En 2a etapa el beneficio es 50% + 20% adicional.",
  "peso": "MANDATORY",
  "aplica_a": null,
  "etapa_aplicable": ["2"],
  "condicion_libre": null,
  "referencia_no_resuelta": false
}
```

## Compatibilidad

- Los 3 campos v1.1 son **aditivos y opcionales**: un JSON v1.0 sin ellos sigue siendo válido.
- Los motores (`retrieval_engine.py`, etc.) leen con `.get()` e ignoran campos desconocidos; en v1.1 los campos nuevos **aún no se usan para filtrar** — el filtrado por `etapa_aplicable` es alcance de la Sesión C.

## Historial

| Versión | Fecha | Cambio |
|---|---|---|
| 1.0 | 2026-06-28 | Schema de facto: `id`, `aliases`, `texto`, `peso`, `aplica_a` + metadatos de archivo |
| 1.1 | 2026-07-02 | Se agregan `etapa_aplicable`, `condicion_libre`, `referencia_no_resuelta` |
