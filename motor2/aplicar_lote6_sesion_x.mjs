// aplicar_lote6_sesion_x.mjs — Sesión X (bloque conversacional)
// Cierra el Lote 6 (p43/44, 15 criterios pendientes) según decisión de Gerardo:
//  - 7 criterios reales (p43 completo ×4 + 3 de p44) -> revisado_por_gerardo=true.
//  - 8 unidad_exhibicion_* (p44, bloque descriptivo de planograma salido de Vision)
//    NO son compliance evaluable -> se EXCLUYEN del JSON de criterios y se documentan
//    en motor2/referencia_no_evaluable.md (mismo tratamiento que p47, Sesión N).
//    Motivo (hallazgo 6 Jul 2026): valor real 60%+20% (zona azul) ausente en los 8
//    candidatos; mapeo de posición no confiable contra la imagen real del manual.
// NO toca peso/severidad/texto/id/aliases de los 7 aprobados ni de ningún otro criterio.
// Guards de conteo exacto — aborta sin escribir si algo no calza.

import fs from "node:fs";

const RUTA = "motor2/capa2_validado_con_candidatos.json";
const RUTA_REF = "motor2/referencia_no_evaluable.md";
const PAGINAS_LOTE6 = [43, 44];
const ESPERADO_PENDIENTES = 15;
const ESPERADO_EXCLUIR = 8;
const ESPERADO_APROBAR = 7;
const IDS_APROBAR = new Set([
  "exhibe_mesa_parte_visible_descuentos",
  "coloca_cartulina_descuento_agresivo_cuentes",
  "perimetro_coloca_parte_superior_descuentos",
  "mesa_lanzamientos_sigue_manejando_lanzamientos",
  "exhibe_siembra_espacio_visible_disciplina",
  "barra_ballet_exhibe_producto_sola",
  "exhibicion_ropa_deportiva_estanterias_maniquies",
]);

const data = JSON.parse(fs.readFileSync(RUTA, "utf8"));
const arr = data.criterios;
if (!Array.isArray(arr)) { console.error("ABORTA: no encuentro el array de criterios."); process.exit(1); }

const pendientes = arr.filter(c => PAGINAS_LOTE6.includes(c.pagina_origen) && c.revisado_por_gerardo !== true);
if (pendientes.length !== ESPERADO_PENDIENTES) {
  console.error(`ABORTA: esperaba ${ESPERADO_PENDIENTES} pendientes en p43/44, encontré ${pendientes.length}. No se escribe nada.`);
  process.exit(1);
}

const excluir = pendientes.filter(c => c.id.startsWith("unidad_exhibicion_"));
const aprobar = pendientes.filter(c => !c.id.startsWith("unidad_exhibicion_"));
if (excluir.length !== ESPERADO_EXCLUIR || !excluir.every(c => c.pagina_origen === 44)) {
  console.error(`ABORTA: esperaba ${ESPERADO_EXCLUIR} unidad_exhibicion_* en p44, encontré ${excluir.length}. No se escribe nada.`);
  process.exit(1);
}
if (aprobar.length !== ESPERADO_APROBAR || !aprobar.every(c => IDS_APROBAR.has(c.id))) {
  console.error(`ABORTA: los ${aprobar.length} a aprobar no calzan con la lista esperada de ${ESPERADO_APROBAR} ids. No se escribe nada.`);
  process.exit(1);
}

const ts = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 15).replace(/(\d{8})(\d+)/, "$1-$2");
fs.copyFileSync(RUTA, `${RUTA}.bak-${ts}`);

for (const c of aprobar) c.revisado_por_gerardo = true;
const idsExcluir = new Set(excluir.map(c => c.id));
data.criterios = arr.filter(c => !(c.pagina_origen === 44 && idsExcluir.has(c.id)));
if (data.criterios.length !== arr.length - ESPERADO_EXCLUIR) {
  console.error("ABORTA: el filtrado de exclusión no removió exactamente 8. No se escribe nada.");
  process.exit(1);
}

data.meta.lote6_sesion_x = new Date().toISOString().slice(0, 19);
data.meta.lote6_sesion_x_nota = "Gerardo cerró el Lote 6 (p43/44): 7 criterios reales revisado_por_gerardo=true. Los 8 unidad_exhibicion_* de p44 (bloque descriptivo de planograma, vision_fallback) se EXCLUYERON como compliance no evaluable — hallazgo 6 Jul 2026: valor 60%+20% (zona azul) ausente en la extracción, mapeo de posición no confiable contra la imagen real; mismo tratamiento que p47 (Sesión N). Documentados en motor2/referencia_no_evaluable.md. Total pasa de 156 a 148 criterios evaluables, todos revisado_por_gerardo=true.";

const filasMd = excluir.map(c =>
  `### \`${c.id}\` (p${c.pagina_origen})\n\n` +
  "```json\n" + JSON.stringify(c, null, 2) + "\n```\n"
).join("\n");

const md = `# Referencia NO evaluable — bloque de planograma p44 (Deportes)

> **Excluido de compliance — hallazgo 6 Jul 2026**: verificación cruzada de Gerardo contra la
> imagen real del manual encontró un valor real (**60%+20%, zona azul**) ausente en los 8
> candidatos, y el mapeo de posición (superior/media/inferior × izquierda/centro/derecha) es
> poco confiable con esa densidad visual. Mismo tratamiento que p47 (Aparadores, Sesión N):
> se documenta como referencia, no como criterio de compliance verificable.
>
> Origen: \`vision_fallback.py\` sobre la p44 (planograma Deportes), extraídos por \`extractor.py\`
> (Sesión O) y validados por schema en Sesión P. Retirados de
> \`capa2_validado_con_candidatos.json\` por \`aplicar_lote6_sesion_x.mjs\` (Sesión X) —
> el total de criterios evaluables pasa de 156 a **148**.
> Pendiente de scope relacionado (Sesión Q): criterios descriptivos en páginas Vision.

## Los 8 registros excluidos (tal cual estaban en el JSON, sin editar)

${filasMd}`;

fs.writeFileSync(RUTA_REF, md, "utf8");
fs.writeFileSync(RUTA, JSON.stringify(data, null, 2) + "\n", "utf8");

let t = 0, f = 0;
for (const c of data.criterios) { c.revisado_por_gerardo === true ? t++ : f++; }
console.log(`OK: ${aprobar.length} criterios del Lote 6 marcados revisado_por_gerardo=true.`);
console.log(`OK: ${excluir.length} unidad_exhibicion_* excluidos del JSON y documentados en ${RUTA_REF}.`);
console.log(`Tracking global: total=${data.criterios.length} | true=${t} | false=${f}`);
