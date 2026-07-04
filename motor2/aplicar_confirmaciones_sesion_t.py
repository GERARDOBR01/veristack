# -*- coding: utf-8 -*-
"""Motor 2 — aplica ids confirmados por Gerardo sobre capa2_validado_con_candidatos.json (Sesión T).

Sesión S generó candidatos deterministas de id/aliases/aplica_a y reportó 18
grupos de colisión (50 criterios) sin resolverlos. Esta sesión aplica las
decisiones que Gerardo confirmó para 3 de esos clusters — NO todos: 7 grupos
(20 criterios) siguen sin resolver, ver PENDIENTES abajo.

Matching por (pagina_origen, texto exacto) — no por índice de lista, para no
depender del orden del archivo. Cada entrada de OVERRIDES debe encontrar
EXACTAMENTE la cantidad de criterios declarada en "n_esperado"; si no,
aborta sin escribir nada (mismo principio de "nunca silencioso" que
validator.py).

CLUSTER 1 — p6, torre/barras/columnas:
  Gerardo revisó la página 6 del PDF (pendiente Sesión Q) y confirmó que los
  pares "duplicados" son en realidad DOS mecanismos físicos distintos
  (barras y columnas) que el extractor no distinguió por texto. Convención
  aplicada (declarada, no inventada): primera aparición en el archivo = barras,
  segunda = columnas.
  OJO: "3era etapa 100% beneficio" tiene una sola instancia en los datos
  (no está duplicada como las otras dos etapas) — se asigna barras_etapa3_100
  por ser la única; columnas_etapa3_100 QUEDA SIN CRITERIO CORRESPONDIENTE
  en la extracción actual. No se inventa una entrada para llenarlo.

CLUSTER 2 — p20-25, Focal Show por departamento:
  Cada página agrupa 3 criterios antes colisionados (ids distintos con texto
  distinto) bajo UN id por departamento+etapa — retrieval_engine.py cachea
  hasta 3 evidencias por capa (max_evidencias_por_capa), así que las 3 quedan
  disponibles como evidencia del mismo tópico. Los criterios de cada página
  que NO colisionaban (ej. "Exhibir producto de la sección de...") no se
  tocan — quedan con su id candidato original.
  revisa_producto_focal_sea_mercancia también tenía una instancia en p16
  (fuera del rango 20-25): esa instancia NO se toca, se queda con su id
  original — al mover las otras 3 (p20/22/24), deja de colisionar.

CLUSTER 3 — p31/34/39/40, "no mezclar marcas":
  Colapso a 3 ids universales (aplica_a: null, seccion_aplicable sigue
  distinguiendo dónde aplica cada instancia). Ninguna entrada se borra —
  se mantienen todas, solo se unifica el id.

PENDIENTES (Sesión S, no resueltos por Gerardo todavía — quedan como candidatos):
  - acercate_jefe_seccion_pueda_dar (p43/44, 2 criterios)
  - coloca_producto_mayor_descuento_sea (p28/29/33/38, 4 criterios)
  - exhibicion_disciplinas_mantiene_dentro_separan (p43/44, 2 criterios)
  - identificar_cartulina_descuento (p13/14, 2 criterios)
  - maniquies_etiquetas (p10, 2 criterios) — OJO: esta colisión es un
    FALSO POSITIVO del generador de slugs: "3 maniquíes → 2 etiquetas" y
    "5 maniquíes → 3 etiquetas" son reglas DISTINTAS (cantidades distintas)
    que colapsaron al mismo id porque los números de 1 dígito se descartan
    como keyword (MIN_LARGO_TOKEN=3 en generar_candidatos_ids.py). Reportar
    a Gerardo como limitación del generador, no como duplicado real.
  - manten_orden_exhibicion (p28/29/33/38, 4 criterios)
  - mercadeo_bloqueo_producto (p28/29/33/38, 4 criterios)

INPUT/OUTPUT: motor2/capa2_validado_con_candidatos.json (se sobreescribe en
sitio, respaldo .bak-<timestamp> — igual que las demás salidas de Motor 2).

NO toca: retrieval_engine.py, confidence_engine.py, mandatory_engine.py,
app.py, ni ningún archivo de Motor 2 existente.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

MOTOR2 = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUTA = MOTOR2 / "capa2_validado_con_candidatos.json"

# Cada override: (pagina_origen, texto EXACTO) -> nuevo id.
# n_esperado por override_id: cuántas entradas (pagina,texto) distintas
# se esperan encontrar en total para ese id nuevo — guard de conteo.
OVERRIDES: dict[tuple[int, str], str] = {
    # ── Cluster 1 — p6 torre/barras/columnas ──────────────────────
    (6, "3era etapa 100% beneficio (Como años pasados)"):     "barras_etapa3_100",     # única instancia
    # (las "segundas ocurrencias" de textos idénticos se resuelven por
    # posición — ver _aplicar_duplicados_p6 más abajo, json no permite
    # dos claves iguales en OVERRIDES para (pagina,texto) repetido)

    # ── Cluster 2 — p20-25 Focal Show por departamento ────────────
    (20, "Revisa que el producto para este focal sea mercancía con el mismo descuento."): "focal_show_mujeres_etapa1_2",
    (20, "Integra los maniquíes de manera que se logren apreciar bien todos los looks."): "focal_show_mujeres_etapa1_2",
    (20, "[AMBIGUO] En en los focales solo se colocan los gráficos de torres slim y maniquíes."): "focal_show_mujeres_etapa1_2",

    (22, "Revisa que el producto para este focal sea mercancía con el mismo descuento."): "focal_show_hombres_etapa1_2",
    (22, "Integra los maniquíes de manera que se logren apreciar bien todos los looks."): "focal_show_hombres_etapa1_2",
    (22, "[AMBIGUO] En en los focales solo se colocan los gráficos de torres slim y maniquíes."): "focal_show_hombres_etapa1_2",

    (24, "Revisa que el producto para este focal sea mercancía con el mismo descuento."): "focal_show_infantiles_etapa1_2",
    (24, "Integra los maniquíes de manera que se logren apreciar bien todos los looks."):  "focal_show_infantiles_etapa1_2",
    (24, "En en los focales solo se colocan los gráficos de torres slim y maniquíes."):     "focal_show_infantiles_etapa1_2",

    (21, "No colocar gráficos de Barata."):                            "focal_show_mujeres_etapa3",
    (21, "En estos focales colocar los atriles de marca."):            "focal_show_mujeres_etapa3",

    (23, "No colocar gráficos de Barata."):                            "focal_show_hombres_etapa3",
    (23, "En estos focales colocar los atriles de marca."):            "focal_show_hombres_etapa3",

    (25, "No colocar gráficos de Barata."):                            "focal_show_infantiles_etapa3",
    (25, "En estos focales colocar los atriles de marca."):            "focal_show_infantiles_etapa3",

    # ── Cluster 3 — p31/34/39/40 "no mezclar marcas" ──────────────
    (31, "No mezclar marcas"):    "no_mezclar_marcas",
    (34, "No mezclar marcas."):   "no_mezclar_marcas",
    (31, "Exhibir 1 focal por marca"):  "exhibir_1_focal_por_marca",
    (34, "Exhibir 1 focal por marca."): "exhibir_1_focal_por_marca",
    (31, "Colocar alternando a lo largo de la sección"):  "colocar_alternando_seccion",
    (39, "Colocar alternando a lo largo de la sección."): "colocar_alternando_seccion",
    (40, "Colocar alternando a lo largo de la sección."): "colocar_alternando_seccion",
}

# p6 tiene DOS pares de texto idéntico (mismo pagina+texto) que deben
# resolverse a ids DISTINTOS por posición (barras=1ra, columnas=2da) — no
# se pueden expresar como una sola clave de dict. Se resuelven aparte.
DUPLICADOS_P6_EN_ORDEN = [
    ("Imprimir primera etapa 40% genérico 60% beneficio", ["barras_etapa1_40_60", "columnas_etapa1_40_60"]),
    ("2da etapa 100% beneficio (Como años pasados)",       ["barras_etapa2_100",   "columnas_etapa2_100"]),
]

# El texto de "impulsará IMO..." en p21/23/25 usa comillas tipográficas y
# puntos suspensivos (U+201C/U+2026/U+201D) — se matchea por subcadena
# segura en vez de texto completo para no depender de transcribir esos
# caracteres a mano.
OVERRIDES_SUBSTRING: list[tuple[int, str, str]] = [
    (21, "impulsará IMO", "focal_show_mujeres_etapa3"),
    (23, "impulsará IMO", "focal_show_hombres_etapa3"),
    (25, "impulsará IMO", "focal_show_infantiles_etapa3"),
]

CLUSTER3_APLICA_A_NULL = {
    "no_mezclar_marcas", "exhibir_1_focal_por_marca", "colocar_alternando_seccion",
}


def _respaldar_si_existe(ruta: Path) -> None:
    if ruta.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        respaldo = ruta.with_name(f"{ruta.name}.bak-{timestamp}")
        respaldo.write_bytes(ruta.read_bytes())
        print(f"  respaldo: {respaldo.name}")


def main() -> None:
    data = json.loads(RUTA.read_text(encoding="utf-8"))
    criterios = data["criterios"]

    tocados = 0

    # 1) Duplicados exactos de p6 (mismo texto, misma página, 2 ocurrencias)
    #    — por orden de aparición en la lista.
    for texto_dup, ids_en_orden in DUPLICADOS_P6_EN_ORDEN:
        ocurrencias = [c for c in criterios if c.get("pagina_origen") == 6 and c.get("texto") == texto_dup]
        if len(ocurrencias) != len(ids_en_orden):
            print(f"*** ABORTA: se esperaban {len(ids_en_orden)} ocurrencias de {texto_dup!r} en p6, "
                  f"se encontraron {len(ocurrencias)}")
            sys.exit(1)
        for criterio, nuevo_id in zip(ocurrencias, ids_en_orden):
            criterio["id"] = nuevo_id
            criterio["revisado_por_gerardo"] = True
            tocados += 1

    # 2) Overrides únicos por (pagina_origen, texto) — el resto de p6 +
    #    clusters 2 y 3.
    for (pagina, texto), nuevo_id in OVERRIDES.items():
        candidatos = [c for c in criterios if c.get("pagina_origen") == pagina and c.get("texto") == texto]
        if len(candidatos) != 1:
            print(f"*** ABORTA: se esperaba EXACTAMENTE 1 criterio en p{pagina} con texto {texto!r}, "
                  f"se encontraron {len(candidatos)}")
            sys.exit(1)
        criterio = candidatos[0]
        criterio["id"] = nuevo_id
        criterio["revisado_por_gerardo"] = True
        if nuevo_id in CLUSTER3_APLICA_A_NULL:
            criterio["aplica_a"] = None
        tocados += 1

    # 2b) Overrides por subcadena (texto con caracteres tipográficos)
    for pagina, subcadena, nuevo_id in OVERRIDES_SUBSTRING:
        candidatos = [c for c in criterios
                      if c.get("pagina_origen") == pagina and subcadena in (c.get("texto") or "")]
        if len(candidatos) != 1:
            print(f"*** ABORTA: se esperaba EXACTAMENTE 1 criterio en p{pagina} conteniendo {subcadena!r}, "
                  f"se encontraron {len(candidatos)}")
            sys.exit(1)
        criterio = candidatos[0]
        criterio["id"] = nuevo_id
        criterio["revisado_por_gerardo"] = True
        tocados += 1

    print(f"Criterios actualizados: {tocados} (esperado: 30 — cluster1=5, cluster2=18, cluster3=7)")

    meta = dict(data.get("meta", {}))
    meta["confirmaciones_sesion_t"] = datetime.now().isoformat(timespec="seconds")
    meta["confirmaciones_nota"] = (
        "30 de 156 criterios confirmados por Gerardo y marcados "
        "revisado_por_gerardo=true (3 de los 18 grupos de colisión de Sesión "
        "S: p6 barras/columnas, Focal Show p20-25 por departamento, "
        "'no mezclar marcas' p31/34/39/40). Quedan 7 grupos de colisión "
        "(20 criterios) sin confirmar — ver docstring de "
        "aplicar_confirmaciones_sesion_t.py, incluye un falso positivo "
        "detectado (maniquies_etiquetas, p10) por limitación del generador "
        "de slugs con números de 1 dígito."
    )
    data["meta"] = meta

    _respaldar_si_existe(RUTA)
    RUTA.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Escrito: {RUTA.name}")


if __name__ == "__main__":
    main()
