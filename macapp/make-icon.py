#!/usr/bin/env python3
"""Genere AppIcon.icns pour l'app (sans dependance externe au build Swift).

Dessine un iPhone stylise avec deux courbes de monitoring (CPU bleu, reseau
vert), puis fabrique l'iconset et l'icns via iconutil.
"""
import os
import subprocess
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "Resources")
S = 1024

ACCENT = (78, 161, 255)   # bleu
GREEN = (54, 211, 153)    # vert


def _lerp(a, b, f):
    return tuple(int(a[i] * (1 - f) + b[i] * f) for i in range(3))


def draw_master() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Fond degrade, coins arrondis facon icone macOS.
    bg = Image.new("RGB", (S, S))
    bd = ImageDraw.Draw(bg)
    top, bot = (20, 26, 40), (8, 10, 14)
    for y in range(S):
        bd.line([(0, y), (S, y)], fill=_lerp(top, bot, y / S))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S, S], radius=int(S * 0.225), fill=255)
    img.paste(bg, (0, 0), mask)

    d = ImageDraw.Draw(img, "RGBA")

    # Silhouette iPhone.
    pw, ph = int(S * 0.40), int(S * 0.66)
    px, py = (S - pw) // 2, (S - ph) // 2
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=int(pw * 0.20),
                        outline=ACCENT + (120,), width=12)
    nw = int(pw * 0.34)
    d.rounded_rectangle([(S - nw) // 2, py + 26, (S + nw) // 2, py + 52],
                        radius=14, fill=ACCENT + (120,))

    # Zone graphe a l'interieur de l'ecran.
    gx0, gx1 = px + int(pw * 0.12), px + int(pw * 0.88)
    gy0, gy1 = py + int(ph * 0.30), py + int(ph * 0.78)

    def curve(samples, color):
        n = len(samples)
        pts = []
        for i, v in enumerate(samples):
            x = gx0 + (gx1 - gx0) * i / (n - 1)
            y = gy1 - (gy1 - gy0) * v
            pts.append((x, y))
        d.line(pts, fill=color + (255,), width=16, joint="curve")

    cpu = [.45, .5, .42, .7, .35, .9, .4, .6, .5, .78, .38, .55, .5, .85, .45]
    net = [.2, .25, .22, .3, .28, .35, .3, .42, .38, .3, .45, .35, .4, .33, .38]
    curve(net, GREEN)
    curve(cpu, ACCENT)

    return img


def make_icns():
    os.makedirs(RES, exist_ok=True)
    master = draw_master()
    iconset = os.path.join(RES, "AppIcon.iconset")
    os.makedirs(iconset, exist_ok=True)
    specs = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
             (256, 1), (256, 2), (512, 1), (512, 2)]
    for size, scale in specs:
        px = size * scale
        im = master.resize((px, px), Image.LANCZOS)
        suffix = f"@{scale}x" if scale == 2 else ""
        im.save(os.path.join(iconset, f"icon_{size}x{size}{suffix}.png"))
    icns = os.path.join(RES, "AppIcon.icns")
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns], check=True)
    print(f"icns cree: {icns}")


if __name__ == "__main__":
    try:
        make_icns()
    except Exception as exc:  # noqa: BLE001
        print(f"echec generation icone: {exc}", file=sys.stderr)
        sys.exit(1)
