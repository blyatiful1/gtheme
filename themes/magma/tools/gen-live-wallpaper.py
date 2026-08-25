#!/usr/bin/env python3
"""Render the MAGMA live-wallpaper loop (dark minimal: obsidian field,
breathing floor glow, sparse rising embers).

Every animated term is periodic in tau = frame/N (integer cycle counts),
so frame N wraps exactly to frame 0 — Hanabi loops by seeking to 0 at EOS.

Preview frames:  ./gen-live-wallpaper.py --frames 0,300 --outdir /tmp/x
Full render:     ./gen-live-wallpaper.py --out magma-loop.mp4
"""
import argparse
import subprocess
import sys

import numpy as np

LOOP_SECONDS = 20
FPS = 30
W, H = 2560, 1440

OBSIDIAN_TOP = np.array((13, 10, 15), dtype=np.float32)
OBSIDIAN_BOT = np.array((5, 3, 8), dtype=np.float32)
# heat ramp: black -> deep ember red -> lava -> gold
RAMP_POS = np.array((0.0, 0.45, 0.80, 1.0), dtype=np.float32)
RAMP_RGB = np.array(((0, 0, 0), (120, 22, 38), (255, 109, 58), (255, 193, 69)),
                    dtype=np.float32)

N_EMBERS = 14
RNG = np.random.default_rng(20260707)


def build_static():
    y = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None]
    base = OBSIDIAN_TOP[None, None, :] + (OBSIDIAN_BOT - OBSIDIAN_TOP)[None, None, :] * (y ** 1.3)[..., None]
    base = np.broadcast_to(base, (H, W, 3)).copy()
    d = 1.0 - y                                   # distance from bottom edge
    glow_env = np.exp(-d / 0.075)                 # sharp under-glass band
    haze_env = np.exp(-d / 0.20) * 0.16           # soft upward haze
    grain = RNG.uniform(-1.5, 1.5, (H, W, 1)).astype(np.float32)  # static: no flicker
    embers = []
    for _ in range(N_EMBERS):
        embers.append(dict(
            x0=RNG.uniform(0.03, 0.97), y0=RNG.uniform(0, 1),
            laps=int(RNG.integers(1, 3)), sway=RNG.uniform(0.004, 0.012),
            sway_cycles=int(RNG.integers(2, 5)), phase=RNG.uniform(0, 2 * np.pi),
            twinkle=int(RNG.integers(3, 7)), sigma=RNG.uniform(1.3, 2.8),
            warm=RNG.uniform(0.0, 1.0), gain=RNG.uniform(0.55, 1.0)))
    return base, glow_env, haze_env, grain, embers


def floor_profile(tau, x):
    """Slow breathing 1-D heat profile along the bottom edge (all integer cycles)."""
    b = (0.42
         + 0.20 * np.sin(2 * np.pi * (1.7 * x + 1 * tau) + 0.9)
         + 0.16 * np.sin(2 * np.pi * (3.1 * x - 2 * tau) + 4.1)
         + 0.12 * np.sin(2 * np.pi * (0.9 * x + 1 * tau) + 2.3))
    return np.clip(b, 0.0, 1.0).astype(np.float32)


def heat_to_rgb(heat):
    flat = heat.ravel()
    out = np.empty((flat.size, 3), dtype=np.float32)
    for c in range(3):
        out[:, c] = np.interp(flat, RAMP_POS, RAMP_RGB[:, c])
    return out.reshape(*heat.shape, 3)


def render_frame(i, n_frames, static):
    base, glow_env, haze_env, grain, embers = static
    tau = i / n_frames
    x = np.linspace(0.0, 1.0, W, dtype=np.float32)[None, :]

    smoke = (0.5 * np.sin(2 * np.pi * (1.3 * x + 1 * tau) + 1.1)
             + 0.3 * np.sin(2 * np.pi * (2.6 * x - 2 * tau) + 5.0)) * 0.05

    prof = floor_profile(tau, x)                          # (1, W)
    heat = glow_env * prof * (1.0 + smoke)                # (H, W)
    frame = base + heat_to_rgb(np.clip(heat, 0, 1) * 0.72)
    frame += (haze_env * prof)[..., None] * np.array((60, 22, 12), dtype=np.float32)

    for e in embers:
        rise = (e["y0"] + e["laps"] * tau) % 1.0
        ex = (e["x0"] + e["sway"] * np.sin(2 * np.pi * e["sway_cycles"] * tau + e["phase"])) * W
        ey = (1.0 - rise * 1.06 + 0.03) * H
        if not (-8 < ey < H + 8):
            continue
        alpha = min(rise / 0.06, 1.0) * (1.0 - rise) ** 1.6 * e["gain"]
        alpha *= 0.75 + 0.25 * np.sin(2 * np.pi * e["twinkle"] * tau + e["phase"])
        if alpha <= 0.01:
            continue
        r = int(np.ceil(e["sigma"] * 3))
        x0, x1 = max(int(ex) - r, 0), min(int(ex) + r + 1, W)
        y0, y1 = max(int(ey) - r, 0), min(int(ey) + r + 1, H)
        if x0 >= x1 or y0 >= y1:
            continue
        gy, gx = np.mgrid[y0:y1, x0:x1]
        blob = np.exp(-((gx - ex) ** 2 + (gy - ey) ** 2) / (2 * e["sigma"] ** 2))
        col = np.array((255, 109 + 84 * e["warm"], 58 + 11 * e["warm"]), dtype=np.float32)
        frame[y0:y1, x0:x1] += (alpha * blob)[..., None] * col[None, None, :]

    return np.clip(frame + grain, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="encode full loop to this mp4 via ffmpeg")
    ap.add_argument("--frames", help="comma list of frame indices to dump as PNGs")
    ap.add_argument("--outdir", default=".", help="dir for --frames PNGs")
    args = ap.parse_args()
    n_frames = LOOP_SECONDS * FPS
    static = build_static()

    if args.frames:
        from PIL import Image
        for i in (int(s) for s in args.frames.split(",")):
            Image.fromarray(render_frame(i, n_frames, static)).save(
                f"{args.outdir}/frame_{i:04d}.png")
        return
    if not args.out:
        sys.exit("need --out or --frames")

    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", args.out],
        stdin=subprocess.PIPE)
    for i in range(n_frames):
        enc.stdin.write(render_frame(i, n_frames, static).tobytes())
        if i % 100 == 0:
            print(f"{i}/{n_frames}", file=sys.stderr)
    enc.stdin.close()
    sys.exit(enc.wait())


if __name__ == "__main__":
    main()
