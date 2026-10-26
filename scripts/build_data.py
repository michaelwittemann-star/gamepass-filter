"""Baut public/data/games.json aus Game-Pass-Katalog + Metacritic + HowLongToBeat + Steam-Tags.

Aufruf:  python scripts/build_data.py            (nutzt den Cache, schlägt nur Neues/Veraltetes nach)
         python scripts/build_data.py --refresh  (alle Anreicherungen neu holen)

Falsche Zuordnungen in data/overrides.json korrigieren, z. B.
  {"9NPDN9R45JX4": {"metacritic": "1000xresist", "hltb": 143595, "steam": 1675830}}
Ein Wert null heißt "keine Zuordnung".
"""
from __future__ import annotations

import argparse
import http.client
import difflib
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = ROOT / "data" / "cache" / "enrich.json"
FIRST_SEEN_FILE = ROOT / "data" / "first_seen.json"
OVERRIDES_FILE = ROOT / "data" / "overrides.json"
OUT_FILE = ROOT / "public" / "data" / "games.json"

MARKET = "DE"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
SIGLS = {
    "console": "f6f1f99f-9b49-4ccd-b3bf-4d9767a77f5e",
    "pc": "fdd9e2a7-0fee-49f6-ad69-4354098401ff",
    "cloud": "29a81209-df6f-41fd-a528-2ae6b91f719c",
    "ea": "b8900d09-a491-44cc-916e-32b5acae621b",
    "new": "f13cf6b4-57e6-4459-89df-6aec18cf0538",
    "leaving": "393f05bf-e596-4ef6-9487-6d4fa0eab987",
}
MC_KEY = "1MOZgmNFxvmljaQR1X9KAij9Mo4xAY3u"  # öffentlicher Schlüssel der Metacritic-Website
# Treffer erneut nachschlagen nach ... Tagen (Fehlschläge früher, weil neue Spiele oft erst später Wertungen haben)
REFRESH_HIT_DAYS = 45
REFRESH_MISS_DAYS = 10


def log(*a):
    print(*a, flush=True)


def http_json(url: str, data: bytes | None = None, headers: dict | None = None, tries: int = 3):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


class RateLimit:
    def __init__(self, per_sec: float):
        self.gap = 1 / per_sec
        self.lock = threading.Lock()
        self.next = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next)
            self.next = t + self.gap
        time.sleep(max(0, t - now))


# ---------- Titel-Normalisierung ----------

EDITION_RE = re.compile(
    r"\s*[-–:(]?\s*(standard|deluxe|definitive|complete|ultimate|game of the year|goty|gold|premium|enhanced|anniversary|"
    r"digital|director'?s cut|special|legendary|collector'?s|console|xbox series x\|s|xbox one|windows( 10)?|pc)\s*(edition|version|cut)?\)?\s*$",
    re.I,
)
NOISE_RE = re.compile(r"\s*[-–]?\s*cross-gen[- ]bundle|\((game preview|early access|xbox series x\|s|xbox one|windows|pc|preview)\)|for windows( 10)?|- windows edition", re.I)


# nur ein Wort vor "Edition" (Voidheart-Edition, 2026 Edition); bekannte Editionen übernimmt EDITION_RE
ANY_EDITION_RE = re.compile(r"\s*[:\-–]\s*[^:\-–\s]{1,20}[\s-]*\b(edition|edici[oó]n)\s*$", re.I)


def clean_title(t: str) -> str:
    t = re.sub(r"[™®©]", "", t)
    t = NOISE_RE.sub("", t)
    for _ in range(2):
        t = EDITION_RE.sub("", t)
    t = ANY_EDITION_RE.sub("", t)
    return re.sub(r"\s+", " ", t).strip(" -–:")


def search_terms(t: str) -> list[str]:
    """Suchbegriffe: bereinigter Titel, dann der Teil vor ':' (für Untertitel, die die Datenbanken anders führen)."""
    c = clean_title(t)
    terms = [c]
    head = re.split(r"\s*[:–]\s+|\s+-\s+", c)[0]
    if head != c and len(head) >= 4:
        terms.append(head)
    return terms


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", clean_title(t)).encode("ascii", "ignore").decode()
    t = t.lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", t)


def sim(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


ROMAN = {"ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12,
         "xiii": 13, "xiv": 14, "xv": 15, "xvi": 16}


def numbers(t: str) -> set[int]:
    """Zahlen und römische Ziffern im Titel ("Final Fantasy III" -> {3}); müssen beim Abgleich übereinstimmen."""
    out = set()
    t = re.sub(r"\([^)]*\)", " ", clean_title(t).lower())  # Klammerzusätze wie "(2020)"
    t = re.sub(r"\d+\s*-\s*\d+", " ", t)  # Bereiche wie "Kapitel 1-3"
    t = re.sub(r"(?<=[a-z])(?=\d)", " ", t)  # "Dogs2" -> "Dogs 2"
    t = re.sub(r"[-–]\s*(19|20)\d\d\s*$", " ", t)  # angehängte Jahreszahl wie "– 2009"
    for w in re.findall(r"[a-z0-9]+", t):
        if w.isdigit():
            out.add(int(w))
        elif w in ROMAN:
            out.add(ROMAN[w])
    return out


def best_match(title: str, year: int | None, items: list, name_of, year_of, min_sim=0.82, full_title: str | None = None):
    """Bester Kandidat nach Titelähnlichkeit, bei Gleichstand der mit passendem Jahr."""
    nums = numbers(full_title or title)
    scored = []
    for it in items:
        if numbers(name_of(it)) != nums:
            continue
        s = sim(title, name_of(it))
        if s < min_sim:
            continue
        y = year_of(it)
        # Original kann vor dem Xbox-Release liegen, aber nicht deutlich danach
        penalty = 0.0
        if year and y:
            if y > year + 1:
                penalty = 0.15
            else:
                penalty = min(abs(year - y), 15) * 0.004
        scored.append((s - penalty, it))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


# ---------- Game-Pass-Katalog + Microsoft Store ----------

def fetch_catalog() -> dict[str, set[str]]:
    flags: dict[str, set[str]] = {}
    for key, sid in SIGLS.items():
        lst = http_json(f"https://catalog.gamepass.com/sigls/v2?id={sid}&language=de-de&market={MARKET}")
        for x in lst[1:]:
            flags.setdefault(x["id"], set()).add(key)
        log(f"Katalog {key}: {len(lst) - 1}")
    # nur Spiele, die in einer der echten Bibliotheken sind
    return {k: v for k, v in flags.items() if v & {"console", "pc", "cloud", "ea"}}


# ---------- Amazon Luna ----------
# Katalog über dieselbe (inoffizielle) Schnittstelle, die luna.amazon.de ohne Anmeldung nutzt.
# Luna Premium enthält alle Prime-Spiele.
PLATFORMS = ("console", "pc", "cloud", "ea", "lunaPrime", "lunaPremium", "netflixMobile", "netflixTV",
             "psEssential", "psExtra", "psPremium",
             "epicFree", "epicSoon", "primeClaim", "primeSoon", "steamFree", "steamCheap", "steamCheap10")
# Reihenfolge für das Cover-Ziel, wenn ein Spiel auf mehreren Plattformen ist (Xbox zuerst)
SOURCE_ORDER = ("luna-", "nf-", "ps-", "epic-", "prime-", "primesoon-", "steam-")
LUNA_LISTS = {"lunaPrime": "included_with_prime", "lunaPremium": "luna_premium"}
LUNA_GENRES = {
    "action": "Action & adventure", "adventure": "Action & adventure", "horror": "Action & adventure",
    "rätsel/puzzle": "Puzzle & trivia", "puzzle": "Puzzle & trivia", "strategie": "Strategy", "strategy": "Strategy",
    "simulation": "Simulation", "shooter": "Shooter", "sport": "Sports", "sports": "Sports",
    "rennspiel": "Racing & flying", "racing": "Racing & flying", "tabletop": "Card & board",
    "rollenspiel": "Role playing", "rpg": "Role playing", "kampfspiel": "Fighting", "fighting": "Fighting",
    "party": "Party", "arcade": "Arcade", "plattformer": "Platformer", "platformer": "Platformer",
}


def fetch_luna_list(query: str) -> dict[str, dict]:
    body = {
        "timeout": 10000,
        "searchContext": {"query": query, "sort": "TITLE_A_TO_Z", "filtersList": []},
        "featureScheme": "WEB_V1",
        "pageContext": {"pageType": "multistate_browse_results", "pageId": "default"},
        "clientContext": {"browserMetadata": {"browserClientRole": "browser", "browserType": "Chrome", "browserVersion": "130.0.0.0",
                                              "deviceModel": "unknown", "deviceType": "unknown", "osName": "Windows", "osVersion": "10"},
                          "refMarker": None, "referrer": None},
        "inputContext": {"gamepadTypes": []},
        "dynamicFeatures": [],
    }
    sid = "261-1234567-7654321"
    headers = {
        "content-type": "text/plain;charset=UTF-8", "x-amz-locale": "de_DE", "x-amz-country-of-residence": "DE",
        "x-amz-marketplace-id": "A1PA6795UKMFR9", "x-amz-platform": "web", "x-amz-device-type": "browser",
        "x-amz-session-id": sid, "x-amz-device-serial-number": sid, "Origin": "https://luna.amazon.de",
    }
    d = http_json("https://proxy-prod.eu-west-1.tempo.digital.a2z.com/getPage", data=json.dumps(body).encode(), headers=headers)
    out: dict[str, dict] = {}

    def walk(w):
        if isinstance(w, dict):
            targets = [a.get("target") for a in w.get("actions") or [] if isinstance(a, dict)]
            if w.get("type") == "GAME_TILE" and targets and (targets[0] or "").startswith("/game/"):
                pd = json.loads(w.get("presentationData") or "{}")
                pd["_target"] = targets[0]
                out[targets[0].rsplit("/", 1)[-1]] = pd
            for v in w.values():
                walk(v)
        elif isinstance(w, list):
            for v in w:
                walk(v)

    walk(d)
    return out


def parse_luna(asin: str, pd: dict) -> dict:
    title = re.sub(r"\s+", " ", pd.get("title") or "").strip()
    hover = pd.get("hoverDetails") or {}
    genres = list(dict.fromkeys(LUNA_GENRES[x.lower()] for x in pd.get("genreTags") or [] if x.lower() in LUNA_GENRES))
    m = re.search(r"(\d+)$", (hover.get("ageRating") or {}).get("categoryId") or "")
    img = pd.get("imagePortrait")
    if img:
        img = re.sub(r"\.(png|jpg)$", r"._SX300_.\1", img)  # Amazon-Bildgröße
    yr = str(pd.get("releaseYear") or "")
    url = "https://luna.amazon.de" + pd["_target"]
    return {
        "id": "luna-" + asin,
        "t": clean_title(title) if len(clean_title(title)) > 2 else title,
        "tFull": title,
        "tEn": title,
        "img": img,
        "imgSq": False,
        "url": url,
        "links": {"luna": url},
        "genres": genres,
        "feat": [],
        "onlineOnly": False,
        "onlineMax": None,
        "localMax": None,
        "yx": int(yr) if yr.isdigit() else None,
        "pegi": int(m.group(1)) if m else None,
        "stars": None,
        "pub": hover.get("publishersText"),
        "dev": None,
    }


def fetch_luna() -> tuple[list[dict], dict[str, set[str]]]:
    games: dict[str, dict] = {}
    flags: dict[str, set[str]] = {}
    for key, query in LUNA_LISTS.items():
        lst = fetch_luna_list(query)
        log(f"Luna {key}: {len(lst)}")
        for asin, pd in lst.items():
            games.setdefault(asin, parse_luna(asin, pd))
            flags.setdefault("luna-" + asin, set()).add(key)
    return list(games.values()), flags


# ---------- Weitere Plattformen: Netflix, Epic-Gratisspiele, Prime zum Abholen ----------

def base_entry(id_: str, title: str, url: str, link_key: str, img: str | None = None, sq: bool = True, **extra) -> dict:
    title = re.sub(r"\s+", " ", (title or "").replace("\\'", "'")).strip()
    e = {
        "id": id_, "t": clean_title(title) if len(clean_title(title)) > 2 else title, "tFull": title, "tEn": title,
        "img": img, "imgSq": sq, "url": url, "links": {link_key: url}, "genres": [], "feat": [], "onlineOnly": False,
        "onlineMax": None, "localMax": None, "yx": None, "pegi": None, "stars": None, "pub": None, "dev": None,
    }
    e.update(extra)
    return e


NETFLIX_LIST = "https://www.whats-on-netflix.com/news/netflix-games/full-list-mobile-cloud-games-on-netflix/"
NETFLIX_CACHE = ROOT / "data" / "cache" / "netflix_de.json"
NETFLIX_GENRES = {
    "action": "Action & adventure", "adventure": "Action & adventure", "arcade": "Arcade", "acarde": "Arcade",
    "card": "Card & board", "tabletop": "Card & board", "fighting": "Fighting", "interactive story": "Interactive story",
    "dating": "Interactive story", "kids": "Family & kids", "educational": "Family & kids", "music": "Music",
    "party": "Party", "puzzle": "Puzzle & trivia", "racing": "Racing & flying", "role-playing": "Role playing",
    "simulation": "Simulation", "sport": "Sports", "sports": "Sports", "strategy": "Strategy",
}


def http_text(url: str) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "de-DE"})
        with urllib.request.urlopen(req, timeout=30) as r:
            try:
                body = r.read()
            except http.client.IncompleteRead as e:  # Netflix bricht gelegentlich ab; der Kopf reicht uns
                body = e.partial
            if "/NotFound" in r.geturl():  # Netflix leitet unbekannte/gesperrte Titel um, Status bleibt 200
                return 404, ""
            return r.status, body.decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, ""


def fetch_netflix() -> tuple[list[dict], dict[str, set[str]]]:
    """Liste von What's on Netflix (Fan-Seite); ob ein Spiel in Deutschland verfügbar ist, prüft netflix.com/de."""
    import html as htmllib

    status, page = http_text(NETFLIX_LIST)
    if status != 200:
        raise RuntimeError(f"What's on Netflix: HTTP {status}")
    cache = load_json(NETFLIX_CACHE, {})
    games, flags = [], {}
    cards = re.findall(r'<div class="game-card"(.*?)(?=<div class="game-card"|<h3)', page, re.S)
    for c in cards:
        m = re.search(r"netflix\.com/games/(\d+)", c)
        h4 = re.search(r"<h4>(.*?)<div", c, re.S)
        if not m or not h4:
            continue
        nid = m.group(1)
        title = htmllib.unescape(re.sub(r"<[^>]+>", "", h4.group(1))).strip()

        def field(name: str) -> str:
            f = re.search(rf"<strong>{name}:</strong>\s*([^<]*)", c)
            return f.group(1).strip() if f else ""

        ent = cache.get(nid)
        # Auf GitHub-Servern (USA) sähe netflix.com den US-Katalog: dort nur neue Spiele prüfen, bekannte behalten
        stale = not ent or (datetime.now(timezone.utc) - datetime.fromisoformat(ent["at"])) > timedelta(days=7)
        if stale and not (ent and os.environ.get("GITHUB_ACTIONS")):
            st, de = http_text(f"https://www.netflix.com/de/games/{nid}")
            img = re.search(r'og:image" content="([^"]+)', de)
            if st in (200, 404):
                ent = {"at": datetime.now(timezone.utc).isoformat(), "ok": st == 200, "img": img and htmllib.unescape(img.group(1))}
                cache[nid] = ent
            else:  # Netzfehler: alten Stand behalten bzw. erst einmal als verfügbar annehmen
                ent = ent or {"at": "2000-01-01T00:00:00+00:00", "ok": True, "img": None}
        if not ent["ok"]:
            continue  # in Deutschland nicht verfügbar
        ym = re.search(r"(19|20)\d\d", field("Release Date"))
        age = re.search(r"(\d+)", field("Rating"))
        mobile = 'data-mobile="mobile"' in c
        cloud = 'data-cloud="cloud"' in c
        cat = field("Category").lower()
        url = f"https://www.netflix.com/de/games/{nid}"
        g = base_entry(
            "nf-" + nid, title, url, "netflix", img=ent.get("img"), sq=True,
            genres=[NETFLIX_GENRES[cat]] if cat in NETFLIX_GENRES else [],
            yx=int(ym.group(0)) if ym else None, pegi=int(age.group(1)) if age else None, dev=field("Developer") or None,
            onlineOnly=field("Offline Play").lower() == "no" and mobile,
        )
        games.append(g)
        flags[g["id"]] = ({"netflixMobile"} if mobile else set()) | ({"netflixTV"} if cloud else set())
    save_json(NETFLIX_CACHE, cache)
    log(f"Netflix: {len(games)} von {len(cards)} in Deutschland verfügbar")
    return games, flags


PS_LISTS = {"psExtra": "plus-games-list", "psPremium": "plus-classics-list", "psEssential": "plus-monthly-games-list"}
# Höhere Stufen enthalten die niedrigeren: Monatsspiele gibt es in allen, den Extra-Katalog auch in Premium
PS_TIERS = {"psEssential": {"psEssential", "psExtra", "psPremium"}, "psExtra": {"psExtra", "psPremium"}, "psPremium": {"psPremium"}}
PS_GENRES = {
    "ACTION": "Action & adventure", "ADVENTURE": "Action & adventure", "HORROR": "Action & adventure",
    "ROLE_PLAYING_GAMES": "Role playing", "SHOOTER": "Shooter", "SIMULATION": "Simulation", "SIMULATOR": "Simulation",
    "STRATEGY": "Strategy", "PUZZLE": "Puzzle & trivia", "BRAIN_TRAINING": "Puzzle & trivia", "EDUCATIONAL": "Family & kids",
    "RACING": "Racing & flying", "FAMILY": "Family & kids", "CASUAL": "Family & kids", "SPORTS": "Sports",
    "ARCADE": "Arcade", "FIGHTING": "Fighting", "PARTY": "Party", "MUSIC/RHYTHM": "Music", "UNIQUE": "Other",
}
PS_SUFFIX = re.compile(r"\s*[-–]?\s*[(\[]?\s*\bPS[45]\b(\s*(&|und|and|/|,)?\s*\bPS[45]\b)?\s*[)\]]?(\s+version|\s+(?-i:[A-Z]{2}))?\s*$", re.I)  # "PS4 & PS5", "(PS4 & PS5)", "[PS4 & PS5]", "PS4&PS5 LV"


def fetch_psplus() -> tuple[list[dict], dict[str, set[str]]]:
    """PlayStation-Plus-Kataloge (Essential-Monatsspiele, Extra-Spielekatalog, Premium-Klassiker) von playstation.com."""
    games: dict[str, dict] = {}
    flags: dict[str, set[str]] = {}
    for key, cat in PS_LISTS.items():
        d = http_json(f"https://www.playstation.com/bin/imagic/gameslist?locale=de-de&categoryList={cat}")
        lst = [x for c in d for x in c.get("games") or []]
        log(f"PS Plus {key}: {len(lst)}")
        for x in lst:
            gid = f"ps-{x['conceptId']}"
            flags.setdefault(gid, set()).update(PS_TIERS[key])
            if gid in games:
                continue
            def strip_ps(t: str) -> str:
                return PS_SUFFIX.sub("", re.sub(r"[\u2122\u00ae\u00a9]", "", t).replace("\u3000", " ")).strip()

            name = strip_ps(x.get("name") or "")
            name_en = strip_ps(x.get("nameEn") or x.get("name") or "")
            age = re.search(r"(\d+)", (x.get("ageRating") or {}).get("name") or "")
            rel = (x.get("releaseDate") or "")[:4]
            img = x.get("imageUrl")
            url = x.get("conceptUrl") or f"https://store.playstation.com/de-de/concept/{x['conceptId']}"
            games[gid] = base_entry(
                gid, name, url, "playstation", img=img and img + "?w=320", sq=True, tEn=name_en,
                genres=list(dict.fromkeys(PS_GENRES[gg] for gg in x.get("genre") or [] if gg in PS_GENRES)),
                yx=int(rel) if rel.isdigit() else None, pegi=int(age.group(1)) if age else None,
                ps=sorted(set(x.get("device") or [])),
            )
    return list(games.values()), flags


# ---------- Steam: kostenlose und günstige (≤ 5 €) Spiele mit guten Bewertungen ----------
# Kandidaten aus der Steam-Shop-Suche ("Free to Play" bzw. "bis 5 €", nach Bewertung sortiert): liefert Euro-Preis,
# Rabatt und Bewertung in einem, nicht käufliche Spiele tauchen dort nicht auf. Große Gratis-Spiele unter 80 %
# (Apex, Halo Infinite …) kommen aus Steams Meistgespielt-Liste und der SteamSpy-Topliste. Die endgültige
# Auswahl (steam_rules_keep) passiert in main(), weil dafür die AAA/AA-Einstufung nötig ist.
STEAMSPY_CACHE = ROOT / "data" / "cache" / "steamspy_all.json"
STEAM_RULES = {
    # (mindestens % positiv, mindestens Anzahl Bewertungen)
    "free_top": (80, 100),   # kostenlos und sehr gut bewertet
    "free_big": (60, 100),   # kostenlos, AAA/AA, ordentlich bewertet
    "cheap_top": (85, 100),  # bis 5 € (auch im Angebot), gut bewertet
    "cheap_max_eur": 5.00,
    "cheap10_max_eur": 10.00,
}
search_rl = RateLimit(0.6)


def steam_pct(pos: int, neg: int) -> tuple[int | None, int]:
    n = (pos or 0) + (neg or 0)
    return (round(100 * pos / n) if n else None), n


def steam_search(params: str, stop_pct: int) -> list[dict]:
    """Steam-Shop-Suche seitenweise, nach Bewertung sortiert, bis die Bewertung unter stop_pct fällt."""
    rows, start = [], 0
    while start < 20000:
        url = (f"https://store.steampowered.com/search/results/?{params}&sort_by=Reviews_DESC&start={start}"
               "&count=100&cc=de&l=english&category1=998&infinite=1")
        d = None
        for i in range(5):
            search_rl.wait()
            try:
                d = http_json(url, tries=1)
                break
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    raise
                time.sleep(30 * (i + 1))  # Steam bremst schnelle Abrufe kurz aus
        if d is None:
            raise RuntimeError("Steam-Suche: dauerhaft HTTP 429")
        page = []
        for b in (d.get("results_html") or "").split('<a href="https://store.steampowered.com/app/')[1:]:
            appid = b.split("/")[0]
            if not appid.isdigit():
                continue
            t = re.search(r'<span class="title">(.*?)</span>', b)
            rev = re.search(r"(\d+)% of the ([\d,]+) user reviews", b)
            price = re.search(r'data-price-final="(\d+)"', b)
            disc = re.search(r'data-discount="(\d+)"', b)
            orig = re.search(r'discount_original_price">([\d,.]+)', b)
            page.append({
                "appid": int(appid), "name": htmllib_unescape(t.group(1)) if t else "",
                "pct": int(rev.group(1)) if rev else None, "n": int(rev.group(2).replace(",", "")) if rev else 0,
                "price": int(price.group(1)) / 100 if price else None, "disc": int(disc.group(1)) if disc else 0,
                "initial": float(orig.group(1).replace(".", "").replace(",", ".")) if orig else None,
            })
        rows += page
        start += 100
        pcts = [x["pct"] for x in page if x["pct"] is not None]
        if not page or (pcts and max(pcts) < stop_pct):
            break
    return rows


def htmllib_unescape(s: str) -> str:
    import html as htmllib
    return htmllib.unescape(s)


def fetch_steamspy_top() -> list[dict]:
    """Die 1000 meistbesessenen Spiele (SteamSpy) – für große Gratis-Spiele mit mittlerer Bewertung."""
    cache = load_json(STEAMSPY_CACHE, {})
    today = datetime.now(timezone.utc).date().isoformat()
    if cache.get("date") == today and cache.get("apps"):
        return cache["apps"]
    apps = list(http_json("https://steamspy.com/api.php?request=all&page=0").values())
    save_json(STEAMSPY_CACHE, {"date": today, "apps": apps})
    return apps


def steam_prices(appids: list[int]) -> dict[int, dict | None]:
    """Euro-Preise über die Steam-API: {} = kostenlos, None = nicht (mehr) erhältlich."""
    out: dict[int, dict | None] = {}
    for i in range(0, len(appids), 50):
        chunk = appids[i: i + 50]
        steam_rl.wait()
        d = http_json("https://store.steampowered.com/api/appdetails?cc=de&filters=price_overview&appids=" + ",".join(map(str, chunk)))
        for a in chunk:
            e = d.get(str(a)) or {}
            if not e.get("success"):
                out[a] = None
            else:
                po = (e.get("data") or {}).get("price_overview") if isinstance(e.get("data"), dict) else None
                out[a] = {} if not po else {"price": po["final"] / 100, "initial": po["initial"] / 100, "disc": po["discount_percent"]}
    return out


STEAM_FREE_CACHE = ROOT / "data" / "cache" / "steam_free.json"
free_rl = RateLimit(0.6)  # Einzelabfragen der Steam-API: ca. 200 pro 5 Minuten erlaubt


def steam_really_free(appids: list[int]) -> dict[int, bool]:
    """Ohne Preis heißt bei Steam entweder kostenlos oder nicht mehr käuflich (z. B. GTA V Legacy) – is_free klärt das.
    Geht nur einzeln; Ergebnisse 14 Tage zwischengespeichert."""
    cache = load_json(STEAM_FREE_CACHE, {})
    now = datetime.now(timezone.utc)
    out = {}
    for a in appids:
        e = cache.get(str(a))
        if e and now - datetime.fromisoformat(e["at"]) < timedelta(days=14):
            out[a] = e["free"]
            continue
        for _ in range(3):
            free_rl.wait()
            try:
                d = http_json(f"https://store.steampowered.com/api/appdetails?appids={a}&cc=de&filters=basic", tries=1)
                data = (d.get(str(a)) or {}).get("data")
                out[a] = bool(isinstance(data, dict) and data.get("is_free"))
                cache[str(a)] = {"at": now.isoformat(), "free": out[a]}
                break
            except Exception:  # noqa: BLE001 – meist HTTP 429, kurz warten
                time.sleep(60)
        else:
            out[a] = False
    save_json(STEAM_FREE_CACHE, cache)
    return out


def steam_entry(appid: int, name: str, pct: int, n: int, price: float, initial: float, disc: int, **extra) -> dict:
    cdn = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}"
    return base_entry(
        f"steam-{appid}", name, f"https://store.steampowered.com/app/{appid}/", "steam",
        img=f"{cdn}/library_600x900.jpg", sq=False, img2=f"{cdn}/header.jpg", sp=pct, spN=n, steamAppid=appid,
        deals=[{"src": "steam", "price": price, "initial": initial, "disc": disc}], **extra,
    )


def fetch_steam_deals() -> tuple[list[dict], dict[str, set[str]]]:
    r = STEAM_RULES
    games: dict[int, dict] = {}
    flags: dict[str, set[str]] = {}

    for x in steam_search("genre=Free%20to%20Play", r["free_top"][0]):
        if x["price"] == 0 and x["pct"] is not None and x["pct"] >= r["free_top"][0] and x["n"] >= r["free_top"][1]:
            games[x["appid"]] = steam_entry(x["appid"], x["name"], x["pct"], x["n"], 0, 0, 0)
            flags[f"steam-{x['appid']}"] = {"steamFree"}
    log(f"  Steam-Suche gratis: {len(games)}")
    # eine Suche bis 10 €; was bis 5 € kostet, steht in beiden Kategorien
    for x in steam_search(f"maxprice={int(r['cheap10_max_eur'])}", r["cheap_top"][0]):
        if (x["price"] and x["price"] <= r["cheap10_max_eur"] and x["pct"] is not None
                and x["pct"] >= r["cheap_top"][0] and x["n"] >= r["cheap_top"][1] and x["appid"] not in games):
            games[x["appid"]] = steam_entry(x["appid"], x["name"], x["pct"], x["n"], x["price"],
                                            x["initial"] or x["price"], x["disc"])
            flags[f"steam-{x['appid']}"] = {"steamCheap10"} | ({"steamCheap"} if x["price"] <= r["cheap_max_eur"] else set())

    # große Gratis-Spiele mit 60–79 %: Kandidaten aus Meistgespielt-Liste und SteamSpy-Top-1000
    big: dict[int, tuple[str, int, int]] = {}
    try:
        for a in fetch_steamspy_top():
            pct, n = steam_pct(a.get("positive", 0), a.get("negative", 0))
            if str(a.get("price")) == "0" and pct is not None and pct >= r["free_big"][0] and n >= r["free_big"][1]:
                big[int(a["appid"])] = (a.get("name") or "", pct, n)
    except Exception as e:  # noqa: BLE001
        log(f"  SteamSpy-Topliste nicht abrufbar ({e})")
    try:
        ranks = http_json("https://api.steampowered.com/ISteamChartsService/GetMostPlayedGames/v1/")["response"]["ranks"]
        for rk in ranks:
            a = rk["appid"]
            if a in big or a in games:
                continue
            spy_rl.wait()
            d = http_json(f"https://steamspy.com/api.php?request=appdetails&appid={a}")
            pct, n = steam_pct(d.get("positive", 0), d.get("negative", 0))
            if str(d.get("price")) == "0" and pct is not None and pct >= r["free_big"][0] and n >= r["free_big"][1]:
                big[a] = (d.get("name") or "", pct, n)
    except Exception as e:  # noqa: BLE001
        log(f"  Meistgespielt-Liste nicht abrufbar ({e})")
    big = {a: v for a, v in big.items() if a not in games}
    if big:
        prices = steam_prices(list(big))
        free_ok = steam_really_free([a for a in big if prices.get(a) == {}])
        for a, (name, pct, n) in big.items():
            if prices.get(a) == {} and free_ok.get(a):
                games[a] = steam_entry(a, name, pct, n, 0, 0, 0)
                flags[f"steam-{a}"] = {"steamFree"}

    log(f"Steam: {sum('steamFree' in f for f in flags.values())} kostenlos, "
        f"{sum('steamCheap' in f for f in flags.values())} bis {r['cheap_max_eur']:.0f} €, "
        f"{sum('steamCheap10' in f for f in flags.values())} bis {r['cheap10_max_eur']:.0f} € (vor Feinauswahl)")
    return list(games.values()), flags


def steam_rules_keep(f: set[str], sp: int | None, sp_n: int, mc: int | None, tier: str | None) -> set[str]:
    """Feinauswahl nach Einstufung; gibt die verbleibenden Steam-Flags zurück."""
    r = STEAM_RULES
    keep = set()
    if "steamFree" in f and sp is not None:
        if (sp >= r["free_top"][0] and sp_n >= r["free_top"][1]) or (
            tier in ("AAA", "AA") and sp >= r["free_big"][0] and sp_n >= r["free_big"][1]):
            keep.add("steamFree")
    if sp is not None and sp >= r["cheap_top"][0] and sp_n >= r["cheap_top"][1]:
        keep |= f & {"steamCheap", "steamCheap10"}
    return keep


EPIC_URL = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale={loc}&country=DE&allowCountries=DE"


def fetch_epic() -> tuple[list[dict], dict[str, set[str]]]:
    de = http_json(EPIC_URL.format(loc="de"))["data"]["Catalog"]["searchStore"]["elements"]
    en = {e["id"]: e for e in http_json(EPIC_URL.format(loc="en-US"))["data"]["Catalog"]["searchStore"]["elements"]}
    games, flags = [], {}
    for e in de:
        p = e.get("promotions") or {}

        def free(key: str) -> list:
            return [o for x in p.get(key) or [] for o in x["promotionalOffers"] if o["discountSetting"]["discountPercentage"] == 0]

        now, soon = free("promotionalOffers"), free("upcomingPromotionalOffers")
        if not now and not soon:
            continue
        maps = (e.get("catalogNs") or {}).get("mappings") or []
        slug = next((m["pageSlug"] for m in maps if m.get("pageType") == "productHome"), None)
        slug = slug or (e.get("productSlug") or "").split("/")[0] or e.get("urlSlug")
        imgs = {i["type"]: i["url"] for i in e.get("keyImages") or []}
        tall = imgs.get("OfferImageTall") or imgs.get("DieselStoreFrontTall")
        img = tall or imgs.get("Thumbnail") or imgs.get("OfferImageWide")
        g = base_entry(
            "epic-" + e["id"], e["title"], f"https://store.epicgames.com/de/p/{slug}", "epic",
            img=img and img + ("?h=450&resize=1" if "epicgames.com" in img else ""), sq=not tall,
            tEn=(en.get(e["id"]) or e)["title"], pub=(e.get("seller") or {}).get("name"),
            deals=[{"src": "epic", "until": now[0]["endDate"][:10]}] if now else [{"src": "epic", "from": soon[0]["startDate"][:10]}],
        )
        games.append(g)
        flags[g["id"]] = {"epicFree" if now else "epicSoon"}
    log(f"Epic: {sum('epicFree' in f for f in flags.values())} gratis, {sum('epicSoon' in f for f in flags.values())} demnächst")
    return games, flags


PRIME_VIA = {"gog": "GOG", "epic": "Epic", "aga": "Amazon Games", "legacy": "Legacy Games", "microsoft": "Microsoft Store",
             "ubisoft": "Ubisoft Connect", "ea": "EA app", "origin": "EA app", "steam": "Steam"}
RATING_JUNK = re.compile(r"\s*\([^)]*(erwachsene|unbewertet|rated|mature|adult|eltern|pegi|usk|parental)[^)]*\)", re.I)


PRIME_LAST = ROOT / "data" / "cache" / "prime_last.json"
MONTHS_EN = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
MONTHS_DE = ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember"]
PRIME_SOON_VIA = {"epic": "Epic", "gog": "GOG", "amazon games": "Amazon Games", "legacy": "Legacy Games",
                  "microsoft": "Microsoft Store", "xbox": "Microsoft Store", "ubisoft": "Ubisoft Connect", "ea": "EA app"}


def fetch_prime_soon() -> tuple[list[dict], dict[str, set[str]]]:
    """Angekündigte Prime-Abholspiele aus Amazons Monatsartikel (amazongamestudios.com, "luna-<monat>-<jahr>")."""
    import html as htmllib

    today = datetime.now(timezone.utc).date()
    months = [(today.year, today.month), (today.year + (today.month == 12), today.month % 12 + 1)]
    live = {norm(g["t"]) for g in load_json(PRIME_LAST, [])}  # aktuelle Abholliste (fetch_prime läuft vorher)
    games, flags = [], {}
    for year, month in months:
        url = f"https://www.amazongamestudios.com/de-de/news/articles/luna-{MONTHS_EN[month - 1]}-{year}"
        st, page = http_text(url)
        if st != 200:
            continue  # Artikel für den nächsten Monat gibt es meist erst Ende des Vormonats
        text = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
        text = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", text)).replace(" ", " "))
        start = text.find("PC-Titel")
        if start < 0:
            continue
        section = text[start: text.find("Auf dieser Seite", start) if "Auf dieser Seite" in text[start:] else None]
        # "Titel (15. Oktober, Epic Games Store)"
        for m in re.finditer(r"(?<=\))\s*:?\s*([^()]+?)\s*\((\d{1,2})\. ?([A-Za-zäÄ]+),?\s*([^)]*)\)", section):
            title, day, mon, store = m.group(1).strip(), int(m.group(2)), m.group(3).lower(), m.group(4).lower()
            if mon not in MONTHS_DE:
                continue
            date = f"{year}-{MONTHS_DE.index(mon) + 1:02d}-{day:02d}"
            if norm(title) in live:
                continue  # schon freigeschaltet, steht in der normalen Abholliste
            via = next((v for k, v in PRIME_SOON_VIA.items() if k in store), store.title() or None)
            started = date < today.isoformat()  # Amazon schaltet am Starttag erst abends frei
            # Schon gestartet, aber nicht in der Abholliste (auf GitHub ist die blockiert): als abholbar führen, Frist unbekannt
            g = base_entry("primesoon-" + norm(title), title, url, "prime", sq=True,
                           deals=[{"src": "prime", "via": via} if started else {"src": "prime", "from": date, "via": via}])
            games.append(g)
            flags[g["id"]] = {"primeClaim" if started else "primeSoon"}
    log(f"Prime demnächst: {len(games)}")
    return games, flags


def fetch_prime() -> tuple[list[dict], dict[str, set[str]]]:
    """Wie _fetch_prime; blockt Amazon (von GitHub-Servern aus: HTTP 418), gilt die zuletzt geholte Liste ohne Abgelaufene."""
    try:
        games, flags = _fetch_prime()
        save_json(PRIME_LAST, games)
        return games, flags
    except Exception as e:  # noqa: BLE001
        today = datetime.now(timezone.utc).date().isoformat()
        games = [g for g in load_json(PRIME_LAST, []) if (g["deals"][0].get("until") or "9999") >= today]
        if not games:
            raise
        log(f"Prime: Abruf fehlgeschlagen ({e}), nutze letzte Liste ({len(games)} noch gültig)")
        return games, {g["id"]: {"primeClaim"} for g in games}


def _fetch_prime() -> tuple[list[dict], dict[str, set[str]]]:
    """Monatliche Gratis-PC-Spiele zum Behalten (früher Prime Gaming), Daten der Luna-Claims-Seite."""
    import http.cookiejar
    import uuid

    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    browser = {
        "User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9,en;q=0.8", "sec-ch-ua": '"Chromium";v="130", "Google Chrome";v="130"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
    }
    req = urllib.request.Request("https://luna.amazon.de/claims/home", headers={
        **browser, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Upgrade-Insecure-Requests": "1"})
    page = op.open(req, timeout=30).read().decode()
    tok = re.search(r"name=['\"]csrf-key['\"]\s+value=['\"]([^'\"]+)", page)
    if not tok:
        raise RuntimeError("csrf-key nicht gefunden")
    q = ("query FreeGames($pageSize: Int) { games: items(collectionType: FREE_GAMES, pageSize: $pageSize) { items { id category "
         "assets { title externalClaimLink cardMedia { defaultMedia { src2x } } } offers { startTime endTime } } } }")
    body = json.dumps({"operationName": "FreeGames", "variables": {"pageSize": 999}, "extensions": {}, "query": q}).encode()
    h = {**browser, "Content-Type": "application/json", "Accept": "*/*", "Origin": "https://luna.amazon.de",
         "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
         "Referer": "https://luna.amazon.de/claims/home", "client-id": "CarboniteApp", "csrf-token": tok.group(1),
         "prime-gaming-language": "en-US"}
    req = urllib.request.Request(f"https://luna.amazon.de/graphql?nonce={uuid.uuid4()}", data=body, headers=h)
    d = json.loads(op.open(req, timeout=30).read())
    games, flags = [], {}
    for it in d["data"]["games"]["items"]:
        if it.get("category") != "FULL_GAME":
            continue
        a = it["assets"]
        link = a.get("externalClaimLink") or "https://luna.amazon.de/claims/home"
        store = link.split("/dp/")[0].rstrip("/").rsplit("/", 1)[-1].rsplit("-", 1)[-1]
        ends = sorted(o["endTime"][:10] for o in it.get("offers") or [] if o.get("endTime"))
        img = ((a.get("cardMedia") or {}).get("defaultMedia") or {}).get("src2x")
        g = base_entry(
            "prime-" + it["id"].rsplit(".", 1)[-1], RATING_JUNK.sub("", a["title"]), link, "prime",
            img=img and img.replace("._FMwebp_.", "._SX450_._FMjpg_."), sq=True,
            deals=[{"src": "prime", "until": ends[0] if ends else None, "via": PRIME_VIA.get(store, store)}],
        )
        games.append(g)
        flags[g["id"]] = {"primeClaim"}
    log(f"Prime zum Abholen: {len(games)}")
    return games, flags


# Spielmodi aus Steam-Tags, wenn es keine Xbox-Angaben gibt (Luna-exklusive Spiele)
STEAM_MODE_TAGS = {
    "Singleplayer": "single", "Online Co-Op": "onlineCoop", "Local Co-Op": "localCoop", "Local Multiplayer": "localMP",
    "Split Screen": "splitscreen", "PvP": "onlineMP", "Online PvP": "onlineMP", "Massively Multiplayer": "onlineMP",
    "Cross-Platform Multiplayer": "crossplay",
}


def fetch_products(ids: list[str], lang: str) -> dict[str, dict]:
    out = {}
    for i in range(0, len(ids), 20):
        url = (
            "https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds="
            + ",".join(ids[i : i + 20])
            + f"&market={MARKET}&languages={lang}&MS-CV=DGU1mcuYo0WMMp+F.1"
        )
        for p in http_json(url).get("Products", []):
            out[p["ProductId"]] = p
    return out


def image_url(lp: dict) -> str | None:
    imgs = lp.get("Images") or []
    for purpose in ("Poster", "BoxArt", "BrandedKeyArt"):
        for im in imgs:
            if im.get("ImagePurpose") == purpose:
                u = im["Uri"]
                return ("https:" + u if u.startswith("//") else u), purpose
    return None, None


def slug(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "spiel"


def parse_product(p: dict, p_en: dict | None) -> dict:
    lp = p["LocalizedProperties"][0]
    title = lp["ProductTitle"].strip()
    en_title = (p_en or p)["LocalizedProperties"][0]["ProductTitle"].strip()
    props = p.get("Properties") or {}
    mp = (p.get("MarketProperties") or [{}])[0]
    img, purpose = image_url(lp)

    attrs = {}
    for a in props.get("Attributes") or []:
        attrs[a["Name"]] = a
    def mx(*names):
        vals = [attrs[n].get("Maximum") for n in names if n in attrs and attrs[n].get("Maximum")]
        return max(vals) if vals else None

    feats = set()
    if "SinglePlayer" in attrs:
        feats.add("single")
    if {"XblOnlineMultiPlayer", "OnlineMultiplayerWithGold"} & attrs.keys():
        feats.add("onlineMP")
    if {"XblOnlineCoop", "CoopSupportOnline"} & attrs.keys():
        feats.add("onlineCoop")
    if {"XblLocalMultiPlayer", "LocalMultiplayer"} & attrs.keys():
        feats.add("localMP")
    if {"XblLocalCoop", "CoopSupportLocal"} & attrs.keys():
        feats.add("localCoop")
    if "SharedSplitScreen" in attrs:
        feats.add("splitscreen")
    if {"XblCrossPlatformMultiPlayer", "XblCrossPlatformCoop", "CrossPlatformMultiPlayer", "CrossPlatformCoOp"} & attrs.keys():
        feats.add("crossplay")
    if "XPA" in attrs:
        feats.add("playAnywhere")
    if "ConsoleGen9Optimized" in attrs:
        feats.add("seriesOptimized")
    if "Capability4k" in attrs:
        feats.add("4k")
    if {"120fps"} & attrs.keys():
        feats.add("120fps")
    if "RayTracing" in attrs:
        feats.add("raytracing")
    if "ConsoleKeyboardMouse" in attrs:
        feats.add("mouseKeyboard")
    if "XblCloudSaves" in attrs:
        feats.add("cloudSaves")
    # reine Online-Spiele: kein Einzelspieler, aber Online-Modi
    online_only = "single" not in feats and bool(feats & {"onlineMP", "onlineCoop"}) and not (feats & {"localMP", "localCoop"})

    pegi = None
    for r in mp.get("ContentRatings") or []:
        if r.get("RatingSystem") == "PEGI":
            m = re.search(r"(\d+)", r.get("RatingId", ""))
            pegi = int(m.group(1)) if m else None
    if pegi is None and mp.get("MinimumUserAge") is not None:
        pegi = mp.get("MinimumUserAge")

    stars = None
    for u in mp.get("UsageData") or []:
        if u.get("AggregateTimeSpan") == "AllTime" and u.get("RatingCount", 0) >= 20:
            stars = round(u.get("AverageRating", 0), 1)

    rel = mp.get("OriginalReleaseDate") or ""
    xbox_year = int(rel[:4]) if rel[:4].isdigit() and 1980 < int(rel[:4]) < 2100 else None

    return {
        "id": p["ProductId"],
        "t": clean_title(title) if len(clean_title(title)) > 2 else title,
        "tFull": title,
        "tEn": en_title,
        "img": img,
        "imgSq": purpose != "Poster",
        "url": f"https://www.xbox.com/de-DE/games/store/{slug(title)}/{p['ProductId']}",
        "genres": props.get("Categories") or ([props["Category"]] if props.get("Category") else []),
        "feat": sorted(feats),
        "onlineOnly": online_only,
        "onlineMax": mx("XblOnlineMultiPlayer", "XblOnlineCoop"),
        "localMax": mx("XblLocalMultiPlayer", "XblLocalCoop"),
        "yx": xbox_year,
        "pegi": pegi,
        "stars": stars,
        "pub": lp.get("PublisherName"),
        "dev": lp.get("DeveloperName"),
    }


# ---------- Anreicherung ----------

mc_rl = RateLimit(4)
steam_rl = RateLimit(3)
spy_rl = RateLimit(0.9)


def mc_lookup(g: dict, forced=...) -> dict | None:
    if forced is None:
        return None
    hit = None
    for term in [forced.replace("-", " ")] if forced is not ... else search_terms(g["tEn"]):
        mc_rl.wait()
        q = urllib.parse.quote(term.replace("/", " "))
        d = http_json(
            f"https://backend.metacritic.com/finder/metacritic/search/{q}/web?apiKey={MC_KEY}&offset=0&limit=12&mcoTypeId=13"
        )
        items = [i for i in d["data"]["items"] if i.get("typeId") == 13]
        if forced is not ...:
            hit = next((i for i in items if i["slug"] == forced), None)
        else:
            def plat_ok(i):
                names = " ".join(p["name"] for p in i.get("platforms") or [])
                return "Xbox" in names or "PC" in names
            hit = best_match(term, g["yx"], [i for i in items if plat_ok(i)] or items,
                             lambda i: i["title"], lambda i: i.get("premiereYear"), full_title=g["tEn"])
        if hit:
            break
    if not hit:
        return None
    score = (hit.get("criticScoreSummary") or {}).get("score") or None  # 0 = noch keine Wertung
    return {
        **mc_details(hit["slug"]),
        "slug": hit["slug"],
        "title": hit["title"],
        "score": score,
        "year": hit.get("premiereYear"),
        "genres": [x["name"] for x in hit.get("genres") or [] if x.get("name")],
    }


def mc_details(slug: str) -> dict:
    """Zahl der Kritiken über alle Plattformen (Anhaltspunkt für die Produktionsgröße) und User Score."""
    mc_rl.wait()
    d = http_json(f"https://backend.metacritic.com/composer/metacritic/pages/games/{slug}/web?apiKey={MC_KEY}")
    out = {"reviews": None, "user": None, "userCount": None}
    for c in d.get("components") or []:
        name = (c.get("meta") or {}).get("componentName")
        item = (c.get("data") or {}).get("item") or {} if isinstance(c.get("data"), dict) else {}
        if name == "product":
            out["reviews"] = (item.get("criticScoreSummary") or {}).get("reviewCount")
        elif name == "user-score-summary":
            out["user"] = item.get("score") or None  # 0 / fehlend = "tbd" (zu wenige Bewertungen)
            out["userCount"] = item.get("reviewCount")
    return out


_hltb = None


def hltb_lookup(g: dict, forced=...) -> dict | None:
    global _hltb
    if forced is None:
        return None
    from howlongtobeatpy import HowLongToBeat

    if _hltb is None:
        _hltb = HowLongToBeat(0.0)
    hit = None
    if forced is not ...:
        hit = _hltb.search_from_id(int(forced))
    else:
        for term in search_terms(g["tEn"]):
            res = None
            for i in range(3):
                res = _hltb.search(term)
                if res is not None:
                    break
                time.sleep(3 * (i + 1))
            if res is None:
                raise RuntimeError("HLTB-Abfrage fehlgeschlagen")
            hit = best_match(term, g["yx"], res, lambda r: r.game_name, lambda r: r.release_world, full_title=g["tEn"])
            if hit:
                break
    if not hit:
        return None
    def h(x):
        return round(x, 1) if x else None
    return {
        "id": hit.game_id,
        "title": hit.game_name,
        "main": h(hit.main_story),
        "extra": h(hit.main_extra),
        "comp": h(hit.completionist),
        "year": hit.release_world or None,
    }


def steam_lookup(g: dict, forced=...) -> dict | None:
    if forced is None:
        return None
    if forced is ...:
        hit = None
        for term in search_terms(g["tEn"]):
            steam_rl.wait()
            q = urllib.parse.quote(term)
            d = http_json(f"https://store.steampowered.com/api/storesearch/?term={q}&cc=DE&l=english")
            hit = best_match(term, None, d.get("items") or [], lambda i: i["name"], lambda i: None, min_sim=0.9, full_title=g["tEn"])
            if hit:
                break
        if not hit:
            return None
        appid, name = hit["id"], hit["name"]
    else:
        appid, name = int(forced), None
    spy_rl.wait()
    d = http_json(f"https://steamspy.com/api.php?request=appdetails&appid={appid}")
    tags = d.get("tags") or {}
    tags = list(tags.keys()) if isinstance(tags, dict) else []
    price = d.get("initialprice")
    return {
        "appid": appid,
        "name": name or d.get("name"),
        "tags": tags[:20],
        "price": int(price) / 100 if str(price or "").isdigit() and int(price) > 0 else None,
        "owners": d.get("owners"),
        "publisher": d.get("publisher"),
        "pos": d.get("positive") or 0,
        "neg": d.get("negative") or 0,
    }


SOURCES = {"mc": ("metacritic", mc_lookup), "hltb": ("hltb", hltb_lookup), "steam": ("steam", steam_lookup)}


# Felder, die ein Treffer haben muss; ältere Cache-Einträge ohne sie werden neu geholt
REQUIRED = {"mc": "userCount", "hltb": "main", "steam": "pos"}


def is_stale(entry: dict | None, refresh: bool, src: str = "") -> bool:
    if refresh or not entry:
        return True
    if entry.get("v") and REQUIRED.get(src) not in entry["v"]:
        return True
    age = datetime.now(timezone.utc) - datetime.fromisoformat(entry["at"])
    if entry.get("err"):
        return age > timedelta(days=1)
    return age > timedelta(days=REFRESH_HIT_DAYS if entry.get("v") else REFRESH_MISS_DAYS)


def enrich(games: list[dict], cache: dict, overrides: dict, refresh: bool):
    lock = threading.Lock()
    todo = []
    for g in games:
        c = cache.setdefault(g["id"], {})
        ov = overrides.get(g["id"], {})
        for src, (ov_key, _) in SOURCES.items():
            forced = ov.get(ov_key, ...)
            entry = c.get(src)
            # Override geändert -> neu nachschlagen
            if entry and entry.get("forced", ...) != (forced if forced is not ... else ...):
                entry = None
            if is_stale(entry, refresh, src):
                todo.append((g, src, forced))
    log(f"Nachzuschlagen: {len(todo)} Abfragen")
    done = [0]
    t0 = time.monotonic()

    def run(job):
        g, src, forced = job
        fn = SOURCES[src][1]
        e = {"at": datetime.now(timezone.utc).isoformat()}
        if forced is not ...:
            e["forced"] = forced
        try:
            e["v"] = fn(g, forced)
        except Exception as ex:  # noqa: BLE001
            e["v"] = None
            e["err"] = str(ex)[:200]
        with lock:
            cache[g["id"]][src] = e
            done[0] += 1
            if done[0] % 100 == 0:
                log(f"  {done[0]}/{len(todo)} ({time.monotonic() - t0:.0f}s)")
                save_json(CACHE_FILE, cache)

    # je Quelle ein eigener Pool, damit die Quellen parallel laufen, aber jede für sich gedrosselt bleibt
    pools = {"mc": ThreadPoolExecutor(4), "hltb": ThreadPoolExecutor(3), "steam": ThreadPoolExecutor(2)}
    futs = [pools[j[1]].submit(run, j) for j in todo]
    for f in futs:
        f.result()
    for p in pools.values():
        p.shutdown()
    errs = sum(1 for g in games for s in SOURCES if (cache[g["id"]].get(s) or {}).get("err"))
    if errs:
        log(f"Fehler bei {errs} Abfragen (werden beim nächsten Lauf wiederholt)")


# ---------- Ausgabe ----------

def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(p: Path, data, compact=False):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    if compact:
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    else:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


# ---------- Produktionsgröße (AAA / AA / Indie) ----------
# Ein offizielles Label gibt es nirgends. Geschätzt aus Publisher, Steam-Tag "Indie",
# Zahl der Metacritic-Kritiken und Steam-Vollpreis. Korrektur per overrides.json: {"<id>": {"tier": "AA"}}.

BIG_PUBLISHERS = [
    "xbox game studios", "microsoft", "bethesda", "activision", "blizzard", "electronic arts", "ea sports", "ea swiss",
    "ubisoft", "square enix", "sega", "atlus", "bandai namco", "capcom", "warner bros", "2k", "take-two", "rockstar",
    "sony", "playstation", "konami", "cd projekt", "epic games", "riot games", "nintendo", "mojang", "koei tecmo",
]
MID_PUBLISHERS = [
    "thq nordic", "focus entertainment", "nacon", "bigben", "paradox", "deep silver", "plaion", "koch media", "505 games",
    "kalypso", "frontier", "remedy", "saber", "techland", "private division", "microids", "aspyr", "embracer",
    "gearbox", "quantic dream", "kepler", "nighthawk", "level-5", "spike chunsoft", "nis america", "marvelous",
    "milestone", "codemasters", "people can fly", "starbreeze", "bloober", "11 bit", "warhorse", "dontnod",
    "don't nod", "obsidian", "double fine", "ninja theory", "inxile", "compulsion", "the coalition", "arkane",
]
INDIE_PUBLISHERS = [
    "devolver", "annapurna", "raw fury", "team17", "humble", "finji", "chucklefish", "coffee stain", "tinybuild",
    "curve", "fellow traveller", "akupara", "thunderful", "headup", "playism", "freedom games", "dangen", "whitethorn",
    "hooded horse", "neon doctrine", "ysbryd", "armor games", "kwalee", "silent games", "untold tales", "wired productions",
    "merge games", "modus", "super rare", "serenity forge", "noodlecake", "surprise attack", "secret mode", "joystick ventures",
    "dear villagers", "playtonic", "versus evil", "iam8bit", "skybound", "ratalaika", "eastasiasoft", "assemble",
]


def _has(name: str | None, lst: list[str]) -> bool:
    n = (name or "").lower()
    return any(x in n for x in lst)


def classify_tier(g: dict, mc: dict | None, st: dict | None, year: int | None) -> tuple[str | None, str]:
    st = st or {}
    pubs = [g.get("pub"), st.get("publisher")]
    big = any(_has(p, BIG_PUBLISHERS) for p in pubs)  # Entwickler allein macht kein AAA
    mid = any(_has(p, MID_PUBLISHERS) for p in pubs + [g.get("dev")])
    indie_pub = any(_has(p, INDIE_PUBLISHERS) for p in pubs)
    indie_tag = "Indie" in (st.get("tags") or [])
    reviews = (mc or {}).get("reviews")
    price = st.get("price")
    old = bool(year and year < 2008)  # ältere Spiele haben weniger Online-Kritiken und heute niedrigere Preise

    why = []
    if reviews:
        why.append(f"{reviews} Kritiken")
    if price:
        why.append(f"Steam-Preis {price:.2f} €".replace(".", ","))
    if indie_tag:
        why.append("Steam-Tag Indie")
    why.append(f"Publisher {g.get('pub') or st.get('publisher') or '?'}")
    reason = ", ".join(why)

    many = reviews is not None and reviews >= (35 if old else 55)
    some = reviews is not None and reviews >= (15 if old else 25)
    cheap = price is not None and price < 30 and not old
    pricey = price is not None and price >= 50

    if indie_tag or indie_pub:
        return "Indie", reason  # große Indie-Hits (Hades, Hollow Knight) bleiben Indie
    if big:
        # Preise sinken mit der Zeit: ein günstiges Spiel mit sehr vielen Kritiken war trotzdem eine Großproduktion
        if (cheap and not (reviews or 0) >= 80) or (reviews is not None and not some and not old):
            return "AA", reason
        return "AAA", reason
    if many and pricey:
        return "AAA", reason
    if mid or some or (price is not None and price >= 30):
        return "AA", reason
    if reviews is None and price is None:
        return None, reason  # zu wenig Anhaltspunkte
    return "Indie", reason


def merge_duplicates(games: list[dict]) -> list[dict]:
    """Konsolen- und PC-Fassung (und Luna) haben eigene IDs: gleiche Spiele zu einem Eintrag zusammenführen.
    Gleich = gleicher deutscher oder englischer Titel oder gleicher Metacritic-Eintrag."""
    groups: list[list[dict]] = []
    by_key: dict[str, int] = {}
    for g in games:
        keys = {norm(g["t"]), norm(g.pop("_tEn", "") or g["t"])} - {""}
        if g.get("mcSlug"):
            keys.add("mc:" + g["mcSlug"])
        hit = next((by_key[k] for k in keys if k in by_key), None)
        if hit is None:
            hit = len(groups)
            groups.append([])
        groups[hit].append(g)
        for k in keys:
            by_key.setdefault(k, hit)
    out = []
    for grp in groups:
        # Xbox-Eintrag als Basis (Link zur Xbox-Seite, Store-Angaben), dann Luna, Netflix, Epic, Prime
        def rank(g):
            return next((i + 1 for i, pre in enumerate(SOURCE_ORDER) if g["id"].startswith(pre)), 0)

        grp.sort(key=lambda g: (rank(g), -len(g), "console" not in g["plat"]))
        base = dict(grp[0])
        for o in grp[1:]:
            base["plat"] = [p for p in PLATFORMS if p in base["plat"] or p in o["plat"]]
            for k in ("new", "leaving"):
                if o.get(k):
                    base[k] = True
            base["feat"] = sorted(set(base.get("feat", [])) | set(o.get("feat", [])))
            base["links"] = {**o.get("links", {}), **base.get("links", {})}
            base["deals"] = base.get("deals", []) + o.get("deals", [])
            base["genres"] = list(dict.fromkeys(base.get("genres", []) + o.get("genres", [])))
            for k, v in o.items():
                base.setdefault(k, v)
            if o.get("added") and o["added"] < base.get("added", "9999"):
                base["added"] = o["added"]
        out.append(base)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="nur die ersten N Spiele (zum Testen)")
    args = ap.parse_args()

    flags = fetch_catalog()
    ids = sorted(flags)
    if args.limit:
        ids = ids[: args.limit]
    log(f"{len(ids)} Spiele im Game Pass ({MARKET})")
    de = fetch_products(ids, "de-de")
    en = fetch_products(ids, "en-us")
    games = [parse_product(de[i], en.get(i)) for i in ids if i in de]
    for name, fetch in (("Luna", fetch_luna), ("Netflix", fetch_netflix), ("PS Plus", fetch_psplus), ("Epic", fetch_epic), ("Prime", fetch_prime),
                        ("Prime demnächst", fetch_prime_soon), ("Steam", fetch_steam_deals)):
        try:
            extra, extra_flags = fetch()
        except Exception as e:  # noqa: BLE001
            log(f"WARNUNG: {name} nicht abrufbar ({e}) – diese Spiele fehlen in diesem Lauf")
            continue
        if args.limit:
            extra = extra[: args.limit]
        games += extra
        flags.update(extra_flags)

    today = datetime.now(timezone.utc).date().isoformat()
    first_seen = load_json(FIRST_SEEN_FILE, {})
    for g in games:
        first_seen.setdefault(g["id"], today)

    cache = load_json(CACHE_FILE, {})
    overrides = {k: v for k, v in load_json(OVERRIDES_FILE, {}).items() if not k.startswith("_")}
    for g in games:  # Steam-Spiele kennen ihre App-ID schon, keine Titelsuche nötig
        if g.get("steamAppid"):
            overrides.setdefault(g["id"], {}).setdefault("steam", g["steamAppid"])
    enrich(games, cache, overrides, args.refresh)
    save_json(CACHE_FILE, cache)
    if not args.limit:
        save_json(FIRST_SEEN_FILE, first_seen)

    out = []
    for g in games:
        c = cache.get(g["id"], {})
        mc = (c.get("mc") or {}).get("v")
        hl = (c.get("hltb") or {}).get("v")
        st = (c.get("steam") or {}).get("v")
        f = flags[g["id"]]
        # Erscheinungsjahr = Original-Release (Metacritic, sonst HLTB), nicht der spätere Xbox-Port
        year = (mc and mc.get("year")) or (hl and hl.get("year")) or g["yx"]
        steam_cover = (
            f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{st['appid']}/library_600x900.jpg"
            if g["imgSq"] and st else None
        )
        tier, tier_why = classify_tier(g, mc, st, year)
        if overrides.get(g["id"], {}).get("tier"):
            tier, tier_why = overrides[g["id"]]["tier"], "manuell festgelegt"
        sp, sp_n = (g["sp"], g["spN"]) if g.get("sp") is not None else steam_pct((st or {}).get("pos", 0), (st or {}).get("neg", 0))
        if f & {"steamFree", "steamCheap", "steamCheap10"}:
            f = (f - {"steamFree", "steamCheap", "steamCheap10"}) | steam_rules_keep(f, sp, sp_n, mc and mc.get("score"), tier)
            if not f:
                continue  # Steam-Kandidat, der die Feinauswahl nicht besteht
        mc_ow = any("open-world" in x.lower() for x in (mc or {}).get("genres") or [])
        tags = (st or {}).get("tags") or []
        out.append({
            "id": g["id"],
            "t": g["t"],
            "_tEn": g["tEn"],
            # Querformat-Bilder (Prime, Netflix) durch das Hochformat-Cover von Steam ersetzen, falls vorhanden;
            # das Original bleibt als Ersatz, falls Steam keins hat
            "img": steam_cover if steam_cover else g["img"],
            "img2": g["img"] if steam_cover else g.get("img2"),
            "sq": (g["imgSq"] and not steam_cover) or None,
            "url": g["url"],
            "links": g.get("links"),
            "ps": g.get("ps"),
            "deals": g.get("deals"),
            "plat": [p for p in PLATFORMS if p in f],
            "new": "new" in f or None,
            "leaving": "leaving" in f or None,
            "added": first_seen.get(g["id"]),
            "genres": g["genres"],
            "feat": g["feat"] or sorted({STEAM_MODE_TAGS[t] for t in tags if t in STEAM_MODE_TAGS}),
            "onlineOnly": g["onlineOnly"] or None,
            "onlineMax": g["onlineMax"],
            "localMax": g["localMax"],
            "y": year,
            "yx": g["yx"],
            "mc": mc and mc.get("score"),
            "us": mc and mc.get("user"),
            "usN": mc and mc.get("user") and mc.get("userCount"),
            "mcSlug": mc and mc["slug"],
            "mcGenres": (mc or {}).get("genres") or None,
            "hMain": hl and hl.get("main"),
            "hExtra": hl and hl.get("extra"),
            "hComp": hl and hl.get("comp"),
            "hltbId": hl and hl["id"],
            "openWorld": True if ("Open World" in tags or mc_ow) else (False if st else None),
            "tier": tier,
            "tierWhy": tier_why,
            "tags": tags or None,
            "steam": st and st["appid"],
            "sp": sp,
            "spN": sp_n if sp is not None else None,
            "pegi": g["pegi"],
            "stars": g["stars"],
            "pub": g["pub"],
            "dev": g["dev"],
        })
    out = [{k: v for k, v in g.items() if v not in (None, [], "")} for g in out]
    out = merge_duplicates(out)
    out.sort(key=lambda g: g["t"].lower())
    save_json(OUT_FILE, {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "market": MARKET, "games": out}, compact=True)
    n = len(out)
    log(
        f"Fertig: {n} Spiele -> {OUT_FILE.relative_to(ROOT)} | Metascore {sum('mc' in g for g in out)}, "
        f"HLTB {sum('hMain' in g for g in out)}, Steam-Tags {sum('tags' in g for g in out)}"
    )


if __name__ == "__main__":
    sys.exit(main())
