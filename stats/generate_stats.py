# -*- coding: utf-8 -*-
"""
Fetch live GitHub stats and render animated neofetch-style SVGs
(output/dark_mode.svg + output/light_mode.svg) with a typewriter effect.

Env:
  GH_TOKEN / GITHUB_TOKEN : token for the GraphQL + REST calls
  GH_USER                 : login (default: tkhoaaa)

No token / offline  -> uses FALLBACK seed numbers so the SVGs still render.
Run:  python stats/generate_stats.py
"""
import os
import sys
import time
from datetime import date

sys.stdout.reconfigure(encoding="utf-8")

try:
    import requests
except ImportError:                       # local run without requests -> fallback
    requests = None

USER = os.environ.get("GH_USER", "tkhoaaa")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
API = "https://api.github.com"

FALLBACK = dict(repos=32, commits=1240, stars=27, followers=41,
                additions=312530, deletions=98120)

GQL = """
query($login:String!, $after:String){
  user(login:$login){
    followers { totalCount }
    repositories(first:100, after:$after, ownerAffiliations:OWNER, isFork:false){
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        stargazerCount
        defaultBranchRef { target { ... on Commit { history { totalCount } } } }
      }
    }
  }
}
"""


def gql(after=None):
    r = requests.post(f"{API}/graphql",
                      json={"query": GQL, "variables": {"login": USER, "after": after}},
                      headers={"Authorization": f"bearer {TOKEN}"}, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]["user"]


def code_frequency(owner, name, retries=3):
    """REST weekly [week, additions, deletions]; 202 = computing -> retry."""
    url = f"{API}/repos/{owner}/{name}/stats/code_frequency"
    for _ in range(retries):
        r = requests.get(url, headers={"Authorization": f"bearer {TOKEN}"}, timeout=30)
        if r.status_code == 202:
            time.sleep(2)
            continue
        if r.status_code == 200 and isinstance(r.json(), list):
            return r.json()
        return []
    return []


def fetch():
    if not (requests and TOKEN):
        return None
    try:
        nodes, followers, after = [], 0, None
        while True:
            u = gql(after)
            followers = u["followers"]["totalCount"]
            repo = u["repositories"]
            nodes += repo["nodes"]
            if repo["pageInfo"]["hasNextPage"]:
                after = repo["pageInfo"]["endCursor"]
            else:
                total_repos = repo["totalCount"]
                break

        stars = sum(n["stargazerCount"] for n in nodes)
        commits = 0
        for n in nodes:
            ref = n.get("defaultBranchRef")
            if ref and ref.get("target"):
                commits += ref["target"]["history"]["totalCount"]

        add = dele = 0
        for n in nodes:
            owner, name = n["nameWithOwner"].split("/")
            for wk in code_frequency(owner, name):
                if len(wk) >= 3:
                    add += max(0, wk[1])
                    dele += abs(wk[2])

        if add == 0:                      # code_frequency unavailable -> keep seed LOC
            add, dele = FALLBACK["additions"], FALLBACK["deletions"]

        return dict(repos=total_repos, commits=commits, stars=stars,
                    followers=followers, additions=add, deletions=dele)
    except Exception as e:                # never fail the workflow on a stats hiccup
        print(f"[stats] fetch failed, using fallback: {e}")
        return None


def human(n):
    return f"{n:,}"


# --------------------------------------------------------------------------- #
#  SVG rendering (animated typewriter, dark + light)
# --------------------------------------------------------------------------- #
PALETTE = {
    "dark":  dict(bg="#0d1117", stroke="#30363d", title="#8b949e", prompt="#7ee787",
                  label="#d29922", dots="#484f58", value="#79c0ff", add="#3fb950",
                  dele="#f85149", muted="#8b949e", caret="#58a6ff"),
    "light": dict(bg="#ffffff", stroke="#d0d7de", title="#57606a", prompt="#1a7f37",
                  label="#9a6700", dots="#afb8c1", value="#0969da", add="#1a7f37",
                  dele="#cf222e", muted="#57606a", caret="#0969da"),
}

CHW = 8.7           # monospace char width @ 15px
X0 = 26             # left text margin
VALUE_COL = 12      # char column where values begin


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def leader(label):
    return "." * max(1, VALUE_COL - len(label) - 2)


def render(stats, theme):
    p = PALETTE[theme]
    rows = [
        ("prompt", "$ neofetch --github", None),
        ("kv", "Repos", (human(stats["repos"]), "value")),
        ("kv", "Commits", (human(stats["commits"]), "value")),
        ("kv", "Stars", (human(stats["stars"]), "value")),
        ("kv", "Followers", (human(stats["followers"]), "value")),
        ("loc", "Lines of Code", None),
        ("kv", "Updated", (stats["updated"], "muted")),
    ]
    W, top, dy = 540, 62, 27
    H = top + len(rows) * dy + 22
    parts = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" fill="none" font-family="\'Cascadia Code\','
        f"'JetBrains Mono','SFMono-Regular',Consolas,monospace\">")
    # style: typewriter reveal + blinking caret
    parts.append(
        "<style>"
        ".row{clip-path:inset(0 100% 0 0);animation:type .9s steps(30) forwards;}"
        "@keyframes type{to{clip-path:inset(0 0 0 0);}}"
        ".caret{animation:blink 1s steps(1) infinite;}"
        "@keyframes blink{50%{opacity:0;}}"
        "@media(prefers-reduced-motion:reduce){"
        ".row{clip-path:none;animation:none;}.caret{animation:none;}}"
        "</style>")
    # window
    parts.append(f'<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="12" '
                 f'fill="{p["bg"]}" stroke="{p["stroke"]}"/>')
    # title bar
    parts.append(f'<line x1="0" y1="34" x2="{W}" y2="34" stroke="{p["stroke"]}"/>')
    for i, col in enumerate(("#f85149", "#f0b429", "#3fb950")):
        parts.append(f'<circle cx="{22 + i*20}" cy="18" r="6" fill="{col}"/>')
    parts.append(f'<text x="{W/2}" y="23" text-anchor="middle" font-size="13" '
                 f'fill="{p["title"]}">{USER}@{HOST_LABEL} — live</text>')

    last_len = 0
    for i, (kind, label, val) in enumerate(rows):
        y = top + i * dy
        delay = 0.35 + i * 0.75
        if kind == "prompt":
            body = f'<tspan fill="{p["prompt"]}">{esc(label)}</tspan>'
            last_len = len(label)
        elif kind == "loc":
            add, dele = human(stats["additions"]), human(stats["deletions"])
            dots = leader(label)
            body = (f'<tspan fill="{p["label"]}">{esc(label)}</tspan>'
                    f'<tspan fill="{p["dots"]}"> {dots} </tspan>'
                    f'<tspan fill="{p["add"]}">+{add}</tspan>'
                    f'<tspan fill="{p["muted"]}"> / </tspan>'
                    f'<tspan fill="{p["dele"]}">-{dele}</tspan>')
            last_len = len(label) + len(dots) + len(add) + len(dele) + 6
        else:
            value, vc = val
            dots = leader(label)
            body = (f'<tspan fill="{p["label"]}">{esc(label)}</tspan>'
                    f'<tspan fill="{p["dots"]}"> {dots} </tspan>'
                    f'<tspan fill="{p[vc]}">{esc(value)}</tspan>')
            last_len = len(label) + len(dots) + len(str(value)) + 2
        parts.append(
            f'<text class="row" x="{X0}" y="{y}" font-size="15" '
            f'style="animation-delay:{delay:.2f}s">{body}</text>')

    # blinking caret after the last typed line
    caret_x = X0 + last_len * CHW + 3
    caret_y = top + (len(rows) - 1) * dy - 12
    total = 0.35 + len(rows) * 0.75
    parts.append(f'<rect class="caret" x="{caret_x:.0f}" y="{caret_y:.0f}" width="9" '
                 f'height="16" fill="{p["caret"]}" style="animation-delay:{total:.2f}s"/>')
    parts.append("</svg>")
    return "\n".join(parts)


HOST_LABEL = "github"


def main():
    fetched = fetch()
    stats = fetched if fetched else dict(FALLBACK)
    stats["updated"] = date.today().isoformat()
    os.makedirs("output", exist_ok=True)
    for theme in ("dark", "light"):
        with open(f"output/{theme}_mode.svg", "w", encoding="utf-8", newline="\n") as f:
            f.write(render(stats, theme))
    print(f"[stats] source={'live' if fetched else 'seed'}  "
          f"repos={stats['repos']} commits={stats['commits']} stars={stats['stars']} "
          f"followers={stats['followers']} +{stats['additions']}/-{stats['deletions']}")


if __name__ == "__main__":
    main()
