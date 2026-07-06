// aplicar_lote4_sesion_x.mjs — Sesión X (bloque conversacional)
// Aprueba el Lote 4 (p31-34+p38, 17 criterios pendientes): SOLO marca revisado_por_gerardo=true.
// NO toca id, aliases, texto, peso, severidad ni ningún otro campo.
// NO aplica ninguna corrección de golden set (p32 sigue con su severidad original).
// Principio "nunca silencioso": guard de conteo exacto — aborta sin escribir si tocados != 17.

import fs from "node:fs";

const RUTA = "motor2/capa2_validado_con_candidatos.json";
const PAGINAS_LOTE4 = [31, 32, 33, 34, 38];
const ESPERADO = 17;

const data = JSON.parse(fs.readFileSync(RUTA, "utf8"));
const arr = Array.isArray(data) ? data : (data.criterios || data.data);
if (!Array.isArray(arr)) { console.error("ABORTA: no encuentro el array de criterios."); process.exit(1); }

const objetivo = arr.filter(c => PAGINAS_LOTE4.includes(c.pagina_origen) && c.revisado_por_gerardo !== true);

if (objetivo.length !== ESPERADO) {
  console.error(`ABORTA: esperaba ${ESPERADO} pendientes en p31-34/38, encontré ${objetivo.length}. No se escribe nada.`);
  process.exit(1);
}

const ts = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 15).replace(/(\d{8})(\d+)/, "$1-$2");
const bak = `${RUTA}.bak-${ts}`;
fs.copyFileSync(RUTA, bak);

let tocados = 0;
for (const c of objetivo) { c.revisado_por_gerardo = true; tocados++; }

if (tocados !== ESPERADO) {
  console.error(`ABORTA: toqué ${tocados}, esperaba ${ESPERADO}. No se escribe.`);
  process.exit(1);
}

fs.writeFileSync(RUTA, JSON.stringify(data, null, 2) + "\n", "utf8");

let t = 0, f = 0;
for (const c of arr) { c.revisado_por_gerardo === true ? t++ : f++; }
console.log(`OK: ${tocados} criterios del Lote 4 marcados revisado_por_gerardo=true.`);
console.log(`Respaldo: ${bak}`);
console.log(`Tracking global: total=${arr.length} | true=${t} | false=${f}`);
