// swap_capa2_produccion.mjs — Sesión W
// Swap controlado de la capa2 de producción: reemplaza pipeline/knowledge/capa2_campana_activa.json
// por el archivo validado final (capa2_validado_final.json) SOLO si pasa la validación completa.
//
// Principios (mismos que aplicar_lote*.mjs / validator.py):
//   - "Nunca silencioso": cualquier anomalía ABORTA con mensaje explícito, sin escribir nada.
//   - Autotest obligatorio: toda operación con --confirmar corre primero el autotest completo
//     en un sandbox temporal; si un solo caso falla, no se toca ningún archivo real.
//   - Sin defaults de ruta: --candidato y --activo son SIEMPRE explícitos. Ningún comando
//     puede caerle al archivo de producción por accidente u olvido.
//   - Sin --confirmar todo es dry-run: valida y muestra el plan, cero escrituras.
//   - El swap copia BYTES (no reserializa): cero oportunidad de corrupción por transformación.
//
// Validación del candidato (rechaza, no avisa):
//   - JSON corrupto o sin array `criterios` no vacío.
//   - `schema_version` top-level ausente o fuera de {1.0, 1.1, 1.2}. Distingue un archivo de
//     knowledge sellado de un artefacto intermedio de motor2 (capa2_validado_con_candidatos.json
//     no la tiene → rechazado por diseño hasta que se selle el final).
//   - Por criterio (schema v1.2 completo): id snake_case, aliases (≥1), clave aplica_a
//     (null|array), texto, peso y severidad en catálogo, etapa_aplicable (null|E1/E2/E3|1/2/3),
//     condicion_libre (null|string), referencia_no_resuelta (bool|null — null es el estado
//     [AMBIGUO] del fix de Sesión I), seccion_aplicable (null|string).
//   - Colisiones SIN RESOLVER: dos criterios con el mismo id donde NO todas las instancias
//     tienen revisado_por_gerardo=true → rechazo con el grupo y sus páginas. Un id compartido
//     con TODAS sus instancias revisadas es un colapso confirmado por Gerardo (Sesiones T/U:
//     focal_show_*, colocar_producto_mayor_descuento, no_mezclar_marcas, etc. — retrieval
//     cachea hasta 3 evidencias por id) → aviso informativo, no bloquea.
//   - `revisado_por_gerardo`: si el campo existe y no es true en TODOS → rechazo (el archivo
//     no es final). Un archivo final sin el campo de tracking también es válido.
//   Advertencias (no bloquean): metadatos informativos ausentes (etapa/vigencias/fecha/hash),
//   schema_version=1.2 (retrieval_engine la carga con WARNING; espera 1.0/1.1),
//   posible_herencia_fewshot / referencia_no_resuelta / grounding=failed presentes.
//
// Mecánica del swap (--confirmar):
//   autotest → validar candidato → backup <activo>.bak-swap-<ts> (verificado por sha256)
//   → manifest <activo>.swap-manifest.json (estado en_progreso) → copia atómica
//   (tmp + rename en el mismo directorio) → verificación post-swap (sha256 + relectura +
//   conteo de ids que Motor 1 extraería) → manifest estado completado.
//   Si muere a medio swap, el manifest + backup dejan el rollback listo.
//
// Rollback de un comando (--confirmar):
//   Lee el manifest, verifica sha256(backup) == sha256_activo_antes (no restaura basura),
//   restaura por copia atómica, verifica, y archiva el manifest como .rolled-back-<ts>.json.
//   El backup NUNCA se borra (auditoría).
//
// Uso:
//   node motor2/swap_capa2_produccion.mjs autotest
//   node motor2/swap_capa2_produccion.mjs validar  --candidato <ruta.json>
//   node motor2/swap_capa2_produccion.mjs swap     --candidato <ruta.json> --activo <ruta.json> [--confirmar]
//   node motor2/swap_capa2_produccion.mjs rollback --activo <ruta.json> [--confirmar]
//
// Swap real (SOLO con autorización explícita de Gerardo, cuando exista el final sellado):
//   node motor2/swap_capa2_produccion.mjs swap --candidato motor2/capa2_validado_final.json \
//        --activo pipeline/knowledge/capa2_campana_activa.json --confirmar

import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";

// ── Catálogos (fuente: validator.py + schema_conocimiento_v1.md + retrieval_engine.py) ──
const PESOS_VALIDOS = new Set(["MANDATORY", "RECOMMENDATION", "EXCEPTION"]);
const SEVERIDADES_VALIDAS = new Set(["GRAVE", "OBSERVACION", "NO_CALIFICA"]);
const ETAPAS_VALIDAS = new Set(["E1", "E2", "E3", "1", "2", "3"]); // retrieval._norm_etapa acepta ambas formas
const SCHEMA_VERSIONS_ACEPTADAS = new Set(["1.0", "1.1", "1.2"]);
const SCHEMA_VERSIONS_SIN_WARNING = new Set(["1.0", "1.1"]); // SCHEMAS_VERSION_ESPERADAS de retrieval_engine.py
const ID_RE = /^[a-z0-9_]+$/;

// ── Helpers ──
function ts() {
  const d = new Date();
  const p = (n, w = 2) => String(n).padStart(w, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function sha256(ruta) {
  return crypto.createHash("sha256").update(fs.readFileSync(ruta)).digest("hex");
}

// Copia byte a byte con rename atómico en el mismo directorio (Node en Windows usa
// MOVEFILE_REPLACE_EXISTING: el destino nunca queda a medio escribir).
function copiaAtomica(origen, destino) {
  const tmp = `${destino}.tmp-swap-${process.pid}`;
  fs.copyFileSync(origen, tmp);
  fs.renameSync(tmp, destino);
}

function rutaBackupLibre(activo) {
  const base = `${activo}.bak-swap-${ts()}`;
  if (!fs.existsSync(base)) return base;
  let n = 2;
  while (fs.existsSync(`${base}-${n}`)) n++;
  return `${base}-${n}`;
}

function rutaManifest(activo) {
  return `${activo}.swap-manifest.json`;
}

// Réplica exacta de lo que pipeline._extraer_criterios_del_knowledge() extrae de una capa:
// ids string no vacíos tras strip, únicos.
function idsQueMotor1Extraeria(criterios) {
  const ids = new Set();
  for (const c of criterios) {
    if (typeof c.id === "string" && c.id.trim()) ids.add(c.id.trim());
  }
  return ids;
}

// ── Validación del candidato ──
function validarCandidato(rutaCandidato) {
  const errores = [];
  const warnings = [];
  const resumen = {};

  if (!fs.existsSync(rutaCandidato)) {
    return { ok: false, errores: [`el candidato no existe: ${rutaCandidato}`], warnings, resumen };
  }

  let data;
  try {
    data = JSON.parse(fs.readFileSync(rutaCandidato, "utf8"));
  } catch (e) {
    return { ok: false, errores: [`JSON inválido (corrupto o truncado): ${e.message}`], warnings, resumen };
  }

  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return { ok: false, errores: ["el top-level no es un objeto JSON"], warnings, resumen };
  }
  const criterios = data.criterios;
  if (!Array.isArray(criterios) || criterios.length === 0) {
    return { ok: false, errores: ["falta el array `criterios` o está vacío"], warnings, resumen };
  }

  // Metadatos top-level
  const sv = data.schema_version;
  if (sv === undefined) {
    errores.push(
      "falta `schema_version` top-level — un archivo de knowledge sellado la declara " +
      "(los artefactos intermedios de motor2 no la tienen; sellar el final antes de promover)"
    );
  } else if (!SCHEMA_VERSIONS_ACEPTADAS.has(sv)) {
    errores.push(`schema_version=${JSON.stringify(sv)} no aceptada (válidas: ${[...SCHEMA_VERSIONS_ACEPTADAS].join(", ")})`);
  } else if (!SCHEMA_VERSIONS_SIN_WARNING.has(sv)) {
    warnings.push(`schema_version=${sv}: retrieval_engine la carga pero con WARNING (espera 1.0/1.1)`);
  }
  for (const campo of ["etapa", "vigencia_inicio", "vigencia_fin", "fecha_actualizacion", "hash_contenido"]) {
    if (data[campo] === undefined) {
      warnings.push(`metadato top-level ausente: \`${campo}\` (informativo — ningún motor lo lee, pero el activo actual lo trae)`);
    }
  }

  // Por criterio
  const porId = new Map(); // id -> [{i, pagina, revisadoTrue}]
  let revisadosTrue = 0;
  let revisadosFalse = 0;
  let conCampoRevisado = 0;
  let fewshot = 0;
  let refsNoResueltas = 0;
  let refsAmbiguas = 0;
  let groundingFailed = 0;
  const pesos = {};
  const severidades = {};

  criterios.forEach((c, i) => {
    const etiqueta = `criterio #${i} (p${c?.pagina_origen ?? "?"}, id=${typeof c?.id === "string" ? c.id : "—"})`;
    if (typeof c !== "object" || c === null || Array.isArray(c)) {
      errores.push(`${etiqueta}: no es un objeto`);
      return;
    }

    if (typeof c.id !== "string" || !c.id.trim()) {
      errores.push(`${etiqueta}: falta \`id\` (string no vacío)`);
    } else if (!ID_RE.test(c.id)) {
      errores.push(`${etiqueta}: id ${JSON.stringify(c.id)} no cumple snake_case ^[a-z0-9_]+$`);
    } else {
      if (!porId.has(c.id)) porId.set(c.id, []);
      porId.get(c.id).push({ i, pagina: c.pagina_origen ?? "?", revisadoTrue: c.revisado_por_gerardo === true });
    }

    if (!Array.isArray(c.aliases) || c.aliases.length === 0 || c.aliases.some((a) => typeof a !== "string" || !a.trim())) {
      errores.push(`${etiqueta}: falta \`aliases\` (array con ≥1 string no vacío)`);
    }

    if (!("aplica_a" in c)) {
      errores.push(`${etiqueta}: falta la clave \`aplica_a\` (null o array de strings)`);
    } else if (c.aplica_a !== null && (!Array.isArray(c.aplica_a) || c.aplica_a.some((a) => typeof a !== "string" || !a.trim()))) {
      errores.push(`${etiqueta}: \`aplica_a\` debe ser null o array de strings no vacíos`);
    }

    if (typeof c.texto !== "string" || !c.texto.trim()) {
      errores.push(`${etiqueta}: falta \`texto\` (string no vacío)`);
    }

    if (!PESOS_VALIDOS.has(c.peso)) {
      errores.push(`${etiqueta}: peso ${JSON.stringify(c.peso)} fuera de catálogo (${[...PESOS_VALIDOS].join(", ")})`);
    } else {
      pesos[c.peso] = (pesos[c.peso] || 0) + 1;
    }

    if (!SEVERIDADES_VALIDAS.has(c.severidad)) {
      errores.push(`${etiqueta}: severidad ${JSON.stringify(c.severidad)} fuera de catálogo (${[...SEVERIDADES_VALIDAS].join(", ")})`);
    } else {
      severidades[c.severidad] = (severidades[c.severidad] || 0) + 1;
    }

    if (!("etapa_aplicable" in c)) {
      errores.push(`${etiqueta}: falta la clave \`etapa_aplicable\` (null o array E1/E2/E3)`);
    } else if (c.etapa_aplicable !== null) {
      if (!Array.isArray(c.etapa_aplicable) || c.etapa_aplicable.length === 0 || c.etapa_aplicable.some((e) => !ETAPAS_VALIDAS.has(e))) {
        errores.push(`${etiqueta}: etapa_aplicable ${JSON.stringify(c.etapa_aplicable)} inválida (null o array con ${[...ETAPAS_VALIDAS].join("/")})`);
      }
    }

    if (!("condicion_libre" in c)) {
      errores.push(`${etiqueta}: falta la clave \`condicion_libre\` (null o string)`);
    } else if (c.condicion_libre !== null && typeof c.condicion_libre !== "string") {
      errores.push(`${etiqueta}: \`condicion_libre\` debe ser null o string`);
    }

    // 3 estados desde el fix de Sesión I: true (doc externo nombrado), false (normal),
    // null (estándar externo NO nombrado — el criterio lleva prefijo [AMBIGUO]).
    if (!("referencia_no_resuelta" in c)) {
      errores.push(`${etiqueta}: falta la clave \`referencia_no_resuelta\` (boolean o null)`);
    } else if (c.referencia_no_resuelta !== null && typeof c.referencia_no_resuelta !== "boolean") {
      errores.push(`${etiqueta}: \`referencia_no_resuelta\` debe ser boolean o null`);
    } else if (c.referencia_no_resuelta === true) {
      refsNoResueltas++;
    } else if (c.referencia_no_resuelta === null) {
      refsAmbiguas++;
    }

    if (!("seccion_aplicable" in c)) {
      errores.push(`${etiqueta}: falta la clave \`seccion_aplicable\` (null o string — campo v1.2)`);
    } else if (c.seccion_aplicable !== null && typeof c.seccion_aplicable !== "string") {
      errores.push(`${etiqueta}: \`seccion_aplicable\` debe ser null o string`);
    }

    if ("revisado_por_gerardo" in c) {
      conCampoRevisado++;
      if (c.revisado_por_gerardo === true) revisadosTrue++;
      else revisadosFalse++;
    }
    if (c.posible_herencia_fewshot === true) fewshot++;
    if (c.grounding === "failed") groundingFailed++;
  });

  if (revisadosFalse > 0) {
    errores.push(
      `${revisadosFalse}/${criterios.length} criterios con revisado_por_gerardo≠true — ` +
      "el archivo NO es final; solo se promueve un archivo 100% revisado por Gerardo"
    );
  }

  // Colisiones de id. Compartir id es válido SOLO como colapso confirmado por Gerardo
  // (todas las instancias revisado_por_gerardo=true — Sesiones T/U); si alguna instancia
  // no está explícitamente revisada, no hay forma de distinguirlo de un duplicado
  // accidental → colisión sin resolver, rechazo.
  let idsCompartidosConfirmados = 0;
  for (const [id, apariciones] of porId) {
    if (apariciones.length > 1) {
      const donde = apariciones.map((a) => `#${a.i} p${a.pagina}`).join(", ");
      if (apariciones.every((a) => a.revisadoTrue)) {
        idsCompartidosConfirmados++;
        warnings.push(`id compartido confirmado (todas las instancias revisadas): \`${id}\` × ${apariciones.length} (${donde})`);
      } else {
        errores.push(`colisión sin resolver: id \`${id}\` aparece ${apariciones.length} veces (${donde}) y no todas las instancias están revisadas`);
      }
    }
  }

  if (fewshot > 0) warnings.push(`${fewshot} criterios con posible_herencia_fewshot=true (marca informativa, no bloquea)`);
  if (refsNoResueltas > 0) warnings.push(`${refsNoResueltas} criterios con referencia_no_resuelta=true (requieren resolución manual posterior)`);
  if (refsAmbiguas > 0) warnings.push(`${refsAmbiguas} criterios con referencia_no_resuelta=null (estado [AMBIGUO] — estándar externo sin nombrar)`);
  if (groundingFailed > 0) warnings.push(`${groundingFailed} criterios con grounding=failed (el validador de Sesión P los filtraba — revisar por qué siguen aquí)`);

  resumen.total = criterios.length;
  resumen.idsUnicos = porId.size;
  resumen.idsCompartidosConfirmados = idsCompartidosConfirmados;
  resumen.motor1Extraeria = idsQueMotor1Extraeria(criterios).size;
  resumen.pesos = pesos;
  resumen.severidades = severidades;
  resumen.revisados = conCampoRevisado > 0 ? `${revisadosTrue}/${criterios.length} true (campo presente)` : "campo de tracking ausente (archivo final limpio)";
  resumen.schema_version = sv ?? null;

  return { ok: errores.length === 0, errores, warnings, resumen };
}

function imprimirValidacion(rutaCandidato, v, log) {
  log(`Validación de: ${rutaCandidato}`);
  if (v.resumen.total !== undefined) {
    log(`  criterios: ${v.resumen.total} | ids únicos: ${v.resumen.idsUnicos} (${v.resumen.idsCompartidosConfirmados} compartidos confirmados) | Motor 1 extraería: ${v.resumen.motor1Extraeria} ids`);
    log(`  pesos: ${JSON.stringify(v.resumen.pesos)} | severidades: ${JSON.stringify(v.resumen.severidades)}`);
    log(`  revisado_por_gerardo: ${v.resumen.revisados} | schema_version: ${JSON.stringify(v.resumen.schema_version)}`);
  }
  for (const w of v.warnings) log(`  ⚠ AVISO: ${w}`);
  const MAX = 40;
  v.errores.slice(0, MAX).forEach((e) => log(`  ✗ RECHAZO: ${e}`));
  if (v.errores.length > MAX) log(`  ✗ ... y ${v.errores.length - MAX} errores más`);
  log(v.ok ? "  → VÁLIDO para swap." : `  → RECHAZADO (${v.errores.length} errores). No se escribe nada.`);
}

// ── Comandos ──
function cmdValidar({ candidato }, log = console.log) {
  const v = validarCandidato(candidato);
  imprimirValidacion(candidato, v, log);
  return { ok: v.ok };
}

function cmdSwap({ candidato, activo, confirmar, gate = true }, log = console.log) {
  const rCand = path.resolve(candidato);
  const rActivo = path.resolve(activo);

  if (rCand === rActivo) {
    log("ABORTA: --candidato y --activo son la misma ruta.");
    return { ok: false };
  }
  if (!fs.existsSync(rActivo)) {
    log(`ABORTA: el activo no existe (${rActivo}). El swap reemplaza un archivo de producción existente — verifica la ruta.`);
    return { ok: false };
  }

  // Gate obligatorio: autotest completo antes de cualquier escritura real.
  if (confirmar && gate) {
    const r = runAutotest(() => {});
    if (!r.ok) {
      log(`ABORTA: gate de autotest FALLÓ (${r.pass}/${r.total}). Corre \`autotest\` para el detalle. No se toca nada.`);
      return { ok: false };
    }
    log(`GATE: autotest ${r.pass}/${r.total} PASS`);
  }

  const v = validarCandidato(rCand);
  imprimirValidacion(rCand, v, log);
  if (!v.ok) return { ok: false };

  const hashActivoAntes = sha256(rActivo);
  const hashCandidato = sha256(rCand);
  const backup = rutaBackupLibre(rActivo);
  const manifest = rutaManifest(rActivo);

  if (!confirmar) {
    log("");
    log("DRY-RUN (sin --confirmar) — plan del swap, nada se escribe:");
    log(`  activo:    ${rActivo}`);
    log(`             sha256 ${hashActivoAntes.slice(0, 16)}…`);
    log(`  candidato: ${rCand}`);
    log(`             sha256 ${hashCandidato.slice(0, 16)}…`);
    log(`  backup →   ${backup}`);
    log(`  manifest → ${manifest}`);
    log("  Para ejecutar de verdad: agregar --confirmar (corre el autotest como gate).");
    return { ok: true };
  }

  if (fs.existsSync(manifest)) {
    log(`ABORTA: ya existe un manifest de swap (${manifest}). Resuélvelo primero: \`rollback\` para deshacer ese swap, o archívalo a mano si ya quedó bien.`);
    return { ok: false };
  }

  // 1. Backup verificado
  fs.copyFileSync(rActivo, backup);
  if (sha256(backup) !== hashActivoAntes) {
    log(`ABORTA: el backup no coincide con el activo (disco inestable). Backup sospechoso en ${backup} — no se siguió.`);
    return { ok: false };
  }

  // 2. Manifest ANTES de mutar el activo: si el swap muere a medias, el rollback ya está listo.
  const mf = {
    script: "swap_capa2_produccion.mjs",
    creado: new Date().toISOString(),
    estado: "en_progreso",
    activo: rActivo,
    candidato: rCand,
    backup,
    sha256_activo_antes: hashActivoAntes,
    sha256_candidato: hashCandidato,
  };
  fs.writeFileSync(manifest, JSON.stringify(mf, null, 2) + "\n", "utf8");

  // 3. Copia atómica (único punto de mutación del activo)
  copiaAtomica(rCand, rActivo);

  // 4. Verificación post-swap
  const hashDespues = sha256(rActivo);
  if (hashDespues !== hashCandidato) {
    log(`FALLA POST-SWAP: el activo no coincide con el candidato. Rollback inmediato: node motor2/swap_capa2_produccion.mjs rollback --activo "${activo}" --confirmar`);
    return { ok: false };
  }
  const releido = JSON.parse(fs.readFileSync(rActivo, "utf8"));
  const nIds = idsQueMotor1Extraeria(releido.criterios || []).size;

  mf.estado = "completado";
  mf.completado = new Date().toISOString();
  mf.sha256_activo_despues = hashDespues;
  fs.writeFileSync(manifest, JSON.stringify(mf, null, 2) + "\n", "utf8");

  log("");
  log(`OK: swap completado. El activo ahora es el candidato (byte a byte, sha256 verificado).`);
  log(`  Motor 1 extraería ${nIds} ids de la nueva capa2.`);
  log(`  Backup:   ${backup}`);
  log(`  Manifest: ${manifest}`);
  log(`  Rollback de un comando: node motor2/swap_capa2_produccion.mjs rollback --activo "${activo}" --confirmar`);
  return { ok: true };
}

function cmdRollback({ activo, confirmar, gate = true }, log = console.log) {
  const rActivo = path.resolve(activo);
  const manifest = rutaManifest(rActivo);

  if (!fs.existsSync(manifest)) {
    log(`ABORTA: no hay manifest de swap (${manifest}) — nada que revertir automáticamente.`);
    const dir = path.dirname(rActivo);
    const base = path.basename(rActivo);
    const baks = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => f.startsWith(`${base}.bak-swap-`)) : [];
    if (baks.length) log(`  Backups de swap encontrados (restauración manual si hace falta): ${baks.join(", ")}`);
    return { ok: false };
  }

  let mf;
  try {
    mf = JSON.parse(fs.readFileSync(manifest, "utf8"));
  } catch (e) {
    log(`ABORTA: manifest corrupto (${e.message}). Restauración manual desde el .bak-swap-* correspondiente.`);
    return { ok: false };
  }

  if (!mf.backup || !fs.existsSync(mf.backup)) {
    log(`ABORTA: el backup del manifest no existe (${mf.backup}). No hay de dónde restaurar.`);
    return { ok: false };
  }
  const hashBackup = sha256(mf.backup);
  if (hashBackup !== mf.sha256_activo_antes) {
    log("ABORTA: sha256 del backup NO coincide con el manifest — el backup fue alterado o no es de este swap. No se restaura basura.");
    return { ok: false };
  }

  if (!confirmar) {
    log("DRY-RUN (sin --confirmar) — plan del rollback, nada se escribe:");
    log(`  restaurar ${mf.backup}`);
    log(`  →  sobre  ${rActivo}`);
    log(`  sha256 esperado tras restaurar: ${mf.sha256_activo_antes.slice(0, 16)}… (verificado contra el backup: coincide)`);
    log("  Para ejecutar de verdad: agregar --confirmar.");
    return { ok: true };
  }

  if (gate) {
    const r = runAutotest(() => {});
    if (!r.ok) {
      log(`ABORTA: gate de autotest FALLÓ (${r.pass}/${r.total}). No se toca nada.`);
      return { ok: false };
    }
    log(`GATE: autotest ${r.pass}/${r.total} PASS`);
  }

  copiaAtomica(mf.backup, rActivo);
  if (sha256(rActivo) !== mf.sha256_activo_antes) {
    log("FALLA POST-ROLLBACK: el activo restaurado no coincide con el hash esperado. Revisar disco a mano — el backup sigue intacto.");
    return { ok: false };
  }

  const archivado = `${rActivo}.swap-manifest.rolled-back-${ts()}.json`;
  fs.renameSync(manifest, archivado);

  log(`OK: rollback completado — el activo volvió a su estado pre-swap (sha256 verificado).`);
  log(`  Backup conservado (auditoría): ${mf.backup}`);
  log(`  Manifest archivado: ${archivado}`);
  return { ok: true };
}

// ── Autotest ──
// Fixtures 100% sintéticos y marcados como tales (regla fija #1: jamás parecer conocimiento real).
function fxCriterio(n, extra = {}) {
  return {
    texto: `FIXTURE AUTOTEST — criterio sintético ${n}, no es conocimiento real`,
    peso: "MANDATORY",
    severidad: "GRAVE",
    condicion_libre: null,
    referencia_no_resuelta: false,
    pagina_origen: n,
    seccion_aplicable: null,
    etapa_aplicable: null,
    id: `fixture_autotest_criterio_${n}`,
    aliases: [`fixture ${n}`, `sintetico ${n}`],
    aplica_a: null,
    revisado_por_gerardo: true,
    ...extra,
  };
}

function fxCandidatoValido() {
  return {
    version: "1.1",
    etapa: "fixture_autotest_campana",
    vigencia_inicio: "2026-01-01",
    vigencia_fin: "2026-12-31",
    criterios: [fxCriterio(1), fxCriterio(2, { etapa_aplicable: ["E1", "E2"] }), fxCriterio(3, { peso: "RECOMMENDATION", severidad: "OBSERVACION" })],
    schema_version: "1.1",
    fecha_actualizacion: "2026-07-06",
    hash_contenido: "fixture-autotest",
  };
}

function fxActivoViejo() {
  return {
    version: "1.1",
    etapa: "fixture_autotest_campana_vieja",
    criterios: [fxCriterio(90), fxCriterio(91)],
    schema_version: "1.1",
    fecha_actualizacion: "2026-01-01",
    hash_contenido: "fixture-autotest-viejo",
  };
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

function snapshotDir(dir) {
  return fs.readdirSync(dir).sort().join("|");
}

// Cada caso recibe un subdirectorio limpio con activo.json + candidato.json ya escritos
// (el caso los muta según lo que prueba). silencio = logger que descarta todo.
const silencio = () => {};

const CASOS = [
  {
    nombre: "swap_valido_y_rollback",
    fn(dir, { activo, candidato }) {
      const hashOriginal = sha256(activo);
      const hashCandidato = sha256(candidato);

      // dry-run no escribe nada
      const antes = snapshotDir(dir);
      let r = cmdSwap({ candidato, activo, confirmar: false, gate: false }, silencio);
      assert(r.ok, "dry-run de candidato válido debería pasar");
      assert(snapshotDir(dir) === antes, "el dry-run creó o borró archivos");
      assert(sha256(activo) === hashOriginal, "el dry-run modificó el activo");

      // swap real
      r = cmdSwap({ candidato, activo, confirmar: true, gate: false }, silencio);
      assert(r.ok, "swap válido rechazado");
      assert(sha256(activo) === hashCandidato, "el activo no quedó igual al candidato");
      const manifest = JSON.parse(fs.readFileSync(rutaManifest(activo), "utf8"));
      assert(manifest.estado === "completado", "manifest sin estado completado");
      assert(fs.existsSync(manifest.backup) && sha256(manifest.backup) === hashOriginal, "backup ausente o distinto del original");

      // rollback feliz de un comando
      r = cmdRollback({ activo, confirmar: true, gate: false }, silencio);
      assert(r.ok, "rollback tras swap válido falló");
      assert(sha256(activo) === hashOriginal, "el rollback no restauró el original");
      assert(!fs.existsSync(rutaManifest(activo)), "el manifest no se archivó tras el rollback");
      assert(fs.existsSync(manifest.backup), "el backup se borró (debe conservarse)");
    },
  },
  {
    nombre: "rechaza_criterio_sin_id",
    fn: rechazoDeCandidato((c) => delete c.criterios[1].id),
  },
  {
    nombre: "rechaza_criterio_sin_aliases",
    fn: rechazoDeCandidato((c) => (c.criterios[0].aliases = [])),
  },
  {
    nombre: "rechaza_sin_clave_aplica_a",
    fn: rechazoDeCandidato((c) => delete c.criterios[2].aplica_a),
  },
  {
    nombre: "rechaza_colision_sin_resolver",
    // Mismo id en dos criterios y la 2ª instancia SIN confirmación explícita de Gerardo:
    // debe rechazar por la regla de colisión (no por el check global de revisado).
    fn: rechazoDeCandidato((c) => {
      c.criterios[1].id = c.criterios[0].id;
      delete c.criterios[1].revisado_por_gerardo;
    }),
  },
  {
    nombre: "acepta_id_compartido_confirmado",
    // Colapso intencional estilo Sesiones T/U: mismo id, TODAS las instancias revisadas
    // → válido, con aviso informativo (no bloquea el swap).
    fn(dir, { activo, candidato }) {
      const c = JSON.parse(fs.readFileSync(candidato, "utf8"));
      c.criterios[1].id = c.criterios[0].id; // ambas ya traen revisado_por_gerardo=true
      fs.writeFileSync(candidato, JSON.stringify(c, null, 2) + "\n", "utf8");
      const v = validarCandidato(candidato);
      assert(v.ok, `id compartido confirmado no debería rechazarse (errores: ${v.errores.join(" | ")})`);
      assert(v.warnings.some((w) => w.includes("id compartido confirmado")), "falta el aviso de id compartido");
      const r = cmdSwap({ candidato, activo, confirmar: true, gate: false }, silencio);
      assert(r.ok, "el swap con id compartido confirmado debería proceder");
      assert(sha256(activo) === sha256(candidato), "el activo no quedó igual al candidato");
    },
  },
  {
    nombre: "acepta_referencia_no_resuelta_null",
    // null = estado [AMBIGUO] del fix de Sesión I — es schema v1.2 legítimo.
    fn(dir, { candidato }) {
      const c = JSON.parse(fs.readFileSync(candidato, "utf8"));
      c.criterios[0].referencia_no_resuelta = null;
      fs.writeFileSync(candidato, JSON.stringify(c, null, 2) + "\n", "utf8");
      const v = validarCandidato(candidato);
      assert(v.ok, `referencia_no_resuelta=null no debería rechazarse (errores: ${v.errores.join(" | ")})`);
      assert(v.warnings.some((w) => w.includes("[AMBIGUO]")), "falta el aviso informativo de referencias ambiguas");
    },
  },
  {
    nombre: "rechaza_referencia_tipo_invalido",
    fn: rechazoDeCandidato((c) => (c.criterios[0].referencia_no_resuelta = "si")),
  },
  {
    nombre: "rechaza_json_corrupto",
    fn(dir, { activo, candidato }) {
      fs.writeFileSync(candidato, '{ "criterios": [ esto no es JSON', "utf8");
      verificarRechazo(dir, activo, candidato);
    },
  },
  {
    nombre: "rechaza_revisado_false",
    fn: rechazoDeCandidato((c) => (c.criterios[2].revisado_por_gerardo = false)),
  },
  {
    nombre: "rechaza_sin_schema_version",
    fn: rechazoDeCandidato((c) => delete c.schema_version),
  },
  {
    nombre: "rechaza_peso_invalido",
    fn: rechazoDeCandidato((c) => (c.criterios[0].peso = "OBLIGATORIO")),
  },
  {
    nombre: "rechaza_severidad_invalida",
    fn: rechazoDeCandidato((c) => (c.criterios[0].severidad = "CRITICA")),
  },
  {
    nombre: "rechaza_etapa_invalida",
    fn: rechazoDeCandidato((c) => (c.criterios[1].etapa_aplicable = ["E9"])),
  },
  {
    nombre: "rollback_medio_swap",
    fn(dir, { activo, candidato }) {
      // Simula un swap muerto a medias: backup + manifest en_progreso existen,
      // el activo quedó corrupto/truncado. El rollback debe restaurar el original.
      const hashOriginal = sha256(activo);
      const backup = rutaBackupLibre(activo);
      fs.copyFileSync(activo, backup);
      const mf = {
        script: "swap_capa2_produccion.mjs",
        creado: new Date().toISOString(),
        estado: "en_progreso",
        activo: path.resolve(activo),
        candidato: path.resolve(candidato),
        backup,
        sha256_activo_antes: hashOriginal,
        sha256_candidato: sha256(candidato),
      };
      fs.writeFileSync(rutaManifest(activo), JSON.stringify(mf, null, 2) + "\n", "utf8");
      fs.writeFileSync(activo, '{ "criterios": [ TRUNCADO A MEDIO SWAP', "utf8");

      const r = cmdRollback({ activo, confirmar: true, gate: false }, silencio);
      assert(r.ok, "rollback de medio swap falló");
      assert(sha256(activo) === hashOriginal, "el activo no volvió a su estado original");
      assert(!fs.existsSync(rutaManifest(activo)), "el manifest no se archivó");
    },
  },
  {
    nombre: "rollback_sin_manifest",
    fn(dir, { activo }) {
      const hashOriginal = sha256(activo);
      const antes = snapshotDir(dir);
      const r = cmdRollback({ activo, confirmar: true, gate: false }, silencio);
      assert(!r.ok, "rollback sin manifest debería fallar");
      assert(sha256(activo) === hashOriginal, "rollback sin manifest tocó el activo");
      assert(snapshotDir(dir) === antes, "rollback sin manifest creó archivos");
    },
  },
  {
    nombre: "rollback_backup_alterado",
    fn(dir, { activo, candidato }) {
      const hashOriginal = sha256(activo);
      const backup = rutaBackupLibre(activo);
      fs.copyFileSync(activo, backup);
      const mf = {
        estado: "en_progreso",
        activo: path.resolve(activo),
        backup,
        sha256_activo_antes: hashOriginal,
        sha256_candidato: sha256(candidato),
      };
      fs.writeFileSync(rutaManifest(activo), JSON.stringify(mf, null, 2) + "\n", "utf8");
      fs.appendFileSync(backup, "\nBASURA AGREGADA AL BACKUP", "utf8"); // backup ya no coincide

      const r = cmdRollback({ activo, confirmar: true, gate: false }, silencio);
      assert(!r.ok, "rollback con backup alterado debería abortar");
      assert(sha256(activo) === hashOriginal, "abortó pero igual tocó el activo");
      assert(fs.existsSync(rutaManifest(activo)), "abortó pero archivó el manifest");
    },
  },
  {
    nombre: "rechaza_candidato_igual_activo",
    fn(dir, { activo }) {
      const hashOriginal = sha256(activo);
      const r = cmdSwap({ candidato: activo, activo, confirmar: true, gate: false }, silencio);
      assert(!r.ok, "candidato==activo debería abortar");
      assert(sha256(activo) === hashOriginal, "abortó pero tocó el activo");
    },
  },
  {
    nombre: "rechaza_activo_inexistente",
    fn(dir, { candidato }) {
      const fantasma = path.join(dir, "no_existe.json");
      const antes = snapshotDir(dir);
      const r = cmdSwap({ candidato, activo: fantasma, confirmar: true, gate: false }, silencio);
      assert(!r.ok, "swap hacia activo inexistente debería abortar");
      assert(snapshotDir(dir) === antes, "abortó pero creó archivos");
    },
  },
];

// Patrón común: mutar el candidato → el swap --confirmar debe rechazar SIN tocar nada.
function rechazoDeCandidato(mutacion) {
  return function (dir, { activo, candidato }) {
    const c = JSON.parse(fs.readFileSync(candidato, "utf8"));
    mutacion(c);
    fs.writeFileSync(candidato, JSON.stringify(c, null, 2) + "\n", "utf8");
    verificarRechazo(dir, activo, candidato);
  };
}

function verificarRechazo(dir, activo, candidato) {
  const hashOriginal = sha256(activo);
  const antes = snapshotDir(dir);
  const rV = cmdValidar({ candidato }, silencio);
  assert(!rV.ok, "validar debería rechazar este candidato");
  const rS = cmdSwap({ candidato, activo, confirmar: true, gate: false }, silencio);
  assert(!rS.ok, "swap debería rechazar este candidato");
  assert(sha256(activo) === hashOriginal, "el rechazo modificó el activo");
  assert(snapshotDir(dir) === antes, "el rechazo creó backup/manifest (debe rechazar ANTES de escribir)");
}

function runAutotest(log = console.log) {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), "swap-capa2-autotest-"));
  let pass = 0;
  const fallos = [];
  try {
    for (const caso of CASOS) {
      const dir = path.join(raiz, caso.nombre);
      fs.mkdirSync(dir);
      const activo = path.join(dir, "activo.json");
      const candidato = path.join(dir, "candidato.json");
      fs.writeFileSync(activo, JSON.stringify(fxActivoViejo(), null, 2) + "\n", "utf8");
      fs.writeFileSync(candidato, JSON.stringify(fxCandidatoValido(), null, 2) + "\n", "utf8");
      try {
        caso.fn(dir, { activo, candidato });
        pass++;
        log(`  PASS ${caso.nombre}`);
      } catch (e) {
        fallos.push(`${caso.nombre}: ${e.message}`);
        log(`  FAIL ${caso.nombre} — ${e.message}`);
      }
    }
  } finally {
    try {
      fs.rmSync(raiz, { recursive: true, force: true });
    } catch {
      log(`  (no se pudo borrar el sandbox ${raiz} — inspeccionable a mano)`);
    }
  }
  return { ok: fallos.length === 0, pass, total: CASOS.length, fallos };
}

// ── CLI ──
function ayuda() {
  console.log(`swap_capa2_produccion.mjs — swap controlado de la capa2 de producción (Sesión W)

Comandos:
  autotest                                        corre los ${CASOS.length} casos del gate en sandbox temporal
  validar  --candidato <ruta>                     valida un candidato (solo lectura)
  swap     --candidato <ruta> --activo <ruta>     dry-run del swap; con --confirmar lo ejecuta
  rollback --activo <ruta>                        dry-run del rollback; con --confirmar lo ejecuta

Sin --confirmar NADA se escribe. Con --confirmar, el autotest corre primero como gate
obligatorio y la operación aborta si un solo caso falla.

Swap real (SOLO con autorización explícita de Gerardo):
  node motor2/swap_capa2_produccion.mjs swap --candidato motor2/capa2_validado_final.json --activo pipeline/knowledge/capa2_campana_activa.json --confirmar`);
}

function main() {
  const [, , cmd, ...resto] = process.argv;
  const flags = { confirmar: false };
  for (let i = 0; i < resto.length; i++) {
    const a = resto[i];
    if (a === "--confirmar") flags.confirmar = true;
    else if (a === "--candidato" || a === "--activo") {
      const v = resto[++i];
      if (!v || v.startsWith("--")) {
        console.error(`ABORTA: ${a} requiere una ruta.`);
        process.exit(2);
      }
      flags[a.slice(2)] = v;
    } else {
      console.error(`ABORTA: argumento desconocido ${JSON.stringify(a)}.`);
      ayuda();
      process.exit(2);
    }
  }

  const exige = (campo) => {
    if (!flags[campo]) {
      console.error(`ABORTA: falta --${campo} (sin defaults a propósito — la ruta de producción siempre se escribe explícita).`);
      process.exit(2);
    }
  };

  let ok;
  switch (cmd) {
    case "autotest": {
      console.log(`Autotest (${CASOS.length} casos, sandbox en dir temporal del sistema):`);
      const r = runAutotest();
      console.log(r.ok ? `RESULTADO: ${r.pass}/${r.total} PASS` : `RESULTADO: ${r.pass}/${r.total} — FALLARON: ${r.fallos.length}`);
      ok = r.ok;
      break;
    }
    case "validar":
      exige("candidato");
      ok = cmdValidar(flags).ok;
      break;
    case "swap":
      exige("candidato");
      exige("activo");
      ok = cmdSwap(flags).ok;
      break;
    case "rollback":
      exige("activo");
      ok = cmdRollback(flags).ok;
      break;
    default:
      ayuda();
      process.exit(cmd ? 2 : 0);
  }
  process.exit(ok ? 0 : 1);
}

main();
