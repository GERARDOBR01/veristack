Ejecuta el protocolo de cierre de sesión para el proyecto veristack. Sigue estos pasos en orden — no asumas el estado, verifica cada punto contra el repo real.

## Paso 1 — Verifica estado real del repo remoto

Corre estos comandos (NO confíes en tu propio reporte de la sesión):
```
git -C C:\Users\jesus\veristack fetch origin
git -C C:\Users\jesus\veristack status
git -C C:\Users\jesus\veristack log --oneline -5
git -C C:\Users\jesus\veristack diff HEAD origin/main --stat
```

Reporta exactamente: ¿qué commits están locales pero no en remoto? ¿Hay archivos sin commitear?

## Paso 2 — Actualiza "Estado actual" en CLAUDE.md

Edita la sección `## Estado actual` de `C:\Users\jesus\veristack\CLAUDE.md` con la fecha de hoy:
- ✅ Mueve a Completado lo que hayas verificado que está en el repo remoto (no lo que crees que hiciste — lo que ESTÁ en remoto)
- 🔴 Marca lo que quedó pendiente o incompleto en esta sesión
- ⏳ Preserva pendientes de diseño que no se tocaron

Regla: si algo está solo local (no pusheado), va en 🔴 pendiente hasta que esté en remoto.

## Paso 3 — Sincroniza AGENTS.md y commitea

Primero copia CLAUDE.md a AGENTS.md (en Windows no hay symlinks sin admin — la copia es la sincronización para OpenCode):
```powershell
Copy-Item C:\Users\jesus\veristack\CLAUDE.md C:\Users\jesus\veristack\AGENTS.md -Force
```

Luego commitea ambos:
```
git -C C:\Users\jesus\veristack add CLAUDE.md AGENTS.md
git -C C:\Users\jesus\veristack commit -m "docs: cierre sesión FECHA — actualiza estado actual"
```

Si no hay cambios en CLAUDE.md, dilo explícitamente y salta este paso.

## Paso 4 — Entrega resumen de 3-5 líneas

Imprime un resumen conciso con exactamente esto:
1. ¿Qué se completó y verificó hoy (en remoto)?
2. ¿Qué quedó pendiente o solo local?
3. ¿Necesita Gerardo hacer algo antes de la próxima sesión? (push manual, descarga, validación en piso, etc.)
