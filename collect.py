import difflib, json, os, re, time, unicodedata, urllib.request
from urllib.parse import urljoin, urlparse, quote, urlencode
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape

# (URL, Quelle, Liga oder None, Verein oder None). Eigene Feeds einfach als neue Zeile ergänzen.
def gn(q):
    return "https://news.google.com/rss/search?q=" + quote(q) + "&hl=de&gl=DE&ceid=DE:de"


GN_NAMES = {"kicker": "Kicker", "sky sport": "Sky Sport", "transfermarkt": "Transfermarkt",
            "transfermarkt.de": "Transfermarkt", "sportschau": "Sportschau"}
TW = "(Transfer OR Wechsel OR Gerücht OR verpflichtet OR Leihe OR Vertrag)"

FEEDS = [
    ("https://newsfeed.kicker.de/news/aktuell", "Kicker", None, None),
    ("https://newsfeed.kicker.de/news/bundesliga", "Kicker", "Bundesliga", None),
    ("https://newsfeed.kicker.de/news/fussball", "Kicker", None, None),
    ("https://newsfeed.kicker.de/team/borussia-dortmund", "Kicker", None, "BVB"),
    ("https://newsfeed.kicker.de/team/hamburger-sv", "Kicker", None, "HSV"),
    ("https://newsfeed.kicker.de/team/1-fc-nuernberg", "Kicker", None, "FCN"),
    ("https://www.fcn.de/rss-feed/", "FCN.de", None, "FCN"),
    # Liga-Feeds von Kicker (Adressen ungeprüft, im Protokoll nachsehen)
    ("https://newsfeed.kicker.de/league/2-bundesliga", "Kicker", "2. Bundesliga", None),
    ("https://newsfeed.kicker.de/league/3-liga", "Kicker", "3. Liga", None),
    ("https://newsfeed.kicker.de/league/regionalliga-nord", "Kicker", "Regionalliga Nord", None),
    ("https://www.sportschau.de/fussball/index~rss2.xml", "Sportschau", None, None),
    ("https://www.sportschau.de/fussball/bundesliga/index~rss2.xml", "Sportschau", "Bundesliga", None),
    # Google-News-Suchfeeds: Transfers und Gerüchte aus vielen Medien, auch Sky, Kicker und Transfermarkt
    (gn('"Borussia Dortmund" ' + TW + " when:14d"), "Google News", None, "BVB", "TG"),
    (gn('"Hamburger SV" ' + TW + " when:14d"), "Google News", None, "HSV", "TG"),
    (gn('"1. FC Nürnberg" ' + TW + " when:14d"), "Google News", None, "FCN", "TG"),
    (gn('"Weiche Flensburg" ' + TW + " when:30d"), "Google News", None, "SCW", "TG"),
    (gn("Bundesliga Transfer Gerücht when:7d"), "Google News", "Bundesliga", None, "TG", True),
    (gn("2. Bundesliga Transfer when:7d"), "Google News", "2. Bundesliga", None, "TG", True),
    (gn("3. Liga Transfer when:7d"), "Google News", "3. Liga", None, "TG", True),
    (gn("site:sport.sky.de Transfer when:14d"), "Google News", None, None, "TG", True),
    (gn("site:transfermarkt.de when:14d"), "Google News", None, None, "TG", True),
]
# Webseiten ohne bekannten Feed: (URL, Quelle, Verein, Pflicht-Muster im Link, Art). Der Sammler sucht zuerst
# einen Feed im Seitenkopf und liest sonst die Überschriften samt Links von der Seite.
PAGES = [
    ("https://sport.sky.de/fussball/artikel/transfer-update-news/12478082/34942", "Sky Sport", None, r"/(fussball/artikel|transfer/news)/", None),
    ("https://sport.sky.de/transfer-news", "Sky Sport", None, r"/(fussball/artikel|transfer/news)/", "TG"),
    ("https://www.bvb.de/de/de/aktuelles/news.html", "BVB.de", "BVB", r"/aktuelles/news/", None),
    ("https://www.hsv.de/uebersicht", "HSV.de", "HSV", None, None),
    ("https://www.fcn.de/home/", "FCN.de", "FCN", r"/news/artikel/", None),
    ("https://weiche-liga.de/", "SC Weiche", "SCW", None, None),
]
# YouTube-Kanäle (Handle wie @bvb oder Kanalnummer wie UCxxxx, Verein). Handles sind ungeprüft, bei FEHLER im Protokoll korrigieren.
YOUTUBE = [("@bvb", "BVB"), ("@hsv", "HSV"), ("@fcnuernberg", "FCN")]
CLUBS = {"BVB": ["dortmund", "bvb"], "HSV": ["hsv", "hamburger sv"],
         "FCN": ["nürnberg", "nuernberg", "nurnberg", "nuremberg"], "SCW": ["weiche flensburg", "sc weiche"]}
LEAGUES = [("DFB-Pokal", "DFB-Pokal"), ("2. Bundesliga", "2. Bundesliga"), ("3. Liga", "3. Liga"), ("Regionalliga", "Regionalliga Nord"),
           ("Schleswig-Holstein-Liga", "SH-Liga"), ("Bundesliga", "Bundesliga"),
          ]
OPENLIGA = [("bl1", "Bundesliga"), ("bl2", "2. Bundesliga"), ("bl3", "3. Liga"), ("dfb", "DFB-Pokal")]
NOW = datetime.now(timezone.utc)


def get(url, extra=None):
    req = urllib.request.Request(url, headers={**(extra or {}), "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "de-DE,de;q=0.9"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def club_of(s):
    s = s.lower()
    for k, words in CLUBS.items():
        if any(re.search(r"\b" + re.escape(w), s) for w in words):
            return k
    return None


def league_of(s):
    for kw, name in LEAGUES:
        if kw.lower() in s.lower():
            return name
    return None


def tag_of(s):
    s = s.lower()
    if re.search(r"gerücht|interesse|offenbar|angeblich|soll .* wechseln|vor dem wechsel|reportedly|linked with|interested in|rumour|according to", s):
        return "Gerücht"
    if re.search(r"transfer|wechsel|verpflicht|leihe|ablöse|zugang|abgang|vertrag|unterschreibt|signs|signing|loan|here we go|fichaje|ficha por|cesión", s):
        return "Transfer"
    return "News"


def child(e, name):
    for c in e:
        if c.tag.split("}")[-1] == name:
            return (c.text or "").strip() or c.get("href", "")
    return ""


def parse_date(s):
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except Exception:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return NOW


def img_of(e):
    for c in e.iter():
        u = c.get("url")
        if c.tag.split("}")[-1] in ("thumbnail", "content", "enclosure") and u and \
                re.search(r"\.(jpe?g|png|webp)|image", u + c.get("type", "") + c.get("medium", ""), re.I):
            return u
    m = re.search(r'<img[^>]+src=["\']([^"\']+)', unescape(child(e, "description") or child(e, "encoded") or ""))
    return m.group(1) if m else ""


def feed_items(url, source, league, club, tag=None, keep=False):
    root = ET.fromstring(get(url))
    out = []
    for e in root.iter():
        if e.tag.split("}")[-1] not in ("item", "entry"):
            continue
        title = unescape(child(e, "title"))
        summ = re.sub(r"<[^>]+>", "", unescape(child(e, "description") or child(e, "summary")))[:220].strip()
        src = source
        if "news.google.com" in url:
            pub = child(e, "source")
            if pub and title.endswith(" - " + pub):
                title = title[: -len(pub) - 3]
            src = GN_NAMES.get(pub.lower(), "Weitere Medien")
            summ = "Gemeldet von " + pub if pub else ""
        ts = parse_date(child(e, "pubDate") or child(e, "published") or child(e, "updated"))
        full = title + " " + summ
        c, l = club or club_of(full), league or league_of(full)
        if not (keep or c or l) or NOW - ts > timedelta(days=14):
            continue
        out.append({"club": c, "league": l, "tag": tg_of(full) if tag == "TG" else (tag or tag_of(full)),
                    "title": title, "summary": summ, "source": src, "url": fixurl(source, child(e, "link")), "img": img_of(e),
                    "ts": ts.isoformat()})
    return men_only(out) if source in CLUBSITES else out


def fixurl(source, link):
    # FCN.de verlinkt Artikel relativ zur Basisadresse; richtig ist /news/artikel/..., nicht /home/news/artikel/...
    return link.replace("/home/news/", "/news/") if source == "FCN.de" else link


def tg_of(s):
    return "Gerücht" if tag_of(s) == "Gerücht" or "?" in s else "Transfer"


_TS = None


def old_ts():
    global _TS
    if _TS is None:
        try:
            with open("news.json", encoding="utf-8") as f:
                _TS = {i["url"]: i["ts"] for i in json.load(f)["items"] if i.get("url")}
        except Exception:
            _TS = {}
    return _TS


BAD = re.compile(r"shop|ticket|login|impressum|datenschutz|cookie|kontakt|partner|karriere|newsletter|mailto|javascript|\.(jpg|png|svg|pdf)", re.I)


YOUTH = re.compile(r"\bU\s?(?:1[0-9]|2[0-3])\b|\bII\b|jugend|junioren|juniorinnen|nachwuchs|\bnlz\b|akademie|amateure|reserve|zweite mannschaft|"
                   r"frauen|mädchen|handball|tischtennis|efootball|gaming|e-?sport|basketball|futsal|eishockey", re.I)
CLUBSITES = ("BVB.de", "HSV.de", "FCN.de", "SC Weiche")


def men_only(items):
    return [i for i in items if not YOUTH.search(i["title"] + " " + i["url"] + " " + i["summary"])]


def page_items(url, source, club, hint, tag):
    html = get(url).decode("utf-8", "ignore")
    bm = re.search(r'<base[^>]+href=["\']?([^"\'\s>]+)', html, re.I)
    base = urljoin(url, bm.group(1)) if bm else url
    m = re.search(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*href=["\']([^"\']+)["\']', html, re.I) or \
        re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]*type=["\']application/(?:rss|atom)\+xml', html, re.I)
    if m:
        try:
            got = feed_items(urljoin(base, m.group(1)), source, None, club, tag, True)
            if got:
                return men_only(got) if club else got
        except Exception as ex:
            print("Kein Feed nutzbar bei", url, ex)
    host, ts_map, out, seen = urlparse(url).netloc, old_ts(), [], set()
    for href, inner in re.findall(r'<a\s[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        link = fixurl(source, urljoin(base, unescape(href)))
        text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        text = re.sub(r"^Nächster Artikel\s*", "", text)
        if link in seen or urlparse(link).netloc != host or not 28 <= len(text) <= 200 or len(text.split()) < 4:
            continue
        if (hint and not re.search(hint, link)) or (not hint and BAD.search(link)):
            continue
        seen.add(link)
        out.append({"club": club or club_of(text), "league": league_of(text),
                    "tag": tg_of(text) if (tag == "TG" or "/transfer/" in link) else (tag or tag_of(text)),
                    "title": text, "summary": "", "source": source, "url": link, "img": "",
                    "ts": ts_map.get(link, NOW.isoformat())})
    return (men_only(out) if club else out)[:40]


STOPLINE = re.compile(r"^(Mehr|Direkt|Erlebe|Zum |Hol dir|Alle |Auf Sky|Sportfan|Image|Die Zu)", re.I)


def split_top(txt):
    parts, depth, cur = [], 0, ""
    for ch in txt:
        depth += (ch == "(") - (ch == ")" and depth > 0)
        if ch in ",;" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [x.strip(" .\u00a0") for x in parts if x.strip(" .\u00a0")]


def sky_transfers(url):
    """Liest die Sky-Übersicht 'Fixe Transfers' (Zu- und Abgänge je Verein, Bundesliga und 2. Bundesliga)."""
    html = get(url).decode("utf-8", "ignore")
    club_a = r'https?://sport\.sky\.de/[a-z0-9-]+/?'
    html = re.sub(r'<a[^>]+href=["\']' + club_a + r'["\'][^>]*>\s*<(?:strong|b)[^>]*>(.*?)</(?:strong|b)>', r"\n##CLUB##\1\n", html, flags=re.S | re.I)
    html = re.sub(r'<(?:strong|b)[^>]*>\s*<a[^>]+href=["\']' + club_a + r'["\'][^>]*>(.*?)</a>\s*</(?:strong|b)>', r"\n##CLUB##\1\n", html, flags=re.S | re.I)
    html = re.sub(r"</(?:p|li|h[1-6]|div|ul|ol|section|article|tr)>|<br\s*/?>", "\n", html, flags=re.I)
    lines = [re.sub(r"\s+", " ", x).strip() for x in unescape(re.sub(r"<[^>]+>", "", html)).split("\n")]
    league, club, last, marked, out = "Bundesliga", None, None, False, []
    for line in lines:
        if not line:
            continue
        if "Zweitligisten" in line:
            league = "2. Bundesliga"
        elif "Bundesligisten" in line:
            league = "Bundesliga"
        if line.startswith("##CLUB##"):
            club, marked = line[8:].strip(), True
            continue
        m = re.match(r"^(Zugänge|Abgänge)\s*:?\s*(.*)$", line)
        if m:
            if not marked and last:
                club = last
            if not club:
                continue
            for e in split_top(m.group(2).lstrip(": ")):
                mm = re.match(r"^(.*?)\s*\((.*)\)\s*$", e)
                name, info = (mm.group(1).strip(), mm.group(2)) if mm else (e, "")
                other, _, note = info.partition(",")
                out.append({"c": club, "l": league, "d": "in" if m.group(1) == "Zugänge" else "out",
                            "p": name, "o": other.strip(), "n": note.strip()})
        elif len(line) <= 40 and ":" not in line and not STOPLINE.match(line):
            last = line
    if len(out) < 50:
        raise Exception("nur %d Transfers gefunden, Seitenaufbau geändert?" % len(out))
    return out


AF_KEY = os.environ.get("APIFOOTBALL_KEY", "")
USE_TM_API = True  # auf False setzen, um die Transfermarkt-API (Testinstanz) nicht zu nutzen
TM_BASES = ["https://transfermarkt-api.fly.dev", "https://transfermarkt-api.vercel.app"]
TM_OK = None
TM_CLUBS = {"BVB": "16", "HSV": "41", "FCN": "4"}  # Transfermarkt-Vereinsnummern (ungeprüft)
AF_SEARCH = {"BVB": "Dortmund", "HSV": "Hamburger", "FCN": "Nurnberg"}
CANON = {"BVB": "Borussia Dortmund", "HSV": "Hamburger SV", "FCN": "1. FC Nürnberg"}
WINDOW = timedelta(days=300)


def any_date(x):
    for f in ("%Y-%m-%d", "%b %d, %Y", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(x)[:12].strip(), f).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(str(x).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def league_for(code, tables):
    for name, rows in tables.items():
        if any(club_of(r["team"]) == code for r in rows):
            return name
    return "2. Bundesliga" if code == "FCN" else "Bundesliga"


def af_get(path, **q):
    d = json.loads(get("https://v3.football.api-sports.io/" + path + "?" + urlencode(q), {"x-apisports-key": AF_KEY}))
    if d.get("errors"):
        raise Exception(str(d["errors"]))
    return d["response"]


def ascii_(x):
    return unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower()


AF_STOP = {"fc", "sv", "sc", "vfl", "vfb", "tsg", "fsv", "tsv", "ev", "borussia", "eintracht", "fortuna", "spvgg", "vfr", "sg", "tus", "rb"}


def nk(name):
    return " ".join(t for t in re.findall(r"[a-z0-9]+", ascii_(name)) if t not in AF_STOP and not t.isdigit())


def af_term(name):
    toks = [t for t in re.findall(r"[a-z]+", ascii_(name)) if t not in AF_STOP and len(t) >= 3]
    return max(toks, key=len) if toks else ascii_(name)[:10]


def af_best(name, teams):
    n, best, score = " ".join(re.findall(r"[a-z0-9]+", ascii_(name))), None, 0
    for t in teams:
        if t.get("national") or YOUTH.search(t["name"]) or t.get("country") not in (None, "Germany"):
            continue
        sc = difflib.SequenceMatcher(None, n, " ".join(re.findall(r"[a-z0-9]+", ascii_(t["name"])))).ratio()
        if sc > score:
            best, score = t, sc
    return best if score >= 0.55 else None


class Budget(Exception):
    pass


AF_LEAGUES = [("Bundesliga", 78), ("2. Bundesliga", 79), ("3. Liga", 80)]
AF_CAP, AF_PER_RUN = 85, 30  # Anfragen pro Tag bzw. pro Lauf (Gratis-Tarif: 100 pro Tag)


def club_list(tables, meta):
    lst = [(lg, r["team"]) for lg, _ in AF_LEAGUES for r in tables.get(lg, [])]
    if not lst:
        lst = [("Bundesliga", "Borussia Dortmund"), ("Bundesliga", "Hamburger SV"), ("2. Bundesliga", "1. FC Nürnberg")]
    return lst + [("Regionalliga Nord", n) for n in meta.get("reg_nord", [])]


def af_run(tables, meta, old, covered=()):
    day = NOW.strftime("%Y-%m-%d")
    used = meta.get("af_used") or {}
    if used.get("d") != day:
        used = {"d": day, "n": 0}
    meta["af_used"] = used
    ids, season, run = dict(meta.get("af_ids", {})), NOW.year if NOW.month >= 7 else NOW.year - 1, [0]
    by_club = {}
    for e in old:
        by_club.setdefault(e["c"], []).append(e)

    def call(path, **q):
        if used["n"] >= AF_CAP or run[0] >= AF_PER_RUN:
            raise Budget()
        used["n"] += 1
        run[0] += 1
        return af_get(path, **q)

    try:
        clubs = club_list(tables, meta)
        if not meta.get("af_bulk"):  # eine Anfrage pro Liga liefert alle Vereinsnummern, falls der Tarif es erlaubt
            meta["af_bulk"] = True
            for lg, lid in AF_LEAGUES:
                try:
                    teams = [r["team"] for r in call("teams", league=lid, season=season)]
                    for l2, name in clubs:
                        t = af_best(name, teams) if l2 == lg else None
                        if t:
                            ids[name] = t["id"]
                except Budget:
                    raise
                except Exception as ex:
                    print("API-Football Liste", lg, "nicht verfügbar:", str(ex)[:120])
        if not meta.get("reg_nord") and (not meta.get("reg_try") or NOW - datetime.fromisoformat(meta["reg_try"]) > timedelta(days=7)):
            meta["reg_try"] = NOW.isoformat()
            names = []
            try:
                for r in call("leagues", search="Regionalliga"):
                    toks = re.findall(r"[a-z]+", ascii_(r["league"]["name"]))
                    if (r.get("country") or {}).get("name") == "Germany" and "nord" in toks:
                        for t in call("teams", league=r["league"]["id"], season=season):
                            names.append(t["team"]["name"])
                            ids[t["team"]["name"]] = t["team"]["id"]
                        break
            except Budget:
                raise
            except Exception as ex:
                print("API-Football Regionalliga Nord nicht verfügbar:", str(ex)[:120])
            meta["reg_nord"] = names or ["SC Weiche Flensburg"]
            clubs = club_list(tables, meta)
        pos = meta.get("af_pos", 0) % max(1, len(clubs))
        for step in range(len(clubs)):
            lg, name = clubs[(pos + step) % len(clubs)]
            if nk(name) in covered and club_of(name) not in CANON:  # schon über die Liga-Übersicht abgedeckt, spart Anfragen
                meta["af_pos"] = (pos + step + 1) % len(clubs)
                continue
            if ids.get(name, 0) == 0 and name not in ids:
                res = call("teams", search=af_term(name))
                t = af_best(name, [r["team"] for r in res])
                ids[name] = t["id"] if t else -1
            tid = ids.get(name, -1)
            if tid > 0:
                entries = []
                for pl in call("transfers", team=tid):
                    for tr in pl.get("transfers", []):
                        dt = any_date(tr.get("date"))
                        tin, tout = tr["teams"]["in"], tr["teams"]["out"]
                        if not dt or NOW - dt > WINDOW or dt > NOW + timedelta(days=120):
                            continue
                        if tin.get("id") == tid:
                            d, other = "in", tout.get("name") or ""
                        elif tout.get("id") == tid:
                            d, other = "out", tin.get("name") or ""
                        else:
                            continue
                        if difflib.SequenceMatcher(None, ascii_(other), ascii_(name)).ratio() >= 0.8:
                            continue
                        typ = (tr.get("type") or "").strip()
                        typ = {"Loan": "Leihe", "Free": "ablösefrei", "N/A": "", "-": ""}.get(typ, typ)
                        entries.append({"c": name, "l": lg, "d": d, "p": pl["player"]["name"], "o": other,
                                        "n": ", ".join(x for x in (typ, dt.strftime("%d.%m.%Y")) if x),
                                        "s": "API-Football", "t": dt.isoformat()})
                by_club[name] = entries
            meta["af_pos"] = (pos + step + 1) % len(clubs)
    except Budget:
        print("API-Football: Anfragegrenze für diesen Lauf oder Tag erreicht, es geht beim nächsten Lauf weiter")
    meta["af_ids"] = ids
    return [e for lst in by_club.values() for e in lst]


def tm_get(path):
    global TM_OK
    last = None
    for base in ([TM_OK] if TM_OK else TM_BASES):
        time.sleep(2)  # Testinstanz erlaubt etwa 2 Anfragen pro 3 Sekunden
        try:
            d = json.loads(get(base + path))
            TM_OK = base
            return d
        except Exception as ex:
            last = ex
            print("Transfermarkt-API", base, type(ex).__name__, ex)
    raise last


def tm_transfers(old_squads, tables):
    out, squads = [], {}
    for code, cid in TM_CLUBS.items():
        lg = league_for(code, tables)
        players = tm_get("/clubs/%s/players" % cid).get("players", [])
        print("Transfermarkt-API", code, len(players), "Spieler gelesen")
        squads[code] = [{"id": str(p["id"]), "name": p.get("name", "")} for p in players if p.get("id")]
        for p in players:
            dt = any_date(p.get("joinedOn"))
            if dt and NOW - dt < WINDOW and p.get("signedFrom") and club_of(p["signedFrom"]) != code:
                out.append({"c": CANON[code], "l": lg, "d": "in", "p": p.get("name", ""), "o": p["signedFrom"],
                            "n": dt.strftime("%d.%m.%Y"), "s": "Transfermarkt-API", "t": dt.isoformat()})
        now_ids = {x["id"] for x in squads[code]}
        for gone in [x for x in old_squads.get(code, []) if x["id"] not in now_ids][:8]:
            try:
                for t in tm_get("/players/%s/transfers" % gone["id"]).get("transfers", []):
                    dt = any_date(t.get("date"))
                    if str((t.get("from") or {}).get("clubID")) == cid and dt and NOW - dt < WINDOW:
                        out.append({"c": CANON[code], "l": lg, "d": "out", "p": gone["name"],
                                    "o": (t.get("to") or {}).get("clubName", ""), "n": dt.strftime("%d.%m.%Y"),
                                    "s": "Transfermarkt-API", "t": dt.isoformat()})
                        break
            except Exception as ex:
                print("Transfermarkt-API Abgang", gone["name"], ex)
    return out, squads


def merge_tx(lists):
    out, seen = [], set()
    for e in (x for l in lists for x in l):
        code = club_of(e["c"])
        if code in CANON and not YOUTH.search(e["c"]):
            e = {**e, "c": CANON[code]}
        words = e["p"].split()
        k = (nk(e["c"]), e["d"], ascii_(words[-1]) if words else "")
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def yt_items(handle, club):
    html = "channel_id=" + handle if handle.startswith("UC") else get("https://www.youtube.com/" + handle).decode("utf-8", "ignore")
    m = re.search(r'"channelId":"(UC[\w-]{22})"', html) or re.search(r'channel_id=(UC[\w-]{22})', html)
    if not m:
        raise Exception("Keine Kanalnummer gefunden auf https://www.youtube.com/" + handle)
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + m.group(1)
    print("YouTube", handle, "->", url)
    return feed_items(url, "YouTube", None, club, "Video")


NEXTALL, TABLES = {}, {}


def league(short, name, season, out):
    if short != "dfb":
        try:
            tb = json.loads(get(f"https://api.openligadb.de/getbltable/{short}/{season}"))
            tb.sort(key=lambda t: (-t["points"], -t["goalDiff"], -t["goals"]))
            TABLES[name] = [{"team": t["teamName"], "played": t["matches"], "gd": t["goalDiff"], "pts": t["points"], "icon": t.get("teamIconUrl") or ""} for t in tb]
        except Exception as ex:
            print("Tabelle fehlt", name, ex)
    for m in json.loads(get(f"https://api.openligadb.de/getmatchdata/{short}/{season}")):
        t1, t2 = m["team1"]["teamName"], m["team2"]["teamName"]
        c = club_of(t1) or club_of(t2)
        if not c:
            continue
        ts = datetime.fromisoformat(m["matchDateTimeUTC"].replace("Z", "+00:00"))
        done = m.get("matchIsFinished")
        if not done and ts > NOW - timedelta(hours=3):
            NEXTALL.setdefault(c, []).append({"club": c, "id": m.get("matchID"), "league": name, "home": t1, "away": t2, "ts": ts.isoformat(),
                                              "hi": m["team1"].get("teamIconUrl") or "", "ai": m["team2"].get("teamIconUrl") or ""})
        res = [r for r in m.get("matchResults", []) if r.get("resultTypeID") == 2]
        if done and res and NOW - ts < timedelta(days=4):
            title, summ = f"{t1} {res[0]['pointsTeam1']}:{res[0]['pointsTeam2']} {t2}", "Endergebnis"
        else:
            continue
        out.append({"club": c, "league": name, "tag": "Spiel", "title": title, "summary": summ,
                    "source": "OpenLigaDB", "url": "", "img": "", "ts": ts.isoformat()})


def matches():
    out = []
    season = NOW.year if NOW.month >= 7 else NOW.year - 1
    for short, name in OPENLIGA:
        try:
            league(short, name, season, out)
        except Exception as ex:
            print("FEHLER OpenLigaDB", name, type(ex).__name__, ex)
    return out


items = []
for fn, args in [(matches, ())] + [(feed_items, f) for f in FEEDS] + [(yt_items, y) for y in YOUTUBE] + [(page_items, p) for p in PAGES]:
    try:
        got = fn(*args)
        print("OK ", args[0] if args else "OpenLigaDB", len(got))
        items += got
    except Exception as ex:
        print("FEHLER", args[0] if args else "OpenLigaDB", type(ex).__name__, ex)

TRANSFERS = []
for turl in ("https://sport.sky.de/fixe-transfers",
             "https://www.bundesliga.com/de/bundesliga/news/offizieller-transfermarkt-alle-wechsel-transfers-ubersicht-11850"):
    try:
        TRANSFERS = sky_transfers(turl)
        print("OK ", turl, len(TRANSFERS), "Wechsel")
        break
    except Exception as ex:
        print("FEHLER", turl, type(ex).__name__, ex)

OLD = {}
try:
    with open("news.json", encoding="utf-8") as f:
        OLD = json.load(f)
        items += [{**i, "url": fixurl(i["source"], i.get("url", ""))} for i in OLD["items"] if i["tag"] != "Spiel" and i.get("league") not in ("Premier League", "LaLiga")
                  and i["source"] not in ("BBC Sport", "The Guardian", "Marca", "AS", "Sky Sports")
                  and not (i["source"] in CLUBSITES and YOUTH.search(i["title"] + " " + i.get("url", "")))
                  and NOW - datetime.fromisoformat(i["ts"]) < timedelta(days=30)]
except Exception as ex:
    print("Alte news.json nicht lesbar:", ex)

META = dict(OLD.get("meta", {}))
AFX, TMX, SQUADS = OLD.get("tx_af", []), OLD.get("tx_tm", []), OLD.get("tm_squads", {})
TAB = {**OLD.get("tables", {}), **TABLES}


def due(k, hours):
    return not META.get(k) or NOW - datetime.fromisoformat(META[k]) > timedelta(hours=hours)


if AF_KEY and due("af", 3):
    try:
        try:
            st = af_get("status")
            if isinstance(st, dict):
                print("API-Football Tarif:", (st.get("subscription") or {}).get("plan"), "- Anfragen heute:",
                      (st.get("requests") or {}).get("current"), "von", (st.get("requests") or {}).get("limit_day"))
        except Exception as ex:
            print("API-Football Status nicht lesbar", ex)
        AFX = af_run(TAB, META, AFX, {nk(e["c"]) for e in TRANSFERS})
        META["af"] = NOW.isoformat()
        print("OK  API-Football Transfers", len(AFX), "Einträge, Anfragen heute:", META["af_used"]["n"])
    except Exception as ex:
        print("FEHLER API-Football", type(ex).__name__, ex)
elif not AF_KEY:
    print("Hinweis: Kein APIFOOTBALL_KEY gesetzt, API-Football wird übersprungen")
if USE_TM_API and due("tm", 12):
    try:
        TMX, SQUADS = tm_transfers(SQUADS, TAB)
        META["tm"] = NOW.isoformat()
        print("OK  Transfermarkt-API", len(TMX))
    except Exception as ex:
        print("FEHLER Transfermarkt-API", type(ex).__name__, ex)
ALLTX = sorted(merge_tx([AFX, TMX, TRANSFERS]), key=lambda e: e.get("t", ""), reverse=True)

seen, final = {}, []
for i in sorted(items, key=lambda x: x["ts"], reverse=True):
    k = i["url"] or i["title"]
    if k not in seen:
        seen[k] = i
        final.append(i)
    elif (i["summary"] or i.get("img")) and not (seen[k]["summary"] or seen[k].get("img")):
        final[final.index(seen[k])] = i
        seen[k] = i
NEXT3 = [g for c in NEXTALL for g in sorted(NEXTALL[c], key=lambda g: g["ts"])[:3]]
if final:
    vids = [i for i in final if i["tag"] == "Video"][:60]
    out = sorted(vids + [i for i in final if i["tag"] != "Video"][:400], key=lambda x: x["ts"], reverse=True)
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump({"updated": NOW.isoformat(), "items": out,
                   "next": NEXT3 or OLD.get("next", []),
                   "tables": {**OLD.get("tables", {}), **TABLES},
                   "transfers": ALLTX or OLD.get("transfers", []),
                   "tx_af": AFX, "tx_tm": TMX, "tm_squads": SQUADS, "meta": META}, f, ensure_ascii=False, indent=1)
