// -*- coding: utf-8 -*-
// Motor 2 — Sesión V: aplica las decisiones de Gerardo sobre el Lote 1
// (18 criterios: p6/7/10/16/18/20/22/24) presentado en esta conversación.
//
// Node.js nativo (sin dependencias) — misma razón que los scripts previos:
// esta máquina no tiene Python instalado.
//
// Decisiones de Gerardo (3 renombres manuales + confirmación del resto tal
// cual salió del generador ya corregido dos veces esta sesión: preserva
// dígitos puros, descarta marcadores de lista "(N)"):
//
//   1. p6 COLUMNAS etapa 3: "3era_etapa_solo_producir_parches"
//        -> "columnas_etapa3_parches_20"
//      (completa el patrón de sus hermanos barras_etapaN/columnas_etapaN;
//       Sesión T había asumido que este dato no existía)
//   2. p6 ATRILES: "imprimir_primera_etapa_generico_usan"
//        -> "atriles_primera_etapa_generico"
//   3. p20/22/24 al esquema de cluster (hermanos de focal_show_X_etapa1_2
//      ya confirmado en Sesión T):
//        p20 "exhibir_producto_seccion_juniors_joven"
//          -> "focal_show_mujeres_departamento_juniors"
//        p22 "exhibir_producto_seccion_juveniles_hombre"
//          -> "focal_show_hombres_departamento_juveniles"
//        p24 "exhibir_producto_seccion_ninos_8"
//          -> "focal_show_infantiles_departamento_ninos8"
//
// Los otros 13 del lote quedan con el id que ya trae el generador corregido
// (sin cambio adicional) — Gerardo los confirmó tal cual.
//
// Guard "nunca silencioso": matchea por el id ACTUAL de cada criterio
// pendiente + verifica que sea exactamente 1 match cada uno; aborta sin
// escribir nada si el total tocado ≠ 18, si algún id no se encuentra, o si
// algún id final (tras los 3 renombres) choca con otro id ya confirmado.
//
// USO:
//   node aplicar_lote1_sesion_v.mjs            -> escribe en sitio (respaldo .bak-<ts>)
//   node aplicar_lote1_sesion_v.mjs --dry-run  -> solo reporta, no escribe nada
//
// NO toca: retrieval_engine.py, confidence_engine.py, mandatory_engine.py,
// app.py, ni ningún otro archivo de Motor 2. NO toca los 88 criterios
// restantes que siguen pendientes (Lotes 2-6).

import { readFileSync, writeFileSync, copyFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, basename } from "node:path";

const MOTOR2 = dirname(fileURLToPath(import.meta.url));
const RUTA = join(MOTOR2, "capa2_validado_con_candidatos.json");

// Renombres manuales confirmados por Gerardo (id actual -> id final).
const RENOMBRES = {
  "3era_etapa_solo_producir_parches": "columnas_etapa3_parches_20",
  "imprimir_primera_etapa_generico_usan": "atriles_primera_etapa_generico",
  "exhibir_producto_seccion_juniors_joven": "focal_show_mujeres_departamento_juniors",
  "exhibir_producto_seccion_juveniles_hombre": "focal_show_hombres_departamento_juveniles",
  "exhibir_producto_seccion_ninos_8": "focal_show_infantiles_departamento_ninos8",
};

// Los 18 ids del Lote 1 tal como salieron del generador (antes de renombres).
const LOTE1_IDS = [
  "imprimir_torre_slim_mandar_parche",
  "3era_etapa_solo_producir_parches",
  "imprimir_primera_etapa_generico_usan",
  "nada_resguarda",
  "agregar_puntos_dependiendo_etapa_encuentre",
  "caso_muebles_focal_coloca_etiqueta",
  "utilizar_siguiente_formula",
  "2_maniquies_1_etiqueta",
  "recuerda_etiquetas_solo_van_cadera",
  "consulta_liga_manual_senalizacion_barata",
  "ubica_puntos_focales_accesos_importantes",
  "vestimenta_maniquies_revisa_apuestas_comerciales",
  "revisa_producto_focal_sea_mercancia",
  "maniqui_maniquies_deben_integrarse_elementos",
  "requiere_1_fotografia_focal",
  "exhibir_producto_seccion_juniors_joven",
  "exhibir_producto_seccion_juveniles_hombre",
  "exhibir_producto_seccion_ninos_8",
];

function abort(msg) {
  console.error("*** ABORTA: " + msg);
  process.exit(1);
}

function timestamp() {
  const now = new Date().toISOString().slice(0, 19);
  return { iso: now, bak: now.slice(0, 10).replace(/-/g, "") + "-" + now.slice(11, 19).replace(/:/g, "") };
}

function main() {
  const dryRun = process.argv.includes("--dry-run");
  const data = JSON.parse(readFileSync(RUTA, "utf-8"));
  const criterios = data.criterios;

  if (LOTE1_IDS.length !== 18) abort(`LOTE1_IDS debe tener 18 entradas, tiene ${LOTE1_IDS.length}`);

  let tocados = 0;
  const idsFinales = [];
  for (const idActual of LOTE1_IDS) {
    const match = criterios.filter((c) => c.id === idActual && c.revisado_por_gerardo === false);
    if (match.length !== 1) abort(`se esperaba EXACTAMENTE 1 criterio pendiente con id '${idActual}', se encontraron ${match.length}`);
    const c = match[0];
    const idFinal = RENOMBRES[idActual] || idActual;
    c.id = idFinal;
    c.revisado_por_gerardo = true;
    idsFinales.push(idFinal);
    tocados++;
  }

  console.log(`Criterios actualizados: ${tocados} (esperado: 18)`);
  if (tocados !== 18) abort("el total tocado no es 18");

  // Guard: ningún id final del lote choca entre sí ni contra otro ya confirmado.
  const setIdsFinales = new Set(idsFinales);
  if (setIdsFinales.size !== idsFinales.length) abort("dos criterios del Lote 1 terminaron con el mismo id final");

  const otrosConfirmados = criterios.filter((c) => c.revisado_por_gerardo === true && !idsFinales.includes(c.id));
  for (const idFinal of idsFinales) {
    if (otrosConfirmados.some((c) => c.id === idFinal)) abort(`el id final '${idFinal}' del Lote 1 choca con un criterio ya confirmado antes de esta sesión`);
  }

  const confirmadosTotal = criterios.filter((c) => c.revisado_por_gerardo === true).length;
  const pendientesTotal = criterios.filter((c) => c.revisado_por_gerardo === false).length;
  console.log(`revisado_por_gerardo=true tras esta corrida: ${confirmadosTotal}/${criterios.length} (pendientes: ${pendientesTotal})`);
  if (confirmadosTotal !== 68 || pendientesTotal !== 88) abort(`conteo inesperado: confirmados=${confirmadosTotal} (esperado 68), pendientes=${pendientesTotal} (esperado 88)`);

  const ts = timestamp();
  data.meta.lote1_sesion_v = ts.iso;
  data.meta.lote1_sesion_v_nota =
    "Gerardo revisó y confirmó el Lote 1 (18 criterios: p6/7/10/16/18/20/22/24) " +
    "presentado en Sesión V. 3 renombres manuales aplicados: " +
    "3era_etapa_solo_producir_parches -> columnas_etapa3_parches_20 (completa el " +
    "patrón de sus hermanos barras/columnas etapa1-3, dato que Sesión T daba por " +
    "inexistente); imprimir_primera_etapa_generico_usan -> " +
    "atriles_primera_etapa_generico; y los 3 de focal-por-departamento (p20/22/24) " +
    "renombrados al esquema de cluster focal_show_<genero>_departamento_<depto> " +
    "para alinearlos con sus hermanos focal_show_X_etapa1_2 ya confirmados en " +
    "Sesión T. Los otros 13 quedaron con el id tal como lo produjo el generador " +
    "ya corregido (dígitos preservados, marcadores de lista descartados). " +
    "Solo se modificó id y revisado_por_gerardo — texto original intacto.";

  if (dryRun) {
    console.log("\n--dry-run: no se escribió ningún archivo.");
    console.log("ids finales del Lote 1:", idsFinales);
    return;
  }

  if (existsSync(RUTA)) {
    const respaldo = RUTA + ".bak-" + ts.bak;
    copyFileSync(RUTA, respaldo);
    console.log("  respaldo: " + basename(respaldo));
  }

  const salida = JSON.stringify(data, null, 2).replace(/\n/g, "\r\n");
  writeFileSync(RUTA, salida, "utf-8");
  console.log("Escrito: " + basename(RUTA));
}

main();
