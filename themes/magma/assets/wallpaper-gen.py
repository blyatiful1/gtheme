#!/usr/bin/env python3
"""Procedural wallpaper generator for the MAGMA theme.

The three shipped wallpapers are rendered by this script (seeded, so the
output is reproducible byte-for-byte on the same numpy). Re-run it to render
at another resolution:

    python3 wallpaper-gen.py [WIDTH HEIGHT] [OUTDIR]

Needs numpy (authoring-time only — the theme itself never runs this).
The heat ramp is the same one magma-lavalamp uses in the terminal, so the
desktop and the terminal glow the same colours.
"""
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

# Same ramp as files/bin/magma-lavalamp.
STOPS = (
    (0.00, (13, 10, 15)),
    (0.30, (38, 16, 34)),
    (0.46, (96, 24, 40)),
    (0.60, (224, 48, 78)),
    (0.72, (255, 109, 58)),
    (0.84, (255, 193, 69)),
    (0.94, (255, 238, 190)),
    (1.00, (255, 252, 235)),
)
OBSIDIAN = np.array([13, 10, 15], dtype=np.float64)


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


def heat(field):
    """Map a 0..1 field through the lava heat ramp -> HxWx3 float."""
    xs = np.array([s[0] for s in STOPS])
    out = np.empty(field.shape + (3,))
    for c in range(3):
        ys = np.array([s[1][c] for s in STOPS], dtype=np.float64)
        out[..., c] = np.interp(field, xs, ys)
    return out


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


def vignette(h, w, strength=0.35):
    y = np.linspace(-1, 1, h)[:, None]
    x = np.linspace(-1, 1, w)[None, :]
    return 1.0 - strength * np.clip(x * x + y * y * 0.8, 0, 1)


def obsidian_flow(w, h):
    """Cooled glass: faint ridged sheen, thin lava cracks glowing low down."""
    rng = np.random.default_rng(11)
    sheen = fbm(rng, h, w, octaves=6, base_res=3)
    ridge = 1.0 - np.abs(fbm(rng, h, w, octaves=5, base_res=5) * 2.0 - 1.0)

    img = np.zeros((h, w, 3))
    img += OBSIDIAN
    # glassy sheen: barely-there plum highlights along ridges
    tint = np.array([52, 32, 54], dtype=np.float64)
    img += (ridge ** 4.5 * (0.35 + 0.65 * sheen))[..., None] * (tint - OBSIDIAN) * 0.55

    # cracks: near-zero contours of a second field, hotter toward the floor
    crack_field = fbm(rng, h, w, octaves=5, base_res=6) * 2.0 - 1.0
    width = 0.012 + 0.02 * fbm(rng, h, w, octaves=3, base_res=4)
    glow = np.clip(1.0 - np.abs(crack_field) / (width * 3.5), 0, 1)
    core = np.clip(1.0 - np.abs(crack_field) / width, 0, 1)
    depth = (np.linspace(0, 1, h) ** 2.6)[:, None]          # only glows low down
    intensity = np.clip(core * 0.95 + glow * 0.30, 0, 1) * depth
    img = img * (1 - intensity[..., None]) + heat(np.clip(0.35 + intensity * 0.62, 0, 1)) * intensity[..., None]

    img *= vignette(h, w)[..., None]
    return np.clip(img, 0, 255)


def molten_core(w, h):
    """The lava lamp itself: quartic metaballs on the shared heat ramp."""
    rng = np.random.default_rng(23)
    ys = np.linspace(0, 1, h)[:, None]
    xs = np.linspace(0, 1, w)[None, :]
    aspect = w / h
    field = np.zeros((h, w))
    blobs = [
        # (x, y, r) — an ascending column right of centre, sinkers left
        (0.62, 0.80, 0.145), (0.68, 0.52, 0.115), (0.60, 0.24, 0.095),
        (0.30, 0.36, 0.125), (0.24, 0.68, 0.100), (0.42, 0.90, 0.150),
        (0.82, 0.16, 0.070),
    ]
    for bx, by, r in blobs:
        dx = (xs - bx) * aspect
        dy = ys - by
        # gaussian wax: graded orange interior, white only at the core
        field += np.exp(-(dx * dx + dy * dy) / (2 * (r / 1.4) ** 2))
    floor = np.clip((ys - 0.86) / 0.14, 0, 1) ** 1.6 * 0.45
    field = field + floor
    # organic wobble so the blobs don't look machined
    field *= 0.93 + 0.14 * fbm(rng, h, w, octaves=4, base_res=6)
    img = heat(np.clip(field * 0.92, 0, 1))
    # fine grain so the gradients don't band on 8-bit panels
    img += (rng.random((h, w, 1)) - 0.5) * 2.0
    img *= vignette(h, w, 0.30)[..., None]
    return np.clip(img, 0, 255)


def ember_drift(w, h):
    """Night updraft: warm haze low, embers rising, a few big bokeh sparks."""
    rng = np.random.default_rng(47)
    ys = np.linspace(0, 1, h)[:, None]
    img = np.zeros((h, w, 3)) + OBSIDIAN
    img += heat(np.clip((ys - 0.55) * 0.75, 0, 1) * 0.42) * (ys ** 3)[..., None] * 0.55

    yy = np.arange(h)[:, None]
    xx = np.arange(w)[None, :]
    n = 260
    px = rng.random(n) * w
    py = (rng.random(n) ** 0.7) * h                          # denser low down
    size = rng.random(n)
    for i in range(n):
        # heat falls off with altitude; size sets the bloom radius
        alt = 1.0 - py[i] / h
        temp = np.clip(0.95 - alt * 0.75 + rng.normal(0, 0.06), 0.2, 1.0)
        r = 1.2 + size[i] * (2.2 if size[i] < 0.97 else 9.0)  # rare big bokeh
        d2 = (xx - px[i]) ** 2 + (yy - py[i]) ** 2
        bloom = np.exp(-d2 / (2 * r * r))
        colour = heat(np.array([[temp]]))[0, 0]
        img += bloom[..., None] * colour * (0.9 if size[i] < 0.97 else 0.35)

    img *= vignette(h, w, 0.32)[..., None]
    return np.clip(img, 0, 255)


def main():
    args = sys.argv[1:]
    w, h = (int(args[0]), int(args[1])) if len(args) >= 2 else (2560, 1440)
    outdir = Path(args[2]) if len(args) >= 3 else Path(__file__).parent.parent / "files" / "wallpaper"
    outdir.mkdir(parents=True, exist_ok=True)
    for name, fn in (("obsidian-flow", obsidian_flow),
                     ("molten-core", molten_core),
                     ("ember-drift", ember_drift)):
        img = fn(w, h)
        write_png(outdir / f"{name}.png", img)
        print(f"wrote {outdir / (name + '.png')} ({w}x{h})")


if __name__ == "__main__":
    main()
