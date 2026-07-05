# -*- coding: utf-8 -*-
"""Motor 2 — candidatos de id/aliases/aplica_a para capa2_validado (Sesión S).

Los 156 criterios de capa2_mecanica_montaje_gran_barata_pv_2026_validado.json
(Sesión P/Q) no tienen id/aliases — ese campo es curado a mano, según
convención confirmada en capa2_campana_activa.json (producción, ej. real:
"foto_puntos_focales" / ["fotos de focales", "fotografía prioridad"]).

Este script NO decide el id final. Genera CANDIDATOS deterministas (sin IA,
sin invención de texto) para que Gerardo apruebe o edite criterio por
criterio. Cada criterio queda con "revisado_por_gerardo": false.

Algoritmo (determinista, mismo criterio → mismo resultado siempre):
  id candidato:
    normalizar texto (sin acentos, minúsculas, solo [a-z0-9 ]) → tokenizar →
    descartar stopwords + tokens < 3 caracteres (EXCEPTO tokens puramente
    numéricos, que se preservan sin importar su longitud — fix Sesión V,
    ver nota junto a MIN_LARGO_TOKEN) → tomar hasta 5 keywords → unir con
    "_". Si no queda ninguna keyword, fallback "criterio_pXX_NN".
  aliases candidatos (1-2, ventana deslizante sobre las mismas keywords —
    NO es paráfrasis real, es una variante corta derivada del mismo texto;
    la paráfrasis con lenguaje natural queda para la revisión de Gerardo):
    alias 1 = keywords[0:2] unidas con espacio
    alias 2 = keywords[1:3] unidas con espacio, solo si es distinto de alias 1
  aplica_a candidato:
    null salvo que el texto mencione explícitamente un elemento físico
    (torre, atril, columna, barra) — en ese caso, lista con los que aparecen.

Colisiones de id (dos o más criterios con el mismo slug candidato) se
reportan aparte — este script NO las resuelve automáticamente.

INPUT:  motor2/capa2_mecanica_montaje_gran_barata_pv_2026_validado.json
OUTPUT: motor2/capa2_validado_con_candidatos.json  (156 criterios + candidatos)
        motor2/candidatos_id_colisiones.json        (reporte de colisiones)
(respaldo .bak-<timestamp> si ya existían — nunca se pisa)

NO toca: validator.py, extractor.py, normalizer.py, segmenter.py,
clasificador_layout.py, vision_fallback.py, consolidar_manual.py,
schema_conocimiento_v1.md, pipeline/ (Motor 1).

Uso:
    python generar_candidatos_ids.py [ruta_capa2_validado.json]
"""
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

MOTOR2 = Path(__file__).resolve().parent
sys.path.insert(0, str(MOTOR2))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Solo para MARCA_AMBIGUO (una sola fuente de verdad con el prompt real).
import extractor as ex  # noqa: E402

ENTRADA_DEFAULT = MOTOR2 / "capa2_mecanica_montaje_gran_barata_pv_2026_validado.json"
SALIDA_CANDIDATOS = MOTOR2 / "capa2_validado_con_candidatos.json"
SALIDA_COLISIONES = MOTOR2 / "candidatos_id_colisiones.json"

MAX_KEYWORDS_ID = 5
MIN_LARGO_TOKEN = 3
# Fix Sesión V: un token puramente numérico ("3", "5", "20") NUNCA se descarta
# por longitud — un dígito de 1-2 caracteres suele ser la única diferencia
# semántica real entre dos criterios (ej. "3 maniquíes" vs "5 maniquíes"),
# a diferencia de una palabra corta que normalmente ya cae en STOPWORDS.
# Bug original (Sesión T): MIN_LARGO_TOKEN descartaba "3"/"2"/"5" y colapsó
# "3 maniquíes – 2 etiquetas" y "5 maniquíes – 3 etiquetas" al mismo id
# "maniquies_etiquetas" — resuelto a mano en Sesión U; este fix ataca la causa
# raíz en el generador para que no vuelva a pasar en los 106 pendientes.

STOPWORDS = {
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
}

ELEMENTOS_FISICOS = ("torre", "atril", "columna", "barra")


def _sin_acentos(s: str) -> str:
    t = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in t if not unicodedata.combining(ch))


def _sin_marca_ambiguo(texto: str) -> str:
    """Descarta el prefijo [AMBIGUO] — es un marcador que agrega el modelo,
    no forma parte del texto del manual (misma convención que validator.py)."""
    texto = texto or ""
    return texto[len(ex.MARCA_AMBIGUO):] if texto.startswith(ex.MARCA_AMBIGUO) else texto


def _keywords(texto: str) -> list[str]:
    """Tokens normalizados (sin acentos/mayúsculas/puntuación), sin stopwords,
    largo >= MIN_LARGO_TOKEN. Orden de aparición en el texto (determinista)."""
    limpio = _sin_acentos(_sin_marca_ambiguo(texto)).lower()
    limpio = re.sub(r"[^a-z0-9\s]", " ", limpio)
    tokens = limpio.split()
    return [
        t for t in tokens
        if t not in STOPWORDS and (t.isdigit() or len(t) >= MIN_LARGO_TOKEN)
    ]


def generar_id_candidato(criterio: dict) -> str:
    """Slug snake_case determinista derivado del texto. Fallback con página
    + índice si el texto no deja ninguna keyword utilizable."""
    kws = _keywords(criterio.get("texto"))[:MAX_KEYWORDS_ID]
    if kws:
        return "_".join(kws)
    pagina = criterio.get("pagina_origen", "NA")
    return f"criterio_p{pagina}_sin_keywords"


def generar_aliases_candidato(criterio: dict) -> list[str]:
    """1-2 variantes cortas por ventana deslizante sobre las mismas keywords
    del texto — no es paráfrasis inventada, es un recorte determinista del
    mismo criterio para que Gerardo lo edite a lenguaje natural si aplica."""
    kws = _keywords(criterio.get("texto"))
    aliases = []
    if len(kws) >= 2:
        aliases.append(" ".join(kws[0:2]))
    if len(kws) >= 3:
        variante = " ".join(kws[1:3])
        if variante not in aliases:
            aliases.append(variante)
    return aliases


def generar_aplica_a_candidato(criterio: dict) -> list[str] | None:
    """null salvo que el texto mencione explícitamente un elemento físico
    (torre, atril, columna, barra) — determinista, no infiere nada más."""
    texto_norm = _sin_acentos(_sin_marca_ambiguo(criterio.get("texto"))).lower()
    encontrados = [e for e in ELEMENTOS_FISICOS if re.search(rf"\b{e}\w*\b", texto_norm)]
    return encontrados or None


def detectar_colisiones(criterios_con_id: list[dict]) -> list[dict]:
    """Agrupa por id candidato; reporta los grupos con más de 1 criterio.
    NO decide cuál gana el slug — eso es revisión manual de Gerardo."""
    por_id: dict[str, list[dict]] = defaultdict(list)
    for c in criterios_con_id:
        por_id[c["id"]].append(c)

    colisiones = []
    for id_candidato, grupo in sorted(por_id.items()):
        if len(grupo) < 2:
            continue
        colisiones.append({
            "id_candidato": id_candidato,
            "cantidad": len(grupo),
            "criterios": [
                {
                    "pagina_origen": c.get("pagina_origen"),
                    "seccion_aplicable": c.get("seccion_aplicable"),
                    "texto": c.get("texto"),
                }
                for c in grupo
            ],
        })
    return colisiones


def _respaldar_si_existe(ruta: Path) -> None:
    if ruta.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        respaldo = ruta.with_name(f"{ruta.name}.bak-{timestamp}")
        respaldo.write_bytes(ruta.read_bytes())
        print(f"  respaldo: {respaldo.name}")


def main(ruta_entrada: Path = ENTRADA_DEFAULT) -> None:
    data = json.loads(ruta_entrada.read_text(encoding="utf-8"))
    criterios = data.get("criterios", [])
    print(f"Leyendo {ruta_entrada.name} — {len(criterios)} criterios")

    criterios_con_candidatos = []
    for c in criterios:
        nuevo = dict(c)
        nuevo["id"] = generar_id_candidato(c)
        nuevo["aliases"] = generar_aliases_candidato(c)
        nuevo["aplica_a"] = generar_aplica_a_candidato(c)
        nuevo["revisado_por_gerardo"] = False
        criterios_con_candidatos.append(nuevo)

    colisiones = detectar_colisiones(criterios_con_candidatos)

    meta = dict(data.get("meta", {}))
    meta["candidatos_generados"] = datetime.now().isoformat(timespec="seconds")
    meta["candidatos_nota"] = (
        "id/aliases/aplica_a son CANDIDATOS deterministas generados por "
        "generar_candidatos_ids.py (Sesión S) — NO están aprobados. Cada "
        "criterio lleva revisado_por_gerardo=false hasta revisión manual "
        "criterio por criterio. Ver candidatos_id_colisiones.json para los "
        "slugs duplicados sin resolver."
    )

    salida = {"meta": meta, "criterios": criterios_con_candidatos}

    _respaldar_si_existe(SALIDA_CANDIDATOS)
    SALIDA_CANDIDATOS.write_text(
        json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Escrito: {SALIDA_CANDIDATOS.name} ({len(criterios_con_candidatos)} criterios)")

    _respaldar_si_existe(SALIDA_COLISIONES)
    SALIDA_COLISIONES.write_text(
        json.dumps({
            "total_criterios": len(criterios_con_candidatos),
            "ids_unicos": len(set(c["id"] for c in criterios_con_candidatos)),
            "grupos_en_colision": len(colisiones),
            "criterios_afectados": sum(g["cantidad"] for g in colisiones),
            "colisiones": colisiones,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Escrito: {SALIDA_COLISIONES.name} ({len(colisiones)} grupo(s) en colisión, "
          f"{sum(g['cantidad'] for g in colisiones)} criterio(s) afectados)")


if __name__ == "__main__":
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else ENTRADA_DEFAULT
    main(ruta)
