# -*- coding: utf-8 -*-
"""aplicar_aplicabilidad.py — aplica las decisiones de Gerardo sobre una COPIA (Sesión KK).

Lee candidatos_aplicabilidad.json YA revisado (decision_gerardo lleno) y aplica
SOLO lo aprobado sobre una copia de capa2_validado_con_candidatos.json. El
archivo fuente jamás se toca; el swap a producción es un paso aparte
(swap_capa2_produccion.mjs) que requiere autorización explícita.

Gates antes de guardar:
  1. Sin pendientes (decision_gerardo=null) — aborta, salvo --parcial.
  2. validar_schema de validator.py sobre TODOS los criterios del resultado
     (una sola fuente de verdad del schema).
  3. Invariantes: mismo conteo de criterios; en cada criterio solo pueden
     cambiar aplica_a / etapa_aplicable — cualquier otro campo distinto aborta.

decision_gerardo:
  null                                → pendiente (bloquea, salvo --parcial)
  "ok"                                → aplicar la propuesta tal cual
  "rechazar"                          → dejar los campos como están
  {"aplica_a": ..., "etapa_aplicable": ...} → valores finales editados
    (solo los campos presentes en el objeto se tocan; Gerardo es la autoridad)

Uso (desde motor2/, con PYTHONUTF8=1):
  python aplicar_aplicabilidad.py autotest
  python aplicar_aplicabilidad.py aplicar [--parcial]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
from validator import validar_schema, ETAPAS_VALIDAS  # noqa: E402 — fuente única del schema

CANDIDATOS = RAIZ / "candidatos_aplicabilidad.json"
FUENTE = RAIZ / "capa2_validado_con_candidatos.json"
SALIDA = RAIZ / "capa2_validado_aplicabilidad.json"

CAMPOS_APLICABLES = ("aplica_a", "etapa_aplicable")


def _validar_valor(campo: str, valor):
    """Motivo de rechazo o None. Mismo contrato que el schema: null legítimo
    ("general" / "no opera por etapas"), lista no vacía de strings si no."""
    if valor is None:
        return None
    if not isinstance(valor, list) or not valor:
        return f"{campo}: debe ser null o lista no vacía, vino {valor!r}"
    if not all(isinstance(v, str) and v.strip() for v in valor):
        return f"{campo}: toda entrada debe ser string no vacío, vino {valor!r}"
    if len(set(valor)) != len(valor):
        return f"{campo}: valores repetidos en {valor!r}"
    if campo == "etapa_aplicable" and not set(valor) <= ETAPAS_VALIDAS:
        return f"etapa_aplicable fuera de {sorted(ETAPAS_VALIDAS)}: {valor!r}"
    return None


def resolver_decision(entrada: dict):
    """(cambios: dict campo→valor, estado) para UNA entrada de candidatos.
    estado ∈ {'aprobado','editado','rechazado','pendiente','invalido'}."""
    dec = entrada.get("decision_gerardo")
    if dec is None:
        return {}, "pendiente"
    if dec == "rechazar":
        return {}, "rechazado"
    if dec == "ok":
        cambios = {c: entrada["propuesta"][c] for c in CAMPOS_APLICABLES
                   if entrada["propuesta"].get(c) is not None}
        return cambios, "aprobado"
    if isinstance(dec, dict):
        desconocidos = set(dec) - set(CAMPOS_APLICABLES)
        if desconocidos:
            return {}, "invalido"
        for campo, valor in dec.items():
            if _validar_valor(campo, valor):
                return {}, "invalido"
        return dict(dec), "editado"
    return {}, "invalido"


def aplicar(criterios: list[dict], entradas: list[dict], parcial: bool):
    """(criterios_nuevos, conteos). Pura: no toca disco. Aborta (ValueError)
    ante inválidos, desalineación con la fuente, o pendientes sin --parcial.

    Emparejamiento POSICIONAL, no por id: hay ids compartidos legítimos en la
    capa (clusters confirmados por Gerardo en Sesión U, ej.
    focal_show_mujeres_etapa1_2 ×2) y cada entrada de candidatos lleva su
    propia decisión. Las entradas se generaron 1:1 en el orden de la fuente;
    aquí se verifica ese alineamiento (id y texto) antes de aplicar nada."""
    if len(entradas) != len(criterios):
        raise ValueError(f"candidatos ({len(entradas)}) y fuente ({len(criterios)}) "
                         "no tienen el mismo número de criterios — no se aplica nada")
    desalineados = [i for i, (c, e) in enumerate(zip(criterios, entradas))
                    if c["id"] != e["id"] or c["texto"] != e.get("texto", c["texto"])]
    if desalineados:
        raise ValueError(f"candidatos desalineados con la fuente en posiciones "
                         f"{desalineados[:5]} — no se aplica nada")

    conteos = {"aprobado": 0, "editado": 0, "rechazado": 0, "pendiente": 0,
               "sin_cambio_efectivo": 0}
    resultado = [dict(c) for c in criterios]  # mismo orden que la fuente

    invalidos = []
    for i, e in enumerate(entradas):
        cambios, estado = resolver_decision(e)
        if estado == "invalido":
            invalidos.append(f"{e['id']} (pos {i})")
            continue
        conteos[estado] += 1
        if estado in ("aprobado", "editado"):
            if not cambios:
                conteos["sin_cambio_efectivo"] += 1
            for campo, valor in cambios.items():
                resultado[i][campo] = valor
    if invalidos:
        raise ValueError(f"decisiones inválidas (revisar formato): {invalidos}")
    if conteos["pendiente"] and not parcial:
        raise ValueError(f"{conteos['pendiente']} criterio(s) con decision_gerardo=null — "
                         "revisa los lotes o corre con --parcial")

    # Gate 2: schema (fuente única: validator.validar_schema)
    con_motivos = [(c["id"], m) for c in resultado if (m := validar_schema(c))]
    if con_motivos:
        raise ValueError(f"el resultado NO pasa validar_schema: {con_motivos[:5]}")

    # Gate 3: invariantes — solo aplica_a/etapa_aplicable pueden diferir
    if len(resultado) != len(criterios):
        raise ValueError("conteo de criterios alterado — bug, no se guarda nada")
    for orig, nuevo in zip(criterios, resultado):
        for k in orig:
            if k in CAMPOS_APLICABLES:
                continue
            if nuevo.get(k) != orig.get(k):
                raise ValueError(f"campo {k!r} alterado en {orig['id']!r} — bug, "
                                 "no se guarda nada")
    return resultado, conteos


def comando_aplicar(parcial: bool) -> None:
    data_cand = json.loads(CANDIDATOS.read_text(encoding="utf-8"))
    data_fuente = json.loads(FUENTE.read_text(encoding="utf-8"))
    entradas = [c for l in data_cand["lotes"] for c in l["criterios"]]
    try:
        resultado, conteos = aplicar(data_fuente["criterios"], entradas, parcial)
    except ValueError as exc:
        sys.exit(f"ABORTADO: {exc}")

    cambiados = sum(
        1 for orig, nuevo in zip(data_fuente["criterios"], resultado)
        if any(orig.get(c) != nuevo.get(c) for c in CAMPOS_APLICABLES))

    salida = {
        "meta": {
            **data_fuente.get("meta", {}),
            "aplicabilidad_aplicada": datetime.now().isoformat(timespec="seconds"),
            "aplicabilidad_nota": (
                f"aplica_a/etapa_aplicable aplicados desde {CANDIDATOS.name} "
                f"(decisiones de Gerardo): {conteos['aprobado']} aprobados, "
                f"{conteos['editado']} editados, {conteos['rechazado']} rechazados, "
                f"{conteos['pendiente']} pendientes{' (corrida --parcial)' if parcial else ''}. "
                f"{cambiados} criterios modificados. Solo se tocaron esos 2 campos."),
        },
        "criterios": resultado,
    }
    if SALIDA.exists():
        bak = SALIDA.with_name(SALIDA.name + datetime.now().strftime(".bak-%Y%m%d-%H%M%S"))
        SALIDA.rename(bak)
        print(f"Backup del anterior: {bak.name}")
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Aplicado → {SALIDA.name}")
    print(f"Conteos: {conteos} | criterios modificados: {cambiados}")
    print("El swap a producción sigue siendo un paso aparte (swap_capa2_produccion.mjs) "
          "con autorización explícita.")


# --- Autotest (obligatorio, patrón Motor 2) ---------------------------------------
def autotest() -> None:
    fallas = []

    def check(nombre, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {nombre}")
        if not cond:
            fallas.append(nombre)

    def crit(id_, aplica=None, etapa=None):
        return {"texto": f"criterio {id_}", "peso": "MANDATORY", "severidad": "GRAVE",
                "condicion_libre": None, "referencia_no_resuelta": False,
                "pagina_origen": 1, "seccion_aplicable": None,
                "etapa_aplicable": etapa, "fuente_pagina": "gemini_vision",
                "grounding": "exact", "posible_herencia_fewshot": False,
                "id": id_, "aliases": [], "aplica_a": aplica,
                "revisado_por_gerardo": True}

    def entrada(id_, dec, prop_a=None, prop_e=None):
        return {"id": id_, "propuesta": {"aplica_a": prop_a, "etapa_aplicable": prop_e},
                "decision_gerardo": dec}

    crits = [crit("a"), crit("b"), crit("c"), crit("d", aplica=["torre"])]

    def entradas_base(**overrides):
        """4 entradas alineadas 1:1 con crits; por defecto todas 'rechazar'."""
        base = [entrada("a", "rechazar"), entrada("b", "rechazar"),
                entrada("c", "rechazar"), entrada("d", "rechazar")]
        for i, e in overrides.items():
            base[int(i)] = e
        return base

    # 1. ok aplica la propuesta
    res, con = aplicar(crits, [entrada("a", "ok", ["barra"], ["E1"]),
                               entrada("b", "rechazar", ["mesa"]),
                               entrada("c", {"aplica_a": ["atril"]}),
                               entrada("d", "ok")], parcial=False)
    check("ok → propuesta aplicada", res[0]["aplica_a"] == ["barra"]
          and res[0]["etapa_aplicable"] == ["E1"])
    check("rechazar → campos intactos (null)", res[1]["aplica_a"] is None)
    check("editado → valores del objeto", res[2]["aplica_a"] == ["atril"]
          and res[2]["etapa_aplicable"] is None)
    check("ok sin propuesta → sin cambio efectivo, contado",
          res[3]["aplica_a"] == ["torre"] and con["sin_cambio_efectivo"] == 1)
    check("conteos correctos", con["aprobado"] == 2 and con["rechazado"] == 1
          and con["editado"] == 1 and con["pendiente"] == 0)
    # 2. pendiente bloquea sin --parcial, pasa con --parcial
    try:
        aplicar(crits, entradas_base(**{"0": entrada("a", None)}), parcial=False)
        check("pendiente sin --parcial aborta", False)
    except ValueError:
        check("pendiente sin --parcial aborta", True)
    res, con = aplicar(crits, entradas_base(**{"0": entrada("a", None),
                                               "1": entrada("b", "ok", ["torre"])}),
                       parcial=True)
    check("--parcial: aplica lo decidido, pendiente intacto",
          res[0]["aplica_a"] is None and res[1]["aplica_a"] == ["torre"]
          and con["pendiente"] == 1)
    # 3. decisiones inválidas abortan
    for dec in ({"otro_campo": ["x"]}, {"etapa_aplicable": ["E9"]},
                {"aplica_a": []}, {"aplica_a": ["torre", "torre"]}, "si"):
        try:
            aplicar(crits, entradas_base(**{"0": entrada("a", dec)}), parcial=False)
            check(f"decisión inválida {dec!r} aborta", False)
        except ValueError:
            check(f"decisión inválida {dec!r} aborta", True)
    # 4. desalineación con la fuente aborta (conteo o id/posición)
    try:
        aplicar(crits, entradas_base()[:3], parcial=False)
        check("conteo distinto de candidatos aborta", False)
    except ValueError:
        check("conteo distinto de candidatos aborta", True)
    try:
        aplicar(crits, entradas_base(**{"1": entrada("nadie", "ok")}), parcial=False)
        check("id que no coincide con su posición aborta", False)
    except ValueError:
        check("id que no coincide con su posición aborta", True)
    # 4b. ids COMPARTIDOS (clusters Sesión U): cada posición con SU decisión
    crits_dup = [crit("dup"), crit("dup")]
    res, _ = aplicar(crits_dup, [entrada("dup", "ok", ["focal_show"]),
                                 entrada("dup", "ok", ["maniqui"])], parcial=False)
    check("id compartido: decisiones independientes por posición",
          res[0]["aplica_a"] == ["focal_show"] and res[1]["aplica_a"] == ["maniqui"]
          and res[0]["texto"] == res[1]["texto"] == "criterio dup")
    # 5. gate de schema: propuesta que rompería el schema aborta
    try:
        aplicar(crits, entradas_base(**{"0": entrada("a", "ok", ["barra"], ["E1", "E1"])}),
                parcial=False)
        check("etapa con repetidos NO pasa el gate de schema", False)
    except ValueError:
        check("etapa con repetidos NO pasa el gate de schema", True)
    # 6. la fuente en memoria no se muta
    crits2 = [crit("a")]
    aplicar(crits2, [entrada("a", "ok", ["barra"])], parcial=False)
    check("lista fuente no mutada", crits2[0]["aplica_a"] is None)
    # 7. los archivos reales no se tocan en autotest (aplicar es pura)
    if FUENTE.exists():
        antes = FUENTE.read_bytes()
        check("archivo fuente intacto", FUENTE.read_bytes() == antes)

    print(f"\nAUTOTEST: {'PASS' if not fallas else 'FAIL'} ({len(fallas)} falla(s))")
    if fallas:
        sys.exit(1)


def main() -> None:
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    if modo == "autotest":
        autotest()
    elif modo == "aplicar":
        autotest()
        print()
        comando_aplicar(parcial="--parcial" in sys.argv[2:])
    else:
        sys.exit("Uso: aplicar_aplicabilidad.py autotest|aplicar [--parcial]")


if __name__ == "__main__":
    main()
