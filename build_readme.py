# -*- coding: utf-8 -*-
"""
Generate README.md for github.com/tkhoaaa in neofetch "terminal readout" style.

- Left column : 46x28 ASCII portrait rendered from assets/AnhCV3x4.jpg (Pillow).
                Rendered WITHOUT color so it adapts to GitHub light/dark themes.
- Right column: neofetch info panel with dot leaders, wrapped in a ```ansi block
                using REAL ESC (0x1B) bytes so GitHub renders the colors.

Run:  python build_readme.py      (rewrites ./README.md)

Edit DOB / fields below and re-run to regenerate. Alignment is verified in-script.
"""
import re
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")

# ----------------------------------------------------------------------------- #
#  YOUR DATA  (edit here, then re-run)
# ----------------------------------------------------------------------------- #
DOB = date(2004, 12, 6)               # 6 Dec 2004  -> Uptime
USER = "votienkhoa"
HOST = "github"

_days = (date.today() - DOB).days
UPTIME = f"{_days // 365} years, {_days % 365} days"

GROUPS = [
    ("system", [
        ("OS",                    "Windows 11 · Linux (WSL2)"),
        ("Uptime",                UPTIME),
        ("Host",                  "HUTECH · HCMC, Vietnam"),
        ("Kernel",                "Fresher Fullstack Developer"),
        ("IDE",                   "VS Code · Cursor"),
    ]),
    ("langs", [
        ("Languages.Programming", "TypeScript · Java · Dart · SQL"),
        ("Languages.Computer",    "HTML · CSS · Bash · JSON"),
        ("Languages.Real",        "Vietnamese (native) · English"),
    ]),
    ("hobbies", [
        ("Hobbies.Software",      "web apps · open-source · tooling"),
        ("Interests.Software",    "landing pages · portfolio · e-commerce"),
    ]),
    ("contact", [
        ("Email",                 "votienkhoa111@gmail.com"),
        ("LinkedIn",              "in/vo-tien-khoa"),
        ("Facebook",              "fb.com/khoa.votien.16"),
    ]),
    ("stats", [
        ("Repos",                 "30+"),
        ("Commits",               "1.2k+"),
        ("Stars",                 "25+"),
        ("Followers",             "40+"),
        ("Lines of Code",         "312k+"),
    ]),
]

# ----------------------------------------------------------------------------- #
#  ANSI helpers  (\033 -> real ESC byte when written)
# ----------------------------------------------------------------------------- #
ESC = "\033"
RESET = f"{ESC}[0m"

# palette (16-color codes -> visible in BOTH light & dark GitHub themes)
YELLOW = "33"    # labels
CYAN = "36"      # values
GRAY = "90"      # rules + dot leaders
GREEN = "32"     # growth stats
BOLD = "1"


def c(code, text):
    return f"{ESC}[{code}m{text}"


def vis(s):
    """Visible width = string with ANSI escapes removed."""
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


# geometry -------------------------------------------------------------------- #
ART_W = 46
SEP = "   "
VALUE_COL = 26                                   # column where every value starts
_all_values = [v for _, rows in GROUPS for _, v in rows]
PANEL_W = VALUE_COL + max(len(v) for v in _all_values)


def pad(line):
    """Right-pad a colored line to PANEL_W visible chars, then reset."""
    fill = PANEL_W - len(vis(line))
    return line + (" " * max(0, fill)) + RESET


def header():
    left = f"{USER}@{HOST} "
    dashes = "─" * (PANEL_W - len(left))
    return pad(c(BOLD, c(CYAN, USER)) + c(GRAY, "@") + c(CYAN, HOST) + " " + c(GRAY, dashes))


def group_bar(title):
    prefix = f"─ {title} "
    dashes = "─" * (PANEL_W - len(prefix))
    return pad(c(GRAY, "─ ") + c(f"{BOLD};{YELLOW}", title) + c(GRAY, " " + dashes))


def item(label, value, value_code=CYAN):
    dots = "." * max(1, VALUE_COL - 4 - len(label))       # "· " + label + " " + dots + " "
    return pad(c(GRAY, "· ") + c(YELLOW, label) + c(GRAY, f" {dots} ") + c(value_code, value))


def blank():
    return pad("")


def swatches():
    line = ""
    for bg in range(40, 48):
        line += c(str(bg), "   ")
    return pad(line + RESET)


def tagline():
    return pad(c(GRAY, "◍ open to fresher / intern fullstack roles · 2022→"))


# build panel (exactly 28 lines) --------------------------------------------- #
def build_panel():
    p = [header()]
    sysg, langg, hobg, cong, statg = (rows for _, rows in GROUPS)
    for l, v in sysg:
        p.append(item(l, v))
    p.append(blank())
    for l, v in langg:
        p.append(item(l, v))
    p.append(blank())
    for l, v in hobg:
        p.append(item(l, v))
    p.append(blank())
    p.append(group_bar("Contact"))
    for l, v in cong:
        p.append(item(l, v))
    p.append(blank())
    p.append(group_bar("GitHub Stats"))
    for l, v in statg:
        p.append(item(l, v, GREEN))
    p.append(blank())
    p.append(swatches())
    p.append(tagline())
    return p


# ----------------------------------------------------------------------------- #
#  ASCII portrait  (46 x 28, block shading, no color)
# ----------------------------------------------------------------------------- #
# Braille dot bit positions inside each 2x4 cell (Unicode block U+2800..U+28FF)
#   (col, row) -> bit :   1 4 / 2 5 / 3 6 / 7 8
_BRAILLE_BITS = ((0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (1, 0, 0x08),
                 (1, 1, 0x10), (1, 2, 0x20), (0, 3, 0x40), (1, 3, 0x80))

# INVERT=False -> dark pixels become dots (clean portrait on empty background).
# INVERT=True  -> bright pixels become dots (filled background, subject as voids = ACII.md tone).
ART_INVERT = True
ART_DITHER = False         # False = crisp threshold fill (denser); True = Floyd-Steinberg scatter
ART_THRESHOLD = 128        # lower -> denser dots / fewer voids; higher -> more voids
ART_GAMMA = 1.0            # tone curve before threshold (<1 brightens = even denser)


def build_art(h=28):
    """46x28 Braille portrait: 2x4 dots per char = 92x112 px, Floyd-Steinberg
    dithered — same fine-grained style as ACII.md."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return fallback_art(h)
    img = Image.open("assets/AnhCV3x4.jpg").convert("L")
    w0, h0 = img.size
    crop_h = min(h0, round(w0 * 1.217))                  # portrait aspect for 2x4 cells
    img = img.crop((0, 0, w0, crop_h))
    img = ImageOps.autocontrast(img, cutoff=2)
    lut = [min(255, int((i / 255) ** ART_GAMMA * 255)) for i in range(256)]
    big = img.point(lut).resize((ART_W * 2, h * 4))
    if ART_DITHER:
        big = big.convert("1")                           # Floyd-Steinberg (scattered)
    px = big.load()
    rows = []
    for cy in range(h):
        line = []
        for cx in range(ART_W):
            mask = 0
            for dx, dy, bit in _BRAILLE_BITS:
                v = px[cx * 2 + dx, cy * 4 + dy]
                bright = (v != 0) if ART_DITHER else (v >= ART_THRESHOLD)
                if bright == ART_INVERT:                 # INVERT: bright=dot; else dark=dot
                    mask |= bit
            line.append(chr(0x2800 + mask))
        rows.append("".join(line))
    return rows


def fallback_art(h=28):
    name = ["", "", "", "",
            "  ╔══════════════════════════════════╗",
            "  ║                                  ║",
            "  ║   ██╗  ██╗██╗  ██╗ ██████╗  █████╗║",
            "  ║   ██║ ██╔╝██║  ██║██╔═══██╗██╔══██║",
            "  ║   █████╔╝ ███████║██║   ██║███████║",
            "  ║   ██╔═██╗ ██╔══██║██║   ██║██╔══██║",
            "  ║   ██║  ██╗██║  ██║╚██████╔╝██║  ██║",
            "  ║   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝",
            "  ║                                  ║",
            "  ║        V Õ   T I Ế N   K H O A    ║",
            "  ║        fullstack developer       ║",
            "  ║                                  ║",
            "  ╚══════════════════════════════════╝"]
    rows = [s[:ART_W] for s in name]
    while len(rows) < h:
        rows.append("")
    return rows[:h]


# ----------------------------------------------------------------------------- #
#  Assemble + verify + write
# ----------------------------------------------------------------------------- #
def main():
    panel = build_panel()
    art = build_art(len(panel))

    # self-check: every panel line is exactly PANEL_W visible chars
    bad = [(i, len(vis(p))) for i, p in enumerate(panel) if len(vis(p)) != PANEL_W]
    assert not bad, f"panel width mismatch (want {PANEL_W}): {bad}"

    n = max(len(art), len(panel))
    combined = []
    for i in range(n):
        a = art[i] if i < len(art) else ""
        p = panel[i] if i < len(panel) else pad("")
        combined.append(a.ljust(ART_W) + SEP + p)

    # self-check: every combined line has identical visible width
    widths = sorted({len(vis(x)) for x in combined})
    assert len(widths) == 1, f"combined widths not uniform: {widths}"

    block = "```ansi\n" + "\n".join(combined) + "\n```"
    readme = HOWTO + "\n\n" + block + "\n\n" + BODY
    with open("README.md", "w", encoding="utf-8", newline="\n") as f:
        f.write(readme)

    print(f"OK  panel_w={PANEL_W}  combined_w={widths[0]}  lines={n}  esc_bytes~={readme.count(ESC)}")


# ----------------------------------------------------------------------------- #
#  Markdown around the ansi block
# ----------------------------------------------------------------------------- #
HOWTO = """<!--
  📌 ĐƯA README NÀY LÊN TRANG PROFILE:
  1. Tạo repo mới TÊN TRÙNG username: "tkhoaaa"  (github.com/new)
  2. Public + Add a README file
  3. Thay README.md bằng file này (giữ nguyên byte ESC — đừng copy qua chat)
  4. GitHub tự hiện tại github.com/tkhoaaa
  Khối màu ở dưới là ```ansi với ESC thật (0x1B). Regenerate: python build_readme.py
-->"""

BODY = """<div align="center">

[![Portfolio](https://img.shields.io/badge/Portfolio-portfolio--votienkhoa.online-0ea5e9?style=for-the-badge&logo=vercel&logoColor=white)](https://www.portfolio-votienkhoa.online/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-vo--tien--khoa-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/vo-tien-khoa)
[![Email](https://img.shields.io/badge/Email-votienkhoa111%40gmail.com-EA4335?style=for-the-badge&logo=gmail&logoColor=white)](mailto:votienkhoa111@gmail.com)
[![Facebook](https://img.shields.io/badge/Facebook-khoa.votien-1877F2?style=for-the-badge&logo=facebook&logoColor=white)](https://www.facebook.com/khoa.votien.16)

<br/>

<!-- LIVE stats — auto-updated daily by .github/workflows/stats.yml -->
<picture>
  <source media="(prefers-color-scheme: dark)"  srcset="./output/dark_mode.svg" />
  <source media="(prefers-color-scheme: light)" srcset="./output/light_mode.svg" />
  <img alt="Live GitHub stats — Võ Tiến Khoa" src="./output/dark_mode.svg" width="520" />
</picture>

</div>

---

## 🚀 Featured projects

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>📘 LingoRise</h3>
      <p><b>IELTS &amp; TOEIC platform</b> — exam engine, speaking recorder, PayOS, Cognito JWT, PostgreSQL + AWS.</p>
      <p><code>Next.js</code> <code>TypeScript</code> <code>Node.js</code> <code>AWS</code></p>
      <p>🔗 <a href="https://lingorise.xyz/">lingorise.xyz</a></p>
    </td>
    <td width="50%" valign="top">
      <h3>🎓 HUTECH Admission</h3>
      <p><b>Online admissions system</b> — multi-step SPA + Admin Dashboard, JWT, PWA; Lighthouse ~70 → ~92.</p>
      <p><code>React</code> <code>Vite</code> <code>Tailwind</code> <code>MySQL</code></p>
      <p>🔗 <a href="https://hutech-admission.vercel.app/">Live</a> · <a href="https://github.com/tkhoaaa/HutechAdmission">Repo</a></p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>💬 KMess</h3>
      <p><b>Cross-platform social app</b> — realtime chat, stories, voice/video (WebRTC), Flutter + Firebase.</p>
      <p><code>Flutter</code> <code>Dart</code> <code>Firebase</code> <code>Socket.IO</code></p>
      <p>📦 <a href="https://github.com/tkhoaaa/Kmess-App">Kmess-App</a></p>
    </td>
    <td width="50%" valign="top">
      <h3>🪟 ToolChat Widget</h3>
      <p><b>Floating Messenger desktop app</b> — always-on-top, frameless Electron widget, global shortcuts.</p>
      <p><code>Electron</code> <code>JavaScript</code> <code>Node.js</code></p>
      <p>🌐 <a href="https://github.com/tkhoaaa/ToolChatWidgetMess">ToolChatWidgetMess</a></p>
    </td>
  </tr>
</table>

---

## 🛠️ Tech stack

<div align="center">

<img src="https://skillicons.dev/icons?i=html,css,js,ts,react,nextjs,vite,tailwind,redux,flutter" alt="Frontend" /><br/>
<img src="https://skillicons.dev/icons?i=nodejs,express,postgres,mysql,mongodb,firebase,java,spring" alt="Backend" /><br/>
<img src="https://skillicons.dev/icons?i=aws,vercel,docker,git,github,postman,figma,electron" alt="Cloud &amp; tools" />

</div>

<div align="center">
<br/>
<img src="https://komarev.com/ghpvc/?username=tkhoaaa&style=for-the-badge&color=0ea5e9&label=PROFILE+VIEWS" alt="views" />
<br/><br/>
<em>"Ship · Learn · Iterate" — open to intern / fresher fullstack roles.</em>
</div>
"""


if __name__ == "__main__":
    main()
