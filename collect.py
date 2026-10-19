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
]
CLUBS = {"BVB": ["dortmund", "bvb"], "HSV": ["hsv", "hamburger sv"],
         "FCN": ["nürnberg", "nuernberg"], "SCW": ["weiche flensburg", "sc weiche"]}
LEAGUES = [("2. Bundesliga", "2. Bundesliga"), ("3. Liga", "3. Liga"), ("Regionalliga", "Regionalliga Nord"),
           ("Schleswig-Holstein-Liga", "SH-Liga"), ("Bundesliga", "Bundesliga"),
           ("LaLiga", "LaLiga"), ("La Liga", "LaLiga"), ("Premier League", "Premier League")]
OPENLIGA = [("bl1", "Bundesliga"), ("bl2", "2. Bundesliga"), ("bl3", "3. Liga")]
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
    if re.search(r"gerücht|interesse|offenbar|angeblich|soll .* wechseln|vor dem wechsel", s):
        return "Gerücht"
    if re.search(r"transfer|wechsel|verpflicht|leihe|ablöse|zugang|abgang|vertrag|unterschreibt", s):
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


def feed_items(url, source, league, club):
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
        out.append({"club": c, "league": l, "tag": tag_of(full),
                    "title": title, "summary": summ, "source": source, "url": child(e, "link"),
                    "ts": ts.isoformat()})
    return out


def matches():
    out = []
    season = NOW.year if NOW.month >= 7 else NOW.year - 1
    for short, name in OPENLIGA:
        for m in json.loads(get(f"https://api.openligadb.de/getmatchdata/{short}/{season}")):
            t1, t2 = m["team1"]["teamName"], m["team2"]["teamName"]
            c = club_of(t1) or club_of(t2)
            if not c:
                continue
            ts = datetime.fromisoformat(m["matchDateTimeUTC"].replace("Z", "+00:00"))
            res = [r for r in m.get("matchResults", []) if r.get("resultTypeID") == 2]
            if m.get("matchIsFinished") and res and NOW - ts < timedelta(days=4):
                title, summ = f"{t1} {res[0]['pointsTeam1']}:{res[0]['pointsTeam2']} {t2}", "Endergebnis"
            elif not m.get("matchIsFinished") and timedelta(0) < ts - NOW < timedelta(days=8):
                title, summ = f"{t1} gegen {t2}", "Anstoß " + ts.astimezone().strftime("%d.%m. %H:%M UTC")
            else:
                continue
            out.append({"club": c, "league": name, "tag": "Spiel", "title": title, "summary": summ,
                        "source": "OpenLigaDB", "url": "", "ts": ts.isoformat()})
    return out


items = []
for fn, args in [(matches, ())] + [(feed_items, f) for f in FEEDS]:
    try:
        got = fn(*args)
        print("OK ", args[0] if args else "OpenLigaDB", len(got))
        items += got
    except Exception as ex:
        print("FEHLER", args[0] if args else "OpenLigaDB", ex)

seen, final = set(), []
for i in sorted(items, key=lambda x: x["ts"], reverse=True):
    k = i["url"] or i["title"]
    if k not in seen:
        seen.add(k)
        final.append(i)
if final:
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump({"updated": NOW.isoformat(), "items": final[:150]}, f, ensure_ascii=False, indent=1)
