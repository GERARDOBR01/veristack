// aplicar_lote5_sesion_x.mjs — Sesión X (bloque conversacional)
// Aprueba el Lote 5 (p36/37+p39-42, 20 criterios pendientes): marca revisado_por_gerardo=true.
// EXCEPCIÓN con fix de texto (instrucción explícita de Gerardo): en
// impulsa_textiles_entran_98_puedes (p40) el texto trae "mesa mmm" pero el manual
// real dice "mesa MM" (nomenclatura interna) — se corrige SOLO esa subcadena y se aprueba.
// NO toca id, aliases, peso, severidad ni ningún otro campo de ningún criterio.
// Guards: 20 pendientes exactos, el fix aplica exactamente 1 vez, aborta sin escribir si algo no calza.

import fs from "node:fs";

const RUTA = "motor2/capa2_validado_con_candidatos.json";
const PAGINAS_LOTE5 = [36, 37, 39, 40, 41, 42];
const ESPERADO = 20;
const ID_FIX = "impulsa_textiles_entran_98_puedes";
const TEXTO_MAL = "mesa mmm";
const TEXTO_BIEN = "mesa MM";

const data = JSON.parse(fs.readFileSync(RUTA, "utf8"));
const arr = Array.isArray(data) ? data : (data.criterios || data.data);
if (!Array.isArray(arr)) { console.error("ABORTA: no encuentro el array de criterios."); process.exit(1); }

const objetivo = arr.filter(c => PAGINAS_LOTE5.includes(c.pagina_origen) && c.revisado_por_gerardo !== true);

if (objetivo.length !== ESPERADO) {
  console.error(`ABORTA: esperaba ${ESPERADO} pendientes en p36/37/39-42, encontré ${objetivo.length}. No se escribe nada.`);
  process.exit(1);
}

const conFix = objetivo.filter(c => c.id === ID_FIX && c.pagina_origen === 40);
if (conFix.length !== 1) {
  console.error(`ABORTA: esperaba exactamente 1 criterio ${ID_FIX} en p40, encontré ${conFix.length}. No se escribe nada.`);
  process.exit(1);
}
const ocurrencias = conFix[0].texto.split(TEXTO_MAL).length - 1;
if (ocurrencias !== 1) {
  console.error(`ABORTA: "${TEXTO_MAL}" aparece ${ocurrencias} veces en el texto de ${ID_FIX}, esperaba 1. No se escribe nada.`);
  process.exit(1);
}

const ts = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 15).replace(/(\d{8})(\d+)/, "$1-$2");
const bak = `${RUTA}.bak-${ts}`;
fs.copyFileSync(RUTA, bak);

conFix[0].texto = conFix[0].texto.replace(TEXTO_MAL, TEXTO_BIEN);

let tocados = 0;
for (const c of objetivo) { c.revisado_por_gerardo = true; tocados++; }

if (tocados !== ESPERADO) {
  console.error(`ABORTA: toqué ${tocados}, esperaba ${ESPERADO}. No se escribe.`);
  process.exit(1);
}

fs.writeFileSync(RUTA, JSON.stringify(data, null, 2) + "\n", "utf8");

let t = 0, f = 0;
for (const c of arr) { c.revisado_por_gerardo === true ? t++ : f++; }
console.log(`OK: ${tocados} criterios del Lote 5 marcados revisado_por_gerardo=true.`);
console.log(`Fix de texto aplicado en ${ID_FIX} (p40): "${TEXTO_MAL}" -> "${TEXTO_BIEN}".`);
console.log(`Respaldo: ${bak}`);
console.log(`Tracking global: total=${arr.length} | true=${t} | false=${f}`);
