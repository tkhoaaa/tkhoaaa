# -*- coding: utf-8 -*-
"""
Render dark_mode.svg + light_mode.svg — a neofetch-style card with the Braille
portrait (left column) and an info panel (right column), values right-aligned
with computed dot leaders. Pure stdlib (urllib for the GitHub GraphQL API).

Run:   python generate_svg.py
Live stats: set GITHUB_TOKEN (+ GH_LOGIN) in the environment; otherwise the
defaults in config.py are used.
"""
import os
import io
import sys
import json
import calendar
import urllib.request
from datetime import date

import config

# --- layout ----------------------------------------------------------------- #
FONT = "JetBrains Mono, Consolas, monospace"
FS = 15                     # font-size (px)
LINE = "1.2em"              # dy per line
LINE_PX = 18               # 1.2 * 15
CHARW = 9.0                # monospace advance @15px (used only for info column)
PAD = 22
TOP = 8
GAP = 34
ART_W = 46                 # art is 46 braille chars = 92 dots wide
DOT_SP = 4.5               # px per dot (portrait drawn as vector rects, font-independent)
# braille dot bit -> (col, row) inside each 2x4 cell
DOT_BITS = ((0, 0, 1), (0, 1, 2), (0, 2, 4), (1, 0, 8),
            (1, 1, 16), (1, 2, 32), (0, 3, 64), (1, 3, 128))

PALETTES = {
    "dark":  dict(bg="#0d1117", stroke="#30363d", art="#c9d1d9", label="#58a6ff",
                  dots="#6e7681", value="#c9d1d9", stat="#3fb950", accent="#58a6ff", dim="#6e7681"),
    "light": dict(bg="#ffffff", stroke="#d0d7de", art="#24292f", label="#0969da",
                  dots="#afb8c1", value="#24292f", stat="#1a7f37", accent="#0969da", dim="#57606a"),
}


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def uptime():
    y, m, d = config.BIRTHDAY
    t = date.today()
    yy, mm, dd = t.year - y, t.month - m, t.day - d
    if dd < 0:
        mm -= 1
        pm = t.month - 1 or 12
        py = t.year if t.month > 1 else t.year - 1
        dd += calendar.monthrange(py, pm)[1]
    if mm < 0:
        yy -= 1
        mm += 12
    return f"{yy} years, {mm} months, {dd} days"


def fetch_stats():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return {}
    login = os.environ.get("GH_LOGIN") or config.GH_LOGIN

    def gql(query, variables):
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
            headers={"Authorization": f"bearer {token}",
                     "Content-Type": "application/json",
                     "User-Agent": "profile-svg"})
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read())
        if payload.get("errors"):
            raise RuntimeError(payload["errors"])
        return payload["data"]["user"]

    try:
        stars = repos = followers = 0
        created, after = None, None
        while True:
            u = gql("""query($login:String!,$after:String){user(login:$login){
                createdAt followers{totalCount}
                repositories(first:100,after:$after,ownerAffiliations:OWNER,isFork:false){
                  totalCount pageInfo{hasNextPage endCursor} nodes{stargazerCount}}}}""",
                    {"login": login, "after": after})
            followers = u["followers"]["totalCount"]
            created = u["createdAt"]
            rp = u["repositories"]
            repos = rp["totalCount"]
            stars += sum(n["stargazerCount"] for n in rp["nodes"])
            if rp["pageInfo"]["hasNextPage"]:
                after = rp["pageInfo"]["endCursor"]
            else:
                break

        commits = 0
        for yr in range(int(created[:4]), date.today().year + 1):
            cc = gql("""query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){
                contributionsCollection(from:$from,to:$to){
                  totalCommitContributions restrictedContributionsCount}}}""",
                     {"login": login,
                      "from": f"{yr}-01-01T00:00:00Z",
                      "to": f"{yr}-12-31T23:59:59Z"})["contributionsCollection"]
            commits += cc["totalCommitContributions"] + cc["restrictedContributionsCount"]

        return {"repos": f"{repos:,}", "stars": f"{stars:,}",
                "followers": f"{followers:,}", "commits": f"{commits:,}"}
    except Exception as e:
        print(f"[svg] stats fetch failed, using defaults: {e}", file=sys.stderr)
        return {}


def build_rows():
    up = uptime()
    stats = dict(config.STATS_DEFAULT)
    stats.update(fetch_stats())

    def rv(v):
        return v.replace("{uptime}", up)

    rows = [("header", config.USERNAME, config.HOST)]
    rows += [("kv", l, rv(v)) for l, v in config.SYSTEM]
    rows.append(("blank", "", ""))
    rows += [("kv", l, rv(v)) for l, v in config.LANGUAGES]
    rows.append(("blank", "", ""))
    rows += [("kv", l, rv(v)) for l, v in config.HOBBIES]
    rows.append(("blank", "", ""))
    rows.append(("section", "Contact", ""))
    rows += [("kv", l, rv(v)) for l, v in config.CONTACT]
    rows.append(("blank", "", ""))
    rows.append(("section", "GitHub Stats", ""))
    rows += [("stat", l, stats.get(k, "?")) for l, k in config.STATS]
    return rows


def art_dot_grid():
    """Decode the braille art back into a 92 x 112 boolean dot bitmap."""
    dw, dh = ART_W * 2, len(config.ASCII_ART) * 4
    grid = [bytearray(dw) for _ in range(dh)]
    for cy, row in enumerate(config.ASCII_ART):
        for cx, ch in enumerate(row):
            mask = ord(ch) - 0x2800
            if mask <= 0:
                continue
            for dx, dy, bit in DOT_BITS:
                if mask & bit:
                    grid[cy * 4 + dy][cx * 2 + dx] = 1
    return grid, dw, dh


def art_path(ax, ay):
    """Portrait as vector rects (horizontal run-length encoded) — no font needed."""
    grid, dw, dh = art_dot_grid()
    segs = []
    for y in range(dh):
        row, x = grid[y], 0
        while x < dw:
            if row[x]:
                x0 = x
                while x < dw and row[x]:
                    x += 1
                w = (x - x0) * DOT_SP
                px, py = ax + x0 * DOT_SP, ay + y * DOT_SP
                segs.append(f"M{px:.1f} {py:.1f}h{w:.1f}v{DOT_SP}h-{w:.1f}z")
            else:
                x += 1
    return "".join(segs), dw * DOT_SP, dh * DOT_SP


def render(theme, rows):
    P = PALETTES[theme]
    pairs = [(a, b) for k, a, b in rows if k in ("kv", "stat")]
    info_cols = max(len(a) + len(b) for a, b in pairs) + 4      # >=2 dots + 2 spaces

    art_x, art_y = PAD, TOP
    path_d, art_w, art_h = art_path(art_x, art_y)
    info_x = art_x + int(round(art_w)) + GAP
    info_h = len(rows) * LINE_PX
    W = info_x + int(round(info_cols * CHARW)) + PAD + 8
    H = TOP + int(round(max(art_h, info_h))) + 18

    def tsp(text, role):
        return f'<tspan fill="{P[role]}">{esc(text)}</tspan>'

    info = []
    for kind, a, b in rows:
        if kind == "header":
            head = f"{a}@{b} "
            dash = "─" * (info_cols - len(head))
            segs = [tsp(a, "accent"), tsp("@", "dim"), tsp(b, "value"),
                    tsp(" ", "dim"), tsp(dash, "dim")]
        elif kind == "section":
            head = f"─ {a} "
            dash = "─" * (info_cols - len(head))
            segs = [tsp("─ ", "dim"), tsp(a, "accent"),
                    tsp(" ", "dim"), tsp(dash, "dim")]
        elif kind == "blank":
            segs = [tsp(" ", "dim")]
        else:
            role = "stat" if kind == "stat" else "value"
            dots = max(2, info_cols - len(a) - len(b) - 2)
            segs = [tsp(a, "label"), tsp(" " + "." * dots + " ", "dots"), tsp(b, role)]
        info.append(f'<tspan x="{info_x}" dy="{LINE}">' + "".join(segs) + "</tspan>")

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{FONT}" font-size="{FS}px">'
        f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="6" '
        f'fill="{P["bg"]}" stroke="{P["stroke"]}"/>'
        f'<path fill="{P["art"]}" d="{path_d}"/>'
        f'<text xml:space="preserve" x="{info_x}" y="{TOP}">'
        + "".join(info) +
        '</text>'
        '</svg>\n'
    )


def main():
    rows = build_rows()
    for theme in ("dark", "light"):
        svg = render(theme, rows)
        io.open(f"{theme}_mode.svg", "w", encoding="utf-8", newline="\n").write(svg)
    print("wrote dark_mode.svg + light_mode.svg  |  uptime:", uptime())


if __name__ == "__main__":
    main()
