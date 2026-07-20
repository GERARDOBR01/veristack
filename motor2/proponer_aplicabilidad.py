# -*- coding: utf-8 -*-
"""proponer_aplicabilidad.py — candidatos de aplica_a / etapa_aplicable (Sesión KK).

Cierra el lado DATO de GC-delegacion: 126/148 criterios de capa2 con
etapa_aplicable=null y 138/148 con aplica_a=null hacen que el filtro de
retrieval_engine (que YA existe y opera) deje pasar todo → ~10 lotes/foto.
Este script PROPONE valores; Gerardo decide lote por lote. Nunca escribe
sobre el JSON validado.

Reparto ("código decide, modelo interpreta"):
  - Fase heurística (sin cuota): keywords deterministas sobre texto +
    condicion_libre. Vocabulario = valores ya curados (torre/atril/barra) +
    tipos del pipeline (focal_show/tringla/mesa_show) + menciones literales
    de elementos del manual. Etapas SOLO si el texto las nombra explícito.
  - Fase IA (solo ambiguos, batcheada): Gemini REST con fallback GitHub
    Models. La IA puede responder sin evidencia (null) — se respeta.

Principio clave (Gerardo, 19 Jul): la Gran Barata es solo la campaña base —
otras campañas NO operan por etapas. etapa_aplicable=null es un valor
LEGÍTIMO ("todas / no opera por etapas"); la propuesta jamás fuerza etapa.

Uso (desde motor2/, con PYTHONUTF8=1):
  python proponer_aplicabilidad.py autotest
  python proponer_aplicabilidad.py heuristica   # genera candidatos_aplicabilidad.json
  python proponer_aplicabilidad.py ia           # completa ambiguos (gasta cuota)

decision_gerardo (por criterio, en candidatos_aplicabilidad.json):
  null                          → pendiente de revisión
  "ok"                          → aplicar la propuesta tal cual
  "rechazar"                    → dejar los campos como están (null = general)
  {"aplica_a": [...], "etapa_aplicable": [...]}  → valores finales editados
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

RAIZ = Path(__file__).resolve().parent
FUENTE = RAIZ / "capa2_validado_con_candidatos.json"
SALIDA = RAIZ / "candidatos_aplicabilidad.json"

TAM_LOTE = 15
ETAPAS_VALIDAS = {"E1", "E2", "E3"}

# --- Vocabulario aplica_a ---------------------------------------------------------
# Orden IMPORTA: patrones más largos primero ("mesa show" antes que "mesa").
# Solo elementos de exhibición reales del manual — no se inventa taxonomía;
# lo que no esté aquí queda para la fase IA o para Gerardo.
# NOTA: "cuenta" se excluye a propósito (colisiona con el verbo "cuenta con").
VOCAB_ELEMENTOS = [
    (r"\bMESA\s+SHOW\b", "mesa_show"),
    (r"\bFOCAL\s+SHOW\b", "focal_show"),
    (r"\bTORRES?\b", "torre"),
    (r"\bATRIL(?:ES)?\b", "atril"),
    (r"\bBARRAS?\b", "barra"),
    (r"\bCOLUMNAS?\b", "columna"),
    (r"\bTRINGLAS?\b", "tringla"),
    (r"\bMESAS?\b", "mesa"),
    (r"\bZAPATERAS?\b", "zapatera"),  # aprobada por Gerardo en Lote 2 (19 Jul)
    (r"\bFOCAL(?:ES)?\b", "focal_show"),
    (r"\bMANIQUI(?:ES)?\b", "maniqui"),
]

# --- Patrones de etapa (mismos del manual que extractor.detectar_etapas + formas
#     que aparecen dentro del TEXTO de los criterios: "primera etapa", "2da etapa") -
_PATRONES_ETAPA = [
    r"ETAPA\s*(\d)\s*Y\s*(\d)",                      # "ETAPA 2 Y 3"
    r"(\d)[°ª]?\w{0,3}\s*[YO]\s*(\d)[°ª]?\w{0,3}\s*ETAPA",  # "1a y 2da ETAPA", "1° ó 2° etapa" (Lote 5)
    r"(?:PRIMERA|1[°ª]?\w{0,3})\s*ETAPA()",          # "primera etapa" → 1
    r"(?:SEGUNDA|2[°ª]?\w{0,3})\s*ETAPA()",          # "2da etapa" → 2
    r"(?:TERCERA|3[°ª]?\w{0,3})\s*ETAPA()",          # "3era etapa" → 3
    r"ETAPA\s*(\d)",                                 # "ETAPA 3"
]
_ETAPA_ORDINAL = {2: "1", 3: "2", 4: "3"}  # índice de patrón → dígito implícito


def _sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def detectar_elementos(texto: str, condicion: Optional[str]):
    """([valores aplica_a], motivo, confianza) o (None, None, None).

    condicion_libre pesa como fuente de confianza ALTA (es el encabezado del
    bloque en el manual, ej. "BARRAS"); el texto del criterio también es alta.
    """
    hallados: list[str] = []
    citas: list[str] = []
    for origen, crudo in (("condicion_libre", condicion or ""), ("texto", texto or "")):
        up = _sin_acentos(crudo).upper()
        for patron, valor in VOCAB_ELEMENTOS:
            m = re.search(patron, up)
            if not m:
                continue
            # Consumir el span: "MESA SHOW" no debe re-matchear como "MESA"
            up = up[:m.start()] + " " * (m.end() - m.start()) + up[m.end():]
            if valor not in hallados:
                hallados.append(valor)
                citas.append(f'{origen}: "{m.group(0).strip()}"')
    if not hallados:
        return None, None, None
    return hallados, "; ".join(citas), "alta"


def detectar_etapas_texto(texto: str, condicion: Optional[str]):
    """(["E1"..], motivo) o (None, None). SOLO menciones explícitas — nunca
    infiere etapa de porcentajes ni de contexto. null = no opera por etapas."""
    for crudo, origen in ((condicion or "", "condicion_libre"), (texto or "", "texto")):
        up = _sin_acentos(crudo).upper()
        for i, patron in enumerate(_PATRONES_ETAPA):
            m = re.search(patron, up)
            if not m:
                continue
            grupos = [g for g in m.groups() if g]  # los patrones ordinales dan grupo vacío
            if not grupos and i in _ETAPA_ORDINAL:
                grupos = [_ETAPA_ORDINAL[i]]
            etapas = [f"E{g}" for g in grupos]
            if not etapas or not set(etapas) <= ETAPAS_VALIDAS:
                continue  # "5ta etapa" u otra cosa fuera de vocabulario: no se propone
            return etapas, f'{origen}: "{m.group(0).strip()}"'
    return None, None


def proponer_criterio(crit: dict) -> dict:
    """Entrada de candidatos para UN criterio. No modifica el criterio fuente."""
    ya_aplica = crit.get("aplica_a") is not None
    ya_etapa = crit.get("etapa_aplicable") is not None
    entrada = {
        "id": crit["id"],
        "pagina_origen": crit.get("pagina_origen"),
        "texto": crit["texto"],
        "condicion_libre": crit.get("condicion_libre"),
        "actual": {"aplica_a": crit.get("aplica_a"),
                   "etapa_aplicable": crit.get("etapa_aplicable")},
        "propuesta": {"aplica_a": None, "etapa_aplicable": None},
        "origen": "sin_propuesta",
        "confianza": None,
        "motivo": None,
        "decision_gerardo": None,
    }
    if ya_aplica and ya_etapa:
        entrada["origen"] = "ya_curado"
        entrada["motivo"] = "ambos campos ya curados por Gerardo — no se propone nada"
        return entrada

    motivos = []
    if not ya_aplica:
        elems, motivo_e, conf = detectar_elementos(crit["texto"], crit.get("condicion_libre"))
        if elems:
            entrada["propuesta"]["aplica_a"] = elems
            entrada["origen"] = "heuristica"
            entrada["confianza"] = conf
            motivos.append(f"aplica_a ← {motivo_e}")
    if not ya_etapa:
        etapas, motivo_t = detectar_etapas_texto(crit["texto"], crit.get("condicion_libre"))
        if etapas:
            entrada["propuesta"]["etapa_aplicable"] = etapas
            entrada["origen"] = "heuristica"
            entrada["confianza"] = entrada["confianza"] or "alta"
            motivos.append(f"etapa_aplicable ← {motivo_t}")
    if motivos:
        entrada["motivo"] = "; ".join(motivos)
    if ya_aplica:
        motivos.append("aplica_a ya curado — se conserva")
    if ya_etapa:
        motivos.append("etapa_aplicable ya curado — se conserva")
    return entrada


def generar_candidatos(criterios: list[dict]) -> dict:
    entradas = [proponer_criterio(c) for c in criterios]
    lotes = []
    for i in range(0, len(entradas), TAM_LOTE):
        lotes.append({"lote": len(lotes) + 1, "criterios": entradas[i:i + TAM_LOTE]})
    cobertura = {
        "total": len(entradas),
        "ya_curado": sum(1 for e in entradas if e["origen"] == "ya_curado"),
        "heuristica": sum(1 for e in entradas if e["origen"] == "heuristica"),
        "ia": sum(1 for e in entradas if e["origen"] == "ia"),
        "sin_propuesta": sum(1 for e in entradas if e["origen"] == "sin_propuesta"),
    }
    return {
        "meta": {
            "generado": datetime.now().isoformat(timespec="seconds"),
            "fuente": FUENTE.name,
            "nota": ("PROPUESTAS, no decisiones. decision_gerardo: null=pendiente, "
                     "\"ok\"=aplicar propuesta, \"rechazar\"=dejar null (general), "
                     "objeto {aplica_a, etapa_aplicable}=valores finales editados. "
                     "etapa_aplicable=null es LEGÍTIMO: no toda campaña opera por "
                     "etapas (la Gran Barata es solo la campaña base)."),
            "cobertura": cobertura,
        },
        "lotes": lotes,
    }


# --- Fase IA (solo ambiguos) ------------------------------------------------------
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "{model}:generateContent?key={key}")
GITHUB_MODEL = "openai/gpt-4o-mini"
GITHUB_URL = "https://models.github.ai/inference/chat/completions"
IA_TAM_LOTE = 20
IA_TIMEOUT_S = 90

PROMPT_IA = """Eres analista de manuales de retail. Para cada criterio de montaje \
de exhibición decide, SOLO con la evidencia del propio texto:
1. aplica_a: ¿el criterio aplica únicamente a elemento(s) específico(s) de \
exhibición (ej. torre, atril, barra, columna, mesa, tringla, focal_show, maniqui)? \
Si el texto no nombra ni implica un elemento concreto, responde null (= general).
2. etapa_aplicable: ¿el texto nombra explícitamente etapa(s) E1/E2/E3? Si no las \
nombra, responde null. OJO: null es correcto y frecuente — no toda campaña opera \
por etapas. NUNCA inventes.
Responde SOLO un array JSON: \
[{"id": "...", "aplica_a": ["..."] o null, "etapa_aplicable": ["E1"] o null, \
"motivo": "cita textual breve o 'sin evidencia'"}]

Criterios:
"""


def _leer_env(nombre: str):
    """Valor de una variable: entorno primero, luego .env de la raíz. Nunca la imprime."""
    import os
    if os.environ.get(nombre):
        return os.environ[nombre].strip()
    env_path = RAIZ.parent / ".env"
    if env_path.exists():
        m = re.search(rf"^\s*{nombre}\s*=\s*(.+)$",
                      env_path.read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def _claves_gemini() -> list[str]:
    """TODAS las GEMINI_API_KEY (entorno + todas las líneas del .env), sin
    duplicados — mismo contrato que la rotación del pipeline: cada key vive en
    su propio proyecto de Google, con cuota diaria independiente."""
    import os
    claves = []
    if os.environ.get("GEMINI_API_KEY", "").strip():
        claves.append(os.environ["GEMINI_API_KEY"].strip())
    env_path = RAIZ.parent / ".env"
    if env_path.exists():
        for v in re.findall(r"^\s*GEMINI_API_KEY\s*=\s*(.+)$",
                            env_path.read_text(encoding="utf-8"), re.M):
            v = v.strip().strip('"').strip("'")
            if v and v not in claves:
                claves.append(v)
    return claves


def _post_json(url: str, cuerpo: dict, headers: dict) -> dict:
    data = json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=IA_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _detalle_http(exc: Exception) -> str:
    """Código + snippet del body del error — sin esto el fallo es indiagnosticable."""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            body = ""
        return f"HTTP {exc.code}: {body}"
    return f"{type(exc).__name__}: {exc}"


def _llamar_ia(prompt: str) -> Optional[str]:
    """Texto de respuesta del modelo, o None. ROTA por todas las GEMINI_API_KEY
    ante 429/503 (cada key = proyecto = cuota propia); GitHub Models de fallback."""
    for n, key in enumerate(_claves_gemini(), 1):
        try:
            r = _post_json(
                GEMINI_URL.format(model=GEMINI_MODEL, key=key),
                {"contents": [{"parts": [{"text": prompt}]}],
                 "generationConfig": {"temperature": 0.0}},
                {})
            return r["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as exc:  # noqa: BLE001
            detalle = _detalle_http(exc)
            if "HTTP 429" in detalle or "HTTP 503" in detalle:
                print(f"  ⏳ Gemini key #{n} sin cuota/saturada — probando siguiente")
                continue
            print(f"  ⚠️ Gemini key #{n} falló ({detalle[:160]})")
            break
    else:
        print("  ⚠️ todas las keys Gemini agotadas — probando GitHub Models")
    key_gh = _leer_env("GITHUB_API_KEY")
    if not key_gh:
        print("  ⚠️ sin GITHUB_API_KEY — este lote queda sin propuesta IA")
        return None
    try:
        r = _post_json(
            GITHUB_URL,
            {"model": GITHUB_MODEL, "temperature": 0.0,
             "messages": [{"role": "user", "content": prompt}]},
            {"Authorization": f"Bearer {key_gh}"})
        return r["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ GitHub Models también falló ({_detalle_http(exc)[:160]})")
        return None


def parsear_respuesta_ia(texto: Optional[str]) -> Optional[list]:
    """Array de dicts con id, o None. Estricto: basura no se rescata aquí —
    un lote IA fallido simplemente queda sin_propuesta (honesto, sin inventar)."""
    if not texto:
        return None
    limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    try:
        parsed = json.loads(limpio)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, list):
        return None
    filas = [f for f in parsed if isinstance(f, dict) and f.get("id")]
    return filas or None


def _normalizar_lista(valor):
    """La IA puede devolver string en vez de lista; null se respeta."""
    if valor is None:
        return None
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list):
        return None
    limpios = [str(v).strip() for v in valor if str(v).strip()]
    return limpios or None


def aplicar_respuesta_ia(entradas: list[dict], filas: list[dict]) -> int:
    """Vuelca propuestas IA sobre entradas sin_propuesta. Ids desconocidos se
    ignoran. Etapas fuera de E1-E3 se descartan (código decide el vocabulario)."""
    por_id = {e["id"]: e for e in entradas if e["origen"] == "sin_propuesta"}
    aplicadas = 0
    for fila in filas:
        e = por_id.get(fila["id"])
        if e is None:
            continue
        aplica = _normalizar_lista(fila.get("aplica_a"))
        etapas = _normalizar_lista(fila.get("etapa_aplicable"))
        if etapas and not set(etapas) <= ETAPAS_VALIDAS:
            etapas = None
        # Solo cuenta lo que de verdad se aplicaría: un campo ya curado no se
        # pisa, y si tras eso no queda nada, es sin_evidencia efectiva.
        if e["actual"]["aplica_a"] is not None:
            aplica = None
        if e["actual"]["etapa_aplicable"] is not None:
            etapas = None
        if aplica is None and etapas is None:
            e["motivo"] = f"IA: sin evidencia ({fila.get('motivo', '')})".strip()
            continue  # sin_evidencia respetado: sigue sin_propuesta
        e["propuesta"]["aplica_a"] = aplica
        e["propuesta"]["etapa_aplicable"] = etapas
        e["origen"] = "ia"
        e["confianza"] = "media"
        e["motivo"] = f"IA: {fila.get('motivo', 'sin motivo')}"
        aplicadas += 1
    return aplicadas


def fase_ia() -> None:
    if not SALIDA.exists():
        sys.exit("ERROR: corre primero `heuristica` — no existe candidatos_aplicabilidad.json")
    data = json.loads(SALIDA.read_text(encoding="utf-8"))
    entradas = [c for l in data["lotes"] for c in l["criterios"]]
    pendientes = [e for e in entradas if e["origen"] == "sin_propuesta"]
    print(f"Fase IA: {len(pendientes)} criterios sin propuesta heurística")
    if not pendientes:
        return
    total_ok = 0
    for i in range(0, len(pendientes), IA_TAM_LOTE):
        grupo = pendientes[i:i + IA_TAM_LOTE]
        cuerpo = json.dumps(
            [{"id": e["id"], "texto": e["texto"],
              "condicion_libre": e["condicion_libre"],
              "pagina": e["pagina_origen"]} for e in grupo],
            ensure_ascii=False, indent=1)
        print(f"  request {i // IA_TAM_LOTE + 1} ({len(grupo)} criterios)…")
        filas = parsear_respuesta_ia(_llamar_ia(PROMPT_IA + cuerpo))
        if filas is None:
            print("  ⚠️ respuesta inválida/ausente — lote queda sin propuesta (no se inventa)")
            continue
        n = aplicar_respuesta_ia(entradas, filas)
        total_ok += n
        print(f"  ✓ {n} propuestas IA aplicadas")
        time.sleep(1)
    # Recontar cobertura y guardar
    cob = data["meta"]["cobertura"]
    cob["ia"] = sum(1 for e in entradas if e["origen"] == "ia")
    cob["sin_propuesta"] = sum(1 for e in entradas if e["origen"] == "sin_propuesta")
    data["meta"]["fase_ia"] = datetime.now().isoformat(timespec="seconds")
    SALIDA.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nListo: {total_ok} propuestas IA nuevas → {SALIDA.name}")
    print(f"Cobertura: {cob}")


def fase_heuristica() -> None:
    criterios = json.loads(FUENTE.read_text(encoding="utf-8"))["criterios"]
    data = generar_candidatos(criterios)
    SALIDA.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    cob = data["meta"]["cobertura"]
    print(f"Candidatos generados → {SALIDA.name} ({len(data['lotes'])} lotes de ≤{TAM_LOTE})")
    print(f"Cobertura: total={cob['total']}  ya_curado={cob['ya_curado']}  "
          f"heuristica={cob['heuristica']}  sin_propuesta={cob['sin_propuesta']} (van a IA)")


# --- Autotest (obligatorio, patrón Motor 2) ---------------------------------------
def autotest() -> None:
    fallas = []

    def check(nombre, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {nombre}")
        if not cond:
            fallas.append(nombre)

    def crit(texto, condicion=None, aplica=None, etapa=None, id_="x"):
        return {"texto": texto, "condicion_libre": condicion, "aplica_a": aplica,
                "etapa_aplicable": etapa, "id": id_, "pagina_origen": 1}

    # 1. keyword clara en texto
    e = proponer_criterio(crit("Imprimir una torre slim, mandar parche 50"))
    check("torre detectada en texto, confianza alta",
          e["propuesta"]["aplica_a"] == ["torre"] and e["confianza"] == "alta"
          and e["origen"] == "heuristica" and 'texto: "TORRE"' in e["motivo"])
    # 2. condicion_libre como fuente
    e = proponer_criterio(crit("Imprimir primera etapa 40% genérico", condicion="BARRAS"))
    check("barra desde condicion_libre + E1 desde texto",
          e["propuesta"]["aplica_a"] == ["barra"]
          and e["propuesta"]["etapa_aplicable"] == ["E1"])
    # 3. sin keyword → no inventa
    e = proponer_criterio(crit("Mantener el orden de la exhibición en todo momento"))
    check("sin keyword → sin_propuesta, nada inventado",
          e["origen"] == "sin_propuesta" and e["propuesta"]["aplica_a"] is None
          and e["propuesta"]["etapa_aplicable"] is None)
    # 4. variantes de etapa explícita
    et, _ = detectar_etapas_texto("2da etapa 100% beneficio", None)
    check('"2da etapa" → E2', et == ["E2"])
    et, _ = detectar_etapas_texto("3era etapa solo producir parches", None)
    check('"3era etapa" → E3', et == ["E3"])
    et, _ = detectar_etapas_texto("aplicar en ETAPA 2 Y 3", None)
    check('"ETAPA 2 Y 3" → E2+E3', et == ["E2", "E3"])
    et, _ = detectar_etapas_texto("vigente 1a y 2da ETAPA", None)
    check('"1a y 2da ETAPA" → E1+E2', et == ["E1", "E2"])
    et, _ = detectar_etapas_texto("Si el campamento se realiza en la 1° ó 2° etapa de la promoción", None)
    check('"1° ó 2° etapa" → E1+E2 (fix Lote 5)', et == ["E1", "E2"])
    et, _ = detectar_etapas_texto("aplicar en la 2° etapa", None)
    check('"2° etapa" → E2', et == ["E2"])
    # 5. campaña sin etapas → null respetado
    et, _ = detectar_etapas_texto("Arma una exhibición de vinos y licores por tiempo limitado", None)
    check("campaña sin etapas → null (legítimo)", et is None)
    # 6. etapa fuera de vocabulario
    et, _ = detectar_etapas_texto("la 5ta etapa del proyecto", None)
    check('"5ta etapa" fuera de vocabulario → null', et is None)
    # 7. ya curado → no se pisa
    e = proponer_criterio(crit("Torre con parche", aplica=["torre"], etapa=["E1"]))
    check("ambos campos curados → ya_curado, sin propuesta",
          e["origen"] == "ya_curado" and e["propuesta"]["aplica_a"] is None)
    e = proponer_criterio(crit("Torre con parche en 2da etapa", aplica=["torre"]))
    check("aplica_a curado se conserva; solo se propone etapa",
          e["propuesta"]["aplica_a"] is None
          and e["propuesta"]["etapa_aplicable"] == ["E2"])
    # 8. mesa show gana sobre mesa; focal → focal_show
    els, _, _ = detectar_elementos("montar la mesa show del área", None)
    check('"mesa show" → mesa_show (no "mesa")', els == ["mesa_show"])
    els, _, _ = detectar_elementos("para la creación del focal", None)
    check('"focal" → focal_show', els == ["focal_show"])
    els, _, _ = detectar_elementos("la gran barata inicia", None)
    check('"barata" NO dispara "barra"', els is None)
    els, _, _ = detectar_elementos("exhibidos en las zapateras o mesas", None)
    check('"zapateras o mesas" → ambas', els == ["mesa", "zapatera"] or els == ["zapatera", "mesa"])
    # 9. generar_candidatos: lotes y decision_gerardo
    data = generar_candidatos([crit(f"criterio {i}", id_=f"c{i}") for i in range(31)])
    check("31 criterios → 3 lotes (15/15/1)",
          len(data["lotes"]) == 3 and len(data["lotes"][2]["criterios"]) == 1)
    check("decision_gerardo=null en todos",
          all(c["decision_gerardo"] is None
              for l in data["lotes"] for c in l["criterios"]))
    check("cobertura suma el total",
          sum(v for k, v in data["meta"]["cobertura"].items() if k != "total") == 31)
    # 10. parseo de respuesta IA
    ok = parsear_respuesta_ia('```json\n[{"id": "a", "aplica_a": ["torre"], '
                              '"etapa_aplicable": null, "motivo": "x"}]\n```')
    check("respuesta IA válida con fences se parsea", ok is not None and ok[0]["id"] == "a")
    check("basura IA → None", parsear_respuesta_ia("esto no es json") is None)
    check("array sin ids → None", parsear_respuesta_ia("[1, 2, 3]") is None)
    # 11. aplicar_respuesta_ia: sin_evidencia respetado, id desconocido ignorado,
    #     etapa fuera de vocabulario descartada
    ents = [proponer_criterio(crit("criterio ambiguo uno", id_="amb1")),
            proponer_criterio(crit("criterio ambiguo dos", id_="amb2"))]
    n = aplicar_respuesta_ia(ents, [
        {"id": "amb1", "aplica_a": "torre", "etapa_aplicable": ["E9"], "motivo": "cita"},
        {"id": "amb2", "aplica_a": None, "etapa_aplicable": None, "motivo": "sin evidencia"},
        {"id": "fantasma", "aplica_a": ["barra"], "etapa_aplicable": None, "motivo": "x"},
    ])
    check("IA: string→lista, E9 descartada, 1 aplicada",
          n == 1 and ents[0]["propuesta"]["aplica_a"] == ["torre"]
          and ents[0]["propuesta"]["etapa_aplicable"] is None
          and ents[0]["origen"] == "ia" and ents[0]["confianza"] == "media")
    check("IA sin_evidencia → sigue sin_propuesta",
          ents[1]["origen"] == "sin_propuesta"
          and "sin evidencia" in (ents[1]["motivo"] or ""))
    # 11b. la IA re-propone un campo YA curado → no se pisa NI se marca "ia"
    ents2 = [proponer_criterio(crit("criterio con torre ya curada sin keyword nueva",
                                    aplica=["torre"], id_="cur1"))]
    ents2[0]["origen"] = "sin_propuesta"  # simular que la heurística no propuso etapa
    n2 = aplicar_respuesta_ia(ents2, [
        {"id": "cur1", "aplica_a": ["torre"], "etapa_aplicable": None, "motivo": "torre"}])
    check("IA sobre campo ya curado → sin_evidencia efectiva, no origen=ia",
          n2 == 0 and ents2[0]["origen"] == "sin_propuesta"
          and ents2[0]["propuesta"]["aplica_a"] is None)
    # 12. el archivo fuente jamás se toca en la generación
    antes = FUENTE.read_bytes() if FUENTE.exists() else None
    if antes is not None:
        generar_candidatos(json.loads(antes.decode("utf-8"))["criterios"])
        check("archivo fuente intacto tras generar", FUENTE.read_bytes() == antes)

    print(f"\nAUTOTEST: {'PASS' if not fallas else 'FAIL'} ({len(fallas)} falla(s))")
    if fallas:
        sys.exit(1)


def main() -> None:
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    if modo == "autotest":
        autotest()
    elif modo == "heuristica":
        autotest()
        print()
        fase_heuristica()
    elif modo == "ia":
        autotest()
        print()
        fase_ia()
    else:
        sys.exit("Uso: proponer_aplicabilidad.py autotest|heuristica|ia")


if __name__ == "__main__":
    main()
