// -*- coding: utf-8 -*-
// Motor 2 — aplica los 7 grupos de colisión que Gerardo resolvió (Sesión U).
//
// Node.js nativo (solo fs + JSON, sin dependencias). Se usa Node porque esta
// máquina de trabajo no tiene Python instalado y no se quiere instalar nada.
// Equivale a los scripts .py de sesiones previas (aplicar_confirmaciones_sesion_t.py).
//
// Sesión T dejó 7 grupos de colisión real (20 criterios) SIN confirmar en
// candidatos_id_colisiones.json. Gerardo revisó los 7 y decidió, caso por caso:
//
//   1. acercate_jefe_seccion_pueda_dar (p43/44, 2)            -> MANTENER id compartido
//   2. coloca_producto_mayor_descuento_sea (p28/29/33/38, 4)  -> COLAPSAR a colocar_producto_mayor_descuento
//   3. exhibicion_disciplinas_mantiene_dentro_separan (p43/44, 2) -> MANTENER id compartido
//   4. identificar_cartulina_descuento (p13/14, 2)            -> MANTENER id compartido
//   5. maniquies_etiquetas (p10, 2)                           -> SEPARAR en dos ids distintos
//        "3 maniquíes – 2 etiquetas" -> maniquies_3_etiquetas_2
//        "5 maniquíes – 3 etiquetas" -> maniquies_5_etiquetas_3
//      (único bug REAL del generador de slugs: descarta números de 1 dígito como
//       keyword — MIN_LARGO_TOKEN=3 en generar_candidatos_ids.py — y colapsó dos
//       reglas de cantidad distinta al mismo id.)
//   6. manten_orden_exhibicion (p28/29/33/38, 4)             -> COLAPSAR a mantener_orden_exhibicion
//   7. mercadeo_bloqueo_producto (p28/29/33/38, 4)           -> MANTENER id compartido
//
// Los 20 criterios afectados quedan revisado_por_gerardo=true. SOLO se toca el
// campo `id` (y `revisado_por_gerardo`) — el `texto` original del manual NO se
// modifica en ningún caso.
//
// Matching por el `id` candidato actual (los grupos colisionaban BAJO ese id) +
// guard de conteo exacto por grupo. Para maniquies, además, se distingue las dos
// instancias por subcadena del texto ("3 maniquíes" / "5 maniquíes") para no
// depender de transcribir el en-dash (U+2013). Aborta sin escribir nada si algún
// conteo no calza exacto (mismo principio "nunca silencioso" que validator.py).
//
// USO:
//   node aplicar_confirmaciones_sesion_u.mjs            -> escribe en sitio (respaldo .bak-<ts>)
//   node aplicar_confirmaciones_sesion_u.mjs --out RUTA -> escribe la salida en RUTA (dry-run, sin respaldo)
//
// NO toca: retrieval_engine.py, confidence_engine.py, mandatory_engine.py,
// app.py, ni ningún otro archivo de Motor 2.

import { readFileSync, writeFileSync, copyFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, basename } from "node:path";

const MOTOR2 = dirname(fileURLToPath(import.meta.url));
const RUTA = join(MOTOR2, "capa2_validado_con_candidatos.json");

// id candidato actual -> [nuevo id, n_esperado] (colapso de id compartido).
const COLAPSAR = {
  coloca_producto_mayor_descuento_sea: ["colocar_producto_mayor_descuento", 4],
  manten_orden_exhibicion: ["mantener_orden_exhibicion", 4],
};

// id candidato actual -> n_esperado. El id se conserva; solo se marca revisado.
const MANTENER_ID_COMPARTIDO = {
  acercate_jefe_seccion_pueda_dar: 2,
  exhibicion_disciplinas_mantiene_dentro_separan: 2,
  identificar_cartulina_descuento: 2,
  mercadeo_bloqueo_producto: 4,
};

// Grupo maniquies_etiquetas (p10): separar por subcadena del texto.
const SEPARAR_ID = "maniquies_etiquetas";
const SEPARAR_POR_SUBCADENA = [
  ["3 maniquíes", "maniquies_3_etiquetas_2"],
  ["5 maniquíes", "maniquies_5_etiquetas_3"],
];

function abort(msg) {
  console.error("*** ABORTA: " + msg);
  process.exit(1);
}

function timestamp() {
  const now = new Date().toISOString().slice(0, 19); // "2026-07-04T13:05:30"
  return {
    iso: now,
    bak: now.slice(0, 10).replace(/-/g, "") + "-" + now.slice(11, 19).replace(/:/g, ""),
  };
}

function main() {
  const args = process.argv.slice(2);
  const outIdx = args.indexOf("--out");
  const outPath = outIdx !== -1 ? args[outIdx + 1] : RUTA;
  const enSitio = outPath === RUTA;

  const data = JSON.parse(readFileSync(RUTA, "utf-8"));
  const criterios = data.criterios;
  let tocados = 0;

  // 1) Colapsos (renombre de id compartido).
  for (const [idActual, [nuevoId, nEsp]] of Object.entries(COLAPSAR)) {
    const grupo = criterios.filter((c) => c.id === idActual);
    if (grupo.length !== nEsp) abort(`se esperaban ${nEsp} criterios con id '${idActual}', se encontraron ${grupo.length}`);
    for (const c of grupo) {
      c.id = nuevoId;
      c.revisado_por_gerardo = true;
      tocados++;
    }
  }

  // 2) Mantener id compartido (solo marcar revisado).
  for (const [idActual, nEsp] of Object.entries(MANTENER_ID_COMPARTIDO)) {
    const grupo = criterios.filter((c) => c.id === idActual);
    if (grupo.length !== nEsp) abort(`se esperaban ${nEsp} criterios con id '${idActual}', se encontraron ${grupo.length}`);
    for (const c of grupo) {
      c.revisado_por_gerardo = true;
      tocados++;
    }
  }

  // 3) Separar maniquies_etiquetas en dos ids distintos por subcadena.
  const grupoManiquies = criterios.filter((c) => c.id === SEPARAR_ID);
  if (grupoManiquies.length !== SEPARAR_POR_SUBCADENA.length)
    abort(`se esperaban ${SEPARAR_POR_SUBCADENA.length} criterios con id '${SEPARAR_ID}', se encontraron ${grupoManiquies.length}`);
  for (const [subcadena, nuevoId] of SEPARAR_POR_SUBCADENA) {
    const match = grupoManiquies.filter((c) => (c.texto || "").includes(subcadena));
    if (match.length !== 1) abort(`se esperaba EXACTAMENTE 1 criterio '${SEPARAR_ID}' conteniendo '${subcadena}', se encontraron ${match.length}`);
    match[0].id = nuevoId;
    match[0].revisado_por_gerardo = true;
    tocados++;
  }

  console.log(`Criterios actualizados: ${tocados} (esperado: 20)`);
  if (tocados !== 20) abort("el total tocado no es 20");

  const revisados = criterios.filter((c) => c.revisado_por_gerardo === true).length;
  console.log(`revisado_por_gerardo=true tras esta corrida: ${revisados}/${criterios.length}`);

  const ts = timestamp();
  data.meta.confirmaciones_sesion_u = ts.iso;
  data.meta.confirmaciones_sesion_u_nota =
    "Gerardo resolvió los 7 grupos de colisión real de Sesión T (20 criterios, ahora " +
    "revisado_por_gerardo=true): colapso de coloca_producto_mayor_descuento_sea -> " +
    "colocar_producto_mayor_descuento y manten_orden_exhibicion -> mantener_orden_exhibicion; " +
    "separación del falso positivo maniquies_etiquetas (p10) en maniquies_3_etiquetas_2 y " +
    "maniquies_5_etiquetas_3; y confirmación del id compartido en acercate_jefe_seccion_pueda_dar, " +
    "exhibicion_disciplinas_mantiene_dentro_separan, identificar_cartulina_descuento y " +
    "mercadeo_bloqueo_producto. Solo se modificó el campo id; el texto original del manual no se tocó.";

  if (enSitio && existsSync(RUTA)) {
    const respaldo = RUTA + ".bak-" + ts.bak;
    copyFileSync(RUTA, respaldo);
    console.log("  respaldo: " + basename(respaldo));
  }

  // El archivo original usa CRLF y no termina en newline (lo escribió el .py de
  // Sesión T en modo texto de Windows); se replica para un diff mínimo.
  const salida = JSON.stringify(data, null, 2).replace(/\n/g, "\r\n");
  writeFileSync(outPath, salida, "utf-8");
  console.log("Escrito: " + (enSitio ? basename(RUTA) : outPath));
}

main();
