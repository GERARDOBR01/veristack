"""
generar_fixtures.py — Fixtures sintéticos para el stress test de código de Motor 1.

Genera en fixtures/:
  - Fronteras de brillo: brillo_39_0.png ... brillo_41_0.png
    Imágenes binarias (píxeles 0 y 255) de 100×100: con C píxeles blancos,
    el brillo medido por photo_analyzer._average_brightness es EXACTAMENTE
    C·255/10000/255·100 = C/100. Se usa PNG (lossless) porque JPEG alteraría
    los valores y correría la frontera. El patrón disperso además da varianza
    Laplaciana alta (la regla imagen_borrosa no contamina la medición).
    Cada fixture se VERIFICA con la _average_brightness real del motor.
  - Archivos rotos: inexistente (no se genera, obvio), vacio.webp (0 bytes),
    texto.webp (txt renombrado), truncada.jpg (JPEG cortado al 50%),
    gigante.png (16000×16000 = 256 MP > límite DecompressionBomb de PIL).
  - fixtures/knowledge_roto/: COPIAS corruptas/vacías del knowledge.
    Los originales de pipeline/knowledge/ NO se tocan.

Cero llamadas de red, cero modelo.
"""

import json
import random
import shutil
import sys
from pathlib import Path

from PIL import Image

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent.parent
FIXTURES = AQUI / "fixtures"
KNOWLEDGE_ROTO = FIXTURES / "knowledge_roto"
KNOWLEDGE_PROD = REPO / "pipeline" / "knowledge"

sys.path.insert(0, str(REPO / "core"))
from photo_analyzer import _average_brightness  # noqa: E402  (la misma función del motor)

LADO = 100  # 100×100 = 10000 píxeles → C píxeles blancos = brillo C/100 exacto


def _fixture_brillo(target: float) -> Path:
    """Imagen binaria con brillo medido exactamente `target` (0-100)."""
    n = LADO * LADO
    blancos = round(target * n / 100 / 255 * 255)  # = target*100 para LADO=100
    assert abs(blancos - target * 100) < 1e-6, f"target {target} no da conteo entero"
    blancos = int(target * 100)

    rng = random.Random(42)
    posiciones = list(range(n))
    rng.shuffle(posiciones)
    pixeles = bytearray(n)
    for p in posiciones[:blancos]:
        pixeles[p] = 255

    img = Image.frombytes("L", (LADO, LADO), bytes(pixeles))
    ruta = FIXTURES / f"brillo_{str(target).replace('.', '_')}.png"
    img.save(ruta, format="PNG")

    medido = _average_brightness(Image.open(ruta).convert("RGB"))
    if abs(medido - target) > 1e-9:
        raise SystemExit(f"FIXTURE INVALIDO: {ruta.name} target={target} medido={medido!r}")
    print(f"  {ruta.name}: brillo medido = {medido} (target {target}) OK")
    return ruta


def _fixture_base_valida() -> Path:
    """Foto sintética 'sana' (brillo ~55, nítida) para los casos que necesitan
    pasar mandatory (G1, C*, K*, T1, P0)."""
    n = LADO * LADO
    rng = random.Random(7)
    posiciones = list(range(n))
    rng.shuffle(posiciones)
    pixeles = bytearray(n)
    for p in posiciones[:5500]:
        pixeles[p] = 255
    img = Image.frombytes("L", (LADO, LADO), bytes(pixeles))
    ruta = FIXTURES / "base_valida.png"
    img.save(ruta, format="PNG")
    print(f"  {ruta.name}: brillo medido = {_average_brightness(img.convert('RGB'))}")
    return ruta


def _fixtures_archivos_rotos() -> None:
    (FIXTURES / "vacio.webp").write_bytes(b"")
    print("  vacio.webp: 0 bytes")

    (FIXTURES / "texto.webp").write_text(
        "esto no es una imagen, es un txt renombrado a .webp\n", encoding="utf-8")
    print("  texto.webp: txt renombrado")

    jpg_completo = FIXTURES / "_completa_tmp.jpg"
    Image.frombytes("L", (LADO, LADO), bytes(bytearray(range(256)) * 40)[:LADO * LADO]) \
         .save(jpg_completo, format="JPEG", quality=90)
    datos = jpg_completo.read_bytes()
    (FIXTURES / "truncada.jpg").write_bytes(datos[: len(datos) // 2])
    jpg_completo.unlink()
    print(f"  truncada.jpg: JPEG cortado a {len(datos) // 2} de {len(datos)} bytes")

    # 16000×16000 = 256 MP: sobre el límite DecompressionBomb (~178.9 MP).
    # Se construye el PNG a mano (IHDR gigante + un solo IDAT mínimo): PIL debe
    # rechazarlo en Image.open/convert SIN decodificar — no necesitamos 256 MB.
    import struct, zlib
    def chunk(tipo: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tipo + data + \
               struct.pack(">I", zlib.crc32(tipo + data) & 0xFFFFFFFF)
    lado = 16000
    ihdr = struct.pack(">IIBBBBB", lado, lado, 8, 0, 0, 0, 0)  # 8-bit gris
    idat = zlib.compress(b"\x00" * 10)  # datos incompletos a propósito
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    (FIXTURES / "gigante.png").write_bytes(png)
    print(f"  gigante.png: header declara {lado}x{lado} = {lado*lado/1e6:.0f} MP ({len(png)} bytes en disco)")


def _fixtures_knowledge() -> None:
    KNOWLEDGE_ROTO.mkdir(exist_ok=True)

    # Copias sanas de las 3 capas reales (solo lectura del original)
    for nombre in ("capa1_display_basics.json", "capa2_campana_activa.json",
                   "capa3_focal_show.json"):
        shutil.copyfile(KNOWLEDGE_PROD / nombre, KNOWLEDGE_ROTO / nombre)

    corrupto = KNOWLEDGE_ROTO / "capa2_corrupta.json"
    sano = (KNOWLEDGE_ROTO / "capa2_campana_activa.json").read_text(encoding="utf-8")
    corrupto.write_text(sano[: len(sano) // 2] + '\n{{{"sintaxis rota', encoding="utf-8")
    print(f"  knowledge_roto/capa2_corrupta.json: JSON invalido ({corrupto.stat().st_size} bytes)")

    vacio = KNOWLEDGE_ROTO / "capa2_vacia.json"
    vacio.write_text(json.dumps({"schema_version": "1.1", "criterios": []}), encoding="utf-8")
    print("  knowledge_roto/capa2_vacia.json: {'criterios': []}")

    for capa in ("capa1_corrupta.json", "capa3_corrupta.json"):
        (KNOWLEDGE_ROTO / capa).write_text("ni siquiera es json {", encoding="utf-8")
    print("  knowledge_roto/capa1_corrupta.json + capa3_corrupta.json")


if __name__ == "__main__":
    FIXTURES.mkdir(exist_ok=True)
    print("== Fixtures de frontera de brillo (medidos con photo_analyzer._average_brightness) ==")
    for t in (39.0, 39.9, 40.0, 40.1, 41.0):
        _fixture_brillo(t)
    print("== Foto base valida ==")
    _fixture_base_valida()
    print("== Archivos rotos ==")
    _fixtures_archivos_rotos()
    print("== Knowledge roto (copias, produccion intacta) ==")
    _fixtures_knowledge()
    print("\nFixtures listos en", FIXTURES)
