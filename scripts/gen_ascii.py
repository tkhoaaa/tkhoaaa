#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_ascii.py — turn a portrait photo into (A) a pure-ASCII ramp portrait and
(B) a tonal Braille portrait, from ONE shared background-removed input, then
render real-display-size PNG previews of each for side-by-side review.

Pipeline
    photo
      -> background removal (rembg if importable, else flat-bg flood fill)
      -> assets/portrait_clean.png            (RGBA, subject on transparency)
      -> bust crop + gentle sub-chin luminance falloff (white collar won't vanish)
      -> grayscale -> unsharp -> percentile stretch -> gamma
      -> resample to char grid (+ background mask -> sentinel blank)
      -> ASCII  : Floyd-Steinberg over a >=14-level pure-ASCII ramp
      -> Braille: Floyd-Steinberg to 1-bit dots, packed 2x4 per cell
      -> assets/ascii_art.txt , assets/braille_art.txt   (tuned for DARK theme)
      -> previews/{ascii,braille}_{400,800}.png (+ ascii rendered in a 2nd font)

Everything you might want to re-tune is a CLI flag, so you can iterate without
editing code:

    python scripts/gen_ascii.py --width 60 --gamma 0.85 --ramp medium --dither
    python scripts/gen_ascii.py --width 80 --contrast 4 --no-dither --mode ascii

The committed art is tuned for the DARK card; generate.py re-polarizes it for
the light card, so DO NOT bake a light-mode variant here.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# sparse -> dense ; index 0 (space) is reserved for the background sentinel.
RAMPS = {
    "short":  " .:-=+*#%@",
    "medium": " .,:;i1tfLCG08@",
    "long":   " .'`^\",:;Il!i~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
}

# monospace fonts known to exist on this machine (for faithful previews +
# the "columns don't shift across fonts" check).
FONT_CANDIDATES = {
    "cascadia": [r"C:\Windows\Fonts\CascadiaMono.ttf", r"C:\Windows\Fonts\CascadiaCode.ttf"],
    "consolas": [r"C:\Windows\Fonts\consola.ttf"],
}

DARK_BG = (13, 17, 23)      # #0d1117  (GitHub dark canvas)
DARK_FG = (201, 209, 217)   # #c9d1d9  (art colour on dark)

BRAILLE_BITS = ((0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (1, 0, 0x08),
                (1, 1, 0x10), (1, 2, 0x20), (0, 3, 0x40), (1, 3, 0x80))


# --------------------------------------------------------------------------- #
# background removal
# --------------------------------------------------------------------------- #
def remove_bg(img: Image.Image) -> np.ndarray:
    """Return uint8 alpha (H, W): 255 = subject, 0 = background."""
    rgb = img.convert("RGB")
    try:                                    # best effort: crisp hair edges
        import rembg
        cut = rembg.remove(rgb)
        alpha = np.asarray(cut.convert("RGBA"))[..., 3]
        if (alpha > 127).mean() > 0.02:
            print("[bg] using rembg")
            return alpha
    except Exception as e:                  # noqa: BLE001
        print(f"[bg] rembg unavailable ({e.__class__.__name__}); manual flood fill")

    arr = np.asarray(rgb).astype(np.float32)
    H, W, _ = arr.shape
    seed = np.median(arr[: max(4, H // 20)].reshape(-1, 3), axis=0)      # top strip = bg
    dist = np.sqrt(((arr - seed) ** 2).sum(2))
    bright = arr.mean(2)
    cand = (dist < 42.0) & (bright > 195.0)                             # "looks like bg"

    # keep only bg connected to the TOP border (protects the white collar,
    # which the head/neck separates from the top background).
    scale = 360.0 / max(H, W)
    sw, sh = max(1, int(W * scale)), max(1, int(H * scale))
    small = np.asarray(Image.fromarray((cand * 255).astype(np.uint8))
                       .resize((sw, sh), Image.NEAREST)) > 127
    reach = np.zeros_like(small)
    reach[0] |= small[0]
    reach[:, 0] |= small[:, 0]
    reach[:, -1] |= small[:, -1]
    for _ in range(sh + sw):
        nxt = reach.copy()
        nxt[1:] |= reach[:-1]
        nxt[:-1] |= reach[1:]
        nxt[:, 1:] |= reach[:, :-1]
        nxt[:, :-1] |= reach[:, 1:]
        nxt &= small
        if np.array_equal(nxt, reach):
            break
        reach = nxt
    reach_full = np.asarray(Image.fromarray((reach * 255).astype(np.uint8))
                            .resize((W, H), Image.NEAREST)) > 127
    alpha = np.where(reach_full & cand, 0, 255).astype(np.uint8)
    alpha = np.asarray(Image.fromarray(alpha).filter(ImageFilter.MedianFilter(3)))
    return alpha


# --------------------------------------------------------------------------- #
# crop + tone
# --------------------------------------------------------------------------- #
def local_contrast(g: np.ndarray, strength: float, radius: float) -> np.ndarray:
    """CLAHE-style local contrast: local z-score, blended with global tone.

    Equalises contrast within small neighbourhoods so soft facial modelling
    (eyes, nostrils, lips) separates, while a global blend keeps hair dark and
    skin light overall. No OpenCV needed — Gaussian mean/variance via Pillow.
    """
    g = np.clip(g, 0, 1).astype(np.float32)

    def blur(a):
        return np.asarray(Image.fromarray((a * 255).astype(np.uint8))
                          .filter(ImageFilter.GaussianBlur(radius))).astype(np.float32) / 255.0

    mean = blur(g)
    std = np.sqrt(np.clip(blur(g * g) - mean * mean, 0, None)) + 1e-2
    local = np.clip(0.5 + 0.18 * ((g - mean) / std), 0, 1)          # equalised
    out = np.clip((1.0 - 0.35) * local + 0.35 * g, 0, 1)           # keep global cue
    return g + strength * (out - g)


def bust_crop(img: Image.Image, alpha: np.ndarray, args):
    """Grayscale bust crop (float 0..1) + boolean subject mask, enhanced."""
    ys, xs = np.where(alpha > 127)
    if xs.size == 0:
        sys.exit("[crop] empty subject mask — check background removal")
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    Hb, Wb = y1 - y0, x1 - x0

    cy0 = max(0, y0 - int(0.03 * Hb))
    cy1 = min(alpha.shape[0], int(y0 + args.crop_bottom * Hb))
    padx = int(args.crop_padx * Wb)
    cx0 = max(0, x0 - padx)
    cx1 = min(alpha.shape[1], x1 + padx)

    gray = np.asarray(img.convert("L")).astype(np.float32)[cy0:cy1, cx0:cx1]
    mask = alpha[cy0:cy1, cx0:cx1] > 127
    if args.unsharp > 0:
        gray = np.asarray(
            Image.fromarray(gray.astype(np.uint8)).filter(
                ImageFilter.UnsharpMask(radius=2, percent=int(args.unsharp * 100), threshold=2))
        ).astype(np.float32)
    gray /= 255.0
    if args.local > 0:
        gray = local_contrast(gray, args.local, radius=gray.shape[1] / 22.0)
    return gray, mask


def resample(gray: np.ndarray, mask: np.ndarray, cols: int, rows: int):
    g = np.asarray(Image.fromarray((np.clip(gray, 0, 1) * 255).astype(np.uint8))
                   .resize((cols, rows), Image.BOX)).astype(np.float32) / 255.0
    m = np.asarray(Image.fromarray((mask * 255).astype(np.uint8))
                   .resize((cols, rows), Image.BOX)).astype(np.float32) / 255.0 > 0.5
    return g, m


def tone(g: np.ndarray, m: np.ndarray, contrast: float, gamma: float, falloff: float):
    sub = g[m]
    if sub.size:
        lo, hi = np.percentile(sub, [contrast, 100.0 - contrast])
        hi = hi if hi > lo else lo + 1e-3
        g = np.clip((g - lo) / (hi - lo), 0, 1)
    g = np.power(np.clip(g, 0, 1), gamma)
    if falloff < 1.0:                                   # darken below the chin
        rows = g.shape[0]
        b0 = int(rows * 0.62)
        r = np.ones(rows, np.float32)
        if rows - 1 > b0:
            t = (np.arange(b0, rows) - b0) / (rows - 1 - b0)
            r[b0:] = 1.0 - (1.0 - falloff) * t
        g = g * r[:, None]
    return np.clip(g, 0, 1)


# --------------------------------------------------------------------------- #
# quantisation
# --------------------------------------------------------------------------- #
def quantize(g: np.ndarray, m: np.ndarray, levels: int, dither: bool) -> np.ndarray:
    """Return int grid: 0..levels-1 for subject, -1 for background."""
    if not dither:
        out = np.round(np.clip(g, 0, 1) * (levels - 1)).astype(np.int32)
        return np.where(m, out, -1)

    g = g.astype(np.float32).copy()
    H, W = g.shape
    out = np.full((H, W), -1, np.int32)
    for y in range(H):
        for x in range(W):
            if not m[y, x]:
                continue
            old = float(min(1.0, max(0.0, g[y, x])))
            q = int(round(old * (levels - 1)))
            out[y, x] = q
            err = old - q / (levels - 1)
            for dx, dy, w in ((1, 0, 0.4375), (-1, 1, 0.1875), (0, 1, 0.3125), (1, 1, 0.0625)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H and m[ny, nx]:
                    g[ny, nx] += err * w
    return out


def ascii_lines(q: np.ndarray, ramp: str) -> list[str]:
    sub = ramp[1:]                                      # ramp[0] == ' ' == background
    n = len(sub)
    rows = []
    for row in q:
        rows.append("".join(" " if v < 0 else sub[min(n - 1, v)] for v in row))
    return [r.rstrip() or " " for r in rows]


def braille_lines(dot_on: np.ndarray) -> list[str]:
    R, C = dot_on.shape[0] // 4, dot_on.shape[1] // 2
    out = []
    for cy in range(R):
        s = []
        for cx in range(C):
            mask = 0
            for dx, dy, bit in BRAILLE_BITS:
                if dot_on[cy * 4 + dy, cx * 2 + dx]:
                    mask |= bit
            s.append(chr(0x2800 + mask))
        out.append("".join(s).rstrip() or "⠀")
    return out


# --------------------------------------------------------------------------- #
# previews
# --------------------------------------------------------------------------- #
def font_path(name: str) -> str | None:
    for p in FONT_CANDIDATES.get(name, []):
        if os.path.exists(p):
            return p
    return None


def render_ascii_png(lines, path, target_w, fp, pad=16):
    cols = max(len(l) for l in lines)
    rows = len(lines)
    size = max(6, int(round(target_w / cols / (ImageFont.truetype(fp, 100).getlength("M") / 100.0))))
    font = ImageFont.truetype(fp, size)
    adv = font.getlength("M")
    lh = int(round(size * 1.20))
    W = int(adv * cols) + 2 * pad
    H = lh * rows + 2 * pad
    im = Image.new("RGB", (W, H), DARK_BG)
    d = ImageDraw.Draw(im)
    for i, line in enumerate(lines):
        d.text((pad, pad + i * lh), line, font=font, fill=DARK_FG)
    im.save(path)
    return im.size


def render_braille_png(dot_on, path, target_w, pad=16, fg=DARK_FG, bg=DARK_BG):
    Dh, Dw = dot_on.shape
    p = target_w / Dw
    s = max(1, int(round(p)))
    W = int(Dw * p) + 2 * pad
    H = int(Dh * p) + 2 * pad
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    ys, xs = np.where(dot_on)
    for y, x in zip(ys.tolist(), xs.tolist()):
        px, py = pad + int(x * p), pad + int(y * p)
        d.rectangle([px, py, px + s - 1, py + s - 1], fill=fg)
    im.save(path)
    return im.size


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=os.path.join(ROOT, "assets", "AnhCV3x4.jpg"))
    ap.add_argument("--width", type=int, default=60, help="portrait width in characters (cols)")
    ap.add_argument("--contrast", type=float, default=3.0, help="percentile clip each side (0..15)")
    ap.add_argument("--gamma", type=float, default=0.85, help="<1 brightens, >1 darkens midtones")
    ap.add_argument("--ramp", default="medium", help="short|medium|long or a literal ramp string")
    ap.add_argument("--unsharp", type=float, default=1.2, help="unsharp amount (0 disables)")
    ap.add_argument("--local", type=float, default=0.0, help="CLAHE-style local contrast (0..1.5)")
    ap.add_argument("--falloff", type=float, default=0.55, help="sub-chin brightness floor (1=off)")
    ap.add_argument("--crop-bottom", dest="crop_bottom", type=float, default=0.66)
    ap.add_argument("--crop-padx", dest="crop_padx", type=float, default=0.06)
    ap.add_argument("--dither", dest="dither", action="store_true", default=True)
    ap.add_argument("--no-dither", dest="dither", action="store_false")
    ap.add_argument("--invert", action="store_true", help="invert tone (debug; themes handle this)")
    ap.add_argument("--mode", choices=("ascii", "braille", "both"), default="both")
    args = ap.parse_args()

    ramp = RAMPS.get(args.ramp, args.ramp)
    if ramp[0] != " ":
        ramp = " " + ramp

    img = Image.open(args.input)
    print(f"[in ] {args.input}  {img.size[0]}x{img.size[1]}")
    alpha = remove_bg(img)

    rgba = img.convert("RGBA")
    rgba.putalpha(Image.fromarray(alpha))
    clean = os.path.join(ROOT, "assets", "portrait_clean.png")
    rgba.save(clean)
    print(f"[bg ] subject={ (alpha>127).mean()*100:.1f}%  -> {os.path.relpath(clean, ROOT)}")

    gray, mask = bust_crop(img, alpha, args)
    ch, cw = gray.shape
    cols = args.width
    rows = max(1, round(cols * (ch / cw) * 0.5))
    print(f"[fit] crop {cw}x{ch}  ->  grid {cols}x{rows} cells")

    if args.invert:
        gray = 1.0 - gray

    made = []
    if args.mode in ("ascii", "both"):
        g, m = resample(gray, mask, cols, rows)
        g = tone(g, m, args.contrast, args.gamma, args.falloff)
        q = quantize(g, m, len(ramp) - 1, args.dither)
        lines = ascii_lines(q, ramp)
        with open(os.path.join(ROOT, "assets", "ascii_art.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        fp_c = font_path("cascadia")
        fp_x = font_path("consolas")
        s400 = render_ascii_png(lines, os.path.join(ROOT, "previews", "ascii_400.png"), 410, fp_c)
        render_ascii_png(lines, os.path.join(ROOT, "previews", "ascii_800.png"), 820, fp_c)
        if fp_x:
            render_ascii_png(lines, os.path.join(ROOT, "previews", "ascii_400_consolas.png"), 410, fp_x)
        made.append(f"ascii  {cols}x{rows}  ramp={len(ramp)-1}lvl  dither={args.dither}  png={s400}")

    if args.mode in ("braille", "both"):
        g, m = resample(gray, mask, cols * 2, rows * 4)
        g = tone(g, m, args.contrast, args.gamma, args.falloff)
        q = quantize(g, m, 2, True)                     # 1-bit dots, always dithered
        dot_dark = (q == 1)                             # dark theme: dots = highlights
        dot_light = m & ~dot_dark                       # light theme: invert, bg stays off
        for name, dots in (("braille_art.txt", dot_dark), ("braille_art_light.txt", dot_light)):
            with open(os.path.join(ROOT, "assets", name), "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(braille_lines(dots)) + "\n")
        s400 = render_braille_png(dot_dark, os.path.join(ROOT, "previews", "braille_400.png"), 410)
        render_braille_png(dot_dark, os.path.join(ROOT, "previews", "braille_800.png"), 820)
        render_braille_png(dot_light, os.path.join(ROOT, "previews", "braille_light_400.png"), 410,
                           fg=(36, 41, 47), bg=(255, 255, 255))
        made.append(f"braille {cols*2}x{rows*4} dots  png={s400}  (+ light inverse)")

    print("[out] " + "\n      ".join(made))


if __name__ == "__main__":
    main()
