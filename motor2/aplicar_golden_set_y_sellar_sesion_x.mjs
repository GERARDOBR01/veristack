// aplicar_golden_set_y_sellar_sesion_x.mjs — Sesión X (cierre)
// PASO 1: aplica las 3 correcciones del golden set (verificadas contra el PDF real,
// golden set sellado en motor2/golden_set/esperado/gran_barata_muestra_18.json):
//   p13 selecciona_producto_dando_prioridad_descuento: peso MANDATORY->RECOMMENDATION (severidad intacta)
//   p27 cuentas_espacio_suficiente_obstruya_paso:      peso MANDATORY->RECOMMENDATION + severidad GRAVE->OBSERVACION
//   p32 exhibe_bloque_tipo_producto_marca:             severidad OBSERVACION->GRAVE (peso intacto)
// Guard por criterio: id+página únicos Y valores actuales EXACTOS a los esperados — aborta si algo no calza.
// PASO 2: sella motor2/capa2_validado_final.json (148 criterios + schema_version 1.1 +
// metadatos de capa que el gate del swap y retrieval_engine esperan). NO ejecuta el swap.
// NO toca texto/id/aliases ni ningún otro criterio.

import fs from "node:fs";
import crypto from "node:crypto";

const RUTA = "motor2/capa2_validado_con_candidatos.json";
const RUTA_FINAL = "motor2/capa2_validado_final.json";

const CORRECCIONES = [
  {
    id: "selecciona_producto_dando_prioridad_descuento", pagina: 13,
    antes: { peso: "MANDATORY", severidad: "GRAVE" },
    cambios: { peso: "RECOMMENDATION" },
  },
  {
    id: "cuentas_espacio_suficiente_obstruya_paso", pagina: 27,
    antes: { peso: "MANDATORY", severidad: "GRAVE" },
    cambios: { peso: "RECOMMENDATION", severidad: "OBSERVACION" },
  },
  {
    id: "exhibe_bloque_tipo_producto_marca", pagina: 32,
    antes: { peso: "MANDATORY", severidad: "OBSERVACION" },
    cambios: { severidad: "GRAVE" },
  },
];

const data = JSON.parse(fs.readFileSync(RUTA, "utf8"));
const arr = data.criterios;
if (!Array.isArray(arr) || arr.length !== 148) {
  console.error(`ABORTA: esperaba 148 criterios, encontré ${Array.isArray(arr) ? arr.length : "N/A"}.`);
  process.exit(1);
}

// Guards ANTES de escribir nada
const objetivos = [];
for (const corr of CORRECCIONES) {
  const matches = arr.filter(c => c.id === corr.id && c.pagina_origen === corr.pagina);
  if (matches.length !== 1) {
    console.error(`ABORTA: ${corr.id} (p${corr.pagina}): esperaba 1 match, encontré ${matches.length}. No se escribe nada.`);
    process.exit(1);
  }
  const c = matches[0];
  if (c.peso !== corr.antes.peso || c.severidad !== corr.antes.severidad) {
    console.error(`ABORTA: ${corr.id}: valores actuales peso=${c.peso}/severidad=${c.severidad} no calzan con los esperados ${corr.antes.peso}/${corr.antes.severidad}. No se escribe nada.`);
    process.exit(1);
  }
  if (c.revisado_por_gerardo !== true) {
    console.error(`ABORTA: ${corr.id}: revisado_por_gerardo != true. No se escribe nada.`);
    process.exit(1);
  }
  objetivos.push({ c, corr });
}

const ts = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 15).replace(/(\d{8})(\d+)/, "$1-$2");
fs.copyFileSync(RUTA, `${RUTA}.bak-${ts}`);

for (const { c, corr } of objetivos) {
  for (const [campo, valor] of Object.entries(corr.cambios)) c[campo] = valor;
}

data.meta.golden_set_sesion_x = new Date().toISOString().slice(0, 19);
data.meta.golden_set_sesion_x_nota = "Aplicadas las 3 correcciones de peso/severidad del golden set #1 (verificadas por Gerardo contra el PDF real, Sesión V): p13 selecciona_producto_dando_prioridad_descuento peso MANDATORY->RECOMMENDATION; p27 cuentas_espacio_suficiente_obstruya_paso MANDATORY->RECOMMENDATION + GRAVE->OBSERVACION; p32 exhibe_bloque_tipo_producto_marca severidad OBSERVACION->GRAVE. Texto/id/aliases intactos.";

fs.writeFileSync(RUTA, JSON.stringify(data, null, 2) + "\n", "utf8");
console.log("OK: 3 correcciones del golden set aplicadas a " + RUTA);

// PASO 2 — sellar el final
const criteriosFinal = arr; // mismos 148 registros, ya corregidos
const noRevisados = criteriosFinal.filter(c => c.revisado_por_gerardo !== true).length;
if (noRevisados !== 0) {
  console.error(`ABORTA sellado: ${noRevisados} criterios sin revisar.`);
  process.exit(1);
}

const hash = crypto.createHash("sha256").update(JSON.stringify(criteriosFinal)).digest("hex");
const final = {
  schema_version: "1.1",
  etapa: "gran_barata_pv2026",
  vigencia_inicio: "2026-06-22",
  vigencia_fin: "2026-08-09",
  fecha_actualizacion: new Date().toISOString().slice(0, 10),
  hash_contenido: hash,
  meta: {
    origen: "motor2/capa2_validado_con_candidatos.json (Sesión X: 148/148 revisado_por_gerardo=true + 3 correcciones golden set aplicadas)",
    manual: "mecanica_montaje_gran_barata_pv_2026",
    sellado: new Date().toISOString().slice(0, 19),
    nota: "148 criterios evaluables. Los 8 unidad_exhibicion_* de p44 excluidos (motor2/referencia_no_evaluable.md). Candidato para reemplazar pipeline/knowledge/capa2_campana_activa.json vía swap_capa2_produccion.mjs — swap real pendiente de autorización de Gerardo.",
  },
  criterios: criteriosFinal,
};

fs.writeFileSync(RUTA_FINAL, JSON.stringify(final, null, 2) + "\n", "utf8");
console.log(`OK: ${RUTA_FINAL} sellado — ${criteriosFinal.length} criterios, schema_version=1.1, sha256(criterios)=${hash.slice(0, 16)}…`);
