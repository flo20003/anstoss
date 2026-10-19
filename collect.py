import json, re, urllib.request
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
    ("https://www.sportschau.de/fussball/index~rss2.xml", "Sportschau", None, None),
    ("https://www.sportschau.de/fussball/bundesliga/index~rss2.xml", "Sportschau", "Bundesliga", None),
    # Premier League (geprüfte Adressen)
    ("https://feeds.bbci.co.uk/sport/football/rss.xml", "BBC Sport", None, None),
    ("https://www.theguardian.com/football/premierleague/rss", "The Guardian", "Premier League", None),
    ("https://www.skysports.com/rss/11095", "Sky Sports", None, None),
    # LaLiga (Adressen noch ungeprüft, im Protokoll nachsehen)
    ("https://www.theguardian.com/football/laligafootball/rss", "The Guardian", "LaLiga", None),
    ("https://e00-marca.uecdn.es/rss/futbol/primera-division.xml", "Marca", "LaLiga", None),
    ("https://as.com/rss/futbol/primera.xml", "AS", "LaLiga", None),
    # Regionalzeitungen und Vereinsseiten: weitere Feeds hier als neue Zeile eintragen
]
# YouTube-Kanäle (Handle wie @bvb oder Kanalnummer wie UCxxxx, Verein). Handles sind ungeprüft, bei FEHLER im Protokoll korrigieren.
YOUTUBE = [("@bvb", "BVB"), ("@hsv", "HSV"), ("@fcnuernberg", "FCN")]
CLUBS = {"BVB": ["dortmund", "bvb"], "HSV": ["hsv", "hamburger sv"],
         "FCN": ["nürnberg", "nuernberg"], "SCW": ["weiche flensburg", "sc weiche"]}
LEAGUES = [("DFB-Pokal", "DFB-Pokal"), ("2. Bundesliga", "2. Bundesliga"), ("3. Liga", "3. Liga"), ("Regionalliga", "Regionalliga Nord"),
           ("Schleswig-Holstein-Liga", "SH-Liga"), ("Bundesliga", "Bundesliga"),
           ("LaLiga", "LaLiga"), ("La Liga", "LaLiga"), ("Premier League", "Premier League")]
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


def feed_items(url, source, league, club, tag=None):
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
        if not (c or l) or NOW - ts > timedelta(days=14):
            continue
        out.append({"club": c, "league": l, "tag": tag or tag_of(full),
                    "title": title, "summary": summ, "source": source, "url": child(e, "link"), "img": img_of(e),
                    "ts": ts.isoformat()})
    return out


def yt_items(handle, club):
    html = "channel_id=" + handle if handle.startswith("UC") else get("https://www.youtube.com/" + handle).decode("utf-8", "ignore")
    m = re.search(r'"channelId":"(UC[\w-]{22})"', html) or re.search(r'channel_id=(UC[\w-]{22})', html)
    if not m:
        raise Exception("Keine Kanalnummer gefunden auf https://www.youtube.com/" + handle)
    url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + m.group(1)
    print("YouTube", handle, "->", url)
    return feed_items(url, "YouTube", None, club, "Video")


NEXT, TABLES = {}, {}


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
        if not done and ts > NOW - timedelta(hours=2) and (c not in NEXT or ts.isoformat() < NEXT[c]["ts"]):
            NEXT[c] = {"club": c, "league": name, "home": t1, "away": t2, "ts": ts.isoformat(),
                          "hi": m["team1"].get("teamIconUrl") or "", "ai": m["team2"].get("teamIconUrl") or ""}
        res = [r for r in m.get("matchResults", []) if r.get("resultTypeID") == 2]
        if done and res and NOW - ts < timedelta(days=4):
            title, summ = f"{t1} {res[0]['pointsTeam1']}:{res[0]['pointsTeam2']} {t2}", "Endergebnis"
        elif not done and timedelta(0) < ts - NOW < timedelta(days=8):
            title, summ = f"{t1} gegen {t2}", "Anstoß " + ts.strftime("%d.%m. %H:%M UTC")
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
for fn, args in [(matches, ())] + [(feed_items, f) for f in FEEDS] + [(yt_items, y) for y in YOUTUBE]:
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
        items += [i for i in OLD["items"] if i["tag"] != "Spiel"
                  and NOW - datetime.fromisoformat(i["ts"]) < timedelta(days=30)]
except Exception as ex:
    print("Alte news.json nicht lesbar:", ex)

seen, final = set(), []
for i in sorted(items, key=lambda x: x["ts"], reverse=True):
    k = i["url"] or i["title"]
    if k not in seen:
        seen.add(k)
        final.append(i)
if final:
    vids = [i for i in final if i["tag"] == "Video"][:60]
    out = sorted(vids + [i for i in final if i["tag"] != "Video"][:400], key=lambda x: x["ts"], reverse=True)
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump({"updated": NOW.isoformat(), "items": out,
                   "next": sorted(NEXT.values(), key=lambda g: g["ts"]) or OLD.get("next", []),
                   "tables": {**OLD.get("tables", {}), **TABLES}}, f, ensure_ascii=False, indent=1)
