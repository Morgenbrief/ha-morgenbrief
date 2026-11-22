"""Morgenbrief: Webseite (über Home-Assistant-Ingress), Zeitplan und Push."""
import json
import os
import signal
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import brief as briefbau
import gedaechtnis
import gemini
import google_api as g
import seite
import speicher
import verkehr as verkehr_mod
from brief import TZ

VERKEHR_PFAD = os.path.join(speicher.DATEN, "verkehr.json")
VORLAUF_MIN = 20  # seit 1.5.0: so lange vor der Abfahrt Arbeitsweg nachprüfen bzw. an eine Fahrt erinnern

PORT = 8099
INGRESS_IP = "172.30.32.2"           # nur der Ingress-Dienst von Home Assistant darf zugreifen
TEST = os.environ.get("MORGENBRIEF_TEST") == "1"
NACHHOLEN_STUNDEN = 4                 # nach einem Neustart wird ein verpasster Brief so lange nachgeholt
WARTEZEIT_GOOGLE = int(os.environ.get("MORGENBRIEF_WARTEZEIT", "300"))  # Sekunden zwischen den Versuchen

_sperre = threading.Lock()
_lauf = {"laeuft": False, "fehler": ""}


def log(text):
    print(f"[{datetime.now(TZ):%d.%m. %H:%M:%S}] {text}", flush=True)


briefbau.melde = log
briefbau.wetter.melde = log


# ---------------------------------------------------------------------- Push

PUSH_VERSUCHE = 3        # seit 1.4.0: nimmt Home Assistant den Push nicht an, später noch einmal
PUSH_PAUSE = int(os.environ.get("MORGENBRIEF_PUSH_PAUSE", "120"))  # Sekunden zwischen den Versuchen


def push(opt: dict, text: str, versuche: int = PUSH_VERSUCHE, titel: str = "Morgenbrief", tag: str = "morgenbrief",
         protokoll: str = "") -> bool:
    """protokoll (seit 1.5.0): was ins Protokoll kommt. Der Push kann Titel enthalten, das Protokoll nie."""
    for nr in range(1, versuche + 1):
        if _push_einmal(opt, text, titel, tag, protokoll or text):
            return True
        if nr < versuche:
            log(f"Push-Versuch {nr} von {versuche} fehlgeschlagen, nächster in {PUSH_PAUSE} s")
            time.sleep(PUSH_PAUSE)
    return False


def _push_einmal(opt: dict, text: str, titel: str = "Morgenbrief", tag: str = "morgenbrief",
                 protokoll: str = "") -> bool:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        log("Push übersprungen: kein SUPERVISOR_TOKEN (läuft das Add-on in Home Assistant?)")
        return False
    daten = json.dumps({
        "title": titel,
        "message": text,
        "data": {"clickAction": opt["push_klick_pfad"], "tag": tag, "channel": "Morgenbrief",
                 "notification_icon": "mdi:weather-sunset-up"},
    }).encode("utf-8")
    req = urllib.request.Request(
        "http://supervisor/core/api/services/notify/" + urllib.parse.quote(opt["push_dienst"]),
        data=daten, method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            log(f"Push gesendet ({r.status}): {protokoll or text}")
            return True
    except (urllib.error.URLError, OSError) as e:
        log(f"Push fehlgeschlagen: {e}")
        return False


# ----------------------------------------------------------------- Brieflauf

def lauf(geplant: bool, mit_push: bool):
    """Erzeugt den Brief. Geplante Läufe versuchen es bei Google-Ausfall dreimal über zehn Minuten."""
    if not _sperre.acquire(blocking=False):
        log("Lauf übersprungen: es läuft bereits einer")
        return
    _lauf.update(laeuft=True, fehler="")
    opt = speicher.optionen()
    try:
        versuche = 3 if geplant else 1
        for nr in range(1, versuche + 1):
            try:
                brief = briefbau.erzeuge_brief(opt, gedaechtnis_pfad=os.path.join(speicher.DATEN, "gedaechtnis.sqlite"),
                                               verkehr_pfad=VERKEHR_PFAD, erledigt=speicher.erledigt_lesen())
                speicher.brief_schreiben(brief)
                zustand = speicher.zustand_lesen()
                offen = len(brief.get("neue_mails") or [])
                zustand["letzter_lauf"] = f"{datetime.now(TZ):%d.%m.%Y %H:%M} erfolgreich" + (
                    f" ({offen} Mails nicht eingeordnet)" if offen else "")
                # seit 1.4.0: Gemini-Tokens je Monat und das zuletzt genutzte Modell für die Einrichtungsseite
                info = brief.get("gemini") or {}
                monat = f"{datetime.now(TZ):%Y-%m}"
                tokens = zustand.get("tokens") if isinstance(zustand.get("tokens"), dict) else {}
                tokens[monat] = int(tokens.get(monat, 0)) + int(info.get("tokens") or 0)
                zustand["tokens"] = {k: tokens[k] for k in sorted(tokens)[-6:]}
                if info.get("modell") and info.get("modell") != "keine Anfrage nötig":
                    zustand["modell"] = info["modell"]
                speicher.zustand_schreiben(zustand)
                log("Brief erzeugt: " + briefbau.push_text(brief))
                if mit_push:  # seit 1.5.0 mit Titeln ohne Beträge, im Protokoll nur die Zahlen
                    titel, text = briefbau.push_inhalt(brief)
                    push(opt, text, titel=titel, protokoll="Morgen-Push mit Inhalt, " + briefbau.push_text(brief))
                return
            except g.GoogleFehler as e:
                log(f"Versuch {nr} von {versuche} fehlgeschlagen ({e.art}): {e}")
                if e.art == "anmeldung" or nr == versuche:
                    raise
                time.sleep(WARTEZEIT_GOOGLE)
    except g.GoogleFehler as e:
        _fehlschlag(opt, str(e), mit_push)
    except Exception as e:                      # unerwarteter Fehler: melden statt still sterben
        traceback.print_exc()
        _fehlschlag(opt, f"Unerwarteter Fehler: {type(e).__name__}: {e}", mit_push)
    finally:
        _lauf["laeuft"] = False
        _sperre.release()


def _fehlschlag(opt, grund: str, mit_push: bool):
    _lauf["fehler"] = grund
    zustand = speicher.zustand_lesen()
    zustand["letzter_lauf"] = f"{datetime.now(TZ):%d.%m.%Y %H:%M} fehlgeschlagen: {grund}"
    speicher.zustand_schreiben(zustand)
    if mit_push:
        push(opt, "Morgenbrief heute nicht möglich: " + grund)


# ------------------------------------------------------------------ Zeitplan

def sollzeit(opt: dict, tag) -> datetime:
    """Mo/Di/Do/Fr zur Arbeitstag-Zeit, Mi/Sa/So zur Zeit der freien Tage."""
    text = opt["zeit_arbeitstage"] if tag.weekday() in (0, 1, 3, 4) else opt["zeit_freie_tage"]
    stunde, minute = (int(x) for x in text.split(":"))
    return datetime(tag.year, tag.month, tag.day, stunde, minute, tzinfo=TZ)


def naechster_lauf(opt: dict, jetzt: datetime) -> datetime:
    soll = sollzeit(opt, jetzt.date())
    erledigt = speicher.zustand_lesen().get("geplant_am") == jetzt.date().isoformat()
    if jetzt < soll and not erledigt:
        return soll
    return sollzeit(opt, jetzt.date() + timedelta(days=1))


def abendzeit(opt: dict, tag):
    """Zeit für den Abend-Push, None wenn abgeschaltet ('aus')."""
    text = (opt.get("zeit_abend") or "19:00").strip()
    try:
        stunde, minute = (int(x) for x in text.split(":"))
    except ValueError:
        return None
    return datetime(tag.year, tag.month, tag.day, stunde, minute, tzinfo=TZ)


def abend_push(opt: dict, jetzt: datetime):
    """Abends nur dann ein Push, wenn morgen eine Frist abläuft oder eine Fahrt ansteht.

    Seit 1.5.0 mit Titeln ohne Beträge (bewusst) und mit Fahrten von morgen ("Fahrt nach München, am besten
    10:30 los"). Im Protokoll nur Zahlen."""
    brief = speicher.brief_lesen(jetzt.date().isoformat())
    titel = briefbau.fristen_morgen_titel(brief, jetzt.date()) if brief else []
    zeilen = []
    if titel:
        zeilen.append("Morgen fällig: " + ", ".join(briefbau.kurztitel(t) for t in titel[:4])
                      + (f" und {len(titel) - 4} weitere" if len(titel) > 4 else ""))
    fahrten = []
    if opt.get("tomtom_api_key"):
        try:
            fahrten = briefbau.fahrten_fuer_tag(opt, jetzt.date() + timedelta(days=1), jetzt, VERKEHR_PFAD)
        except Exception as e:  # Zugabe, der Abend-Push mit Fristen geht trotzdem
            log(f"Abend: Fahrten nicht berechnet ({type(e).__name__})")
    for f in fahrten:
        zeilen.append("Morgen: " + f["zeile"] + ".")
    if zeilen:
        push(opt, "\n".join(zeilen), titel="Morgenbrief: morgen", tag="morgenbrief-abend",
             protokoll=f"Abend-Push: {len(titel)} Fristen, {len(fahrten)} Fahrten morgen")
    else:
        log("Abend: keine Frist und keine Fahrt morgen, kein Push")


def unterwegs_pruefen(opt: dict, jetzt: datetime):
    """Seit 1.5.0: Arbeitsweg 20 Minuten vor der Abfahrt mit dem Verkehr von jetzt nachprüfen (Push nur bei Stau
    oder Sperrung) und 20 Minuten vor jeder Fahrt aus dem Kalender an die Abfahrt erinnern."""
    brief = speicher.brief_lesen(jetzt.date().isoformat())
    if not brief or not opt.get("tomtom_api_key"):
        return
    zustand = speicher.zustand_lesen()
    heute = jetzt.date().isoformat()
    erledigt = zustand.get("unterwegs") if isinstance(zustand.get("unterwegs"), dict) else {}
    erledigt = {k: v for k, v in erledigt.items() if v == heute}
    v = brief.get("verkehr")
    if v and "arbeitsweg" not in erledigt:
        los = datetime.combine(jetzt.date(), datetime.strptime(v["losfahren"], "%H:%M").time(), TZ)
        if los - timedelta(minutes=VORLAUF_MIN) <= jetzt < los:
            erledigt["arbeitsweg"] = heute
            try:
                neu = verkehr_mod.abfahrt(opt, jetzt, VERKEHR_PFAD, live=True)
                neu_los = datetime.combine(jetzt.date(), datetime.strptime(neu["losfahren"], "%H:%M").time(), TZ)
                frueher = int((los - neu_los).total_seconds() // 60)
                if neu["stoerung"] or frueher >= int(opt.get("verkehr_schwelle_min") or 3):
                    grund = neu["meldungen"][0] if neu["meldungen"] else (
                        f"Stau +{neu['extra_min']} Min." if neu["extra_min"] else "Mehr Verkehr als heute früh")
                    push(opt, f"{grund}\nLosfahren bis {verkehr_mod.uhr(neu_los)} ({neu['fahrt_min']} Min. Fahrt).",
                         titel="Arbeitsweg: früher los", tag="morgenbrief-verkehr",
                         protokoll=f"Arbeitsweg-Push: {frueher} Min. früher")
                else:
                    log(f"Arbeitsweg nachgeprüft: {neu['fahrt_min']} Min., kein Push")
            except verkehr_mod.VerkehrFehler as e:
                log(f"Arbeitsweg nicht nachgeprüft: {e}")
    for f in brief.get("fahrten") or []:
        schluessel = "fahrt:" + f.get("termin", "")
        try:
            push_um = datetime.fromisoformat(f["push_um"])
            los = datetime.fromisoformat(f["losfahren"])
        except (KeyError, ValueError):
            continue
        if schluessel in erledigt or not push_um <= jetzt < push_um + timedelta(minutes=30):
            continue
        erledigt[schluessel] = heute
        try:
            minuten = verkehr_mod.fahrt_live(opt, VERKEHR_PFAD, f["ziel"], jetzt)
            if f.get("modus") == "ankunft":
                termin = datetime.fromisoformat(f["termin"])
                los = termin - timedelta(minutes=minuten + verkehr_mod.PUFFER_MIN)
            text = f"{f['titel']}: losfahren um {verkehr_mod.uhr(los)}, {minuten} Min. Fahrt mit dem Verkehr von jetzt."
        except verkehr_mod.VerkehrFehler:
            text = f"{f['titel']}: losfahren um {verkehr_mod.uhr(los)} (Verkehr gerade nicht abrufbar)."
        push(opt, text, titel="Gleich losfahren", tag="morgenbrief-fahrt", protokoll="Fahrt-Push gesendet")
    zustand = speicher.zustand_lesen()
    zustand["unterwegs"] = erledigt
    speicher.zustand_schreiben(zustand)


def zeitplan():
    while True:
        try:
            opt = speicher.optionen()
            jetzt = datetime.now(TZ)
            soll = sollzeit(opt, jetzt.date())
            zustand = speicher.zustand_lesen()
            heute = jetzt.date().isoformat()
            if zustand.get("geplant_am") != heute and soll <= jetzt < soll + timedelta(hours=NACHHOLEN_STUNDEN):
                zustand["geplant_am"] = heute
                speicher.zustand_schreiben(zustand)
                log("Geplanter Lauf startet")
                lauf(geplant=True, mit_push=True)
            zustand = speicher.zustand_lesen()
            abend = abendzeit(opt, jetzt.date())
            if abend and zustand.get("abend_am") != heute and abend <= jetzt < abend + timedelta(hours=2):
                zustand["abend_am"] = heute
                speicher.zustand_schreiben(zustand)
                abend_push(opt, jetzt)
            unterwegs_pruefen(opt, jetzt)  # seit 1.5.0
        except Exception:
            traceback.print_exc()
        time.sleep(20)


# ------------------------------------------------- Im Brief erledigt (seit 1.5.0)

LISTEN = ("braucht_dich", "todos", "demnaechst", "geklaert")


def _eintrag_finden(brief: dict, schluessel: str):
    for name in LISTEN:
        for nr, x in enumerate(brief.get(name) or []):
            if x.get("schluessel") == schluessel:
                return name, nr, x
    return None


def _ablage_text(x: dict, art: str, jetzt: datetime, schluessel: str) -> str:
    """Beschreibung des Ablage-Eintrags. Der Nachtlauf erkennt daran den Punkt im To-do-Doc."""
    zeilen = [f"Im Morgenbrief erledigt am {jetzt:%d.%m.%Y um %H:%M}.",
              "Art: " + ("Rechnung bezahlt" if art == "bezahlt" else "erledigt"),
              "Titel: " + x.get("titel", "")]
    if x.get("nummern"):
        zeilen.append("Rechnungsnummer: " + ", ".join(x["nummern"]))
    if x.get("frist") or x.get("datum"):
        zeilen.append("Frist: " + (x.get("frist") or x.get("datum")))
    if schluessel.startswith("mail:"):
        zeilen.append("Quelle: Mail, Gmail-Thread " + schluessel[5:])
    else:
        zeilen.append("Quelle: Kalender-To-do, Termin-ID " + schluessel[4:])
        if x.get("notiz"):
            zeilen.append("Text in der To-do-Liste: " + x["notiz"])
    return "\n".join(zeilen)


class _OhneAblage(Exception):
    pass


def erledigt_markieren(opt: dict, schluessel: str) -> str:
    """Punkt aus dem heutigen Brief nehmen, merken und für den Nachtlauf in die Ablage eintragen."""
    jetzt = datetime.now(TZ)
    heute = jetzt.date()
    brief = speicher.brief_lesen(heute.isoformat())
    gefunden = _eintrag_finden(brief, schluessel) if brief else None
    if not gefunden:
        return "Der Punkt steht nicht mehr im heutigen Brief."
    name, nr, x = gefunden
    art = "bezahlt" if x.get("rechnung") else "erledigt"
    eintrag = {"titel": x.get("titel", ""), "datum": heute.isoformat(), "zeit": jetzt.isoformat(timespec="seconds"),
               "art": art, "nummern": x.get("nummern") or [], "liste": name, "eintrag": x,
               "ablage_id": "", "ablage_kal": ""}
    zustand = speicher.zustand_lesen()
    try:
        if schluessel.startswith("geb:"):  # seit 1.6.0: Gratulieren steht nicht im To-do-Doc, keine Ablage
            raise _OhneAblage()
        kal = zustand.get("ablage_kalender") or g.ablage_kalender(opt)
        zustand["ablage_kalender"] = kal
        eintrag["ablage_id"] = g.ablage_eintragen(opt, kal, x.get("titel", ""), _ablage_text(x, art, jetzt, schluessel),
                                                  heute)
        eintrag["ablage_kal"] = kal
        zustand["ablage_fehler"] = ""
    except g.GoogleFehler as e:
        zustand["ablage_fehler"] = ("Google neu verbinden (Seite Einrichtung), damit der Nachtlauf davon erfährt."
                                    if e.art in ("recht", "anmeldung") else str(e))
        log(f"Ablage nicht geschrieben ({e.art})")
    except _OhneAblage:
        pass
    speicher.zustand_schreiben(zustand)
    daten = speicher.erledigt_lesen()
    daten[schluessel] = eintrag
    speicher.erledigt_schreiben(daten, heute)
    del brief[name][nr]
    speicher.brief_schreiben(brief)
    log(f"Im Brief {art}: 1 Punkt ({name})" + ("" if eintrag["ablage_id"] or schluessel.startswith("geb:")
                                                else ", ohne Ablage"))
    return ""


def erledigt_zuruecknehmen(opt: dict, schluessel: str):
    heute = datetime.now(TZ).date()
    daten = speicher.erledigt_lesen()
    x = daten.pop(schluessel, None)
    if not x:
        return
    if x.get("ablage_id") and x.get("ablage_kal"):
        try:
            g.ablage_loeschen(opt, x["ablage_kal"], x["ablage_id"])
        except g.GoogleFehler as e:
            log(f"Ablage-Eintrag nicht gelöscht ({e.art})")
    speicher.erledigt_schreiben(daten, heute)
    brief = speicher.brief_lesen(heute.isoformat())
    if brief and x.get("liste") in LISTEN and x.get("eintrag") and not _eintrag_finden(brief, schluessel):
        brief.setdefault(x["liste"], []).append(x["eintrag"])
        speicher.brief_schreiben(brief)
    if schluessel.startswith("mail:"):  # hat ein Lauf den gemerkten Punkt schon geschlossen: wieder öffnen
        try:
            db = gedaechtnis.Gedaechtnis(os.path.join(speicher.DATEN, "gedaechtnis.sqlite"))
            db.db.execute("UPDATE punkte SET status = 'offen', grund = NULL WHERE thread = ? AND grund = ?",
                          (schluessel[5:], "im Brief erledigt"))
            db.db.commit()
            db.schliessen()
        except Exception as e:
            log(f"Gedächtnis nicht zurückgesetzt ({type(e).__name__})")
    log("Im Brief erledigt: 1 Punkt zurückgenommen")


def erledigt_heute() -> list:
    heute = datetime.now(TZ).date().isoformat()
    return [dict(v, schluessel=k) for k, v in speicher.erledigt_lesen().items() if v.get("datum") == heute]


# ------------------------------------------------------------------ Webseite

class Anfrage(BaseHTTPRequestHandler):
    server_version = "Morgenbrief"

    def log_message(self, *args):
        pass

    def _erlaubt(self) -> bool:
        if TEST or self.client_address[0] == INGRESS_IP:
            return True
        self.send_error(403, "Zugriff nur über Home Assistant")
        return False

    def _basis(self) -> str:
        pfad = self.headers.get("X-Ingress-Path", "")
        return pfad.rstrip("/") if pfad.startswith("/") else ""

    def _html(self, text: str, status=200):
        daten = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(daten)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(daten)

    def _weiter(self, ziel: str):
        self.send_response(303)
        self.send_header("Location", self._basis() + ziel)
        self.end_headers()

    def _formular(self) -> dict:
        laenge = min(int(self.headers.get("Content-Length") or 0), 20000)
        roh = self.rfile.read(laenge).decode("utf-8", "replace") if laenge else ""
        return {k: v[0] for k, v in urllib.parse.parse_qs(roh).items()}

    def _einrichtung(self, meldung="", fehler=""):
        opt = speicher.optionen()
        tok = speicher.token_lesen() or {}
        zustand = speicher.zustand_lesen()
        info = {
            "verbunden": bool(tok.get("refresh_token")),
            "verbunden_am": datetime.fromtimestamp(tok.get("verbunden_am", 0), TZ).strftime("%d.%m.%Y %H:%M")
            if tok.get("verbunden_am") else "",
            "konto": zustand.get("konto", ""),
            "auth_url": g.anmeldung_starten(opt["google_client_id"]) if opt["google_client_id"] else "",
            "naechster_lauf": f"{naechster_lauf(opt, datetime.now(TZ)):%d.%m.%Y %H:%M}",
            "letzter_lauf": zustand.get("letzter_lauf", ""),
            "modell": zustand.get("modell", ""),
            "tokens_monat": (zustand.get("tokens") or {}).get(f"{datetime.now(TZ):%Y-%m}", 0)
            if isinstance(zustand.get("tokens"), dict) else 0,
            "ablage": ("fehlt: " + zustand["ablage_fehler"]) if zustand.get("ablage_fehler")
            else ("bereit (Kalender „Morgenbrief-Ablage“)" if zustand.get("ablage_kalender")
                  else "noch nicht eingerichtet, Google neu verbinden"),
        }
        self._html(seite.einrichtung_seite(self._basis(), opt, info, meldung, fehler))

    def do_GET(self):
        if not self._erlaubt():
            return
        pfad = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        heute = datetime.now(TZ).date()
        tage_liste = speicher.brief_tage()
        if pfad == "/einrichtung":
            return self._einrichtung()
        if pfad == "/" or pfad.startswith("/tag/"):
            tag = pfad[5:] if pfad.startswith("/tag/") else heute.isoformat()
            brief = speicher.brief_lesen(tag)
            if brief is None and pfad == "/" and not _lauf["laeuft"] and tage_liste:
                # heute noch nichts: den jüngsten vorhandenen Brief zeigen (mit Hinweis)
                brief = speicher.brief_lesen(tage_liste[0])
            if brief is None:
                verbunden = bool((speicher.token_lesen() or {}).get("refresh_token"))
                return self._html(seite.leere_seite(self._basis(), tage_liste, _lauf, heute, verbunden))
            zustand = speicher.zustand_lesen()
            return self._html(seite.brief_seite(brief, self._basis(), tage_liste, _lauf, heute,
                                                erledigt_heute(), zustand.get("ablage_fehler", "")))
        self.send_error(404)

    def do_POST(self):
        if not self._erlaubt():
            return
        pfad = urllib.parse.urlparse(self.path).path.rstrip("/")
        form = self._formular()
        opt = speicher.optionen()
        if pfad == "/erledigt":  # seit 1.5.0
            erledigt_markieren(opt, form.get("s", ""))
            return self._weiter("/")
        if pfad == "/rueckgaengig":
            erledigt_zuruecknehmen(opt, form.get("s", ""))
            return self._weiter("/")
        if pfad == "/erzeugen":
            if not _lauf["laeuft"]:
                _lauf.update(laeuft=True, fehler="")   # sofort anzeigen, der Thread übernimmt
                threading.Thread(target=lauf, kwargs={"geplant": False, "mit_push": form.get("push") == "1"},
                                 daemon=True).start()
                time.sleep(0.3)
            return self._weiter("/")
        if pfad == "/google/code":
            try:
                g.anmeldung_abschliessen(opt, form.get("adresse", ""))
                konto = g.gmail_profil(opt)
                zustand = speicher.zustand_lesen()
                zustand["konto"] = konto
                text = f"Verbunden mit {konto}. Gmail und deine Kalender darf der Zugang nur lesen."
                try:  # seit 1.5.0: eigenen Kalender "Morgenbrief-Ablage" anlegen bzw. finden
                    zustand["ablage_kalender"] = g.ablage_kalender(opt)
                    zustand["ablage_fehler"] = ""
                    text += " Der Kalender „Morgenbrief-Ablage“ ist bereit."
                except g.GoogleFehler as e:
                    zustand["ablage_fehler"] = str(e)
                speicher.zustand_schreiben(zustand)
                return self._einrichtung(meldung=text)
            except g.GoogleFehler as e:
                return self._einrichtung(fehler=str(e))
        if pfad == "/google/test":
            try:
                konto = g.gmail_profil(opt)
                kalender = [k for k in g.kalender_liste(opt) if not k.get("hidden")]
                text = f"Google antwortet. Konto {konto}, {len(kalender)} Kalender sichtbar."
                if opt["gemini_api_key"]:
                    try:
                        modell = gemini.modell_waehlen(opt["gemini_api_key"], opt.get("gemini_modell", "auto"))
                        zustand = speicher.zustand_lesen()
                        zustand.update(konto=konto, modell=modell)
                        speicher.zustand_schreiben(zustand)
                        text += f" Gemini antwortet, Modell {modell}."
                    except gemini.GeminiFehler as e:
                        return self._einrichtung(meldung=text, fehler=str(e))
                return self._einrichtung(meldung=text)
            except g.GoogleFehler as e:
                return self._einrichtung(fehler=str(e))
        if pfad == "/push/test":
            ok = push(opt, "Test: So sieht der Push des Morgenbriefs aus.", versuche=1)
            if ok:
                return self._einrichtung(meldung="Test-Push gesendet an notify." + opt["push_dienst"] + ".")
            return self._einrichtung(fehler="Test-Push fehlgeschlagen. Details stehen im Protokoll des Add-ons.")
        self.send_error(404)


def main():
    # Beim Stoppen des Add-ons sofort beenden statt auf den Abbruch zu warten
    try:
        signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    except ValueError:
        pass                                  # nur im Hauptthread möglich (betrifft Tests)
    os.makedirs(speicher.BRIEFE, exist_ok=True)
    opt = speicher.optionen()
    log(f"Morgenbrief gestartet. Zeiten: Mo/Di/Do/Fr {opt['zeit_arbeitstage']}, Mi/Sa/So {opt['zeit_freie_tage']}. "
        f"Nächster Lauf: {naechster_lauf(opt, datetime.now(TZ)):%d.%m.%Y %H:%M}")
    threading.Thread(target=zeitplan, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Anfrage).serve_forever()


if __name__ == "__main__":
    main()
