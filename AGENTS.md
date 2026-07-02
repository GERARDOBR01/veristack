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

## Estado actual (2 Jul 2026 — sesión tarde)

✅ Completado y en repo remoto (verificado con `git log origin/main`):
- Pipeline determinista 4 módulos (`mandatory_engine`, `retrieval_engine`, `confidence_engine`, `pipeline`)
- 4 mejoras empresariales: logging estructurado, versionado de capas, retry/backoff Gemini, contrato de salida versionado
- `app.py` (UI Streamlit) — commit `b0eb129`
- Fix Capa2 (`936b21f`, `3238769`): sin `etapa_activa`, Capa2 se excluye del lote; NO_CALIFICA de mandatory solo se excluye del veredicto global cuando etapa es None (Caso 5 y 6 correctos)
- **Detección de etapa por visión** (`f1a084f`): `_detectar_grafico_etapa()` en PASO 0 manda la imagen a Gemini y llena `grafico_detectado`; el código sigue decidiendo GRAVE/CUMPLE. Fallback verificado por 3 vías: sin key, key inválida (400) y quota (429) → NO_CALIFICA sin crash
- **GEMINI_API_KEY real conectada** (`.env` local, git-ignored, nunca en historial) — primer test end-to-end con modelo real: PASO 0 y PASO 6 responden
- `GEMINI_MODEL = gemini-3.5-flash` (1.5-pro retirado de la API con 404; 2.5-pro da 429 en el plan actual; 3.5-flash definido por Gerardo)
- 8 casos de prueba: unitarios 1-6 corren sin key (deterministas), integración con modelo real (Caso 3, 7, 8)
- `CLAUDE.md`, `AGENTS.md`, `.claude/commands/cerrar-sesion.md`

🟡 Verificado solo con imagen sintética:
- Caso 7 (visión detecta gráfico incorrecto → GRAVE) usa imagen generada con texto "primavera_2024" — no hay foto real de focal en el filesystem. Colocar foto real y correr con `VERISTACK_IMG_TEST=<ruta>` para validación definitiva

🔴 Gaps conocidos (sin resolver):
- Faltan `capa3_tringla.json` y `capa3_mesa_show.json` en `pipeline/knowledge/`
- README desactualizado (dice v0.1)

⏳ Pendiente de diseño (decidido, sin implementar):
- Schema versionado de conocimiento v1.0
- Extractor híbrido de PDFs (código extrae texto/tablas, modelo solo interpreta zonas visuales)
- Cola de consenso `pendientes_revision.json`

## Próximos pasos (orden de prioridad)
1. Validar Caso 7 con foto real de piso (`VERISTACK_IMG_TEST=<ruta a la foto>`)
2. Agregar `capa3_tringla.json` y `capa3_mesa_show.json`
3. Probar `app.py` end-to-end con la key real (UI + visión + modelo)
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
