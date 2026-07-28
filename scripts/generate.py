#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate.py — render dark_mode.svg + light_mode.svg: a neofetch-style card with
the Braille portrait (left, vector rects — font independent) and an info panel
(right, monospace <text> with computed dot leaders and right-aligned values).

    python scripts/generate.py

Live numbers (repos / commits / stars / followers / lines-of-code ++/--) are
pulled from the GitHub API when GITHUB_TOKEN is set; otherwise config.yaml's
stats_default values are used, so the card always renders.
"""
import calendar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- layout ---------------------------------------------------------------- #
FONT = ('"JetBrains Mono","Cascadia Code",ui-monospace,"SFMono-Regular",'
        'Menlo,Consolas,"Liberation Mono",monospace')
FS = 15                 # font-size (px)
LINE = 18               # line height (px)  ~1.2em
CHARW = 9.0             # monospace advance @15px (canvas width only)
PAD = 24
TOP = 16
GAP = 36
# braille dot bit -> (col, row) inside each 2x4 cell
DOT_BITS = ((0, 0, 1), (0, 1, 2), (0, 2, 4), (1, 0, 8),
            (1, 1, 16), (1, 2, 32), (0, 3, 64), (1, 3, 128))


def cfg():
    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# --------------------------------------------------------------------------- #
# live data
# --------------------------------------------------------------------------- #
def uptime(birthday):
    y, m, d = birthday
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


def human(n):
    n = abs(int(n))
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if n >= 1_000:
        return (f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k") if n < 100_000 else f"{round(n / 1000)}k"
    return str(n)


def _gql(token, query, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "profile-svg"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.loads(r.read())
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]["user"]


def _rest(token, path, retries=3):
    """GET api.github.com<path>; retry on 202 (stats still computing)."""
    for i in range(retries):
        req = urllib.request.Request(
            "https://api.github.com" + path,
            headers={"Authorization": f"bearer {token}", "User-Agent": "profile-svg",
                     "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 202:
                    time.sleep(1.5)
                    continue
                return json.loads(r.read() or "null")
        except urllib.error.HTTPError as e:
            if e.code == 202:
                time.sleep(1.5)
                continue
            raise
    return None


def fetch_loc(token, login, repos):
    """Best-effort lines added/removed by the user, cached by repo pushedAt."""
    path = os.path.join(ROOT, "loc_cache.json")
    try:
        cache = json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        cache = {}
    add = dele = ok = 0
    for r in repos:
        name, pushed = r["name"], r["pushedAt"]
        hit = cache.get(name)
        if hit and hit.get("pushedAt") == pushed:
            add += hit["a"]; dele += hit["d"]; ok += 1
            continue
        try:
            data = _rest(token, f"/repos/{login}/{name}/stats/contributors")
        except Exception:  # noqa: BLE001
            data = None
        if not data:
            continue
        a = d = 0
        for c in data:
            au = c.get("author") or {}
            if (au.get("login") or "").lower() == login.lower():
                for w in c["weeks"]:
                    a += w["a"]; d += w["d"]
        cache[name] = {"pushedAt": pushed, "a": a, "d": d}
        add += a; dele += d; ok += 1
    try:
        json.dump(cache, open(path, "w", encoding="utf-8"), indent=0)
    except Exception:  # noqa: BLE001
        pass
    if ok == 0:
        return {}
    return {"loc_add": f"+{human(add)}", "loc_del": f"-{human(dele)}"}


def fetch_stats():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("[gen] no GITHUB_TOKEN — using config defaults", file=sys.stderr)
        return {}
    login = os.environ.get("GH_LOGIN") or cfg()["gh_login"]
    try:
        stars = repos = followers = 0
        created, after, nodes = None, None, []
        while True:
            u = _gql(token, """query($login:String!,$after:String){user(login:$login){
                createdAt followers{totalCount}
                repositories(first:100,after:$after,ownerAffiliations:OWNER,isFork:false){
                  totalCount pageInfo{hasNextPage endCursor}
                  nodes{name pushedAt stargazerCount}}}}""",
                       {"login": login, "after": after})
            followers = u["followers"]["totalCount"]
            created = u["createdAt"]
            rp = u["repositories"]
            repos = rp["totalCount"]
            nodes += rp["nodes"]
            stars += sum(n["stargazerCount"] for n in rp["nodes"])
            if rp["pageInfo"]["hasNextPage"]:
                after = rp["pageInfo"]["endCursor"]
            else:
                break

        commits = 0
        for yr in range(int(created[:4]), date.today().year + 1):
            cc = _gql(token, """query($login:String!,$from:DateTime!,$to:DateTime!){
                user(login:$login){contributionsCollection(from:$from,to:$to){
                  totalCommitContributions restrictedContributionsCount}}}""",
                      {"login": login, "from": f"{yr}-01-01T00:00:00Z",
                       "to": f"{yr}-12-31T23:59:59Z"})["contributionsCollection"]
            commits += cc["totalCommitContributions"] + cc["restrictedContributionsCount"]

        out = {"repos": f"{repos:,}", "stars": f"{stars:,}",
               "followers": f"{followers:,}", "commits": f"{commits:,}"}
        out.update(fetch_loc(token, login, nodes))
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[gen] stats fetch failed, using defaults: {e}", file=sys.stderr)
        return {}


# --------------------------------------------------------------------------- #
# portrait: braille file -> vector path (RLE horizontal runs)
# --------------------------------------------------------------------------- #
def art_path(art_file, ax, ay, dot):
    lines = open(os.path.join(ROOT, art_file), encoding="utf-8").read().splitlines()
    dw = max((len(l) for l in lines), default=0) * 2
    dh = len(lines) * 4
    grid = [bytearray(dw) for _ in range(dh)]
    for cy, row in enumerate(lines):
        for cx, ch in enumerate(row):
            mask = ord(ch) - 0x2800
            if mask <= 0:
                continue
            for dx, dy, bit in DOT_BITS:
                if mask & bit:
                    grid[cy * 4 + dy][cx * 2 + dx] = 1
    segs = []
    for y in range(dh):
        row, x = grid[y], 0
        while x < dw:
            if row[x]:
                x0 = x
                while x < dw and row[x]:
                    x += 1
                w = (x - x0) * dot
                px, py = ax + x0 * dot, ay + y * dot
                segs.append(f"M{px:.1f} {py:.1f}h{w:.1f}v{dot}h-{w:.1f}z")
            else:
                x += 1
    return "".join(segs), dw * dot, dh * dot


# --------------------------------------------------------------------------- #
# info panel rows
# --------------------------------------------------------------------------- #
def build_rows(c, stats):
    up = uptime(c["birthday"])
    vals = dict(c["stats_default"])
    vals.update(stats)

    def rv(v):
        return v.replace("{uptime}", up)

    rows = [("header", c["username"], c["host"], None)]
    rows += [("kv", l, rv(v), None) for l, v in c["system"]]
    rows.append(("blank", "", "", None))
    rows += [("kv", l, rv(v), None) for l, v in c["languages"]]
    rows.append(("blank", "", "", None))
    rows += [("kv", l, rv(v), None) for l, v in c["hobbies"]]
    rows.append(("blank", "", "", None))
    rows.append(("section", "Contact", "", None))
    rows += [("link", l, v, href) for l, v, href in c["contact"]]
    rows.append(("blank", "", "", None))
    rows.append(("section", "GitHub Stats", "", None))
    for label, key in c["stats"]:
        if key == "loc":
            rows.append(("loc", label, f'{vals["loc_add"]} / {vals["loc_del"]}', vals))
        else:
            rows.append(("stat", label, vals.get(key, "?"), None))
    return rows


def visible_len(kind, a, b):
    return len(a) + len(b)


def build_info(rows, info_cols, info_x):
    def tsp(txt, cls):
        return f'<tspan class="{cls}">{esc(txt)}</tspan>'

    def leader(a, b_len):
        return max(2, info_cols - len(a) - b_len - 2)

    out = []
    for kind, a, b, extra in rows:
        if kind == "header":
            head = f"{a}@{b} "
            segs = [tsp(a, "accent"), tsp("@", "dim"), tsp(b, "title"),
                    tsp(" " + "─" * max(0, info_cols - len(head)), "dim")]
        elif kind == "section":
            head = f"─ {a} "
            segs = [tsp("─ ", "dim"), tsp(a, "accent"),
                    tsp(" " + "─" * max(0, info_cols - len(head)), "dim")]
        elif kind == "blank":
            segs = [tsp(" ", "dim")]
        elif kind == "loc":
            dots = leader(a, len(b))
            segs = [tsp(a, "label"), tsp(" " + "." * dots + " ", "dots"),
                    tsp(extra["loc_add"], "add"), tsp(" / ", "dim"), tsp(extra["loc_del"], "del")]
        elif kind == "link":
            dots = leader(a, len(b))
            segs = [tsp(a, "label"), tsp(" " + "." * dots + " ", "dots"),
                    f'<a xlink:href="{esc(extra)}" target="_blank" rel="noopener">'
                    f'{tsp(b, "value")}</a>']
        else:  # kv / stat
            dots = leader(a, len(b))
            role = "value"
            segs = [tsp(a, "label"), tsp(" " + "." * dots + " ", "dots"), tsp(b, role)]
        out.append(f'<tspan x="{info_x}" dy="{LINE}">' + "".join(segs) + "</tspan>")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
def render(theme, c, rows, info_cols, layout):
    P = c["palette"][theme]
    art_file = c["portrait"]["art_dark" if theme == "dark" else "art_light"]
    art_d, _, _ = art_path(art_file, layout["art_x"], layout["art_y"], c["portrait"]["dot"])
    info = build_info(rows, info_cols, layout["info_x"])
    tpl = open(os.path.join(ROOT, "templates", "card.svg"), encoding="utf-8").read()
    repl = {
        "__W__": layout["W"], "__H__": layout["H"], "__W1__": layout["W"] - 1,
        "__H1__": layout["H"] - 1, "__FS__": FS, "__FONT__": FONT,
        "__ARIA__": esc(f'{c["username"]}@{c["host"]} — {c["system"][3][1]}'),
        "__INFO_X__": layout["info_x"], "__INFO_Y__": layout["info_y"],
        "__ART_D__": art_d, "__INFO__": info,
        "__BG__": P["bg"], "__STROKE__": P["stroke"], "__ART__": P["art"], "__TITLE__": P["title"],
        "__LABEL__": P["label"], "__VALUE__": P["value"], "__DOTS__": P["dots"],
        "__ACCENT__": P["accent"], "__DIM__": P["dim"], "__ADD__": P["add"], "__DEL__": P["del"],
    }
    for k, v in repl.items():
        tpl = tpl.replace(k, str(v))
    return tpl


def main():
    c = cfg()
    stats = fetch_stats()
    rows = build_rows(c, stats)

    kv = [(a, b) for k, a, b, _ in rows if k in ("kv", "stat", "loc", "link")]
    info_cols = max(len(a) + len(b) for a, b in kv) + 4

    # measure the portrait, then vertically centre the shorter column against
    # the taller one (portrait can be head-only or a full bust)
    _, art_w, art_h = art_path(c["portrait"]["art_dark"], 0, 0, c["portrait"]["dot"])
    info_h = len(rows) * LINE
    half = abs(info_h - art_h) / 2
    art_y = TOP + (0 if art_h >= info_h else half)
    info_y = TOP + (half if art_h >= info_h else 0)
    art_x = PAD
    info_x = int(PAD + art_w + GAP)
    W = int(info_x + info_cols * CHARW + PAD)
    H = int(TOP + max(art_h, info_h) + PAD)
    layout = dict(art_x=art_x, art_y=round(art_y, 1), info_x=info_x,
                  info_y=round(info_y, 1), W=W, H=H)

    for theme in ("dark", "light"):
        svg = render(theme, c, rows, info_cols, layout)
        path = os.path.join(ROOT, f"{theme}_mode.svg")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(svg)
        kb = len(svg.encode("utf-8")) / 1024
        flag = "  !! >300KB" if kb > 300 else ""
        print(f"[gen] {theme}_mode.svg  {W}x{H}  {kb:.1f}KB{flag}")
    print(f"[gen] uptime: {uptime(c['birthday'])}  |  live stats: {'yes' if stats else 'no (defaults)'}")


if __name__ == "__main__":
    main()
