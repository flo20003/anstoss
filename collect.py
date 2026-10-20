import json, re, urllib.request
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape

# (URL, Quelle, Liga oder None, Verein oder None). Eigene Feeds einfach als neue Zeile ergänzen.
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
]
# Webseiten ohne bekannten Feed: (URL, Quelle, Verein, Pflicht-Muster im Link, Art). Der Sammler sucht zuerst
# einen Feed im Seitenkopf und liest sonst die Überschriften samt Links von der Seite.
PAGES = [
    ("https://sport.sky.de/fussball/artikel/transfer-update-news/12478082/34942", "Sky Sport", None, r"/(fussball/artikel|transfer/news)/", None),
    ("https://sport.sky.de/transfer-news", "Sky Sport", None, r"/(fussball/artikel|transfer/news)/", "TG"),
    ("https://sport.sky.de/fixe-transfers", "Sky Sport", None, r"/(fussball/artikel|transfer/news)/", "Transfer"),
    ("https://www.bvb.de/de/de/aktuelles/news.html", "BVB.de", "BVB", r"/aktuelles/news/", None),
    ("https://www.hsv.de/uebersicht", "HSV.de", "HSV", None, None),
    ("https://www.fcn.de/home/", "FCN.de", "FCN", r"/news/artikel/", None),
    ("https://weiche-liga.de/", "SC Weiche", "SCW", None, None),
    # Transfermarkt: nur Überschrift und Link der Nachrichten, ohne Garantie (Seite kann den Abruf blockieren)
    ("https://www.transfermarkt.de/", "Transfermarkt", None, r"/news/\d+", None),
]
# YouTube-Kanäle (Handle wie @bvb oder Kanalnummer wie UCxxxx, Verein). Handles sind ungeprüft, bei FEHLER im Protokoll korrigieren.
YOUTUBE = [("@bvb", "BVB"), ("@hsv", "HSV"), ("@fcnuernberg", "FCN")]
CLUBS = {"BVB": ["dortmund", "bvb"], "HSV": ["hsv", "hamburger sv"],
         "FCN": ["nürnberg", "nuernberg"], "SCW": ["weiche flensburg", "sc weiche"]}
LEAGUES = [("DFB-Pokal", "DFB-Pokal"), ("2. Bundesliga", "2. Bundesliga"), ("3. Liga", "3. Liga"), ("Regionalliga", "Regionalliga Nord"),
           ("Schleswig-Holstein-Liga", "SH-Liga"), ("Bundesliga", "Bundesliga"),
          ]
OPENLIGA = [("bl1", "Bundesliga"), ("bl2", "2. Bundesliga"), ("bl3", "3. Liga"), ("dfb", "DFB-Pokal")]
NOW = datetime.now(timezone.utc)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 anstoss-feed"})
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
        ts = parse_date(child(e, "pubDate") or child(e, "published") or child(e, "updated"))
        full = title + " " + summ
        c, l = club or club_of(full), league or league_of(full)
        if not (keep or c or l) or NOW - ts > timedelta(days=14):
            continue
        out.append({"club": c, "league": l, "tag": tg_of(full) if tag == "TG" else (tag or tag_of(full)),
                    "title": title, "summary": summ, "source": source, "url": fixurl(source, child(e, "link")), "img": img_of(e),
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
        if not done and ts > NOW - timedelta(hours=2):
            NEXTALL.setdefault(c, []).append({"club": c, "league": name, "home": t1, "away": t2, "ts": ts.isoformat(),
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
                   "tables": {**OLD.get("tables", {}), **TABLES}}, f, ensure_ascii=False, indent=1)
