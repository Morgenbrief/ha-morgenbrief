"""Ablage im Add-on-Datenordner /data: Optionen, Google-Token, Briefe, Zustand."""
import json
import os
import tempfile
from datetime import date, timedelta

DATEN = os.environ.get("MORGENBRIEF_DATEN", "/data")
BRIEFE = os.path.join(DATEN, "briefe")
AUFBEWAHRUNG_TAGE = 7  # heute plus die sechs Tage davor

STANDARD = {
    "google_client_id": "",
    "google_client_secret": "",
    "gemini_api_key": "",
    "gemini_modell": "auto",
    "zeit_arbeitstage": "06:54",
    "zeit_freie_tage": "06:54",
    "zeit_abend": "19:00",
    "push_dienst": "mobile_app_mein_handy",
    "push_klick_pfad": "/app/local_morgenbrief",
    "weitere_eigene_adressen": [],
    "tomtom_api_key": "",
    "verkehr_start": "",
    "verkehr_ziel": "",
    "verkehr_ankunft": "07:25",
    "verkehr_schwelle_min": 3,
}


def _lesen(pfad, ersatz=None):
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return ersatz


def _schreiben(pfad, daten):
    """Atomar schreiben, damit ein Abbruch keine halbe Datei hinterlässt."""
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(pfad), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1)
    os.replace(tmp, pfad)


def optionen() -> dict:
    opt = dict(STANDARD)
    gelesen = _lesen(os.path.join(DATEN, "options.json"), {}) or {}
    for k, v in gelesen.items():
        if v is not None:
            opt[k] = v
    for k in ("google_client_id", "google_client_secret", "gemini_api_key", "tomtom_api_key"):
        opt[k] = (opt.get(k) or "").strip()
    # doppelt eingefügter Schlüssel (zweimal derselbe Text hintereinander): einmal verwenden
    s = opt["tomtom_api_key"]
    if len(s) >= 40 and len(s) % 2 == 0 and s[:len(s) // 2] == s[len(s) // 2:]:
        opt["tomtom_api_key"] = s[:len(s) // 2]
    return opt


def token_lesen():
    return _lesen(os.path.join(DATEN, "google_token.json"))


def token_schreiben(tok):
    _schreiben(os.path.join(DATEN, "google_token.json"), tok)


def token_loeschen():
    try:
        os.remove(os.path.join(DATEN, "google_token.json"))
    except OSError:
        pass


def anmeldung_offen_lesen():
    return _lesen(os.path.join(DATEN, "oauth_offen.json"))


def anmeldung_offen_schreiben(d):
    _schreiben(os.path.join(DATEN, "oauth_offen.json"), d)


def zustand_lesen() -> dict:
    return _lesen(os.path.join(DATEN, "zustand.json"), {}) or {}


def zustand_schreiben(z):
    _schreiben(os.path.join(DATEN, "zustand.json"), z)


ERLEDIGT_TAGE = 60  # seit 1.5.0: so lange merkt sich das Add-on, was im Brief erledigt wurde


def erledigt_lesen() -> dict:
    """Im Brief als erledigt oder bezahlt markierte Punkte (seit 1.5.0): {schluessel: {...}}."""
    daten = _lesen(os.path.join(DATEN, "erledigt.json"), {}) or {}
    return daten if isinstance(daten, dict) else {}


def erledigt_schreiben(daten: dict, heute: date):
    grenze = (heute - timedelta(days=ERLEDIGT_TAGE)).isoformat()
    _schreiben(os.path.join(DATEN, "erledigt.json"),
               {k: v for k, v in daten.items() if (v.get("datum") or "") >= grenze})


def brief_schreiben(brief: dict):
    _schreiben(os.path.join(BRIEFE, brief["datum"] + ".json"), brief)
    aufraeumen(date.fromisoformat(brief["datum"]))


def brief_lesen(tag: str):
    # nur ISO-Datum zulassen, damit kein fremder Pfad gelesen wird
    try:
        date.fromisoformat(tag)
    except ValueError:
        return None
    return _lesen(os.path.join(BRIEFE, tag + ".json"))


def brief_tage() -> list:
    try:
        namen = os.listdir(BRIEFE)
    except OSError:
        return []
    tage = []
    for n in namen:
        if n.endswith(".json"):
            try:
                date.fromisoformat(n[:-5])
                tage.append(n[:-5])
            except ValueError:
                pass
    return sorted(tage, reverse=True)


def aufraeumen(heute: date):
    """Briefe löschen, die älter sind als die Aufbewahrungsfrist."""
    grenze = heute - timedelta(days=AUFBEWAHRUNG_TAGE - 1)
    for tag in brief_tage():
        if date.fromisoformat(tag) < grenze:
            try:
                os.remove(os.path.join(BRIEFE, tag + ".json"))
            except OSError:
                pass
