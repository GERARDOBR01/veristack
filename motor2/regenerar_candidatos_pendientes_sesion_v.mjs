// -*- coding: utf-8 -*-
// Motor 2 — Sesión V: fix del bug de dígitos en el generador de slugs +
// regeneración de id/aliases/aplica_a SOLO para los 106 criterios pendientes.
//
// Node.js nativo (solo fs, sin dependencias) — esta máquina no tiene Python
// instalado (igual que aplicar_confirmaciones_sesion_u.mjs). Es un PORT del
// algoritmo ya corregido en generar_candidatos_ids.py (misma sesión) — ambos
// archivos deben mantenerse en sync si el algoritmo cambia de nuevo.
//
// BUG (Sesión T, resuelto a mano en Sesión U para 2 criterios de p10):
//   MIN_LARGO_TOKEN=3 descartaba tokens puramente numéricos de 1-2 dígitos
//   ("3", "2", "5") como si fueran ruido, igual que descartaría "de"/"la".
//   Para criterios donde el ÚNICO diferenciador es una cantidad ("3 maniquíes"
//   vs "5 maniquíes"), eso colapsaba dos reglas distintas al mismo id.
// FIX: un token puramente numérico NUNCA se descarta por longitud (sigue
//   descartándose si fuera stopword, pero ningún dígito está en STOPWORDS).
//
// ALCANCE — respeta el límite explícito de la sesión:
//   - Los 50 criterios con revisado_por_gerardo=true NO se tocan (ni id, ni
//     aliases, ni aplica_a, ni el flag) — son decisiones ya confirmadas por
//     Gerardo en Sesiones T/U.
//   - Los 106 con revisado_por_gerardo=false SÍ se recalculan con el
//     generador corregido. Siguen quedando revisado_por_gerardo=false —
//     este script NO decide nada, solo mejora el candidato.
//
// Detecta colisiones en DOS direcciones (la Sesión S original solo veía
// colisiones dentro del mismo lote de 156 recién generados; acá además hay
// que vigilar que un id recién regenerado no choque con un id YA FINAL de
// los 50 confirmados, porque esos son slugs "congelados"):
//   (a) colisiones internas entre los 106 recién regenerados
//   (b) colisiones cruzadas: un id nuevo de los 106 == un id ya confirmado de los 50
//
// USO:
//   node regenerar_candidatos_pendientes_sesion_v.mjs             -> autotest + reporte + escribe en sitio (respaldo .bak-<ts>)
//   node regenerar_candidatos_pendientes_sesion_v.mjs --dry-run   -> autotest + reporte, NO escribe nada
//
// NO toca: validator.py, extractor.py, normalizer.py, segmenter.py,
// clasificador_layout.py, vision_fallback.py, consolidar_manual.py,
// retrieval_engine.py, confidence_engine.py, mandatory_engine.py, app.py,
// candidatos_id_colisiones.json (se deja como registro histórico, Sesión U).

import { readFileSync, writeFileSync, copyFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, basename } from "node:path";

const MOTOR2 = dirname(fileURLToPath(import.meta.url));
const RUTA_CANDIDATOS = join(MOTOR2, "capa2_validado_con_candidatos.json");
const RUTA_REPORTE_COLISIONES = join(MOTOR2, "candidatos_id_colisiones_pendientes_sesion_v.json");

const MAX_KEYWORDS_ID = 5;
const MIN_LARGO_TOKEN = 3;
const MARCA_AMBIGUO = "[AMBIGUO] ";
const ELEMENTOS_FISICOS = ["torre", "atril", "columna", "barra"];

const STOPWORDS = new Set([
  "a", "al", "algo", "algunas", "algunos", "ante", "antes", "como", "con",
  "contra", "cual", "cuando", "de", "del", "desde", "donde", "durante",
  "e", "el", "ella", "ellas", "ellos", "en", "entre", "era", "es", "esa",
  "esas", "ese", "eso", "esos", "esta", "estas", "este", "esto", "estos",
  "fue", "fueron", "ha", "hace", "hacer", "han", "hay", "la", "las", "le",
  "les", "lo", "los", "mas", "me", "mi", "mis", "mucho", "muchos", "muy",
  "no", "nos", "nosotros", "o", "otra", "otras", "otro", "otros", "para",
  "pero", "poco", "por", "porque", "que", "quien", "se", "sin", "sobre",
  "son", "su", "sus", "te", "tiene", "tienen", "todo", "todos", "tu",
  "tus", "un", "una", "uno", "unos", "y", "ya",
]);

function sinAcentos(s) {
  return (s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "");
}

function sinMarcaAmbiguo(texto) {
  texto = texto || "";
  return texto.startsWith(MARCA_AMBIGUO) ? texto.slice(MARCA_AMBIGUO.length) : texto;
}

function esDigito(t) {
  return /^[0-9]+$/.test(t);
}

// Fix Sesión V (parte 2): marcador de lista "(1)", "(2)"... es numeración de
// la fuente, no una keyword — se descarta ANTES de tokenizar para que no
// ocupe un slot del tope de 5 keywords y tape la última palabra real. Regex
// acotado a "(dígitos)" exacto: "(30%)" no matchea (el "%" rompe el patrón),
// así que los porcentajes siguen preservándose sin cambios.
const RE_MARCADOR_LISTA = /\(\s*\d+\s*\)/g;

function sinMarcadoresLista(texto) {
  return (texto || "").replace(RE_MARCADOR_LISTA, " ");
}

function keywords(texto) {
  let limpio = sinMarcadoresLista(sinMarcaAmbiguo(texto));
  limpio = sinAcentos(limpio).toLowerCase();
  limpio = limpio.replace(/[^a-z0-9\s]/g, " ");
  const tokens = limpio.split(/\s+/).filter(Boolean);
  return tokens.filter((t) => !STOPWORDS.has(t) && (esDigito(t) || t.length >= MIN_LARGO_TOKEN));
}

function generarIdCandidato(criterio) {
  const kws = keywords(criterio.texto).slice(0, MAX_KEYWORDS_ID);
  if (kws.length) return kws.join("_");
  const pagina = criterio.pagina_origen ?? "NA";
  return `criterio_p${pagina}_sin_keywords`;
}

function generarAliasesCandidato(criterio) {
  const kws = keywords(criterio.texto);
  const aliases = [];
  if (kws.length >= 2) aliases.push(kws.slice(0, 2).join(" "));
  if (kws.length >= 3) {
    const variante = kws.slice(1, 3).join(" ");
    if (!aliases.includes(variante)) aliases.push(variante);
  }
  return aliases;
}

function generarAplicaACandidato(criterio) {
  const textoNorm = sinAcentos(sinMarcaAmbiguo(criterio.texto)).toLowerCase();
  const encontrados = ELEMENTOS_FISICOS.filter((e) => new RegExp(`\\b${e}\\w*\\b`).test(textoNorm));
  return encontrados.length ? encontrados : null;
}

// ---------------------------------------------------------------------------
// PASO 1 — autotest obligatorio (gate). Aborta sin tocar datos reales si
// cualquier caso falla. Casos: el bug real ya documentado + bordes nuevos
// que el fix podría afectar (marcadores de lista numerados, fallback vacío,
// stopwords-only, prefijo [AMBIGUO], acentos/mayúsculas).
// ---------------------------------------------------------------------------
function autotest() {
  const casos = [];
  let fallos = 0;

  function caso(nombre, real, esperado) {
    casos.push({ nombre, real, esperado });
    const ok = JSON.stringify(real) === JSON.stringify(esperado);
    console.log(`  [${ok ? "OK" : "FALLO"}] ${nombre}`);
    if (!ok) {
      console.log(`         esperado: ${JSON.stringify(esperado)}`);
      console.log(`         real:     ${JSON.stringify(real)}`);
      fallos++;
    }
  }

  console.log("--- AUTOTEST generador (gate obligatorio, Sesión V) ---");

  // 1) El bug real de Sesión T/U: "3 maniquíes" vs "5 maniquíes" deben producir
  //    ids DISTINTOS ahora que los dígitos se preservan (antes colapsaban).
  const c1 = generarIdCandidato({ texto: "3 maniquíes – 2 etiquetas", pagina_origen: 10 });
  const c2 = generarIdCandidato({ texto: "5 maniquíes – 3 etiquetas", pagina_origen: 10 });
  caso("bug real p10: ids ya no colapsan", c1 !== c2, true);
  caso("bug real p10: id de '3 maniquíes' preserva el 3", c1, "3_maniquies_2_etiquetas");
  caso("bug real p10: id de '5 maniquíes' preserva el 5", c2, "5_maniquies_3_etiquetas");

  // 2) Token numérico puro de 1 dígito se preserva como keyword aislado,
  //    respetando el orden de aparición en el texto.
  caso("dígito aislado no se descarta", keywords("Repite 3 veces el proceso"), ["repite", "3", "veces", "proceso"]);

  // 3) Marcador de lista numerado "(1)"-"(6)" se descarta ANTES de tokenizar
  //    (fix Sesión V parte 2) — ya NO ocupa un slot del tope de 5 y ya NO tapa
  //    la última keyword real (regresión detectada por Gerardo tras el primer
  //    fix: "colocar_producto_descuento_mayor_menor" perdía "menor").
  caso(
    "marcador de lista (1) se descarta, no tapa la última keyword",
    keywords("(1) Colocar el producto por descuento de mayor a menor."),
    ["colocar", "producto", "descuento", "mayor", "menor"]
  );
  caso(
    "marcador de lista (6) se descarta en medio del texto",
    keywords("Se puede colocar (6) etiquetas colgantes en los maniquíes."),
    ["puede", "colocar", "etiquetas", "colgantes", "maniquies"]
  );
  // 3b) Un porcentaje entre paréntesis NO es un marcador de lista — el "%"
  //    rompe el patrón "(dígitos)" exacto, así que se sigue preservando.
  caso(
    "porcentaje entre paréntesis NO se confunde con marcador de lista",
    keywords("Prioridad de producto: Mobility y Cloe (40%)"),
    ["prioridad", "producto", "mobility", "cloe", "40"]
  );

  // 4) Alpha corto no-stopword sigue descartado por longitud (el fix NO
  //    relaja el umbral para letras, solo para dígitos).
  caso("alpha de 2 letras sigue descartado", keywords("ir ya no es un token valido"), ["token", "valido"]);

  // 5) Texto vacío / solo stopwords -> sin keywords -> fallback por página.
  caso("solo stopwords -> id fallback por página", generarIdCandidato({ texto: "de la a un", pagina_origen: 9 }), "criterio_p9_sin_keywords");
  caso("texto vacío -> id fallback por página", generarIdCandidato({ texto: "", pagina_origen: 2 }), "criterio_p2_sin_keywords");

  // 6) Prefijo [AMBIGUO] se descarta antes de tokenizar (no aporta keywords).
  caso(
    "[AMBIGUO] no aporta keywords propias",
    keywords("[AMBIGUO] Cuida tus básicos de Display."),
    keywords("Cuida tus básicos de Display.")
  );

  // 7) Acentos y mayúsculas se normalizan igual que antes del fix.
  caso("acentos/mayúsculas normalizados", keywords("MANIQUÍES Y ETIQUETAS"), ["maniquies", "etiquetas"]);

  // 8) Máximo 5 keywords en el id, aunque el texto tenga más (dígitos puros,
  //    para no depender de qué números son STOPWORDS como palabra "uno").
  caso(
    "id se trunca a 5 keywords",
    generarIdCandidato({ texto: "1 2 3 4 5 6 7", pagina_origen: 1 }),
    "1_2_3_4_5"
  );

  // 9) aplica_a sigue detectando elementos físicos sin cambios por el fix.
  caso("aplica_a detecta torre", generarAplicaACandidato({ texto: "Imprimir una torre slim" }), ["torre"]);
  caso("aplica_a null si no hay elemento físico", generarAplicaACandidato({ texto: "3 maniquíes – 2 etiquetas" }), null);

  console.log(`--- ${casos.length - fallos}/${casos.length} PASS ---`);
  if (fallos > 0) {
    console.error(`*** ABORTA: ${fallos} caso(s) de autotest fallaron. No se toca ningún dato real.`);
    process.exit(1);
  }
}

function timestamp() {
  const now = new Date().toISOString().slice(0, 19);
  return { iso: now, bak: now.slice(0, 10).replace(/-/g, "") + "-" + now.slice(11, 19).replace(/:/g, "") };
}

function main() {
  autotest();

  const dryRun = process.argv.includes("--dry-run");
  const data = JSON.parse(readFileSync(RUTA_CANDIDATOS, "utf-8"));
  const criterios = data.criterios;

  const confirmados = criterios.filter((c) => c.revisado_por_gerardo === true);
  const pendientes = criterios.filter((c) => c.revisado_por_gerardo === false);
  console.log(`\nLeído: ${criterios.length} criterios (${confirmados.length} confirmados, ${pendientes.length} pendientes)`);
  if (confirmados.length + pendientes.length !== criterios.length) {
    console.error("*** ABORTA: hay criterios con revisado_por_gerardo distinto de true/false");
    process.exit(1);
  }

  const idsConfirmados = new Set(confirmados.map((c) => c.id));

  let cambiados = 0;
  const diffs = [];
  for (const c of pendientes) {
    const idViejo = c.id;
    const idNuevo = generarIdCandidato(c);
    const aliasesNuevo = generarAliasesCandidato(c);
    const aplicaANuevo = generarAplicaACandidato(c);
    if (idViejo !== idNuevo) {
      cambiados++;
      diffs.push({ pagina_origen: c.pagina_origen, texto: c.texto, id_viejo: idViejo, id_nuevo: idNuevo });
    }
    c.id = idNuevo;
    c.aliases = aliasesNuevo;
    c.aplica_a = aplicaANuevo;
    // revisado_por_gerardo se deja explícitamente en false — no se decide nada acá.
  }

  console.log(`\nIds regenerados que CAMBIARON por el fix: ${cambiados}/${pendientes.length}`);
  if (cambiados > 0) {
    console.log("Detalle de cambios (id viejo -> id nuevo):");
    for (const d of diffs) {
      console.log(`  p${d.pagina_origen}: "${d.id_viejo}" -> "${d.id_nuevo}"`);
    }
  }

  // Colisiones internas entre los 106 recién regenerados.
  const porIdPendientes = new Map();
  for (const c of pendientes) {
    if (!porIdPendientes.has(c.id)) porIdPendientes.set(c.id, []);
    porIdPendientes.get(c.id).push(c);
  }
  const colisionesInternas = [...porIdPendientes.entries()]
    .filter(([, grupo]) => grupo.length > 1)
    .map(([id, grupo]) => ({
      id_candidato: id,
      cantidad: grupo.length,
      criterios: grupo.map((c) => ({ pagina_origen: c.pagina_origen, seccion_aplicable: c.seccion_aplicable, texto: c.texto })),
    }));

  // Colisiones cruzadas: un id nuevo (106) == un id ya confirmado (50, congelado).
  const colisionesCruzadas = pendientes
    .filter((c) => idsConfirmados.has(c.id))
    .map((c) => ({ id_candidato: c.id, pagina_origen: c.pagina_origen, texto: c.texto }));

  console.log(`\nColisiones internas entre los 106 regenerados: ${colisionesInternas.length} grupo(s), ${colisionesInternas.reduce((n, g) => n + g.cantidad, 0)} criterio(s)`);
  console.log(`Colisiones cruzadas (106 nuevo choca contra id ya confirmado de los 50): ${colisionesCruzadas.length}`);

  const reporte = {
    generado: timestamp().iso,
    contexto: "Sesión V: colisiones detectadas tras fix del generador (preserva dígitos) y regeneración de los 106 pendientes. candidatos_id_colisiones.json (Sesión S/T/U) se deja intacto como registro histórico de los 18 grupos originales, ya resueltos en su totalidad (50/50).",
    total_pendientes_regenerados: pendientes.length,
    ids_cambiados_por_el_fix: cambiados,
    colisiones_internas: { grupos: colisionesInternas.length, criterios_afectados: colisionesInternas.reduce((n, g) => n + g.cantidad, 0), detalle: colisionesInternas },
    colisiones_cruzadas_contra_ids_confirmados: colisionesCruzadas,
    diffs_id_por_el_fix: diffs,
  };

  if (dryRun) {
    console.log("\n--dry-run: no se escribió ningún archivo.");
    return;
  }

  const ts = timestamp();
  data.meta.regenerado_pendientes_sesion_v = ts.iso;
  data.meta.regenerado_pendientes_sesion_v_nota =
    "Fix del generador (Sesión V): los tokens puramente numéricos ya no se " +
    "descartan por longitud (bug Sesión T: '3'/'2'/'5' se perdían y colapsaban " +
    "reglas de cantidad distinta al mismo id, ej. p10 maniquíes, resuelto a mano " +
    "en Sesión U). Se regeneraron id/aliases/aplica_a SOLO para los 106 criterios " +
    "con revisado_por_gerardo=false; los 50 confirmados en Sesiones T/U no se tocaron. " +
    "Ningún criterio se marcó revisado_por_gerardo=true en este paso — eso queda " +
    "para la revisión por lotes de Gerardo.";

  if (existsSync(RUTA_CANDIDATOS)) {
    const respaldo = RUTA_CANDIDATOS + ".bak-" + ts.bak;
    copyFileSync(RUTA_CANDIDATOS, respaldo);
    console.log("\n  respaldo: " + basename(respaldo));
  }

  const salida = JSON.stringify(data, null, 2).replace(/\n/g, "\r\n");
  writeFileSync(RUTA_CANDIDATOS, salida, "utf-8");
  console.log("Escrito: " + basename(RUTA_CANDIDATOS));

  writeFileSync(RUTA_REPORTE_COLISIONES, JSON.stringify(reporte, null, 2).replace(/\n/g, "\r\n"), "utf-8");
  console.log("Escrito: " + basename(RUTA_REPORTE_COLISIONES));
}

main();
