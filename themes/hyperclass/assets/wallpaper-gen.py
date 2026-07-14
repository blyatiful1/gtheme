#!/usr/bin/env python3
"""Procedural wallpaper generator for the HYPERCLASS theme.

The three shipped wallpapers are rendered by this script (seeded, so the
output is reproducible byte-for-byte on the same numpy). Re-run it to render
at another resolution:

    python3 wallpaper-gen.py [WIDTH HEIGHT] [OUTDIR]

Needs numpy (authoring-time only — the theme itself never runs this).
The materials are the palette's: champagne brass trim on deep-space ink,
ivory starlight, one vein of ice. Gold is line weight, never fill weight —
the luxury is the emptiness.
"""
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

# Cabin materials (palette.toml, as float RGB).
INK = np.array([18, 21, 31], dtype=np.float64)          # bg  #12151F
INK_DEEP = np.array([13, 15, 23], dtype=np.float64)
BRASS = np.array([201, 162, 74], dtype=np.float64)      # accent  #C9A24A
CHAMPAGNE = np.array([235, 217, 168], dtype=np.float64) # #EBD9A8
IVORY = np.array([234, 227, 209], dtype=np.float64)     # fg  #EAE3D1
STARLIGHT = np.array([251, 246, 231], dtype=np.float64) # fg_bright  #FBF6E7
ICE = np.array([169, 218, 232], dtype=np.float64)       # #A9DAE8
INDIGO = np.array([46, 56, 92], dtype=np.float64)       # nebula wash


def write_png(path, rgb):
    """Minimal RGB8 PNG writer (filter 0), no dependencies beyond zlib."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].astype(np.uint8).tobytes() for y in range(h))

    def chunk(tag, data):
        block = tag + data
        return struct.pack(">I", len(data)) + block + struct.pack(">I", zlib.crc32(block))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    Path(path).write_bytes(png)


def value_noise(rng, h, w, res):
    """Smooth value noise: a random lattice sampled with quintic fade."""
    lat = rng.random((res + 2, res * w // max(h, 1) + 2))
    ys = np.linspace(0, res, h, endpoint=False)
    xs = np.linspace(0, lat.shape[1] - 2, w, endpoint=False)
    yi, xi = ys.astype(int), xs.astype(int)
    yf, xf = ys - yi, xs - xi
    fy = (yf * yf * yf * (yf * (yf * 6 - 15) + 10))[:, None]
    fx = (xf * xf * xf * (xf * (xf * 6 - 15) + 10))[None, :]
    a = lat[np.ix_(yi, xi)]
    b = lat[np.ix_(yi, xi + 1)]
    c = lat[np.ix_(yi + 1, xi)]
    d = lat[np.ix_(yi + 1, xi + 1)]
    return a * (1 - fx) * (1 - fy) + b * fx * (1 - fy) + c * (1 - fx) * fy + d * fx * fy


def fbm(rng, h, w, octaves=5, base_res=4):
    total = np.zeros((h, w))
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        total += amp * value_noise(rng, h, w, base_res * (2 ** o))
        norm += amp
        amp *= 0.5
    return total / norm


def vignette(h, w, strength=0.30):
    y = np.linspace(-1, 1, h)[:, None]
    x = np.linspace(-1, 1, w)[None, :]
    return 1.0 - strength * np.clip(x * x * 0.9 + y * y * 0.8, 0, 1)


def splat(img, x, y, radius, colour, gain):
    """Additive gaussian bloom into a local window (fast star/streak stamp)."""
    h, w, _ = img.shape
    r = max(radius * 3.0, 2.0)
    x0, x1 = max(int(x - r), 0), min(int(x + r) + 1, w)
    y0, y1 = max(int(y - r), 0), min(int(y + r) + 1, h)
    if x0 >= x1 or y0 >= y1:
        return
    yy = np.arange(y0, y1)[:, None] - y
    xx = np.arange(x0, x1)[None, :] - x
    bloom = np.exp(-(xx * xx + yy * yy) / (2 * radius * radius))
    img[y0:y1, x0:x1] += bloom[..., None] * colour * gain


def star_cross(img, x, y, arm, colour, gain):
    """A four-point star: soft core + thin horizontal/vertical flare arms."""
    splat(img, x, y, arm * 0.28, colour, gain)
    h, w, _ = img.shape
    x0, x1 = max(int(x - arm * 3), 0), min(int(x + arm * 3) + 1, w)
    y0, y1 = max(int(y - arm * 3), 0), min(int(y + arm * 3) + 1, h)
    if x0 >= x1 or y0 >= y1:
        return
    yy = np.arange(y0, y1)[:, None] - y
    xx = np.arange(x0, x1)[None, :] - x
    flare = (np.exp(-(yy * yy) / 1.2) * np.exp(-np.abs(xx) / arm)
             + np.exp(-(xx * xx) / 1.2) * np.exp(-np.abs(yy) / arm))
    img[y0:y1, x0:x1] += flare[..., None] * colour * gain * 0.55


def starfield(img, rng, n, y_max=1.0, ice_bias=0.10):
    """Fine star grain: mostly ivory pinpricks, some champagne, a few ice."""
    h, w, _ = img.shape
    for _ in range(n):
        x, y = rng.random() * w, rng.random() ** 1.1 * h * y_max
        u = rng.random()
        colour = ICE if u < ice_bias else (CHAMPAGNE if u < ice_bias + 0.22 else IVORY)
        mag = rng.random() ** 2.6                       # dim stars dominate
        splat(img, x, y, 0.6 + mag * 1.1, colour, 0.10 + mag * 0.55)


def gilded_void(w, h):
    """The hero: an art-deco sunburst in brass hairlines low on an ink field.

    Vast negative space by design — the marque rises like a theatre curtain
    call at the bottom of the frame and the void does the rest.
    """
    rng = np.random.default_rng(7)
    img = np.zeros((h, w, 3))
    # ink field, a shade deeper at the top so the stars have depth to hang in
    ys = np.linspace(0, 1, h)[:, None, None]
    img += INK_DEEP + (INK - INK_DEEP) * np.clip(ys * 1.4, 0, 1)

    starfield(img, rng, n=(w * h) // 11000, y_max=0.85)
    for _ in range(6):                                   # a few marquee stars
        x, y = rng.random() * w, rng.random() * h * 0.55
        star_cross(img, x, y, 5.0 + rng.random() * 5.0,
                   ICE if rng.random() < 0.3 else STARLIGHT, 0.5)

    # the sunburst origin, low-centre; all geometry hangs off polar coords
    cx, cy = w * 0.5, h * 0.80
    yy = (np.arange(h)[:, None] - cy)
    xx = (np.arange(w)[None, :] - cx)
    r = np.sqrt(xx * xx + yy * yy) + 1e-6
    theta = np.arctan2(yy, xx)                           # -pi..pi, 0 = east

    # a soft brass halo breathing around the origin (the only "fill", kept faint)
    img += np.exp(-(r / (0.16 * h)) ** 2)[..., None] * BRASS * 0.10

    # rays: a deco fan of hairlines, alternating long/medium/short
    n_rays = 30
    px = max(w / 2560.0, 0.8)                            # hairline width in px
    lengths = {0: 0.52, 1: 0.30, 2: 0.40, 3: 0.30}       # of h, pattern L M S M
    up = yy < 0                                          # rays live above origin
    ray_sum = np.zeros((h, w))
    for k in range(n_rays + 1):
        phi = -np.pi * k / n_rays                        # 180° fan, west to east
        L = lengths[k % 4] * h
        delta = np.arctan2(np.sin(theta - phi), np.cos(theta - phi))
        thin = np.exp(-0.5 * (delta * r / (1.5 * px)) ** 2)
        taper = np.clip(1 - r / L, 0, 1) ** 0.7 * np.clip(r / (0.05 * h) - 0.4, 0, 1)
        ray_sum += thin * taper
    ray_sum = np.clip(ray_sum, 0, 1) * up
    img += ray_sum[..., None] * BRASS * 0.85
    # a wider, dimmer glow pass so the hairlines shimmer instead of etch
    glow = np.zeros((h, w))
    for k in range(n_rays + 1):
        phi = -np.pi * k / n_rays
        L = lengths[k % 4] * h
        delta = np.arctan2(np.sin(theta - phi), np.cos(theta - phi))
        wide = np.exp(-0.5 * (delta * r / (6.0 * px)) ** 2)
        glow += wide * np.clip(1 - r / L, 0, 1)
    img += (np.clip(glow, 0, 1) * up)[..., None] * BRASS * 0.10

    # concentric champagne arcs: the rising marque's engraved collar
    for j, (rad, alpha) in enumerate(((0.050, 0.55), (0.066, 0.40), (0.082, 0.28))):
        band = np.exp(-0.5 * ((r - rad * h) / (1.1 * px)) ** 2) * up
        img += band[..., None] * CHAMPAGNE * alpha

    # the sun itself: a small half-disc, champagne rimmed with brass
    disc = np.clip(1 - r / (0.036 * h), 0, 1) ** 0.6 * up
    img += disc[..., None] * (CHAMPAGNE * 0.85 + BRASS * 0.15) * 0.9
    ring = np.exp(-0.5 * ((r - 0.040 * h) / (1.2 * px)) ** 2) * up
    img += ring[..., None] * BRASS * 0.7

    # horizon hairline either side of the marque, fading out
    horiz = np.exp(-0.5 * (yy / (0.9 * px)) ** 2) * np.exp(-np.abs(xx) / (0.30 * w))
    img += (horiz * (r > 0.05 * h))[..., None] * BRASS * 0.45

    img *= vignette(h, w, 0.26)[..., None]
    img += (rng.random((h, w, 1)) - 0.5) * 2.0           # anti-banding grain
    return np.clip(img, 0, 255)


def first_light(w, h):
    """The window seat: a ringed gas giant catching dawn, mostly silhouette."""
    rng = np.random.default_rng(19)
    img = np.zeros((h, w, 3))
    ys = np.linspace(0, 1, h)[:, None, None]
    img += INK_DEEP + (INK - INK_DEEP) * (0.4 + 0.6 * ys)

    # nebula wash, upper left, kept to a whisper
    neb = fbm(rng, h, w, octaves=6, base_res=3)
    fade = (np.linspace(1, 0, h)[:, None] ** 1.6) * (np.linspace(1, 0.15, w)[None, :])
    img += (neb ** 2.2 * fade)[..., None] * INDIGO * 0.55

    starfield(img, rng, n=(w * h) // 6500, y_max=1.0)
    for _ in range(5):
        x, y = rng.random() * w, rng.random() * h * 0.5
        star_cross(img, x, y, 4.0 + rng.random() * 6.0, STARLIGHT, 0.45)

    # the planet: a huge ink sphere low-right, lit by a dawn we cannot see
    pcx, pcy, pr = w * 0.72, h * 0.90, 0.36 * h
    yy = (np.arange(h)[:, None] - pcy)
    xx = (np.arange(w)[None, :] - pcx)
    d = np.sqrt(xx * xx + yy * yy)
    inside = d < pr
    # limb-darkened night side: barely lighter than the void
    depth = np.sqrt(np.clip(1 - (d / pr) ** 2, 0, 1))
    night = (INK * 0.55 + INDIGO * 0.20)
    img = np.where(inside[..., None], night * (0.5 + 0.5 * depth[..., None]), img)
    # faint banded weather, visible only where the rim light reaches
    bands = fbm(rng, h, w, octaves=4, base_res=6)
    lat = np.clip((yy / pr + 1) * 3.0, 0, 6)
    stripes = 0.5 + 0.5 * np.sin(lat * 3.1 + bands * 2.0)
    # rim light: dawn breaks over the upper-left limb
    lx, ly = -0.62, -0.78                                 # toward the dawn (upper-left)
    nx, ny = xx / pr, yy / pr
    ndotl = np.clip(nx * lx + ny * ly, 0, 1)
    rim = np.clip(1 - d / pr, 0, 1)
    crescent = (np.exp(-rim / 0.085) * ndotl ** 2.4) * inside
    img += crescent[..., None] * (CHAMPAGNE * 0.8 + BRASS * 0.2) * 1.5
    img += (crescent * stripes * 0.6)[..., None] * BRASS
    # atmosphere: an ice-thin veil hugging the limb, warmest where lit
    atmo = np.exp(-np.abs(d - pr) / (0.012 * h)) * (~inside)
    img += atmo[..., None] * ICE * 0.30
    img += (atmo * ndotl ** 2)[..., None] * CHAMPAGNE * 0.55

    # the rings: brass hairline ellipses, tilted; far side hides behind the disc
    ang = np.deg2rad(-22.0)
    ca, sa = np.cos(ang), np.sin(ang)
    rx = xx * ca + yy * sa
    ry = -xx * sa + yy * ca
    front = ry > 0                                        # near side passes in front
    # gradient of light along the rings: brightest toward the dawn (upper-left)
    ring_lit = np.clip(-rx / (pr * 2.2) + 0.55, 0.25, 1.0)
    for frac, alpha, width in ((1.36, 0.85, 1.8), (1.50, 0.55, 1.4),
                               (1.66, 0.70, 2.4), (1.84, 0.38, 1.4)):
        a_, b_ = pr * frac, pr * frac * 0.22
        e = np.sqrt((rx / a_) ** 2 + (ry / b_) ** 2)
        band = np.exp(-0.5 * ((e - 1.0) / (width * 1.2 / b_)) ** 2)
        visible = front | (~inside)
        img += (band * visible * ring_lit)[..., None] * BRASS * alpha
        img += (band * visible * ring_lit ** 3)[..., None] * CHAMPAGNE * alpha * 0.45

    # a distant companion moon, ice-lit, upper left — the destination
    splat(img, w * 0.17, h * 0.22, 2.2, ICE, 1.3)
    splat(img, w * 0.17, h * 0.22, 6.0, ICE, 0.12)

    img *= vignette(h, w, 0.30)[..., None]
    img += (rng.random((h, w, 1)) - 0.5) * 2.0
    return np.clip(img, 0, 255)


def warp_transit(w, h):
    """Mid-jump through the void: starlight drawn into champagne threads."""
    rng = np.random.default_rng(31)
    img = np.zeros((h, w, 3))
    img += INK_DEEP

    # the blue-shift: a cold breath of ice at the vanishing point
    cx, cy = w * 0.42, h * 0.50
    yy = (np.arange(h)[:, None] - cy)
    xx = (np.arange(w)[None, :] - cx)
    r = np.sqrt(xx * xx + yy * yy)
    img += np.exp(-(r / (0.14 * h)) ** 2)[..., None] * ICE * 0.10
    img += np.exp(-(r / (0.035 * h)) ** 2)[..., None] * STARLIGHT * 0.14

    diag = np.hypot(w, h)
    n = 430
    for i in range(n):
        ang = rng.random() * 2 * np.pi
        # heads cluster mid-frame; tails reach back toward the point
        head_r = (0.06 + rng.random() ** 1.5 * 0.62) * diag
        length = head_r * (0.22 + rng.random() * 0.45)
        u = rng.random()
        colour = (ICE if u < 0.06 else BRASS if u < 0.22
                  else CHAMPAGNE if u < 0.55 else IVORY)
        gain = 0.22 + rng.random() ** 2 * 0.9
        big = rng.random() < 0.04                        # the near misses
        girth = (1.8 if big else 0.75) + head_r / diag * 1.6
        steps = max(int(length / 2.5), 6)
        for s in range(steps):
            t = s / (steps - 1)
            rr = head_r - length * (1 - t)
            x = cx + np.cos(ang) * rr
            y = cy + np.sin(ang) * rr
            if not (-20 < x < w + 20 and -20 < y < h + 20):
                continue
            # comet law: brightest at the head, thread fades astern
            splat(img, x, y, girth * (0.55 + 0.45 * t), colour, gain * t * t * 0.42)
        # the head itself: a hard bright point, still wearing its colour
        hx, hy = cx + np.cos(ang) * head_r, cy + np.sin(ang) * head_r
        if 0 <= hx < w and 0 <= hy < h:
            splat(img, hx, hy, girth * 0.8, colour * 0.65 + STARLIGHT * 0.35, gain * 0.9)

    img *= vignette(h, w, 0.36)[..., None]
    img += (rng.random((h, w, 1)) - 0.5) * 2.0
    return np.clip(img, 0, 255)


def main():
    args = sys.argv[1:]
    w, h = (int(args[0]), int(args[1])) if len(args) >= 2 else (2560, 1440)
    outdir = Path(args[2]) if len(args) >= 3 else Path(__file__).parent.parent / "files" / "wallpaper"
    outdir.mkdir(parents=True, exist_ok=True)
    for name, fn in (("gilded-void", gilded_void),
                     ("first-light", first_light),
                     ("warp-transit", warp_transit)):
        img = fn(w, h)
        write_png(outdir / f"{name}.png", img)
        print(f"wrote {outdir / (name + '.png')} ({w}x{h})")


if __name__ == "__main__":
    main()
