#!/usr/bin/env python3
"""Procedural wallpaper painter for the SHOJI theme.

Everything is drawn from code — washi grain, the brush-stroke enso, the
ink-wash ridgeline, the vermilion hanko — so the wallpapers are original
assets and fully reproducible:

    python3 themes/shoji/assets/make-wallpapers.py

writes files/wallpaper/{enso,ridgeline,washi}.png (1920x1080, matching the
rest of the collection) and the braille enso used by
files/fastfetch/shoji-logo.txt. Requires Pillow. The RNG is seeded so a
rebuild is byte-stable per Pillow version.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

W, H = 1920, 1080
SS = 2  # supersample factor for ink work

WASHI = (242, 239, 229)
WASHI_DEEP = (232, 228, 214)
SUMI = (42, 38, 32)
VERMILION = (179, 64, 46)
PAPER_BRIGHT = (251, 249, 242)

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "files" / "wallpaper"
LOGO_OUT = HERE.parent / "files" / "fastfetch" / "shoji-logo.txt"


# ── paper ────────────────────────────────────────────────────────────────

def washi_paper(w: int = W, h: int = H) -> Image.Image:
    """Warm paper: vertical tone drift + gaussian grain + stray fibres."""
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        grad.putpixel((0, y), tuple(
            round(a + (b - a) * t * 0.55) for a, b in zip(WASHI, WASHI_DEEP)
        ))
    img = grad.resize((w, h))

    # vignette first: its 1-level quantisation steps would ring on bare
    # paper, so the grain layered on top acts as dither
    vign = Image.radial_gradient("L").resize((w, h)).point(lambda v: v * 9 // 255)
    img = ImageChops.subtract(img, Image.merge("RGB", (vign, vign, vign)))

    # washi mottle: two octaves of low-frequency noise (upscaled) read as
    # pulp clouds and keep the PNG small — per-pixel grain is incompressible
    mottle = (Image.effect_noise((w // 16 + 1, h // 16 + 1), 15)
              .resize((w, h), Image.BILINEAR).convert("RGB"))
    img = Image.blend(img, mottle, 0.055)
    tooth = (Image.effect_noise((w // 8 + 1, h // 8 + 1), 13)
             .resize((w, h), Image.BILINEAR).convert("RGB"))
    img = Image.blend(img, tooth, 0.022)

    fibres = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fibres)
    for _ in range(round(w * h / 1_480_000)):
        x, y = random.uniform(0, w), random.uniform(0, h)
        length = random.uniform(30, 150)
        ang = random.uniform(-0.16, 0.16) + (0 if random.random() < 0.85 else math.pi / 2)
        x2, y2 = x + length * math.cos(ang), y + length * math.sin(ang)
        if random.random() < 0.5:
            col = (*SUMI, random.randint(4, 9))
        else:
            col = (*PAPER_BRIGHT, random.randint(6, 12))
        fd.line([(x, y), (x2, y2)], fill=col, width=1)
    fibres = fibres.filter(ImageFilter.GaussianBlur(0.6))
    return Image.alpha_composite(img.convert("RGBA"), fibres).convert("RGB")


# ── ink brushwork ────────────────────────────────────────────────────────

def paint_enso(w: int, h: int, cx: float, cy: float, radius: float,
               base_th: float) -> Image.Image:
    """One-breath brush ring: thick wet start, dry tapering flick of an end.

    Built as mask arithmetic — ImageDraw REPLACES RGBA pixels rather than
    compositing, so translucent streaks drawn over the body would punch
    uniform light rings through it. Instead: solid body mask, minus ragged
    erase filaments hugging the edges (paper showing through the dry brush),
    the result toned by soft noise so the ink doesn't sit perfectly even.
    """
    body = Image.new("L", (w, h), 0)
    bd = ImageDraw.Draw(body)
    erase = Image.new("L", (w, h), 0)
    ed = ImageDraw.Draw(erase)

    a0 = math.radians(-68)          # start just past the top-right gap
    sweep = math.radians(324)       # leave ~36 degrees of gap
    wob_phase = random.uniform(0, math.tau)
    steps = int(sweep * radius / 1.1)

    def path(t: float) -> tuple[float, float, float]:
        ang = a0 + sweep * t
        r = radius * (1
                      + 0.011 * math.sin(3 * sweep * t + wob_phase)
                      + 0.006 * math.sin(7 * sweep * t + 1.7 * wob_phase))
        th = base_th * (0.72 + 0.55 * math.sin(math.pi * min(t * 1.15, 1.0)))
        if t > 0.86:                # the flick: taper hard at the very end
            th *= max(0.10, 1 - ((t - 0.86) / 0.14) ** 1.3)
        return cx + r * math.cos(ang), cy + r * math.sin(ang), th

    for i in range(steps + 1):
        t = i / steps
        x, y, th = path(t)
        x += random.uniform(-1.2, 1.2)
        y += random.uniform(-1.2, 1.2)
        bd.ellipse([x - th, y - th, x + th, y + th], fill=255)

    # dry-brush filaments: thin, broken, hugging the edges, strongest toward
    # the end of the stroke where the brush runs out of ink
    for _ in range(18):
        edge = random.uniform(0.50, 0.95) * random.choice((-1, 1))
        wave = random.uniform(0, math.tau)
        gate_f = random.uniform(4, 9)
        t_in = random.uniform(0.10, 0.60)
        t_out = random.uniform(t_in + 0.20, 1.0)
        streak_th = base_th * random.uniform(0.030, 0.085)
        strength = random.randint(100, 205)
        for i in range(steps + 1):
            t = i / steps
            if not (t_in <= t <= t_out):
                continue
            # broken filament: stochastic skips + a slow gate along the arc
            if random.random() < 0.30 or math.sin(gate_f * math.tau * t + wave) < -0.35:
                continue
            x, y, th = path(t)
            ang = a0 + sweep * t
            off = (edge + 0.08 * math.sin(3 * math.tau * t + wave)) * max(th - streak_th, 0)
            x += off * math.cos(ang) + random.uniform(-0.9, 0.9)
            y += off * math.sin(ang) + random.uniform(-0.9, 0.9)
            s = int(strength * (0.30 + 0.70 * t))       # drier as it goes
            ed.ellipse([x - streak_th, y - streak_th, x + streak_th, y + streak_th],
                       fill=s)

    # a few flecks thrown off the start of the stroke
    x0, y0, th0 = path(0.02)
    for _ in range(14):
        ang = random.uniform(0, math.tau)
        dist = random.uniform(th0 * 1.5, th0 * 5)
        r = random.uniform(1.2, 3.5)
        x, y = x0 + dist * math.cos(ang), y0 + dist * math.sin(ang)
        bd.ellipse([x - r, y - r, x + r, y + r],
                   fill=random.randint(90, 200))

    tone = (Image.effect_noise((w // 8 + 1, h // 8 + 1), 30)
            .resize((w, h), Image.BILINEAR)
            .point(lambda v: 200 + (v * 55) // 255))
    alpha = ImageChops.multiply(body, tone)
    alpha = ImageChops.subtract(alpha, erase)

    ink = Image.new("RGBA", (w, h), (*SUMI, 0))
    ink.putalpha(alpha)
    return ink.filter(ImageFilter.GaussianBlur(1.6))


def paint_hanko(size: int, glyph: bool = True) -> Image.Image:
    """Vermilion seal, edges eaten by paper tooth; 山 carved in the negative."""
    s4 = size * 4
    stamp = Image.new("RGBA", (s4, s4), (0, 0, 0, 0))
    d = ImageDraw.Draw(stamp)
    m = s4 * 0.04
    d.rounded_rectangle([m, m, s4 - m, s4 - m], radius=s4 * 0.08,
                        fill=(*VERMILION, 240))
    if glyph:
        t = s4 * 0.105          # stroke width of the carved glyph
        lo, hi = s4 * 0.20, s4 * 0.80
        bar_top = s4 * 0.62
        carve = (0, 0, 0, 0)
        # 山 — three uprights meeting a base bar, centre stroke tallest
        d.rectangle([s4 * 0.5 - t / 2, s4 * 0.16, s4 * 0.5 + t / 2, bar_top + t], fill=carve)
        d.rectangle([lo, s4 * 0.34, lo + t, bar_top + t], fill=carve)
        d.rectangle([hi - t, s4 * 0.34, hi, bar_top + t], fill=carve)
        d.rectangle([lo, bar_top, hi, bar_top + t], fill=carve)

    # stamp tooth: modulate alpha with coarse noise so the edges break up
    noise = Image.effect_noise((s4, s4), 46).point(lambda v: min(255, 96 + v))
    r_, g_, b_, a_ = stamp.split()
    stamp = Image.merge("RGBA", (r_, g_, b_, ImageChops.multiply(a_, noise)))
    stamp = stamp.rotate(random.uniform(-3.0, -1.5), expand=True,
                         resample=Image.BICUBIC)
    return stamp.resize((stamp.width // 4, stamp.height // 4), Image.LANCZOS)


# ── the three walls ──────────────────────────────────────────────────────

def wall_enso() -> Image.Image:
    img = washi_paper()
    ink = paint_enso(W * SS, H * SS, cx=0.60 * W * SS, cy=0.50 * H * SS,
                     radius=0.335 * H * SS, base_th=0.030 * H * SS)
    img = Image.alpha_composite(img.convert("RGBA"),
                                ink.resize((W, H), Image.LANCZOS))
    hanko = paint_hanko(round(H * 0.072))
    img.alpha_composite(hanko, (int(W * 0.868), int(H * 0.788)))
    return img.convert("RGB")


def wall_ridgeline() -> Image.Image:
    img = washi_paper().convert("RGBA")

    # vermilion sun, flat and a little worn
    sun = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    ImageDraw.Draw(sun).ellipse([20, 20, 380, 380], fill=(*VERMILION, 228))
    noise = Image.effect_noise((400, 400), 34).point(lambda v: min(255, 128 + v))
    r_, g_, b_, a_ = sun.split()
    sun = Image.merge("RGBA", (r_, g_, b_, ImageChops.multiply(a_, noise)))
    sun = sun.filter(ImageFilter.GaussianBlur(0.8)).resize((round(H * 0.132), round(H * 0.132)), Image.LANCZOS)
    img.alpha_composite(sun, (int(W * 0.205), int(H * 0.240)))

    # five ink washes, faint horizon to near-black foreground
    shades = [(206, 199, 176), (172, 164, 139), (128, 121, 99),
              (84, 79, 64), (45, 42, 34)]
    for k, shade in enumerate(shades):
        base = H * (0.545 + 0.095 * k)
        amp = H * (0.050 - 0.006 * k)
        f1, f2, f3 = random.uniform(0.8, 1.4), random.uniform(2.1, 3.2), random.uniform(4.6, 6.4)
        p1, p2, p3 = (random.uniform(0, math.tau) for _ in range(3))
        drift = random.uniform(-0.02, 0.02) * H
        pts = []
        for x in range(0, W + 8, 8):
            u = x / W
            y = (base + drift * (u - 0.5)
                 + amp * (0.65 * math.sin(math.tau * f1 * u + p1)
                          + 0.30 * math.sin(math.tau * f2 * u + p2)
                          + 0.12 * math.sin(math.tau * f3 * u + p3)))
            pts.append((x, y))
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(layer).polygon(pts + [(W, H), (0, H)], fill=(*shade, 255))
        # mist: alpha thins toward the base of each wash
        fade = Image.new("L", (1, H), 0)
        crest = int(min(p[1] for p in pts))
        for y in range(H):
            if y <= crest:
                fade.putpixel((0, y), 255)
            else:
                t = (y - crest) / max(1, H - crest)
                fade.putpixel((0, y), int(255 - 118 * min(1.0, t * 1.6)))
        r_, g_, b_, a_ = layer.split()
        a_ = ImageChops.multiply(a_, fade.resize((W, H)))
        img = Image.alpha_composite(img, Image.merge("RGBA", (r_, g_, b_, a_)))

    hanko = paint_hanko(round(H * 0.067))
    img.alpha_composite(hanko, (int(W * 0.878), int(H * 0.118)))
    return img.convert("RGB")


def wall_washi() -> Image.Image:
    """For the truly quiet desktop: paper, and one seal in the corner."""
    img = washi_paper().convert("RGBA")
    hanko = paint_hanko(round(H * 0.061))
    img.alpha_composite(hanko, (int(W * 0.885), int(H * 0.816)))
    return img.convert("RGB")


# ── bamboo (take) ────────────────────────────────────────────────────────

def _stamp_leaf(bd: ImageDraw.ImageDraw, x: float, y: float, ang: float,
                length: float, width: float) -> None:
    """One bamboo leaf: hair-thin stem, wide wet belly, hard dry tip."""
    steps = max(int(length / 1.5), 8)
    for s in range(steps + 1):
        t = s / steps
        th = width * math.sin(math.pi * min(t * 1.25, 1.0)) ** 0.9 / 2
        if t > 0.70:
            th *= max(0.04, max(0.0, 1 - (t - 0.70) / 0.30) ** 1.25)
        px = x + length * t * math.cos(ang) + random.uniform(-0.7, 0.7)
        py = y + length * t * math.sin(ang) + random.uniform(-0.7, 0.7)
        bd.ellipse([px - th, py - th, px + th, py + th], fill=255)


def _stamp_twig(bd: ImageDraw.ImageDraw, x: float, y: float, ang: float,
                length: float, th: float) -> tuple[float, float]:
    steps = max(int(length / 2), 6)
    for s in range(steps + 1):
        t = s / steps
        px = x + length * t * math.cos(ang)
        py = y + length * t * math.sin(ang)
        bd.ellipse([px - th, py - th, px + th, py + th], fill=255)
    return x + length * math.cos(ang), y + length * math.sin(ang)


def paint_culm(bd: ImageDraw.ImageDraw, w: int, h: int, x_frac: float,
               lean: float, width: float, leaf_len: float) -> None:
    """One culm bottom-to-past-the-top: waved internode polygons separated by
    node gaps (paper breathing through), a collar stroke in each gap, and
    hanging leaf clusters thrown off the upper nodes."""
    bow = random.uniform(-0.03, 0.03) * h
    seg_h = h * random.uniform(0.155, 0.195)
    x0 = x_frac * w

    def cx(y: float) -> float:
        t = 1 - y / h                     # 0 at bottom, 1 at top
        return x0 + lean * t * h + bow * math.sin(math.pi * t)

    def half(y: float) -> float:
        return width * (1 - 0.30 * (1 - y / h)) / 2

    gap = width * 0.42
    y_bot = h + seg_h * random.uniform(0.2, 0.6)
    nodes: list[float] = []
    while y_bot > -seg_h:
        y_top = y_bot - seg_h * random.uniform(0.92, 1.08)
        wave = random.uniform(0, math.tau)
        left, right = [], []
        yy = min(y_bot, h + 4)
        while yy > y_top + gap:
            wob = 1 + 0.05 * math.sin(yy / 26 + wave)
            left.append((cx(yy) - half(yy) * wob, yy))
            right.append((cx(yy) + half(yy) * wob, yy))
            yy -= 6
        if len(left) > 1:
            bd.polygon(left + right[::-1], fill=255)
        if y_top > 0:
            nodes.append(y_top + gap / 2)
        y_bot = y_top

    # node collars: the short horizontal stroke pressed into each gap
    for ny in nodes:
        x, hw = cx(ny), half(ny)
        bd.ellipse([x - hw * 1.18, ny - width * 0.085,
                    x + hw * 1.18, ny + width * 0.085], fill=255)

    # leaf clusters off the upper nodes, hanging down and outward
    for ny in [n for n in nodes if n < h * 0.62]:
        if random.random() < 0.30:
            continue
        side = random.choice((-1, 1))
        tx, ty = _stamp_twig(bd, cx(ny), ny,
                             math.radians(random.uniform(-38, -14)) if side > 0
                             else math.radians(random.uniform(194, 218)),
                             leaf_len * random.uniform(0.6, 1.1), width * 0.055)
        n_leaves = random.randint(3, 5)
        base_ang = math.radians(random.uniform(55, 95))
        for _ in range(n_leaves):
            ang = base_ang + math.radians(random.uniform(-42, 42))
            _stamp_leaf(bd, tx + random.uniform(-8, 8), ty + random.uniform(-6, 6),
                        ang, leaf_len * random.uniform(0.72, 1.15),
                        leaf_len * random.uniform(0.14, 0.18))


def wall_take() -> Image.Image:
    """A bamboo grove in three washes of ink — and one vermilion leaf
    falling where no red has any business being."""
    img = washi_paper().convert("RGBA")
    w2, h2 = W * SS, H * SS

    planes = [
        # colour, blur, culms as (x_frac, lean, width_frac, leaf_frac)
        ((197, 190, 168), 3.4, [(0.335, 0.030, 0.017, 0.052),
                                (0.500, -0.020, 0.014, 0.046)]),
        ((128, 121, 100), 1.9, [(0.185, 0.085, 0.026, 0.066)]),
        (SUMI, 1.1, [(0.095, 0.040, 0.042, 0.085),
                     (0.270, -0.120, 0.036, 0.080)]),
    ]
    for colour, blur, culms in planes:
        mask = Image.new("L", (w2, h2), 0)
        bd = ImageDraw.Draw(mask)
        for x_frac, lean, width_frac, leaf_frac in culms:
            paint_culm(bd, w2, h2, x_frac, lean, width_frac * h2, leaf_frac * h2)
        tone = (Image.effect_noise((w2 // 8 + 1, h2 // 8 + 1), 30)
                .resize((w2, h2), Image.BILINEAR)
                .point(lambda v: 196 + (v * 59) // 255))
        mask = ImageChops.multiply(mask, tone)
        ink = Image.new("RGBA", (w2, h2), (*colour, 0))
        ink.putalpha(mask)
        ink = ink.filter(ImageFilter.GaussianBlur(blur * SS / 2))
        img = Image.alpha_composite(img, ink.resize((W, H), Image.LANCZOS))

    # the one vermilion leaf, mid-fall in all that empty paper
    leaf = Image.new("L", (w2, h2), 0)
    _stamp_leaf(ImageDraw.Draw(leaf), 0.585 * w2, 0.415 * h2,
                math.radians(104), 0.052 * h2, 0.0085 * h2)
    leaf = ImageChops.multiply(leaf, Image.new("L", (w2, h2), 235))
    red = Image.new("RGBA", (w2, h2), (*VERMILION, 0))
    red.putalpha(leaf)
    red = red.filter(ImageFilter.GaussianBlur(1.2))
    img = Image.alpha_composite(img, red.resize((W, H), Image.LANCZOS))

    hanko = paint_hanko(round(H * 0.065))
    img.alpha_composite(hanko, (int(W * 0.868), int(H * 0.788)))
    return img.convert("RGB")


# ── braille enso for fastfetch ───────────────────────────────────────────

BRAILLE_DOTS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


def braille_enso(cols: int = 22, rows: int = 11) -> str:
    """Render the same brush ring tiny and map it onto braille dots."""
    w, h = cols * 2 * 6, rows * 4 * 6   # 6px per dot, then threshold-sample
    ink = paint_enso(w, h, cx=w * 0.52, cy=h * 0.5, radius=h * 0.40,
                     base_th=h * 0.045)
    mask = ink.split()[3].resize((cols * 2, rows * 4), Image.LANCZOS)
    lines = []
    for row in range(rows):
        chars = []
        for col in range(cols):
            code = 0
            for dy in range(4):
                for dx in range(2):
                    if mask.getpixel((col * 2 + dx, row * 4 + dy)) > 96:
                        code |= BRAILLE_DOTS[dy][dx]
            chars.append(chr(0x2800 + code) if code else " ")
        lines.append("".join(chars).rstrip())
    # press the hanko into the gap the brush leaves (top-right)
    art = [f"$1{line}" for line in lines]
    gap_row = 1
    line = art[gap_row].ljust(3 + cols)
    art[gap_row] = line[: 3 + cols - 3] + "$2■$1 "
    return "\n".join(line.rstrip() for line in art) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    random.seed(0x5B0)  # shoji
    wall_enso().save(OUT / "enso.png", optimize=True)
    wall_ridgeline().save(OUT / "ridgeline.png", optimize=True)
    wall_washi().save(OUT / "washi.png", optimize=True)
    LOGO_OUT.write_text(braille_enso(), encoding="utf-8")
    random.seed(0x7A4E)  # take — own seed keeps the walls above byte-stable
    wall_take().save(OUT / "take.png", optimize=True)
    for p in sorted(OUT.iterdir()):
        print(f"{p.name}: {p.stat().st_size // 1024} KiB")
    print(f"{LOGO_OUT.name} written")


if __name__ == "__main__":
    main()
