# CLAUDE.md — Veristack / El Verificador
> Fuente de verdad del estado del proyecto en este repo público.
> El historial de sesiones y el conocimiento real de clientes viven FUERA del repo (ver "Política de datos").

## Rol
Claude Code es el **ingeniero arquitecto y ejecutor** de Veristack. Cada entrega debe ser robusta, verificable y exacta. Si algo no está claro, pregunta o lo marca como pendiente — **nunca inventa ni asume "razonable"**.

## Reglas fijas — no negociables
1. **El conocimiento real de un cliente nunca entra a este repo** (ni working tree ni historial): manuales, criterios extraídos, evidencias, resultados de piso, nombres de tiendas o personal. Todo eso vive en la carpeta privada local de datos por cliente, fuera del árbol de git. En el repo solo existe knowledge **sintético de demo** (cliente ficticio Mercadep), claramente marcado como tal.
2. **"Hecho" significa que está en el repo remoto y corre**, no que terminó de programarlo en la sesión local. Toda entrega debe ser explícita sobre si ya hizo push o si Gerardo necesita descargarlo manualmente.
3. **Nunca pegar API keys** en código ni en chat. Solo `.env` local, nunca se commitea. `.env.example` documenta las variables.
4. Cualquier criterio o JSON de conocimiento debe seguir el **schema_conocimiento_v1.md** — no cambiar ese formato sin aprobación explícita de Gerardo.
5. `mandatory_engine.py` ejecuta reglas duras y bloquea — el modelo nunca puede sobreescribir un GRAVE que el código ya determinó.

## Decisión fundacional
**"Código decide, modelo interpreta."** El modelo (Gemini/GPT) nunca decide compliance. Solo contextualiza y redacta criterios que el código ya marcó como ambiguos (confianza MEDIO/BAJO).
Filosofía: **"Reloj suizo, no cohete espacial"** — robusto, seguro, confiable, duradero. Simplicidad antes que complejidad. Cero mediocridad.

## Política de datos
- Repo público = motor + demo sintética. Punto.
- El historial de sesiones de desarrollo (bitácora técnica completa) se archivó en privado el 2026-08-13, junto con todo el conocimiento real.
- El vault de Obsidian (`brain/01-Veristack/`) es la memoria de arquitectura y decisiones; este archivo solo gobierna el trabajo dentro del repo.

## Estado actual (13 Ago 2026 — repo público saneado)
- Historia reescrita: el conocimiento real del cliente piloto salió del repo y del historial; los 99 commits de ingeniería se conservan.
- `pipeline/knowledge/` ahora es la capa de demo sintética (Mercadep) con el mismo esquema 1.1.
- Pipeline: 4 módulos funcionando; gate de autotests como criterio de entrega.
- Pendientes técnicos y bitácora completa: en el archivo privado y el vault.

## Protocolo de cierre de sesión
Usar `/cerrar-sesion` al final de cada sesión de trabajo: verifica remoto, actualiza "Estado actual", commit de este archivo, resumen de 3-5 líneas. El detalle largo de sesión va al vault privado, no a este repo.

## Estructura del proyecto
```
veristack/
├── CLAUDE.md               ← este archivo
├── app.py                  ← UI Streamlit (1 foto o modo lote)
├── verificar_lote.py       ← CLI modo lote: carpeta → reporte HTML+Excel
├── lote/                   ← runner + reporte
├── requirements.txt
├── pipeline/
│   ├── pipeline.py         ← orquestador
│   ├── mandatory_engine.py ← reglas duras, sin modelo
│   ├── retrieval_engine.py ← evidencia del knowledge base
│   ├── confidence_engine.py← calibra confianza por criterio
│   └── knowledge/          ← capas 1/2/3 SINTÉTICAS (demo Mercadep)
├── motor1/                 ← arneses de benchmark y stress
├── motor2/                 ← extractor de manuales PDF → criterios
├── core/photo_analyzer.py
└── prompts/
```
