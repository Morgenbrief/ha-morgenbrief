"""Google-Zugang: Anmeldung (OAuth), Gmail und Kalender über die REST-Schnittstellen.

Gmail und deine Kalender werden nur gelesen. Seit 1.5.0 schreibt das Add-on in genau einen Kalender, den es
selbst anlegt: "Morgenbrief-Ablage". Dort steht, was du im Brief als erledigt oder bezahlt markiert hast, damit
die nächtliche Claude-Aufgabe es im To-do-Doc abhakt. Die Berechtigung calendar.app.created erlaubt nur Kalender,
die das Add-on selbst angelegt hat, an deine eigenen Termine kommt es damit nicht heran.
"""
import base64
import hashlib
import json
import secrets
import time
from datetime import timedelta
import urllib.error
import urllib.parse
import urllib.request

import speicher

SCOPES = ("https://www.googleapis.com/auth/gmail.readonly "
          "https://www.googleapis.com/auth/calendar.readonly "
          "https://www.googleapis.com/auth/calendar.app.created")  # seit 1.5.0: nur selbst angelegte Kalender
ABLAGE_NAME = "Morgenbrief-Ablage"
ABLAGE_PRAEFIX = "Erledigt im Morgenbrief: "
# Loopback-Adresse für Desktop-Clients. Dort läuft nichts, die Seite bleibt leer,
# der Code steht dann in der Adresszeile und wird von Hand übernommen.
REDIRECT = "http://127.0.0.1:8765/"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
KALENDER = "https://www.googleapis.com/calendar/v3"
_EIN_TAG = timedelta(days=1)


class GoogleFehler(Exception):
    """art: 'anmeldung' (neu verbinden nötig), 'netz' (nicht erreichbar), 'api' (Antwortfehler)."""

    def __init__(self, art, text):
        super().__init__(text)
        self.art = art


def _abruf(url, daten=None, kopf=None, timeout=30):
    req = urllib.request.Request(url, data=daten, headers=kopf or {},
                                 method="POST" if daten is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GoogleFehler("netz", f"Google nicht erreichbar ({e})") from e


# ---------------------------------------------------------------- Anmeldung

def anmeldung_starten(client_id: str) -> str:
    """Erzeugt die Google-Adresse für die Zustimmung und merkt sich Prüfwerte."""
    offen = speicher.anmeldung_offen_lesen() or {}
    if offen.get("state") and time.time() - offen.get("zeit", 0) < 900:
        # eine gerade begonnene Anmeldung weiterverwenden, damit ein Neuladen der Seite sie nicht entwertet
        verifier, state = offen["verifier"], offen["state"]
    else:
        verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(24)
        speicher.anmeldung_offen_schreiben({"state": state, "verifier": verifier, "zeit": time.time()})
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


def anmeldung_abschliessen(opt: dict, eingabe: str):
    """Nimmt die kopierte Adresse (oder nur den Code) und tauscht sie gegen den Zugang."""
    offen = speicher.anmeldung_offen_lesen()
    if not offen:
        raise GoogleFehler("anmeldung", "Keine offene Anmeldung. Bitte zuerst auf 'Mit Google verbinden' klicken.")
    eingabe = eingabe.strip()
    code = eingabe
    if "code=" in eingabe:
        teile = urllib.parse.urlparse(eingabe)
        q = urllib.parse.parse_qs(teile.query)
        if "error" in q:
            raise GoogleFehler("anmeldung", "Google hat die Anmeldung abgelehnt: " + q["error"][0])
        code = (q.get("code") or [""])[0]
        if (q.get("state") or [""])[0] != offen["state"]:
            raise GoogleFehler("anmeldung", "Die Adresse passt nicht zur gestarteten Anmeldung. Bitte neu beginnen.")
    if not code:
        raise GoogleFehler("anmeldung", "In der Eingabe steht kein Code.")
    status, body = _abruf(TOKEN_URL, urllib.parse.urlencode({
        "client_id": opt["google_client_id"],
        "client_secret": opt["google_client_secret"],
        "code": code,
        "code_verifier": offen["verifier"],
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT,
    }).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
    antwort = _json(body)
    if status != 200 or "refresh_token" not in antwort:
        raise GoogleFehler("anmeldung", "Tausch des Codes fehlgeschlagen: "
                           + str(antwort.get("error_description") or antwort.get("error") or status))
    speicher.token_schreiben({
        "refresh_token": antwort["refresh_token"],
        "access_token": antwort.get("access_token", ""),
        "ablauf": time.time() + int(antwort.get("expires_in", 0)) - 60,
        "verbunden_am": time.time(),
        "scope": antwort.get("scope", ""),  # seit 1.5.0, zeigt, ob die Ablage erlaubt ist
    })
    speicher.anmeldung_offen_schreiben({})


def _json(body):
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return {}


def _zugang(opt: dict, erzwingen=False) -> str:
    tok = speicher.token_lesen()
    if not tok or not tok.get("refresh_token"):
        raise GoogleFehler("anmeldung", "Google ist noch nicht verbunden.")
    if not erzwingen and tok.get("access_token") and tok.get("ablauf", 0) > time.time():
        return tok["access_token"]
    status, body = _abruf(TOKEN_URL, urllib.parse.urlencode({
        "client_id": opt["google_client_id"],
        "client_secret": opt["google_client_secret"],
        "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token",
    }).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
    antwort = _json(body)
    if status == 200 and antwort.get("access_token"):
        tok["access_token"] = antwort["access_token"]
        tok["ablauf"] = time.time() + int(antwort.get("expires_in", 0)) - 60
        speicher.token_schreiben(tok)
        return tok["access_token"]
    fehler = antwort.get("error", "")
    if fehler in ("invalid_grant", "invalid_client", "unauthorized_client"):
        raise GoogleFehler("anmeldung", "Die Google-Anmeldung ist abgelaufen oder widerrufen ("
                           + fehler + "). Bitte auf der Morgenbrief-Seite neu verbinden.")
    raise GoogleFehler("api", f"Google-Anmeldung antwortet mit Fehler {status} {fehler}")


def _get(opt: dict, url: str, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    for versuch in (1, 2):
        status, body = _abruf(url, kopf={"Authorization": "Bearer " + _zugang(opt, erzwingen=versuch == 2)})
        if status == 200:
            return _json(body)
        if status == 401 and versuch == 1:
            continue
        meldung = (_json(body).get("error") or {})
        text = meldung.get("message") if isinstance(meldung, dict) else str(meldung)
        raise GoogleFehler("api", f"Google antwortet mit Fehler {status}: {text or 'ohne Text'}")


# -------------------------------------------------------------------- Gmail

def gmail_profil(opt) -> str:
    return _get(opt, GMAIL + "/profile").get("emailAddress", "")


def gmail_absenderadressen(opt) -> list:
    """Alle Adressen, mit denen aus dem Konto gesendet wird (für 'eigene Adressen')."""
    try:
        daten = _get(opt, GMAIL + "/settings/sendAs")
    except GoogleFehler as e:
        if e.art == "api":
            return []
        raise
    return [s.get("sendAsEmail", "") for s in daten.get("sendAs", []) if s.get("sendAsEmail")]


def gmail_threads(opt, suche: str, hoechstens: int) -> list:
    daten = _get(opt, GMAIL + "/threads", {"q": suche, "maxResults": hoechstens})
    return [t["id"] for t in daten.get("threads", [])]


KOPFZEILEN = ["From", "To", "Cc", "Subject", "Date", "Auto-Submitted", "Precedence",
              "X-Autoreply", "X-Autorespond", "X-Auto-Response-Suppress", "List-Unsubscribe"]


def gmail_thread(opt, thread_id: str, voll: bool) -> dict:
    params = {"format": "full"} if voll else {"format": "metadata", "metadataHeaders": KOPFZEILEN}
    return _get(opt, GMAIL + "/threads/" + urllib.parse.quote(thread_id), params)


# ----------------------------------------------------------------- Kalender

def kalender_liste(opt) -> list:
    ergebnis, seite = [], None
    while True:
        params = {"maxResults": 250}
        if seite:
            params["pageToken"] = seite
        daten = _get(opt, KALENDER + "/users/me/calendarList", params)
        ergebnis += daten.get("items", [])
        seite = daten.get("nextPageToken")
        if not seite:
            return ergebnis


def kalender_termine(opt, kalender_id: str, von_iso: str, bis_iso: str) -> list:
    ergebnis, seite = [], None
    while True:
        params = {"timeMin": von_iso, "timeMax": bis_iso, "singleEvents": "true",
                  "orderBy": "startTime", "maxResults": 250, "timeZone": "Europe/Berlin"}
        if seite:
            params["pageToken"] = seite
        daten = _get(opt, KALENDER + "/calendars/" + urllib.parse.quote(kalender_id, safe="") + "/events", params)
        ergebnis += daten.get("items", [])
        seite = daten.get("nextPageToken")
        if not seite:
            return ergebnis


def _senden(opt: dict, methode: str, url: str, daten=None):
    """Schreibender Aufruf (seit 1.5.0), nur für den Ablage-Kalender."""
    koerper = json.dumps(daten).encode("utf-8") if daten is not None else None
    for versuch in (1, 2):
        req = urllib.request.Request(url, data=koerper, method=methode, headers={
            "Authorization": "Bearer " + _zugang(opt, erzwingen=versuch == 2), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return _json(r.read())
        except urllib.error.HTTPError as e:
            body = e.read()
            if e.code == 401 and versuch == 1:
                continue
            if e.code in (404, 410) and methode == "DELETE":
                return {}  # schon weg
            meldung = (_json(body).get("error") or {})
            text = meldung.get("message") if isinstance(meldung, dict) else str(meldung)
            art = "recht" if e.code == 403 else "api"
            raise GoogleFehler(art, f"Google antwortet mit Fehler {e.code}: {text or 'ohne Text'}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise GoogleFehler("netz", f"Google nicht erreichbar ({e})") from e


def ablage_kalender(opt) -> str:
    """ID des Kalenders "Morgenbrief-Ablage", legt ihn beim ersten Mal an (seit 1.5.0)."""
    for k in kalender_liste(opt):
        if (k.get("summary") or "") == ABLAGE_NAME:
            return k["id"]
    neu = _senden(opt, "POST", KALENDER + "/calendars", {
        "summary": ABLAGE_NAME, "timeZone": "Europe/Berlin",
        "description": "Vom Morgenbrief-Add-on angelegt. Was im Brief als erledigt oder bezahlt markiert wird, "
                       "steht hier, damit die nächtliche Aufräumaufgabe es im To-do-Doc abhakt. Nicht löschen."})
    return neu["id"]


def ablage_eintragen(opt, kalender_id: str, titel: str, beschreibung: str, tag) -> str:
    """Ganztägiger Eintrag "Erledigt im Morgenbrief: <Titel>" im Ablage-Kalender, liefert seine ID."""
    ev = _senden(opt, "POST", KALENDER + "/calendars/" + urllib.parse.quote(kalender_id, safe="") + "/events", {
        "summary": ABLAGE_PRAEFIX + titel[:120], "description": beschreibung, "transparency": "transparent",
        "start": {"date": tag.isoformat()}, "end": {"date": (tag + _EIN_TAG).isoformat()}})
    return ev.get("id", "")


def ablage_loeschen(opt, kalender_id: str, event_id: str):
    _senden(opt, "DELETE", KALENDER + "/calendars/" + urllib.parse.quote(kalender_id, safe="") + "/events/"
            + urllib.parse.quote(event_id, safe=""))


def kalender_suche(opt, kalender_id: str, text: str) -> list:
    """Termine mit diesem Text, ohne Zeitraum (für den Herzschlag-Eintrag)."""
    daten = _get(opt, KALENDER + "/calendars/" + urllib.parse.quote(kalender_id, safe="") + "/events",
                 {"q": text, "maxResults": 5, "singleEvents": "true"})
    return daten.get("items", [])
