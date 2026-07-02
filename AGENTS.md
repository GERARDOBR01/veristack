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

## Estado actual (2 Jul 2026 — sesión noche)

✅ Completado y en repo remoto (verificado con `git log origin/main`, working tree limpio):
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

🟡 Observaciones de la última corrida:
- El modelo NO marcó los props fuera de spec (mochila, espejo, planta) en `props_decoracion` — detectó el tag y el punto verde, pero props quedó CUMPLE. Puede requerir evidencia más explícita en `capa3_focal_show.json` o prompt más agudo. Validar con Gerardo si es aceptable
- Quota free tier (20 req/min) se agota rápido en corridas de suite completa — espaciar corridas o subir de plan

🔴 Gaps conocidos (sin resolver):
- Faltan `capa3_tringla.json` y `capa3_mesa_show.json` en `pipeline/knowledge/`
- README desactualizado (dice v0.1)

⏳ Pendiente de diseño (decidido, sin implementar):
- Schema versionado de conocimiento v1.0
- Extractor híbrido de PDFs (código extrae texto/tablas, modelo solo interpreta zonas visuales)
- Cola de consenso `pendientes_revision.json`

## Próximos pasos (orden de prioridad)
1. Decidir con Gerardo: ¿props_decoracion necesita evidencia más rica en capa3 para que el modelo los marque?
2. Probar `app.py` end-to-end con la key real (UI + visión + modelo)
3. Agregar `capa3_tringla.json` y `capa3_mesa_show.json`
4. Actualizar README a estado real
5. Implementar extractor híbrido de PDFs

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
├── core/
│   └── photo_analyzer.py
├── brains/
└── prompts/
```
