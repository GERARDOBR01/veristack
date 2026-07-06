// aplicar_lote2_sesion_v.mjs — Sesión V (bloque conversacional)
// Aprueba el Lote 2 (p11-14, 18 criterios pendientes): SOLO marca revisado_por_gerardo=true.
// NO toca id, aliases, texto, peso, severidad ni ningún otro campo.
// Excepción de Gerardo: "selecciona_producto_dando_prioridad_descuento" (p13) se aprueba
//   (id/aliases sellados) pero su peso/severidad NO se corrige aquí (golden set, otra sesión).
//   Como este script no toca peso/severidad de NADIE, la excepción se respeta por construcción.
// Principio "nunca silencioso": guard de conteo exacto — aborta sin escribir si tocados != 18.

import fs from "node:fs";

const RUTA = "motor2/capa2_validado_con_candidatos.json";
const PAGINAS_LOTE2 = [11, 12, 13, 14];
const ESPERADO = 18;

const data = JSON.parse(fs.readFileSync(RUTA, "utf8"));
const arr = Array.isArray(data) ? data : (data.criterios || data.data);
if (!Array.isArray(arr)) { console.error("ABORTA: no encuentro el array de criterios."); process.exit(1); }

// Selecciona los pendientes de p11-14
const objetivo = arr.filter(c => PAGINAS_LOTE2.includes(c.pagina_origen) && c.revisado_por_gerardo !== true);

if (objetivo.length !== ESPERADO) {
  console.error(`ABORTA: esperaba ${ESPERADO} pendientes en p11-14, encontré ${objetivo.length}. No se escribe nada.`);
  process.exit(1);
}

// Respaldo con timestamp (local, no se commitea)
const ts = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 15).replace(/(\d{8})(\d+)/, "$1-$2");
const bak = `${RUTA}.bak-${ts}`;
fs.copyFileSync(RUTA, bak);

// Aplica SOLO el flag
let tocados = 0;
for (const c of objetivo) { c.revisado_por_gerardo = true; tocados++; }

if (tocados !== ESPERADO) {
  console.error(`ABORTA: toqué ${tocados}, esperaba ${ESPERADO}. No se escribe.`);
  process.exit(1);
}

fs.writeFileSync(RUTA, JSON.stringify(data, null, 2) + "\n", "utf8");

// Recuento final
let t = 0, f = 0;
for (const c of arr) { c.revisado_por_gerardo === true ? t++ : f++; }
console.log(`OK: ${tocados} criterios del Lote 2 marcados revisado_por_gerardo=true.`);
console.log(`Respaldo: ${bak}`);
console.log(`Tracking global: total=${arr.length} | true=${t} | false=${f}`);
