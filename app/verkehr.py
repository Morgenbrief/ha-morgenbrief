"""Abfahrtszeit mit Verkehr und Störungen auf dem Arbeitsweg (TomTom, seit 1.3.6), seit 1.5.0 auch Fahrten.

Pro Arbeitstag zwei bis drei Abfragen: Routing mit dem erwarteten Verkehr zur Abfahrtszeit und Verkehrsmeldungen
im Umkreis der Strecke, dazu eine Nachprüfung kurz vor der Abfahrt. Eine Fahrt kostet bis zu zehn Abfragen
(beste Abfahrt im Zeitfenster). Das TomTom-Freikontingent liegt weit darüber.
Adressen werden einmal in Koordinaten umgerechnet und mit der normalen Strecke (ohne Verkehr)
im Datenordner gemerkt. Der Schlüssel erscheint nie im Protokoll.
"""
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

BASIS = "https://api.tomtom.com"
ZEITLIMIT = 20
CACHE_TAGE = 30            # so lange gilt die gemerkte normale Strecke
NAH_METER = 60             # so nah muss eine Meldung an der Strecke liegen
RAND_GRAD = 0.01           # Rand um die Strecke für die Meldungsabfrage (ca. 1 km)
MAX_MELDUNGEN = 2
SPERRUNG = 8               # TomTom iconCategory "Road Closed"
STOERUNG_KATEGORIEN = {1, 3, 6, 7, 8, 9, 14}  # Unfall, Gefahr, Stau, Fahrstreifen zu, Sperrung, Baustelle, Panne
FELDER = ("{incidents{type,geometry{type,coordinates},properties{iconCategory,magnitudeOfDelay,"
          "events{description,code,iconCategory},from,to,length,delay,roadNumbers}}}")


class VerkehrFehler(Exception):
    pass


def _holen(pfad: str, parameter: dict) -> dict:
    url = BASIS + pfad + "?" + urllib.parse.urlencode(parameter)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}),
                                    timeout=ZEITLIMIT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:      # Meldung ohne URL, damit der Schlüssel nicht ins Protokoll kommt
        if e.code in (401, 403):
            raise VerkehrFehler(f"TomTom lehnt den Schlüssel ab ({e.code}). Sind Routing, Traffic und "
                                "Search am Schlüssel aktiv?") from None
        if e.code == 429:
            raise VerkehrFehler("TomTom-Tageslimit erreicht (429)") from None
        raise VerkehrFehler(f"TomTom antwortet mit {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise VerkehrFehler(f"TomTom nicht erreichbar ({type(e).__name__})") from None


# --------------------------------------------------------------- Orte, Strecke

def ort(schluessel: str, adresse: str, laender: str = "DE"):
    """'48.14,11.58' direkt, sonst Adresse über die TomTom-Suche (Arbeitsweg: Deutschland, Fahrten: mehr Länder)."""
    teile = [t.strip() for t in adresse.split(",")]
    if len(teile) == 2:
        try:
            lat, lon = float(teile[0]), float(teile[1])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
        except ValueError:
            pass
    daten = _holen("/search/2/geocode/" + urllib.parse.quote(adresse) + ".json",
                   {"key": schluessel, "countrySet": laender, "limit": 1, "language": "de-DE"})
    treffer = daten.get("results") or []
    if not treffer:
        raise VerkehrFehler(f"Adresse nicht gefunden: {adresse}")
    pos = treffer[0]["position"]
    return pos["lat"], pos["lon"]


def strecke(schluessel: str, start, ziel, mit_verkehr: bool, abfahrt: datetime = None, strassen: bool = False) -> dict:
    """Route. abfahrt (seit 1.5.0): Abfahrt in der Zukunft, TomTom rechnet dann mit dem erwarteten Verkehr.
    strassen: Straßennummern der Strecke mitliefern ("A8", "B123")."""
    orte = f"{start[0]},{start[1]}:{ziel[0]},{ziel[1]}"
    parameter = {"key": schluessel, "travelMode": "car", "routeType": "fastest",
                 "traffic": "true" if mit_verkehr else "false", "language": "de-DE"}
    if mit_verkehr:
        parameter["computeTravelTimeFor"] = "all"
    if abfahrt is not None:
        parameter["departAt"] = abfahrt.isoformat(timespec="seconds")
    if strassen:
        parameter["instructionsType"] = "coded"
    daten = _holen(f"/routing/1/calculateRoute/{orte}/json", parameter)
    try:
        route = daten["routes"][0]
    except (KeyError, IndexError):
        raise VerkehrFehler("TomTom liefert keine Strecke") from None
    summe = route.get("summary", {})
    punkte = [(p["latitude"], p["longitude"]) for leg in route.get("legs", []) for p in leg.get("points", [])]
    nummern = []
    for anweisung in (route.get("guidance") or {}).get("instructions") or []:
        for n in anweisung.get("roadNumbers") or []:
            if n and n not in nummern:
                nummern.append(n)
    return {
        "sekunden": int(summe.get("travelTimeInSeconds", 0)),
        "frei_sekunden": int(summe.get("noTrafficTravelTimeInSeconds") or summe.get("travelTimeInSeconds", 0)),
        "verzoegerung": int(summe.get("trafficDelayInSeconds", 0)),
        "meter": int(summe.get("lengthInMeters", 0)),
        "punkte": punkte,
        "strassen": nummern[:3],
    }


def normale_strecke(opt: dict, cache_pfad: str, jetzt: datetime) -> dict:
    """Koordinaten und Strecke ohne Verkehr, gemerkt bis die Adressen sich ändern oder CACHE_TAGE vorbei sind."""
    kennung = opt["verkehr_start"].strip() + " | " + opt["verkehr_ziel"].strip()
    try:
        with open(cache_pfad, encoding="utf-8") as f:
            cache = json.load(f)
        if cache.get("kennung") == kennung and \
                jetzt - datetime.fromisoformat(cache["stand"]) < timedelta(days=CACHE_TAGE):
            return cache
    except (OSError, ValueError, KeyError, TypeError):
        pass
    schluessel = opt["tomtom_api_key"]
    start = ort(schluessel, opt["verkehr_start"])
    ziel = ort(schluessel, opt["verkehr_ziel"])
    s = strecke(schluessel, start, ziel, mit_verkehr=False)
    cache = {"kennung": kennung, "stand": jetzt.isoformat(timespec="minutes"), "start": list(start),
             "ziel": list(ziel), "frei_sekunden": s["frei_sekunden"] or s["sekunden"], "meter": s["meter"],
             "punkte": [list(p) for p in s["punkte"]]}
    os.makedirs(os.path.dirname(cache_pfad) or ".", exist_ok=True)
    tmp = cache_pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, cache_pfad)
    return cache


# --------------------------------------------------------------- Meldungen

def _abstand(a, b) -> float:
    """Meter zwischen zwei (lat, lon), für kurze Strecken genau genug."""
    x = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    y = math.radians(b[0] - a[0])
    return 6371000 * math.hypot(x, y)


def _auf_strecke(geometrie: dict, punkte: list) -> bool:
    """Mindestens zwei Punkte der Meldung (bei einem Punkt: dieser) liegen nahe an der Strecke.
    Zwei Punkte, damit eine kreuzende Straße nicht zählt."""
    art = (geometrie or {}).get("type")
    koord = (geometrie or {}).get("coordinates") or []
    if art == "Point":
        koord = [koord]
    elif art != "LineString":
        return False
    nah = 0
    for lon, lat, *_ in koord:
        if any(_abstand((lat, lon), p) <= NAH_METER for p in punkte):
            nah += 1
            if nah >= 2 or len(koord) == 1:
                return True
    return False


def _bbox(punkte: list) -> str:
    lats = [p[0] for p in punkte]
    lons = [p[1] for p in punkte]
    return (f"{min(lons) - RAND_GRAD:.5f},{min(lats) - RAND_GRAD:.5f},"
            f"{max(lons) + RAND_GRAD:.5f},{max(lats) + RAND_GRAD:.5f}")


def meldungen(schluessel: str, punkte: list) -> list:
    daten = _holen("/traffic/services/5/incidentDetails",
                   {"key": schluessel, "bbox": _bbox(punkte), "fields": FELDER,
                    "language": "de-DE", "timeValidityFilter": "present"})
    ergebnis = []
    for inc in daten.get("incidents") or []:
        p = inc.get("properties") or {}
        kategorie = p.get("iconCategory")
        if kategorie not in STOERUNG_KATEGORIEN or not _auf_strecke(inc.get("geometry"), punkte):
            continue
        beschreibung = ", ".join(dict.fromkeys(
            (ev.get("description") or "").strip() for ev in p.get("events") or [] if ev.get("description")))
        ergebnis.append({
            "kategorie": kategorie,
            "strasse": ", ".join(p.get("roadNumbers") or []),
            "von": (p.get("from") or "").strip(), "nach": (p.get("to") or "").strip(),
            "beschreibung": beschreibung,
            "verzoegerung": int(p.get("delay") or 0),
        })
    # Sperrungen zuerst, dann nach Verzögerung
    ergebnis.sort(key=lambda m: (m["kategorie"] != SPERRUNG, -m["verzoegerung"]))
    return ergebnis


def meldung_text(m: dict) -> str:
    """'B123 bei Musterdorf gesperrt' bzw. 'B123 zwischen Musterdorf und Musterstadt: Stau'"""
    ort_text = ""
    if m["von"] and m["nach"] and m["von"] != m["nach"]:
        ort_text = f"zwischen {m['von']} und {m['nach']}"
    elif m["von"] or m["nach"]:
        ort_text = f"bei {m['von'] or m['nach']}"
    kopf = " ".join(t for t in (m["strasse"], ort_text) if t) or "Auf der Strecke"
    if m["kategorie"] == SPERRUNG and (not m["beschreibung"] or m["beschreibung"].casefold() == "gesperrt"):
        return f"{kopf} gesperrt"
    return f"{kopf}: {m['beschreibung'] or 'Störung'}"


# --------------------------------------------------------------- Auswertung

def _uhr(zeit: datetime) -> str:
    return f"{zeit.hour}:{zeit:%M}"


def ankunft(opt: dict, tag, tz) -> datetime:
    stunde, minute = (int(x) for x in (opt.get("verkehr_ankunft") or "07:25").split(":"))
    return datetime(tag.year, tag.month, tag.day, stunde, minute, tzinfo=tz)


def auswerten(cache: dict, live: dict, liste: list, ziel_zeit: datetime, schwelle_min: int) -> dict:
    """Abfahrtszeit, Mehrzeit gegenüber der freien normalen Strecke und ob eine Störung vorliegt."""
    fahrt_min = math.ceil(live["sekunden"] / 60)
    extra_min = max(0, round((live["sekunden"] - cache["frei_sekunden"]) / 60))
    los = ziel_zeit - timedelta(minutes=fahrt_min)
    gesperrt = any(m["kategorie"] == SPERRUNG for m in liste)
    stoerung = extra_min >= schwelle_min or gesperrt
    return {
        "losfahren": los.strftime("%H:%M"),
        "fahrt_min": fahrt_min,
        "extra_min": extra_min,
        "stoerung": stoerung,
        "gesperrt": gesperrt,
        "meldungen": [meldung_text(m) for m in liste[:MAX_MELDUNGEN]] if stoerung else [],
        "zeile": f"Losfahren bis {_uhr(los)} ({fahrt_min} Min. Fahrt)",
        "ankunft": _uhr(ziel_zeit),
    }


def los_fuer_ankunft(schluessel: str, start, ziel, ankunft_zeit: datetime, jetzt: datetime, frei_sekunden: int):
    """Abfahrt für eine Ankunftszeit mit dem erwarteten Verkehr zur Abfahrtszeit (seit 1.5.0).

    Erst mit der freien Fahrzeit schätzen, dann mit departAt nachrechnen (höchstens zwei Abfragen). Liegt die
    Abfahrt schon fast jetzt, zählt der Verkehr von jetzt. Liefert (abfahrt, route, abfragen)."""
    los = ankunft_zeit - timedelta(seconds=frei_sekunden)
    route, abfragen = None, 0
    for _ in range(2):
        zukunft = los > jetzt + timedelta(minutes=5)
        route = strecke(schluessel, start, ziel, True, abfahrt=los if zukunft else None)
        abfragen += 1
        neu = ankunft_zeit - timedelta(seconds=route["sekunden"])
        if not zukunft or abs((neu - los).total_seconds()) <= 120:
            los = neu
            break
        los = neu
    return los, route, abfragen


def abfahrt(opt: dict, jetzt: datetime, cache_pfad: str, live: bool = False) -> dict:
    """Ganzer Ablauf für den Brief. Wirft VerkehrFehler, wenn TomTom nicht hilft.

    Seit 1.5.0 mit dem erwarteten Verkehr zur Abfahrtszeit (der Brief läuft um 5:55, losgefahren wird um 7:15).
    live=True für die Nachprüfung kurz vor der Abfahrt: Verkehr von jetzt."""
    schluessel = opt["tomtom_api_key"]
    cache = normale_strecke(opt, cache_pfad, jetzt)
    start, ziel = tuple(cache["start"]), tuple(cache["ziel"])
    ziel_zeit = ankunft(opt, jetzt.date(), jetzt.tzinfo)
    route, prognose = None, False
    if not live and ziel_zeit - timedelta(seconds=cache["frei_sekunden"]) > jetzt + timedelta(minutes=5):
        try:
            _, route, _ = los_fuer_ankunft(schluessel, start, ziel, ziel_zeit, jetzt, cache["frei_sekunden"])
            prognose = True
        except VerkehrFehler:
            route = None                 # Prognose abgelehnt: Verkehr von jetzt
    if route is None:
        route = strecke(schluessel, start, ziel, mit_verkehr=True)
    punkte = [tuple(p) for p in cache["punkte"]] or route["punkte"]
    try:
        liste = meldungen(schluessel, punkte)
    except VerkehrFehler:
        liste = []                       # ohne Meldungen bleibt die Abfahrtszeit trotzdem richtig
    ergebnis = auswerten(cache, route, liste, ziel_zeit, int(opt.get("verkehr_schwelle_min") or 3))
    ergebnis["stand"] = jetzt.strftime("%H:%M")
    ergebnis["prognose"] = prognose
    return ergebnis


# --------------------------------------------------------------- Fahrten (seit 1.5.0)

FAHRT_LAENDER = "DE,AT,CH,IT"
FENSTER_MIN = 60          # "Fahrt nach München" um 11:00: beste Abfahrt zwischen 10:00 und 12:00
SCHRITT_MIN = 15
PUFFER_MIN = 5            # bei Terminen mit Ort: so viele Minuten vorher ankommen
ALTERNATIVEN_MIN = (-30, -15, 15, 30, 45, 60)  # seit 1.6.0: so viel früher oder später wird zum Vergleich gerechnet
SPAREN_MIN = 10           # seit 1.6.0: so viel muss eine andere Abfahrt sparen, damit der Brief sie nennt
ORTE_HOECHSTENS = 100


def uhr(zeit: datetime) -> str:
    return _uhr(zeit)


def karten_link(pos) -> str:
    return (f"https://www.google.com/maps/dir/?api=1&destination={pos[0]:.5f},{pos[1]:.5f}"
            "&travelmode=driving")


def ziel_ort(opt: dict, cache_pfad: str, text: str):
    """Koordinaten eines Fahrtziels, einmal gesucht und in orte.json im Datenordner gemerkt."""
    pfad = os.path.join(os.path.dirname(cache_pfad) or ".", "orte.json")
    try:
        with open(pfad, encoding="utf-8") as f:
            orte = json.load(f)
    except (OSError, ValueError):
        orte = {}
    schluessel_text = " ".join(text.split()).casefold()
    if schluessel_text in orte:
        return tuple(orte[schluessel_text]), 0
    pos = ort(opt["tomtom_api_key"], text, FAHRT_LAENDER)
    orte[schluessel_text] = list(pos)
    orte = dict(list(orte.items())[-ORTE_HOECHSTENS:])
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(orte, f, ensure_ascii=False)
    os.replace(tmp, pfad)
    return pos, 1


def fahrt_planen(opt: dict, cache_pfad: str, jetzt: datetime, ziel_text: str, wunsch: datetime, modus: str) -> dict:
    """modus "fenster": beste Abfahrt zwischen wunsch minus und plus FENSTER_MIN (alle SCHRITT_MIN Minuten,
    erwarteter Verkehr). modus "ankunft": spätestens losfahren, um PUFFER_MIN vor wunsch da zu sein."""
    schluessel = opt["tomtom_api_key"]
    cache = normale_strecke(opt, cache_pfad, jetzt)
    start = tuple(cache["start"])
    ziel, abfragen = ziel_ort(opt, cache_pfad, ziel_text)
    if modus == "fahrt":
        # seit 1.6.0: der Termin ist die Fahrt, Abfahrt ist sein Beginn. Andere Zeiten nur als Hinweis,
        # wenn sie mindestens SPAREN_MIN Minuten sparen
        los = max(wunsch, jetzt + timedelta(minutes=5))
        zeiten = [los] + [wunsch + timedelta(minutes=m) for m in ALTERNATIVEN_MIN]
        zeiten = [z for nr, z in enumerate(zeiten) if nr == 0 or (z > jetzt + timedelta(minutes=5) and z != los)]
        ergebnisse = []
        for nr, z in enumerate(zeiten):
            ergebnisse.append((z, strecke(schluessel, start, ziel, True, abfahrt=z, strassen=nr == 0)))
            abfragen += 1
        haupt = ergebnisse[0][1]
        fahrt_min = math.ceil(haupt["sekunden"] / 60)
        alternative = None
        if len(ergebnisse) > 1:
            z, r = min(ergebnisse[1:], key=lambda x: (x[1]["sekunden"], abs((x[0] - wunsch).total_seconds())))
            if math.ceil(r["sekunden"] / 60) <= fahrt_min - SPAREN_MIN:
                alternative = {"losfahren": z, "fahrt_min": math.ceil(r["sekunden"] / 60)}
        return {"losfahren": los, "fahrt_min": fahrt_min, "wunsch_min": None, "alternative": alternative,
                "strassen": haupt.get("strassen", []), "ziel_pos": ziel, "abfragen": abfragen}
    if modus == "fenster":
        zeiten = [wunsch + timedelta(minutes=m) for m in range(-FENSTER_MIN, FENSTER_MIN + 1, SCHRITT_MIN)]
        zeiten = [z for z in zeiten if z > jetzt + timedelta(minutes=5)] or [jetzt + timedelta(minutes=5)]
        ergebnisse = []
        for nr, z in enumerate(zeiten):
            ergebnisse.append((z, strecke(schluessel, start, ziel, True, abfahrt=z, strassen=nr == 0)))
            abfragen += 1
        beste_z, beste = min(ergebnisse, key=lambda x: (x[1]["sekunden"], abs((x[0] - wunsch).total_seconds())))
        zur_wunschzeit = next((r for z, r in ergebnisse if z == wunsch), None)
        return {"losfahren": beste_z, "fahrt_min": math.ceil(beste["sekunden"] / 60),
                "wunsch_min": math.ceil(zur_wunschzeit["sekunden"] / 60) if zur_wunschzeit else None,
                "strassen": ergebnisse[0][1].get("strassen", []), "ziel_pos": ziel, "abfragen": abfragen}
    frei = strecke(schluessel, start, ziel, False, strassen=True)
    los, route, n = los_fuer_ankunft(schluessel, start, ziel, wunsch - timedelta(minutes=PUFFER_MIN), jetzt,
                                     frei["frei_sekunden"])
    return {"losfahren": los, "fahrt_min": math.ceil(route["sekunden"] / 60), "wunsch_min": None,
            "strassen": frei.get("strassen", []), "ziel_pos": ziel, "abfragen": abfragen + 1 + n}


def fahrt_live(opt: dict, cache_pfad: str, ziel_pos, jetzt: datetime) -> int:
    """Fahrzeit in Minuten mit dem Verkehr von jetzt (für den Push kurz vor der Abfahrt)."""
    cache = normale_strecke(opt, cache_pfad, jetzt)
    r = strecke(opt["tomtom_api_key"], tuple(cache["start"]), tuple(ziel_pos), True)
    return math.ceil(r["sekunden"] / 60)


def braucht_eintrag(v: dict) -> dict:
    """Eintrag unter 'Braucht dich', z. B. 'B123 bei Musterdorf gesperrt, +12 Min.'"""
    plus = f", +{v['extra_min']} Min." if v["extra_min"] else ""
    if v["meldungen"]:
        titel = v["meldungen"][0] + plus
        weitere = v["meldungen"][1:]
    else:
        titel = f"Stau auf dem Weg zur Arbeit{plus}"
        weitere = []
    satz = " ".join([m + "." for m in weitere] + [v["zeile"] + f", Ankunft {v['ankunft']}."])
    return {"titel": titel, "quelle": f"Verkehr, TomTom um {v['stand']}.", "satz": satz, "link": "",
            "art": "verkehr"}


def push_zusatz(v: dict) -> str:
    if not v or not v.get("stoerung"):
        return ""
    if v["extra_min"]:
        return f"Stau +{v['extra_min']} Min."
    return "Sperrung auf dem Weg"
