# -*- coding: utf-8 -*-
"""Motor 2 — normalizador de secciones (100% código, SIN IA).

Consume los bloques de segmenter.py y mapea el encabezado crudo de cada bloque
a un valor de `seccion_aplicable`:

    Softline · Hardline · Diversos · Multimedia · Deportes · Niño/Niña · Hogar
    o None (null) si ningún departamento aplica (portada, separadores puros,
    materiales genéricos, exteriores).

El mapeo es por diccionario explícito. Si un encabezado no matchea ninguna
regla conocida, se REPORTA en consola en vez de forzarlo a un valor.

Uso:
    python normalizer.py [ruta_al_pdf]
"""
import sys
from dataclasses import dataclass
from pathlib import Path

from segmenter import PDF_DEFAULT, leer_paginas, segmentar

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- Vocabulario válido de seccion_aplicable (definido por el proyecto) ------
# Keyword (en MAYÚSCULAS, se busca como substring del encabezado) -> valor.
# El ORDEN importa: el primer keyword que aparezca gana. Por eso el prefijo de
# departamento (DEPORTES) se evalúa antes que NIÑO/NIÑA, que en este manual
# aparece bundleado bajo "DEPORTES - DEPORTES Y DEPORTIVO NIÑO/NIÑA".
KEYWORDS_DEPARTAMENTO = [
    ("SOFTLINE", "Softline"),
    ("HARDLINE", "Hardline"),
    ("HOGAR", "Hogar"),
    ("MULTIMEDIA", "Multimedia"),
    ("DEPORTES", "Deportes"),
    ("DIVERSOS", "Diversos"),
    ("COCINA Y ELECTRO", "Hardline"),  # sub-depto de línea dura, sin valor propio
    ("NIÑO", "Niño/Niña"),
    ("NIÑA", "Niño/Niña"),
]

# Encabezados legítimos que NO nombran un departamento -> null explícito.
# (portada, calendario/info, materiales genéricos, planogramas, exteriores).
GENERICOS_NULL = {
    "GRAN BARATA",
    "PREVENTA",
    "INFORMACIÓN GENERAL",
    "LÍNEA DE TIEMPO",
    "LÍNEA DE TIEMPO POR ETAPA",
    "GRÁFICOS",
    "PARCHES ATRILES Y TORRES (ETAPA 2 Y 3)",
    "CARTULINAS",
    "ETIQUETADO EN TIENDA",
    "PLANOGRAMA",
    "PLANOGRAMA REFERENCIA",
    "ETIQUETADO",
    "OUTPOS BOLSA",
    "PRIORIDAD DE PUNTOS FOCALES",
    "PUNTOS DE PUERTA",
    "APARADORES",
}


@dataclass
class BloqueNormalizado:
    seccion: str                 # encabezado ya reparado (sin truncar)
    seccion_aplicable: str | None
    pagina_inicio: int
    pagina_fin: int
    es_separador: bool           # bloque sin contenido real (divisor de sección)
    reparado: bool               # se reparó un título partido por wrap del PDF


# Páginas cuyo título se parte en 2 líneas por el wrap del PDF (verificado a
# mano contra el manual). La continuación real es la 1ª línea del contenido:
#   pág 24: "SOFTLINE: FOCAL SHOW INFANTILES (1a y 2da" + "ETAPA)"
#   pág 44: "DEPORTES - DEPORTES Y DEPORTIVO"          + "NIÑO/NIÑA"
# Se listan explícitamente en vez de detectarlos por heurística: no hay señal
# estructural que separe la continuación ("NIÑO/NIÑA") de una 1ª palabra de
# contenido en mayúsculas ("BARRAS"), y forzar una regla ahí inventa casos.
PAGINAS_TITULO_PARTIDO = {24, 44}


def _reparar_titulo(bloque):
    """Devuelve (encabezado_reparado, reparado_bool).

    Sólo para las páginas con título partido conocido: une el encabezado con la
    1ª línea de su contenido. No modifica el Bloque original.
    """
    if bloque.pagina_inicio not in PAGINAS_TITULO_PARTIDO:
        return bloque.seccion, False
    lineas = [l.strip() for l in bloque.texto.splitlines() if l.strip()]
    if lineas:
        return f"{bloque.seccion} {lineas[0]}", True
    return bloque.seccion, False


def mapear_seccion(encabezado: str, es_separador: bool):
    """Mapea un encabezado a (seccion_aplicable, matcheo_ok).

    matcheo_ok=False significa: no matcheó ninguna regla conocida -> reportar.
    """
    # Regla 1: un separador puro no tiene criterios que ubicar en un depto.
    if es_separador:
        return None, True
    up = encabezado.upper()
    # Regla 2: keyword de departamento (primer match gana).
    for keyword, valor in KEYWORDS_DEPARTAMENTO:
        if keyword in up:
            return valor, True
    # Regla 3: genérico conocido sin departamento.
    if up in GENERICOS_NULL:
        return None, True
    # Regla 4: desconocido -> reportar, no forzar.
    return None, False


def normalizar(bloques):
    normalizados, no_matchean = [], []
    for b in bloques:
        es_sep = not b.texto.strip()
        encabezado, reparado = _reparar_titulo(b)
        valor, ok = mapear_seccion(encabezado, es_sep)
        normalizados.append(
            BloqueNormalizado(
                seccion=encabezado,
                seccion_aplicable=valor,
                pagina_inicio=b.pagina_inicio,
                pagina_fin=b.pagina_fin,
                es_separador=es_sep,
                reparado=reparado,
            )
        )
        if not ok:
            no_matchean.append(encabezado)
    return normalizados, no_matchean


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PDF_DEFAULT
    if not pdf_path.exists():
        sys.exit(f"ERROR: no existe el PDF: {pdf_path}")

    bloques = segmentar(leer_paginas(pdf_path))
    normalizados, no_matchean = normalizar(bloques)

    print(f"PDF: {pdf_path.name}")
    print(f"Bloques: {len(normalizados)}  |  sin match: {len(no_matchean)}")
    print("-" * 80)
    for n in normalizados:
        rango = (
            f"p{n.pagina_inicio}"
            if n.pagina_inicio == n.pagina_fin
            else f"p{n.pagina_inicio}-{n.pagina_fin}"
        )
        valor = n.seccion_aplicable if n.seccion_aplicable is not None else "null"
        marcas = []
        if n.es_separador:
            marcas.append("SEP")
        if n.reparado:
            marcas.append("REPARADO")
        marca = f"  [{', '.join(marcas)}]" if marcas else ""
        print(f"[{rango:>8}] {valor:<10} <- {n.seccion}{marca}")

    print("-" * 80)
    titulos_reparados = [n for n in normalizados if n.reparado]
    print(f"Títulos reparados ({len(titulos_reparados)}): "
          f"{[f'p{n.pagina_inicio}' for n in titulos_reparados]}")
    # Umbral duro del alcance de la sesión: >3 sin match => detener y reportar.
    if no_matchean:
        print(f"\n⚠️  {len(no_matchean)} encabezado(s) SIN match en el diccionario:")
        for e in no_matchean:
            print(f"    - {e!r}")
        if len(no_matchean) > 3:
            sys.exit("DETENER: más de 3 encabezados sin match — revisar el diccionario, "
                     "no inventar reglas.")


if __name__ == "__main__":
    main()
