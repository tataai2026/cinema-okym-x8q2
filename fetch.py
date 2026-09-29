"""岡山5館の上映スケジュールを映画.comから取得して index.html を作る。

使い方: python fetch.py   （標準ライブラリのみ。1回あたり5リクエスト）
"""
import html
import json
import re
import sys
import time
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
DATA_FILE = HERE / "data.json"
TEMPLATE = HERE / "template.html"
OUTPUT = HERE / "index.html"

# url: 映画.com（メイン。監督・出演・チケットリンクもここから）
# mw:  MovieWalker（映画.comより先に翌週分が載ることがあるので、足りない日付だけ補う）
THEATERS = [
    {"id": "aeon", "name": "イオンシネマ岡山", "url": "https://eiga.com/theater/33/330101/7089/", "mw": "th697"},
    {"id": "toho", "name": "TOHOシネマズ岡南", "url": "https://eiga.com/theater/33/330101/6007/", "mw": "th65"},
    {"id": "movix", "name": "MOVIX倉敷", "url": "https://eiga.com/theater/33/330201/6013/", "mw": "th601"},
    {"id": "clair", "name": "シネマ・クレール", "url": "https://eiga.com/theater/33/330101/6009/", "mw": "th478"},
    {"id": "merpa", "name": "岡山メルパ", "url": "https://eiga.com/theater/33/330101/6008/", "mw": "th417"},
]
JST = timezone(timedelta(hours=9))

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


def norm_title(s):
    """映画.comとMovieWalkerで表記ゆれする作品名を突き合わせるためのキー"""
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[\s・:：!！?？、。,.「」『』〈〉《》【】/\"'“”‘’\-‐–—~〜☆★♪]", "", s)


def parse_mw(page, theater_id):
    """MovieWalkerの劇場スケジュールページ → [(作品情報, [上映回])]"""
    today = datetime.now(JST).date()
    out = []
    for art in re.findall(r"<article>(.*?)</article>", page, re.S):
        mv = re.search(r'href="/(mv\d+)/"', art)
        h2 = re.search(r"<h2>(.*?)</h2>", art, re.S)
        if not (mv and h2):
            continue
        img = re.search(r'<img[^>]*src="([^"]+)"', art)
        meta = re.search(r'bl_theaterSchedule_date_rating">(.*?)</div>', art, re.S)
        film = {
            "mw": mv.group(1),
            "title": text(h2.group(1)),
            "poster": html.unescape(img.group(1)) if img else None,
            "info": [x for x in re.split(r"[、,]", text(meta.group(1))) if x] if meta else [],
            "rating": None,
            "url": f"https://press.moviewalker.jp/{mv.group(1)}/",
        }
        shows = []
        for block in art.split('<div class="bl_screen">')[1:]:
            head = block.split('<div class="bl_screen_attention"')[0]
            types = [x for x in text(re.sub(r"<[^>]+>", " ", head)).split() if x != "上映形式"]
            for li in re.finditer(r'<div class="date([^"]*)">\s*(\d{1,2})/(\d{1,2})(.*?)</dd>', block, re.S):
                month, day = int(li.group(2)), int(li.group(3))
                year = today.year + (1 if month < today.month - 6 else 0)
                date = f"{year}{month:02d}{day:02d}"
                for t in re.finditer(r'<(a|div) class="startTime[^"]*"([^>]*)>\s*(\d{1,2}:\d{2})\s*</\1>', li.group(4)):
                    href = re.search(r'data-href="([^"]+)"', t.group(2))
                    shows.append({
                        "t": theater_id, "d": date, "s": t.group(3), "e": None, "type": types,
                        "link": html.unescape(href.group(1)) if href else None,
                        "_daycls": li.group(1).strip(),
                    })
        if shows:
            out.append((film, shows))
    return out


def merge_mw(films, shows, days, mw_pages):
    """映画.comに無い日付の上映回だけMovieWalkerから足す"""
    by_title = {norm_title(f["title"]): m for m, f in films.items()}
    added = 0
    for theater_id, parsed in mw_pages.items():
        have = {s["d"] for s in shows if s["t"] == theater_id}
        for film, mw_shows in parsed:
            new = [s for s in mw_shows if s["d"] not in have]
            if not new:
                continue
            movie_id = by_title.get(norm_title(film["title"]))
            if not movie_id:  # 映画.comにまだ載っていない新作
                movie_id = film["mw"]
                films.setdefault(movie_id, {k: v for k, v in film.items() if k != "mw"})
                by_title[norm_title(film["title"])] = movie_id
            for s in new:
                cls = s.pop("_daycls")
                days.setdefault(s["d"], "holiday" if "sunday" in cls else cls)
                shows.append({**s, "m": movie_id, "src": "mw"})
                added += 1
    return added


CREDITS_FILE = HERE / "credits.json"
MAX_CAST = 4


def fetch_credits(films):
    """監督・主な出演者を作品ページのJSON-LDから取る。一度取った作品は credits.json に保存して再取得しない。"""
    cache = json.loads(CREDITS_FILE.read_text(encoding="utf-8")) if CREDITS_FILE.exists() else {}
    todo = [m for m in films if m not in cache and not m.startswith("mv")]  # mv〜はMovieWalkerのみの作品
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

    mw_pages = {}
    for th in THEATERS:
        time.sleep(2)
        try:
            mw_pages[th["id"]] = parse_mw(get(f"https://press.moviewalker.jp/{th['mw']}/schedule/"), th["id"])
        except Exception as e:
            print(f"NG  MovieWalker {th['name']}: {e}", file=sys.stderr)
    added = merge_mw(films, shows, days, mw_pages)
    print(f"MovieWalkerで補った上映回: {added}回")

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
