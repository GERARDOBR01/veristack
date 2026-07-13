# Veristack — El Verificador

Motor de verificación fotográfica para retail (visual merchandising).
Reemplaza la revisión manual de fotos de exhibiciones: evalúa cada foto
contra el conocimiento extraído de los manuales del cliente y produce un
veredicto por criterio con trazabilidad completa.

**Decisión fundacional: "código decide, modelo interpreta".** El modelo
(Gemini) nunca decide compliance — solo contextualiza criterios que el
código ya marcó como ambiguos. Las reglas duras (`mandatory_engine`)
bloquean y el modelo no puede sobreescribirlas.

## Uso

```bash
pip install -r requirements.txt
# API key en .env (GEMINI_API_KEY=...) — nunca en código ni en la UI

# UI (1 foto o lote con multi-upload):
streamlit run app.py

# Lote por carpeta (reporte HTML visual + Excel de datos):
python verificar_lote.py <carpeta_fotos> --etapa <id_campaña> [--tipo auto]
```

Sin API key el sistema corre igual y lo dice: los criterios delegados al
modelo salen NO_CALIFICA y el resultado queda marcado como **EVALUACIÓN
PARCIAL** — un resultado incompleto nunca se presenta como completo.

## Arquitectura

- `pipeline/` — orquestador (PASO 0-8): metadata → mandatory (reglas duras)
  → retrieval (3 capas de conocimiento) → confianza → modelo por lotes con
  circuit breaker de cuota → merge → `ResultadoFinal` (schema salida 1.1).
- `core/photo_analyzer.py` — análisis objetivo de imagen (sin modelo).
- `lote/` — modo lote de producción: `procesar_lote()` + reporte HTML
  auto-contenido (miniaturas, GRAVES arriba) y Excel/CSV.
- `motor2/` — extractor de manuales PDF → criterios de conocimiento
  (aislado del pipeline).
- `motor1/` — benchmark contra revisión humana, suites de stress de código
  (offline, guard anti-red) y calibración.

## Capas de conocimiento (`pipeline/knowledge/`)

- Capa 1: básicos de presentación visual (permanente)
- Capa 2: mecánica de la campaña activa (caduca por temporada)
- Capa 3: criterios por tipo de foto (`capa3_focal_show.json`; tringla y
  mesa_show pendientes de sus manuales)

## Estado y fuente de verdad

El estado real del proyecto, el registro de bugs y los próximos pasos viven
en `CLAUDE.md` (sesión a sesión) y el historial en `HISTORIAL_SESIONES.md`.
Todos los motores pasan autotests offline obligatorios antes de cualquier
corrida real.
