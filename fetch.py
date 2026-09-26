"""岡山5館の上映スケジュールを映画.comから取得して index.html を作る。

使い方: python fetch.py   （標準ライブラリのみ。1回あたり5リクエスト）
"""
import html
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
DATA_FILE = HERE / "data.json"
TEMPLATE = HERE / "template.html"
OUTPUT = HERE / "index.html"

THEATERS = [
    {"id": "aeon", "name": "イオンシネマ岡山", "url": "https://eiga.com/theater/33/330101/7089/"},
    {"id": "toho", "name": "TOHOシネマズ岡南", "url": "https://eiga.com/theater/33/330101/6007/"},
    {"id": "movix", "name": "MOVIX倉敷", "url": "https://eiga.com/theater/33/330201/6013/"},
    {"id": "clair", "name": "シネマ・クレール", "url": "https://eiga.com/theater/33/330101/6009/"},
    {"id": "merpa", "name": "岡山メルパ", "url": "https://eiga.com/theater/33/330101/6008/"},
]

UA = "Mozilla/5.0 (personal schedule viewer; low frequency)"
TIME_RE = re.compile(
    r"<(a|span)([^>]*)>\s*(\d{1,2}:\d{2})\s*(?:<small>\s*～\s*(\d{1,2}:\d{2})\s*</small>)?\s*</\1>"
)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def text(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse(page, theater_id):
    films, shows, days = {}, [], {}
    for m in re.finditer(r'<section id="m(\d+)"[^>]*>(.*?)</section>', page, re.S):
        movie_id, body = m.group(1), m.group(2)
        title = re.search(r'data-title="([^"]*)"', m.group(0))
        img = re.search(r'<div class="movie-image">.*?<img[^>]*src="([^"]+)"', body, re.S)
        data = re.search(r'<p class="data">(.*?)</p>', body, re.S)
        rating = re.search(r'class="rating-star[^"]*">([\d.]+)<', body)
        info = [text(x) for x in re.findall(r"<span>(.*?)</span>", data.group(1))] if data else []
        films[movie_id] = {
            "title": html.unescape(title.group(1)) if title else "",
            "poster": img.group(1) if img else None,
            "info": info,
            "rating": rating.group(1) if rating and rating.group(1) != "0.0" else None,
            "url": f"https://eiga.com/movie/{movie_id}/",
        }
        for block in body.split('<div class="movie-schedule"')[1:]:
            types = [text(x) for x in re.findall(r'<span class="type-[^"]*">(.*?)</span>', block)]
            for td in re.finditer(r'<td([^>]*)data-date="(\d{8})"[^>]*>(.*?)</td>', block, re.S):
                date = td.group(2)
                cls = re.search(r'class="([^"]*)"', td.group(1))
                days[date] = cls.group(1) if cls else ""
                for t in TIME_RE.finditer(td.group(3)):
                    href = re.search(r'href="([^"]+)"', t.group(2))
                    shows.append({
                        "t": theater_id,
                        "m": movie_id,
                        "d": date,
                        "s": t.group(3),
                        "e": t.group(4),
                        "type": types,
                        "link": html.unescape(href.group(1)) if href else None,
                    })
    return films, shows, days


CREDITS_FILE = HERE / "credits.json"
MAX_CAST = 4


def fetch_credits(films):
    """監督・主な出演者を作品ページのJSON-LDから取る。一度取った作品は credits.json に保存して再取得しない。"""
    cache = json.loads(CREDITS_FILE.read_text(encoding="utf-8")) if CREDITS_FILE.exists() else {}
    todo = [m for m in films if m not in cache]
    for i, movie_id in enumerate(todo):
        time.sleep(1.5)
        try:
            page = get(f"https://eiga.com/movie/{movie_id}/")
            ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
            items = json.loads(ld.group(1)) if ld else []
            movie = next((x for x in (items if isinstance(items, list) else [items]) if x.get("@type") == "Movie"), {})
            cache[movie_id] = {
                "director": [p["name"] for p in movie.get("director", [])],
                "cast": [p["name"] for p in movie.get("actor", [])][:MAX_CAST],
            }
            print(f"    作品情報 {i + 1}/{len(todo)}: {films[movie_id]['title']}")
        except Exception as e:
            print(f"    作品情報 取得失敗 {films[movie_id]['title']}: {e}", file=sys.stderr)
    CREDITS_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    for movie_id, f in films.items():
        f.update(cache.get(movie_id, {"director": [], "cast": []}))


def main():
    old = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else None
    films, shows, days, status = {}, [], {}, {}
    for i, th in enumerate(THEATERS):
        if i:
            time.sleep(2)  # 相手サーバーへの配慮
        try:
            f, s, d = parse(get(th["url"]), th["id"])
            if not s:
                raise ValueError("上映回が0件（ページ構造が変わった可能性）")
            films.update(f)
            shows += s
            days.update(d)
            status[th["id"]] = {"ok": True, "count": len(s)}
            print(f"OK  {th['name']}: {len(f)}作品 / {len(s)}回")
        except Exception as e:
            status[th["id"]] = {"ok": False, "error": str(e)}
            print(f"NG  {th['name']}: {e}", file=sys.stderr)
            if old:  # 失敗した館は前回のデータで埋める
                prev = [x for x in old["shows"] if x["t"] == th["id"]]
                shows += prev
                for x in prev:
                    if x["m"] in old["films"]:
                        films.setdefault(x["m"], old["films"][x["m"]])
                status[th["id"]]["stale"] = True

    fetch_credits(films)
    data = {
        # GitHub上ではUTCで動くので日本時間に揃える
        "generated": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
        "theaters": [{"id": t["id"], "name": t["name"], "url": t["url"]} for t in THEATERS],
        "days": dict(sorted(days.items())),
        "films": films,
        "shows": shows,
        "status": status,
    }
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    page = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    )
    OUTPUT.write_text(page, encoding="utf-8")
    print(f"→ {OUTPUT}")


if __name__ == "__main__":
    main()
