"""Disegna assets/icon.ico (cestino su fondo scuro con accento blu)."""

import os

from PIL import Image, ImageDraw

S = 1024  # si disegna grande e si riduce, per bordi morbidi
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# fondo: quadrato arrotondato con sfumatura verticale
bg = Image.new("RGBA", (S, S))
top, bottom = (45, 55, 72), (17, 24, 39)
for y in range(S):
    t = y / (S - 1)
    bg.paste(tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,), (0, y, S, y + 1))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((40, 40, S - 40, S - 40), radius=210, fill=255)
img.paste(bg, (0, 0), mask)

white = (243, 244, 246, 255)
accent = (96, 165, 250, 255)
# coperchio e maniglia
d.rounded_rectangle((250, 270, 774, 330), radius=26, fill=white)
d.rounded_rectangle((420, 200, 604, 290), radius=30, outline=white, width=34)
# corpo del cestino
d.polygon([(290, 370), (734, 370), (690, 820), (334, 820)], fill=white)
# righe del cestino in accento
for x in (410, 512, 614):
    d.rounded_rectangle((x - 20, 440, x + 20, 750), radius=20, fill=accent)

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.ico")
os.makedirs(os.path.dirname(out), exist_ok=True)
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.resize((256, 256), Image.LANCZOS).save(out.replace(".ico", ".png"))
print(out)
