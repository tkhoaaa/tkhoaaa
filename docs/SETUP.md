# Profile card — setup & maintenance

The GitHub profile is a single self-contained SVG (two themes) generated from a
portrait photo + `config.yaml`. Nothing external is loaded at view time — the
portrait is baked to vector rectangles and the text uses a monospace font
fallback chain, so it renders identically for every visitor.

```
assets/AnhCV3x4.jpg ──gen_ascii.py──> assets/braille_art.txt       (dark)
        (private)                      assets/braille_art_light.txt (light)
                                                │
config.yaml ─────────────────────── generate.py ──> dark_mode.svg
                                                     light_mode.svg  ──> README.md
```

| Path | Role |
| --- | --- |
| `assets/AnhCV3x4.jpg` | Private source photo (git-ignored) |
| `scripts/gen_ascii.py` | Photo → Braille portrait + PNG previews (run locally when the photo changes) |
| `assets/braille_art*.txt` | Committed portrait (dark + light-inverted) that the card reads |
| `config.yaml` | All static text, contact links, and theme palettes |
| `templates/card.svg` | SVG skeleton with CSS classes + `__TOKEN__` placeholders |
| `scripts/generate.py` | Fills the template with live GitHub stats → `dark_mode.svg` / `light_mode.svg` |
| `.github/workflows/update.yml` | Rebuilds + commits the SVGs daily |

## Prerequisites

```bash
python -m pip install -r requirements.txt        # card only (PyYAML)
python -m pip install -r requirements-dev.txt     # + Pillow/numpy for gen_ascii.py
```

## Change text, contact, stats, or colours

Everything visible except the portrait lives in `config.yaml` (system rows,
languages, hobbies, contact + links, the stat labels, `stats_default`, and both
theme palettes). Edit it, then:

```bash
python scripts/generate.py
```

`Uptime` is computed from `birthday`. `Lines of Code` renders as `+added / -deleted`.

## Change the portrait photo

1. Drop the new photo in at `assets/` (a clean, evenly-lit, flat-background
   head-and-shoulders shot works best). Point `--input` at it, or replace
   `assets/AnhCV3x4.jpg`.
2. Regenerate the Braille portrait and review the previews:

   ```bash
   python scripts/gen_ascii.py --width 88 --crop-bottom 0.54 --gamma 1.0 \
       --contrast 3 --falloff 0.5 --mode braille
   ```

   Inspect `previews/braille_400.png` at 100% zoom (that's roughly its size on
   GitHub) and `previews/braille_800.png` for detail. This writes
   `assets/braille_art.txt` (dark) and `assets/braille_art_light.txt` (light).
3. Rebuild the cards: `python scripts/generate.py`, then check
   `previews/card_dark.png` / `card_light.png` (or open the SVGs in a browser).

### `gen_ascii.py` tunables

| Flag | Default | Effect |
| --- | --- | --- |
| `--width` | 60 | Portrait width in characters (try 75–88 for detail) |
| `--contrast` | 3 | Percentile clip each side (higher = punchier) |
| `--gamma` | 0.85 | `<1` brightens, `>1` darkens midtones |
| `--falloff` | 0.55 | Sub-chin darkening so a white collar doesn't vanish (1 = off) |
| `--local` | 0 | CLAHE-style local contrast (0–1.5) |
| `--unsharp` | 1.2 | Edge sharpening for eyes/nose/mouth |
| `--crop-bottom` | 0.66 | Fraction of the subject kept from the top (lower = tighter bust) |
| `--dither` / `--no-dither` | on | Floyd–Steinberg error diffusion |
| `--ramp` | medium | `short` \| `medium` \| `long`, or a literal ASCII ramp |
| `--mode` | both | `braille` \| `ascii` \| `both` |

An **ASCII-text** variant (`--mode ascii`) is also implemented. It was evaluated
but lost to Braille for this soft studio portrait (a coarse character ramp can't
resolve the low facial contrast that Braille's denser dot grid dithers). It
becomes viable with a higher-contrast / directionally-lit photo — regenerate,
compare `previews/ascii_400.png` vs `braille_400.png`, and if ASCII wins, point
`config.yaml`'s `portrait.art_*` at `assets/ascii_art.txt` (rendered as `<text>`).

## Live stats

`generate.py` reads `GITHUB_TOKEN` (+ optional `GH_LOGIN`) and pulls repos,
stars, followers, commits (GraphQL) and lines added/removed (REST
`stats/contributors`, cached in `loc_cache.json` by repo `pushedAt`). Without a
token, `config.yaml`'s `stats_default` values are used, so the card always
renders. The daily workflow supplies the token automatically.

## Notes

- **Contact links inside the SVG are display-only on GitHub.** Because the card
  is embedded via `<img>`/`<picture>`, GitHub renders it as a static image, so
  the in-SVG `<a xlink:href>` links show the text but aren't clickable. To make
  the whole card link to your site, wrap the `<picture>` in `README.md` with
  `<a href="https://www.portfolio-votienkhoa.online/">…</a>`.
- **Contribution snake:** removed. To bring it back, add a
  [`Platane/snk`](https://github.com/Platane/snk) workflow and embed its output
  SVG at the end of `README.md`.
