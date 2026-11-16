"""Crea una libreria Lightcraft dimostrativa con foto sintetiche (per prove e screenshot).

    python tools/make_demo.py CARTELLA [percorso\\lightcraft-cli.exe]

Genera CARTELLA\\Photos con alcuni JPG di paesaggi disegnati, li importa in CARTELLA\\Demo library
e ne mette alcuni nel cestino. Non tocca nessuna foto reale.
"""

import json
import os
import random
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter

PALETTES = [
    ((255, 170, 110), (120, 80, 160), (40, 45, 80)),
    ((140, 200, 255), (60, 120, 200), (30, 70, 60)),
    ((255, 220, 150), (240, 120, 90), (70, 40, 60)),
    ((190, 230, 255), (120, 170, 220), (50, 90, 120)),
    ((255, 200, 200), (180, 110, 160), (60, 50, 90)),
    ((220, 240, 210), (130, 190, 150), (40, 80, 60)),
]


def landscape(path, seed):
    rnd = random.Random(seed)
    w, h = 3000, 2000
    top, mid, ground = PALETTES[seed % len(PALETTES)]
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * k) for a, b in zip(top, mid)))
    sx, sy = rnd.randint(500, 2500), rnd.randint(300, 800)
    d.ellipse((sx - 160, sy - 160, sx + 160, sy + 160), fill=(255, 245, 220))
    for layer in range(3):
        base = 1000 + layer * 280
        shade = tuple(max(0, int(c * (0.55 + 0.2 * layer))) for c in ground)
        pts = [(0, h)]
        x = 0
        while x <= w:
            pts.append((x, base - rnd.randint(0, 420 - layer * 100)))
            x += rnd.randint(180, 420)
        pts += [(w, base), (w, h)]
        d.polygon(pts, fill=shade)
    img.filter(ImageFilter.GaussianBlur(2)).save(path, quality=88)


def main():
    root = os.path.abspath(sys.argv[1])
    cli = sys.argv[2] if len(sys.argv) > 2 else os.path.expandvars(
        r"%LOCALAPPDATA%\Programs\ArtCraft\LightCraft\lightcraft-cli.exe")
    photos, lib = os.path.join(root, "Photos"), os.path.join(root, "Demo library")
    os.makedirs(photos, exist_ok=True)
    os.makedirs(lib, exist_ok=True)
    for i in range(1, 7):
        landscape(os.path.join(photos, f"IMG_{1000 + i}.JPG"), i)
    script = os.path.join(root, "setup.jsonl")
    with open(script, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"command": "library.import", "params": {"paths": [photos], "mode": "add"}}) + "\n")
        f.write(json.dumps({"command": "photo.delete", "params": {"ids": [2, 3, 5]}}) + "\n")
    subprocess.run([cli, "run", "--library", lib, "--script", script], check=True, capture_output=True)
    os.remove(script)
    # un XMP accanto a una foto nel cestino, come lo lascerebbe un altro programma
    with open(os.path.join(photos, "IMG_1002.xmp"), "w", encoding="utf-8") as f:
        f.write('<x:xmpmeta xmlns:x="adobe:ns:meta/"/>\n')
    print(lib)


if __name__ == "__main__":
    main()
