# -*- coding: utf-8 -*-
"""
preparar_fotos_benchmark.py — Prepara el set de fotos del benchmark (Sesión AA).

Los preview*.webp de Downloads son capturas de WhatsApp/slides que contienen la
corrección humana como texto (caption/columna) — evaluarlos tal cual filtraría
la respuesta al modelo. Clasificación autorizada por Gerardo (9 Jul 2026):
  (a) solo marcadores visuales sobre la foto → usar tal cual
  (b) texto en área SEPARADA (caption WhatsApp / columna de slide) → recortar
      al área de la foto (los marcadores círculo/flecha/X se quedan)
  (c) texto superpuesto en los píxeles de la foto → EXCLUIR y reportar

Excluidas: F02 (categoría c — "Rellenar"/"Poner un bloque…" sobre la foto),
F06 (duda — la foto del hallazgo 'flores tapan gráfico' solo existe como
thumbnail; la grande del comedor no cubre ambos hallazgos → decide Gerardo),
F20 (sus 6 imágenes no están en Downloads), F25/F26 (solo chat, sin foto),
F28 (mapeo con confianza media, pendiente de verificación de Gerardo).

Salida por foto en motor1/benchmark/fotos/:
  FXX_original.webp — copia byte a byte del preview original (auditoría)
  FXX.webp          — el recorte que usa el manifest (o copia si categoría a)

Los recortes son cajas fijas en fracciones (left, top, right, bottom) sobre
cada imagen, verificadas visualmente una a una. Determinista: correrlo dos
veces produce el mismo set.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image

DOWNLOADS = Path(r"C:\Users\EEVILLAREALN\Downloads")
SALIDA    = Path(__file__).resolve().parent / "fotos"

# foto_id → (archivo original, categoría, caja de recorte en fracciones o None)
# Cajas (l, t, r, b) estimadas y verificadas visualmente contra cada captura.
FOTOS: dict[str, tuple[str, str, tuple[float, float, float, float] | None]] = {
    "F01":  ("preview (29).webp", "b", (0.01, 0.11, 0.92, 0.74)),
    "F03":  ("preview (27).webp", "b", (0.01, 0.07, 0.50, 0.48)),
    "F04":  ("preview (26).webp", "b", (0.00, 0.04, 0.95, 0.78)),
    "F05":  ("preview (25).webp", "b", (0.00, 0.00, 1.00, 0.85)),
    "F07":  ("preview (23).webp", "b", (0.00, 0.06, 1.00, 0.71)),
    "F08":  ("preview (22).webp", "b", (0.02, 0.075, 0.70, 0.57)),
    "F09":  ("preview (21).webp", "b", (0.00, 0.00, 0.70, 0.55)),
    "F10":  ("preview (20).webp", "b", (0.03, 0.10, 0.84, 0.80)),
    "F11":  ("preview (19).webp", "b", (0.01, 0.06, 0.54, 0.52)),
    "F12a": ("preview (18).webp", "b", (0.02, 0.08, 0.61, 0.64)),
    "F12b": ("preview (17).webp", "b", (0.02, 0.115, 0.72, 0.78)),
    "F13":  ("preview (16).webp", "b", (0.03, 0.08, 0.80, 0.70)),
    "F14":  ("preview (15).webp", "b", (0.05, 0.09, 0.74, 0.84)),
    "F15":  ("preview (14).webp", "b", (0.235, 0.16, 0.71, 0.91)),
    "F16":  ("preview (13).webp", "b", (0.28, 0.15, 0.86, 0.92)),
    "F17":  ("preview (12).webp", "b", (0.03, 0.07, 0.85, 0.66)),
    "F18":  ("preview (11).webp", "b", (0.02, 0.07, 0.88, 0.77)),
    "F19":  ("preview (10).webp", "b", (0.04, 0.07, 0.80, 0.84)),
    "F21":  ("preview (9).webp",  "b", (0.055, 0.03, 0.655, 0.845)),
    "F22":  ("preview (8).webp",  "b", (0.055, 0.00, 0.66, 0.71)),
    # F23: la captura trae 2 tomas de la misma mesa; se usa la 2ª (10:34,
    # más cercana y completa) — decisión documentada.
    "F23":  ("preview (7).webp",  "b", (0.26, 0.315, 0.955, 0.625)),
    # F24: grid de 4 tomas; se usa la inferior-derecha (9:57) — es la que la
    # jefa cita en el reply del chat (thumbnail idéntico) — decisión documentada.
    "F24":  ("preview (6).webp",  "b", (0.615, 0.295, 0.955, 0.505)),
    "F27":  ("preview (3).webp",  "b", (0.035, 0.04, 0.71, 0.685)),
    # Positivas: capturas limpias sin texto de corrección → categoría (a).
    "F29":  ("preview (1).webp",  "a", None),
    "F30":  ("preview.webp",      "a", None),
}

EXCLUIDAS = {
    "F02":  ("preview (28).webp", "c", "texto de corrección superpuesto en los píxeles"),
    "F06":  ("preview (24).webp", "duda", "la foto del hallazgo 'flores' solo existe como thumbnail"),
    "F20":  (None, "faltante", "sus 6 imágenes positivas no están en Downloads"),
    "F25":  ("preview (5).webp", "solo_chat", "sin foto descargada"),
    "F26":  ("preview (4).webp", "solo_chat", "sin foto descargada"),
    "F28":  ("preview (2).webp", "pendiente", "mapeo confianza media, verifica Gerardo"),
}


def preparar() -> int:
    SALIDA.mkdir(parents=True, exist_ok=True)
    errores = 0
    for foto_id, (nombre, categoria, caja) in sorted(FOTOS.items()):
        origen = DOWNLOADS / nombre
        if not origen.exists():
            print(f"  [FAIL] {foto_id}: no existe {origen}")
            errores += 1
            continue

        destino_original = SALIDA / f"{foto_id}_original.webp"
        shutil.copyfile(origen, destino_original)

        destino = SALIDA / f"{foto_id}.webp"
        if categoria == "a" or caja is None:
            shutil.copyfile(origen, destino)
            print(f"  [OK] {foto_id}: categoría (a), copia sin recorte")
        else:
            img = Image.open(origen).convert("RGB")
            w, h = img.size
            l, t, r, b = caja
            px = (round(w * l), round(h * t), round(w * r), round(h * b))
            recorte = img.crop(px)
            recorte.save(destino, "WEBP", quality=92)
            print(f"  [OK] {foto_id}: categoría (b), recorte {px} de {w}x{h} "
                  f"-> {recorte.size[0]}x{recorte.size[1]}")
    print(f"\nPreparación: {'OK' if errores == 0 else f'{errores} error(es)'} "
          f"({len(FOTOS)} fotos evaluables, {len(EXCLUIDAS)} excluidas documentadas)")
    return errores


if __name__ == "__main__":
    sys.exit(1 if preparar() else 0)
