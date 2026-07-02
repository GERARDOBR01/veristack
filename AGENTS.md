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

## Estado actual (2 Jul 2026)

✅ Completado y en repo remoto (verificado con `git diff HEAD origin/main`):
- Pipeline determinista 4 módulos (`mandatory_engine`, `retrieval_engine`, `confidence_engine`, `pipeline`)
- 4 mejoras empresariales: logging estructurado, versionado de capas, retry/backoff Gemini, contrato de salida versionado — verificadas con 7 casos de prueba reales
- `app.py` (UI Streamlit) — confirmado en remoto (commit `b0eb129`)
- Estructura `pipeline/` + `pipeline/knowledge/` correcta en remoto (resuelto en commits anteriores)

🟡 Completado local — pendiente push:
- Fix Capa2: cuando `etapa_activa` es None, los criterios de campaña se excluyen del lote; `_calcular_veredicto_global()` ya no propaga NO_CALIFICA de mandatory — Caso 6 confirmado: CUMPLE sin criterios de Capa2
- `CLAUDE.md` y `AGENTS.md` creados (fuente de verdad + espejo OpenCode)
- `.claude/commands/cerrar-sesion.md` — protocolo de cierre de sesión

🔴 Gaps conocidos (sin resolver):
- Faltan `capa3_tringla.json` y `capa3_mesa_show.json` en `pipeline/knowledge/`
- README desactualizado (dice v0.1)

⏳ Pendiente de diseño (decidido, sin implementar):
- Schema versionado de conocimiento v1.0
- Extractor híbrido de PDFs (código extrae texto/tablas, modelo solo interpreta zonas visuales)
- Cola de consenso `pendientes_revision.json`

## Próximos pasos (orden de prioridad)
1. Confirmar estructura real del repo remoto (git fetch + diff)
2. Reorganizar repo a estructura `pipeline/` + `pipeline/knowledge/` si sigue plano
3. Confirmar `app.py` en GitHub (no asumir)
4. Agregar `capa3_tringla.json` y `capa3_mesa_show.json`
5. Conectar GEMINI_API_KEY real, primer test end-to-end con modelo
6. Implementar extractor híbrido de PDFs

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
