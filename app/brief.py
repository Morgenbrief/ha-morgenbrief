"""Stellt den Morgenbrief zusammen: Kalender, Tagesstatus, Mails, To-dos."""
import base64
import html
import re
import time
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import gedaechtnis
import gemini
import google_api as g
import tage
import verkehr
import wetter

TZ = ZoneInfo("Europe/Berlin")


def melde(text):
    """Wird von main.py durch die Protokollfunktion ersetzt. Protokolliert nur Zahlen und Zeiten, nie Inhalte."""
TODO_MARKE = "aus der to-do-liste"

MAX_KANDIDATEN = 40      # so viele Mails werden je Lauf geprüft (seit 1.6.0 40 wegen des 7-Tage-Fensters)
MAX_NEU_AN_GEMINI = 40   # seit 1.4.0: so viele noch nicht eingeordnete Mails gehen je Lauf an Gemini (1.6.0: 40)
MAX_GEKLAERT = 3
MAX_WARTET = 5
MAX_WARTET_KANDIDATEN = 12
MAX_TODOS = 25           # seit 1.4.0 alle To-dos bis heute + 7 Tage, das ist nur eine Grenze gegen Ausreißer
TEXT_TODO_NOTIZ = 300
TODO_UEBERFAELLIG_TAGE = 14  # so weit zurück offene To-dos zeigen
STOPPWOERTER = {"prüfen", "testen", "fällig", "erledigen", "machen", "aktualisieren", "anrufen",
                "schreiben", "nachfragen", "klären", "kaufen", "bestellen", "einheit", "firmware",
                "update", "termin", "bitte", "wegen", "nicht", "danach", "vorher"}
TEXT_POSTEINGANG = 3000  # Zeichen pro Mail an Gemini (jede Mail geht seit 1.4.0 nur einmal hin)
TEXT_GESENDET = 1500     # 1.4.0 hatte 800, das reichte für "wartet auf Antwort" nicht sicher (1.4.1 wieder 1500)
# 1.4.1: neu eingeordnet; 1.6.0: "post3" wegen des neuen Felds "folge"
EINORDNUNG_ART = {"post": "post3", "gesendet": "gesendet2", "termin": "termin"}
TEXT_REGEL = 20000       # so viel Mailtext prüfen die festen Regeln (geht nicht an Gemini)
# seit 1.6.0: 7 Tage statt 48 Stunden. Ältere Mails erscheinen nur, wenn sie etwas von dir brauchen
# ("Schon geklärt" und "Weggelassen" zeigen nur die letzten FRISCH_STUNDEN)
FENSTER_STUNDEN = 168
FRISCH_STUNDEN = 48
POSTEINGANG_SUCHE = "in:inbox newer_than:8d"
ABGELEGT_STUNDEN = 72    # seit 1.4.0: so alt dürfen ungelesen abgelegte Rechnungen und Fristen sein
ABGELEGT_SUCHE = ("newer_than:3d is:unread -in:inbox -in:sent -in:drafts -in:spam -in:trash "
                  "-category:promotions -category:social")
ZAHLUNG_SUCHE = ('newer_than:21d -in:sent {"zahlung ist eingegangen" "zahlung eingegangen" "zahlung erhalten" '
                 'zahlungseingang zahlungsbestätigung "vielen dank für ihre zahlung" "payment received"}')
WARTET_MIN_TAGE = 3
WARTET_MAX_TAGE = 30
ANDERE_KATEGORIEN = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS"}
# Absender, deren Mails immer unter "Braucht dich" stehen (Rechnungen, die du selbst überweisen musst)
IMMER_WICHTIG = ()  # Stichwörter im Absender, z. B. ("parkdienst",)
IMMER_WICHTIG_TAGE = 14  # Frist bis heute + so viele Tage: IMMER_WICHTIG bleibt unter "Braucht dich"
BRAUCHT_DICH_TAGE = 7  # Frist bis heute + so viele Tage: "Braucht dich", später "Demnächst"
DEMNAECHST_TAGE = 120  # so weit voraus zeigt "Demnächst" Fristen und To-dos (seit 1.4.0 ohne Höchstzahl)
SATZ_UEBERLAPPUNG = 0.7  # Hintergrundsatz aus mehr als 70 % Titelwörtern wiederholt nur die Aufgabe
# Wörter, die beim Abgleich Mail gegen Kalendereintrag nichts aussagen
ALLGEMEINE_WOERTER = {
    "rechnung", "rechnungen", "zahlung", "überweisen", "bezahlen", "frist", "fristen", "verlängern", "aufladen",
    "konto", "online", "mail", "mails", "email", "gmail", "info", "noreply", "service", "team", "newsletter",
    "kundenservice", "nach", "auch", "sich", "eine", "einer", "einen", "dass", "oder", "wird", "sind", "haben",
    "ihre", "ihren", "ihrer", "ihnen", "heute", "morgen", "jetzt", "neue", "neuer", "neues", "kein", "keine",
    "noch", "über", "unter", "diese", "dieser", "dieses", "mehr", "werden", "wurde", "bereits", "gmbh", "from",
    # seit 1.3.2: Fristwörter, die in vielen Mails und To-dos stehen und nichts über die Sache sagen
    "läuft", "abläuft", "ablauf", "fällig", "zahlbar", "erinnerung", "hinweis", "wichtig", "anfrage", "antwort",
    "bestätigung", "deine", "dein", "ihr"}


TEXT_TODO_DETAIL = 160  # seit 1.3.2: Hintergrund zum To-do aus der Kalenderbeschreibung, gekürzt
# seit 1.4.0 "Rechnung" nur als eigenes Wortende: "Taglohnrechnung" ja, "Rechnungsadresse" nein
RECHNUNG = re.compile(r"rechnung(?![a-zäöüß])|zahlungsaufforderung|zahlungserinnerung|mahnung|invoice")
BEZAHLT = re.compile(r"(?<!nicht )(?<!noch )(?<!un)bezahlt|(?<!nicht )überwiesen|(?<!nicht )beglichen|zahlung erhalten|"
                     r"zahlungseingang|zahlungsbestätigung|zahlungsbeleg|zahlung (ist )?(bei uns )?eingegangen|"
                     r"vielen dank für (ihre|deine) zahlung|payment received")  # seit 1.3.3, ergänzt 1.4.0
# seit 1.4.0 auch mit Datum im Satz ("wird am 25.11.2026 von Ihrem Konto abgebucht")
LASTSCHRIFT_ENG = re.compile(r"lastschrift|wird\b.{0,60}?\babgebucht|abbuchung|eingezogen|bankeinzug|"
                             r"einzug von ihrem konto|sepa-mandat|bereits bezahlt")
OFFEN = re.compile(r"mahnung|zahlungserinnerung|zahlungsaufforderung|offene[nr]? (betrag|rechnung|posten)|"
                   r"noch nicht (bezahlt|beglichen|überwiesen)")
# seit 1.4.0: Hinweise, dass eine Mail nur über eine Rechnung informiert, statt Zahlung zu verlangen
ZAHLUNG_GEFORDERT = re.compile(r"zahlbar|zahlungsfrist|zahlungsziel|fällig|überweis|\biban\b|bezahl(en|-?link)|"
                               r"jetzt zahlen|bitte (begleichen|zahlen)|rechnungsbetrag")
NUR_INFO = re.compile(r"zur information|zu (deiner|ihrer) information|"
                      r"rechnung[^.]{0,60}separate[nr]? (e-?mail|mail|nachricht)|rechnung folgt")
ZAHLUNG_BESTAETIGT = re.compile(r"zahlung (ist )?(bei uns )?(eingegangen|erhalten)|zahlungseingang|zahlungsbestätigung|"
                                r"vielen dank für (ihre|deine) zahlung|payment received")
# Vorfilter für ungelesen abgelegte Mails (nur Betreff und Vorschau)
VORFILTER = re.compile(r"rechnung|mahnung|zahlungs|invoice|frist|fällig|zahlbar|sperr|läuft|verläng|aufladen")
NUMMER = re.compile(r"(?:rechnungs?[ -]?(?:nr\.?|nummer)|invoice(?: no\.?| number| #)?|beleg[ -]?(?:nr\.?|nummer))"
                    r"\s*[:#]?\s*([a-z]{0,4}\d[\d-]{4,}\d)", re.I)
MONATE_NR = {name.casefold(): nr for nr, name in enumerate(tage.MONATE, 1)}
FRIST_DATUM = re.compile(r"(?:zahlbar bis|zahlungsfrist|zahlungsziel|fällig (?:am|bis)|spätestens(?: am| bis)?|"
                         r"bis (?:zum|spätestens))\s*:?\s*(?:[a-z]{2,10},?\s+)?(?:den\s+)?"
                         r"(\d{1,2})\.\s*(?:(\d{1,2})\.|([a-zäöü]{3,9}))\s*(\d{4})?")


def rechnung_offen(text: str, anhang: bool = True) -> bool:
    """Rechnung, die du selbst bezahlen musst (seit 1.3.4): wie IMMER_WICHTIG nie weglassen, nie geklärt.

    Seit 1.4.0 strenger: Eine Mail, die nur über eine Rechnung informiert ("zur Information", "Rechnung folgt in
    einer separaten E-Mail"), zählt nicht. Ohne Zahlungsaufforderung im Text zählt sie nur mit PDF-Anhang
    (Betrag und Frist stehen dann oft nur im PDF). anhang=True, wenn das unbekannt ist.
    """
    t = (text or "").casefold()
    if OFFEN.search(t):
        return True
    if not RECHNUNG.search(t) or LASTSCHRIFT_ENG.search(t) or BEZAHLT.search(t) or "kauf auf rechnung" in t:
        return False
    gefordert = bool(ZAHLUNG_GEFORDERT.search(t))
    if NUR_INFO.search(t) and not gefordert:
        return False
    return gefordert or anhang


def rechnungsnummern(betreff: str, text: str = "") -> set:
    """Rechnungsnummern zum Abgleich mit Zahlungsbestätigungen (seit 1.4.0).

    Im Text nur ausdrücklich genannte ("Rechnung Nr. 12345678"), im Betreff auch lange Ziffernfolgen
    ("Taglohnrechnung 87654321"). Kundennummern und Bankdaten zählen so nicht."""
    nummern = {m.group(1).casefold().replace("-", "") for m in NUMMER.finditer((betreff or "") + " " + (text or ""))}
    nummern |= set(re.findall(r"\b[a-z]{0,4}\d{6,}\b", (betreff or "").casefold()))
    return nummern


def frist_aus_text(text: str, heute: date):
    """Zahlungs- oder Handlungsfrist aus dem Mailtext ("zahlbar bis 01.12.2026", "Zahlungsfrist: 30. November
    2026"), wenn Gemini keine liefert (seit 1.4.0). Ohne Jahr das nächste passende Datum."""
    for m in FRIST_DATUM.finditer((text or "").casefold()):
        monat = int(m.group(2)) if m.group(2) else MONATE_NR.get(m.group(3) or "")
        if not monat:
            continue
        jahr = int(m.group(4)) if m.group(4) else heute.year
        try:
            d = date(jahr, monat, int(m.group(1)))
        except ValueError:
            continue
        if not m.group(4) and d < heute - timedelta(days=60):
            d = date(jahr + 1, monat, int(m.group(1)))
        return d
    return None


def hat_anhang(payload: dict) -> bool:
    """PDF-Anhang vorhanden (nur der Name wird geprüft, der Anhang selbst nie gelesen)."""
    def lauf(teil):
        name = (teil.get("filename") or "").casefold()
        if name and (name.endswith(".pdf") or teil.get("mimeType") == "application/pdf"):
            return True
        return any(lauf(u) for u in teil.get("parts") or [])
    return lauf(payload or {})


def immer_wichtig(text: str) -> bool:
    t = (text or "").casefold()
    return any(w in t for w in IMMER_WICHTIG)


# seit 1.3.7: To-do ist nur dann eine zu zahlende Rechnung, wenn auch ein Zahlwort oder ein Betrag dasteht
# (sonst wären "Rechnungs-Backup" oder "Rechnungsapp prüfen" betroffen)
ZAHLEN = re.compile(r"überweis|bezahl|zahl|begleich|€|\beur\b|\beuro\b")


def rechnung_zu_zahlen(text: str) -> bool:
    t = (text or "").casefold()
    return rechnung_offen(t) and bool(OFFEN.search(t) or ZAHLEN.search(t))


def kal_schluessel(t: dict) -> str:
    """Fester Schlüssel eines Kalender-To-dos für den Erledigt-Knopf (seit 1.5.0)."""
    return "kal:" + (t.get("id") or t.get("link") or t.get("titel", ""))


def rechnungs_todos(nah: list, demnaechst_kalender: list, heute: date, wichtig_woerter: list) -> list:
    """Rechnungs-To-dos aus dem Kalender für "Braucht dich" (seit 1.3.7).

    Regel seit 18.11.: Jede Rechnung, die du selbst bezahlen musst, steht unter "Braucht dich", nicht unter
    "Demnächst" und nicht doppelt. nah = Rechnungs-To-dos bis heute + 7 (auch überfällige), schon aus "Offene
    To-dos" herausgenommen. Aus "Demnächst" kommen Rechnungs-To-dos bis heute + IMMER_WICHTIG_TAGE dazu und werden
    dort herausgenommen; spätere Fristen bleiben wie bei Mails unter "Demnächst". Steht dieselbe Rechnung schon als
    Mail unter "Braucht dich" (wichtig_woerter), bleibt nur die Mail.
    """
    grenze = heute + timedelta(days=IMMER_WICHTIG_TAGE)
    ergebnis = []
    for t in nah:
        woerter_t = schluesselwoerter(t["titel"])
        if any(woerter_t & w for w in wichtig_woerter if w):
            continue
        frist = t["start"].date()
        eintrag = {"titel": t["titel"], "quelle": f"Bis {tage.datum_kurz(frist)} Aus der To-do-Liste.",
                   "satz": hintergrund("", t["titel"], t.get("notiz", "")), "link": t.get("link", ""),
                   "frist": frist.isoformat(), "_wichtig": True, "_woerter": woerter_t, "_frist": frist,
                   "schluessel": kal_schluessel(t), "rechnung": True, "notiz": t.get("notiz", ""),
                   "nummern": sorted(rechnungsnummern(t["titel"], t.get("notiz", "")))}
        if frist < heute:
            eintrag["marke"] = "überfällig"
        ergebnis.append(eintrag)
    for k in list(demnaechst_kalender):
        if k["_frist"] <= grenze and rechnung_zu_zahlen(k["titel"] + " " + k.get("_notiz", "")):
            ergebnis.append({"titel": k["titel"], "quelle": k["quelle"],
                             "satz": hintergrund("", k["titel"], k.get("_notiz", "")), "link": k.get("link", ""),
                             "frist": k["frist"], "_wichtig": True, "_woerter": k["_woerter"], "_frist": k["_frist"],
                             "schluessel": k.get("schluessel", ""), "rechnung": True, "notiz": k.get("_notiz", ""),
                             "nummern": sorted(rechnungsnummern(k["titel"], k.get("_notiz", "")))})
            demnaechst_kalender.remove(k)
    return sorted(ergebnis, key=lambda x: x["_frist"])



def frist_lesen(wert):
    """ISO-Datum aus der Gemini-Antwort, sonst None."""
    try:
        return date.fromisoformat(str(wert or "").strip()[:10])
    except ValueError:
        return None


_WORT = re.compile(r"[0-9a-zäöüß]+")


def woerter(text: str) -> set:
    return {w for w in _WORT.findall((text or "").casefold()) if len(w) >= 3}


def schluesselwoerter(text: str) -> set:
    """Wörter, an denen man eine Sache wiedererkennt (Abgleich Mail gegen Kalendereintrag)."""
    return {w for w in woerter(text) if len(w) >= 4 and not w.isdigit()
            and w not in STOPPWOERTER and w not in ALLGEMEINE_WOERTER}


def ueberlappung(satz: str, titel: str) -> float:
    """Anteil der Satzwörter, die auch im Titel stehen."""
    s = woerter(satz)
    return len(s & woerter(titel)) / len(s) if s else 1.0


_SATZENDE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ])")


def notiz_rest(s: str, titel: str) -> str:
    """'Alexa Media Player auf v5.20.0 updaten: erst Vollbackup ...' -> 'Erst Vollbackup ...' (Titel vorne weg)."""
    # seit 1.6.2 auch beim Komma: "KI-Zusammenfassung der Log-Fehler im Home-Assistant-Statusbericht neu bewerten,
    # nach drei Sonntagsberichten ..." -> "Nach drei Sonntagsberichten ..."
    for trenner in (": ", ", "):
        if trenner in s:
            vor, nach = s.split(trenner, 1)
            if nach.strip() and ueberlappung(vor, titel) >= 0.5:
                nach = nach.strip()
                return nach[:1].upper() + nach[1:]
    return s


# seit 1.6.0: Füllwörter zählen nicht als neue Information gegenüber dem Titel
FUELLWOERTER = {"mit", "und", "der", "die", "das", "den", "dem", "des", "für", "von", "vom", "zum", "zur", "auf",
                "aus", "bei", "ist", "sind", "wird", "nach", "vor", "ein", "eine", "einen", "einem", "einer", "noch",
                "auch", "dann", "oder", "als", "wie", "uhr", "chat", "heute", "morgen", "seit", "bis"}
NEUE_WOERTER_MIN = 2
QUELLE_HINTEN = re.compile(r",? Chat [^,.]{1,60}, \d{1,2}\.\d{1,2}\.\d{4}\.?$")


def _neu_gegen_titel(s: str, titel: str) -> int:
    """Anzahl der Wörter im Satz, die weder im Titel stehen noch Füllwörter oder Zahlen sind."""
    t = woerter(titel)
    # Wortteile zählen mit: "Morgen-Push" im Titel deckt "Push" im Satz ab
    return len({w for w in woerter(s) if w not in t and w not in FUELLWOERTER and not w.isdigit()
                and not any(w in x or x in w for x in t if len(x) >= 4)})


def hintergrund(satz: str, titel: str, notiz: str) -> str:
    """Hintergrund zum To-do. Leerer Satz oder einer, der nur die Aufgabe wiederholt: erster Notizsatz
    (Kalenderbeschreibung), der mehr sagt als der Titel, gekürzt (seit 1.3.2 auch bei leerem Satz).
    Seit 1.6.0 muss ein Satz mindestens NEUE_WOERTER_MIN neue Wörter bringen, sonst wiederholt er den Titel."""
    satz = sauber(satz)
    if satz and ueberlappung(satz, titel) <= SATZ_UEBERLAPPUNG and _neu_gegen_titel(satz, titel) >= NEUE_WOERTER_MIN:
        return satz
    for s in _SATZENDE.split(sauber(notiz)):
        s = QUELLE_HINTEN.sub("", notiz_rest(s.strip(), titel))  # seit 1.6.2: ", Chat Projekt, 21.11.2026" weg
        if s.casefold().startswith("chat "):  # Quellenangabe wie "Chat Morgenbrief 1.5.0, 20.11.2026"
            continue
        if s and ueberlappung(s, titel) <= SATZ_UEBERLAPPUNG and _neu_gegen_titel(s, titel) >= NEUE_WOERTER_MIN:
            return kuerzen(s, TEXT_TODO_DETAIL)
    return ""


# seit 1.6.0: Befehle in To-do-Notizen gehören unter "Werkzeuge", nicht in den Satz
BEFEHL = re.compile(r'\b((?:ha|grep|docker|tail|sudo|curl|journalctl)\s+(?:[^".\n]|"[^"\n]*"|\.(?=\S))+)')
BEFEHL_SICHER = re.compile(r"\||\s-{1,2}[a-z]|^ha\s+(?:apps|addons|core|supervisor|host|os|backups|store)\b", re.I)


def befehle_trennen(notiz: str) -> tuple:
    """'... prüfen am 23.11.: ha apps logs x | grep y. Erwartet ...' -> ('... prüfen am 23.11. Erwartet ...', [Befehl])"""
    befehle = []

    def weg(m):
        b = m.group(1).strip()
        if not BEFEHL_SICHER.search(b):
            return m.group(0)
        befehle.append(b)
        return ""

    rest = BEFEHL.sub(weg, notiz or "")
    rest = re.sub(r":\s*(?=[.,;]|$)", "", rest)
    rest = re.sub(r"\s+([.,;])", r"\1", rest)
    rest = re.sub(r"\.{2,}", ".", rest)
    return sauber(rest), befehle


# seit 1.6.0: To-dos, die nur informieren ("Rückmeldung abwarten"), bekommen keinen Erledigt-Knopf
PASSIV = re.compile(r"\babwarten\b|nur (zur )?info|zur kenntnis|zur information|nichts zu tun|kein handlungsbedarf")


def passiv(titel: str, notiz: str) -> bool:
    return bool(PASSIV.search((titel + " " + (notiz or "")).casefold()))


def tagessatz_regel(status: dict, liste: list, tag: date, status_morgen: dict, jetzt: datetime = None) -> str:
    """Warmer Satz zum Tag ohne Gemini, nur aus Tagesstatus und Terminen (seit 1.3.2).
    Seit 1.6.0 nur echte Termine (keine To-dos, keine Erinnerungen), die noch nicht vorbei sind."""
    zeitlich = [t for t in liste if not t["ganztag"] and not t.get("todo")
                and (jetzt is None or t["ende"] > jetzt)]
    if status.get("arbeit"):
        ende = _feierabend(status, tag)
        nach = [t for t in zeitlich if t["start"] >= ende]
        if nach:
            return f"Nach Feierabend um {_uhr(ende)} wartet noch {_kurz(nach[0], tag)}."
        return (f"Ab {_uhr(ende)} gehört der Abend dir"
                + (", und morgen ist frei." if not status_morgen.get("arbeit") else "."))
    if not zeitlich:
        return "Der ganze Tag gehört dir, nichts steht im Kalender."
    if len(zeitlich) == 1:
        return f"Der Tag gehört dir, einziger fester Punkt: {_kurz(zeitlich[0], tag)}."
    return f"Der Tag gehört dir, der erste Termin ist {_kurz(zeitlich[0], tag)}."


HERZSCHLAG_TITEL = "MB-Herzschlag"
HERZSCHLAG_STUNDEN = 26  # so lange darf die nächtliche Aufräumaufgabe schweigen, dann warnt der Brief
FRIST_REGEL = re.compile(r"verlängert sich|kündigungsfrist|kündigen bis|zahlbar bis|zahlungsfrist|fällig am|"
                         r"läuft (am [^.]{0,25})?ab|wird [^.]{0,40}gesperrt|vor ablauf")
LASTSCHRIFT = re.compile(r"lastschrift|abgebucht|eingezogen|sepa|bereits bezahlt|zahlung erhalten")
VERDACHT = re.compile(r"ignoriere (alle |die )?(vorherigen |bisherigen )?(anweisungen|regeln)|"
                      r"ignore (all |any )?(previous |prior )?instructions|system ?prompt|du bist (jetzt|nun) |"
                      r"you are now |anweisung(en)? an (die|eine|den) (ki|assistent)|als (ki|sprachmodell)|"
                      r"as an ai|ordne diese mail|setze diese mail")


def frist_regel(text: str) -> bool:
    """Frist- und Abo-Mails, die nie verschluckt werden (nicht bei Lastschrift)."""
    t = (text or "").casefold()
    return bool(FRIST_REGEL.search(t)) and not LASTSCHRIFT.search(t)


def verdaechtig(text: str) -> bool:
    """Mail enthält Anweisungen an eine KI (Prompt-Injection)."""
    return bool(VERDACHT.search((text or "").casefold()))


def absender(p: dict) -> str:
    """Anzeigename mit echter Absenderdomain, wenn der Name sie nicht schon enthält (Schutz vor Täuschung)."""
    domain = (p.get("adresse") or "").split("@")[-1]
    return p["von"] if not domain or domain.casefold() in p["von"].casefold() else f"{p['von']} ({domain})"


def absender_woerter(text: str) -> set:
    """Wörter des Absenders (auch kurze wie "Amt"), um ihn in einem Kalendertitel mit ✓ wiederzuerkennen."""
    return {w for w in woerter(text) if not w.isdigit() and w not in STOPPWOERTER and w not in ALLGEMEINE_WOERTER
            and w not in ("com", "net", "org", "www")}


def herzschlag_pruefen(opt, jetzt: datetime) -> str:
    """Warnung, wenn die nächtliche Aufräumaufgabe den Herzschlag-Eintrag zu lange nicht aktualisiert hat."""
    try:
        treffer = [e for e in g.kalender_suche(opt, "primary", HERZSCHLAG_TITEL)
                   if (e.get("summary") or "").startswith(HERZSCHLAG_TITEL) and e.get("status") != "cancelled"]
    except g.GoogleFehler:
        return ""  # nicht prüfbar, der Rest des Briefs läuft weiter
    zeiten = [datetime.fromisoformat(e["updated"].replace("Z", "+00:00")).astimezone(TZ)
              for e in treffer if e.get("updated")]
    if not zeiten:
        return ("Der Kalendereintrag „MB-Herzschlag“ fehlt. Ob die nächtliche Aufräumaufgabe läuft, "
                "lässt sich nicht prüfen.")
    zuletzt = max(zeiten)
    if jetzt - zuletzt > timedelta(hours=HERZSCHLAG_STUNDEN):
        return (f"Die nächtliche Aufräumaufgabe hat sich zuletzt am {tage.datum_kurz(zuletzt.date())} um "
                f"{zuletzt:%H:%M} gemeldet. To-dos, ✓ und neue Fristen im Kalender können veraltet sein.")
    return ""


def _gedaechtnis_abgleich(opt, pfad, gemerkt, abgeschlossen, termine, eigene, heute, bezahlt=frozenset(),
                          heute_gezeigt=frozenset(), heute_weggelassen=frozenset(), im_brief_erledigt=frozenset(),
                          termin_pruefer=None):
    """Merkt die heute eingeordneten Punkte, prüft die alten und liefert die weiter offenen.

    Seit 1.4.0: Eine Zahlungsbestätigung mit derselben Rechnungsnummer schließt einen Punkt. Ungelesen abgelegte
    Mails (quelle "abgelegt") lagen nie im Posteingang, für sie gilt "archiviert" darum nicht als erledigt."""
    db = gedaechtnis.Gedaechtnis(pfad)
    try:
        for p, eintrag, frist in gemerkt:
            db.merken(p["thread"], eintrag, frist, absender_woerter(absender(p)), absender(p), heute,
                      quelle="abgelegt" if p.get("abgelegt") else "posteingang", nummern=p.get("nummern") or (),
                      termin=eintrag.get("_termin"))
        for tid in abgeschlossen:
            db.setzen(tid, "erledigt", "geklärt", heute)
        heute_da = {p["thread"] for p, _, _ in gemerkt} | set(heute_gezeigt)
        erledigt_woerter = [woerter(t["titel"]) for t in termine
                            if t["todo"] and t["titel"].lstrip().startswith("✓")]
        zurueck = []
        for pk in db.offene():
            if pk["thread"] in heute_weggelassen:  # seit 1.4.1: die neueste Mail im Thread braucht nichts mehr
                db.setzen(pk["thread"], "erledigt", "heute ohne Handlungsbedarf", heute)
                continue
            if pk["thread"] in im_brief_erledigt:  # seit 1.5.0: im Brief per Knopf erledigt oder bezahlt
                db.setzen(pk["thread"], "erledigt", "im Brief erledigt", heute)
                continue
            if pk.get("termin") and termin_pruefer:  # seit 1.5.0: Termin aus Mail inzwischen im Kalender?
                try:
                    t_datum = date.fromisoformat(pk["termin"].get("datum", ""))
                    t_zeit = (datetime.strptime(pk["termin"]["zeit"], "%H:%M").time()
                              if pk["termin"].get("zeit") else None)
                except (ValueError, TypeError):
                    t_datum = None
                if t_datum and t_datum < heute:
                    db.setzen(pk["thread"], "erledigt", "Termin vorbei", heute)
                    continue
                if t_datum and termin_pruefer(t_datum, t_zeit, pk["woerter"] | woerter_von(pk["titel"])):
                    db.setzen(pk["thread"], "erledigt", "Termin im Kalender", heute)
                    continue
            if pk["thread"] in heute_da:
                continue
            if pk["frist"]:
                zu_alt = heute > pk["frist"] + timedelta(days=gedaechtnis.NACH_FRIST_TAGE)
            else:
                zu_alt = heute > pk["erstmals"] + timedelta(days=gedaechtnis.OHNE_FRIST_TAGE)
            if zu_alt:
                db.setzen(pk["thread"], "alt", "zu alt", heute)
                continue
            if pk["nummern"] & set(bezahlt):
                db.setzen(pk["thread"], "erledigt", "Zahlung bestätigt", heute)
                continue
            if pk["woerter"] and any(pk["woerter"] & w for w in erledigt_woerter):
                db.setzen(pk["thread"], "erledigt", "Kalender ✓", heute)
                continue
            try:
                liste = _nachrichten(g.gmail_thread(opt, pk["thread"], voll=False), eigene)
            except g.GoogleFehler as fehler:
                if "404" not in str(fehler):
                    raise
                liste = []
            if not liste:
                db.setzen(pk["thread"], "erledigt", "Mail gelöscht", heute)
            elif pk["quelle"] != "abgelegt" and not any("INBOX" in n.labels for n in liste):
                db.setzen(pk["thread"], "erledigt", "archiviert", heute)
            elif liste[-1].eigen:
                db.setzen(pk["thread"], "wartet", "beantwortet", heute)
            else:
                zurueck.append(pk)
        db.aufraeumen(heute)
        return zurueck, db.zaehlen()
    finally:
        db.schliessen()


# ------------------------------------------------------------ Texthilfen

def sauber(text) -> str:
    """Lange Gedankenstriche entfernen und Leerraum glätten."""
    if not text:
        return ""
    text = str(text).replace(" – ", ", ").replace(" — ", ", ")
    text = text.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def kuerzen(text: str, laenge: int) -> str:
    text = text.strip()
    if len(text) <= laenge:
        return text
    return text[:laenge].rsplit(" ", 1)[0].rstrip(",.;:") + " …"


def kopf_text(wert: str) -> str:
    try:
        return str(make_header(decode_header(wert or "")))
    except Exception:
        return wert or ""


def relativ(zeit: datetime, heute: date) -> str:
    """heute 06:12, gestern 14:10 oder Di 10.11. 09:30"""
    uhr = zeit.strftime("%H:%M")
    if zeit.date() == heute:
        return f"heute {uhr}"
    if zeit.date() == heute - timedelta(days=1):
        return f"gestern {uhr}"
    return f"{tage.datum_kurz(zeit.date())} {uhr}"


class _HtmlText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.teile, self.stumm = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.stumm += 1
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
            self.teile.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.stumm:
            self.stumm -= 1

    def handle_data(self, data):
        if not self.stumm:
            self.teile.append(data)


def html_zu_text(quelle: str) -> str:
    p = _HtmlText()
    try:
        p.feed(quelle)
    except Exception:
        return re.sub(r"<[^>]+>", " ", quelle)
    return "".join(p.teile)


_ZITAT = re.compile(
    r"^(Am .{5,120} schrieb .*|On .{5,120} wrote:.*|-{2,} ?(Ursprüngliche Nachricht|Original Message).*"
    r"|Von: .*|From: .*|_{10,})$")


def ohne_zitat(text: str) -> str:
    """Zitierte Vorgänger-Mails abschneiden, damit nur der neue Text übrig bleibt."""
    zeilen = []
    for z in text.replace("\r", "").split("\n"):
        s = z.strip()
        if _ZITAT.match(s):
            break
        if s.startswith(">"):
            continue
        zeilen.append(s)
    text = "\n".join(zeilen)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _b64(daten: str) -> str:
    try:
        return base64.urlsafe_b64decode(daten + "=" * (-len(daten) % 4)).decode("utf-8", "replace")
    except Exception:
        return ""


def nachricht_text(payload: dict) -> str:
    """Text der Mail aus der Gmail-Struktur holen. Anhänge werden nie gelesen."""
    plain, htmlteile = [], []

    def lauf(teil):
        if teil.get("filename"):          # Anhang: überspringen
            return
        mime = teil.get("mimeType", "")
        daten = (teil.get("body") or {}).get("data")
        if mime == "text/plain" and daten:
            plain.append(_b64(daten))
        elif mime == "text/html" and daten:
            htmlteile.append(_b64(daten))
        for unter in teil.get("parts", []) or []:
            lauf(unter)

    lauf(payload or {})
    text = "\n".join(plain) if plain else html_zu_text("\n".join(htmlteile))
    return ohne_zitat(html.unescape(text))


# ----------------------------------------------------------- Mail-Modell

class Nachricht:
    def __init__(self, roh: dict, eigene: set):
        self.roh = roh
        self.labels = set(roh.get("labelIds", []))
        kopf = {}
        for h in (roh.get("payload") or {}).get("headers", []):
            kopf.setdefault(h.get("name", "").lower(), h.get("value", ""))
        self.kopf = kopf
        self.zeit = datetime.fromtimestamp(int(roh.get("internalDate", "0")) / 1000, TZ)
        von_kopf = kopf_text(kopf.get("from", ""))
        name, adresse = parseaddr(von_kopf)
        if not adresse:  # seit 1.4.0: Name mit Komma ohne Anführungszeichen ("Muster, Erika <a@b.de>")
            m = re.match(r'\s*(.*?)\s*<([^<>@\s]+@[^<>\s]+)>\s*$', von_kopf)
            if m:
                name, adresse = m.group(1).strip('" '), m.group(2)
        self.von_name = sauber(name) or adresse
        self.von_adresse = adresse.lower()
        self.betreff = sauber(kopf_text(kopf.get("subject", ""))) or "(ohne Betreff)"
        self.empfaenger = [(sauber(n), a.lower()) for n, a in
                           getaddresses([kopf_text(kopf.get("to", "")), kopf_text(kopf.get("cc", ""))]) if a]
        self.entwurf = "DRAFT" in self.labels
        self.eigen = "SENT" in self.labels or self.von_adresse in eigene
        self.snippet = sauber(html.unescape(roh.get("snippet", "")))

    def automatisch(self) -> bool:
        """Automatische Antworten (Abwesenheit, Eingangsbestätigung) zählen nicht als Antwort."""
        k = self.kopf
        if k.get("auto-submitted", "no").strip().lower() not in ("", "no"):
            return True
        if k.get("precedence", "").strip().lower() in ("bulk", "junk", "auto_reply", "list"):
            return True
        if k.get("x-autoreply") or k.get("x-autorespond"):
            return True
        lokal = self.von_adresse.split("@")[0]
        if re.search(r"(no-?reply|do-?not-?reply|nicht-?antworten|mailer-daemon|postmaster|noreply)", lokal):
            return True
        return bool(re.match(
            r"^(automatische antwort|automatic reply|auto(-|matische )?reply|abwesenheit|out of office|"
            r"eingangsbestätigung|empfangsbestätigung|ihre anfrage ist eingegangen)", self.betreff.casefold()))

    def text(self) -> str:
        return nachricht_text(self.roh.get("payload"))


def thread_link(konto: str, thread_id: str) -> str:
    from urllib.parse import quote
    return f"https://mail.google.com/mail/?authuser={quote(konto)}#all/{thread_id}"


def _nachrichten(thread: dict, eigene: set) -> list:
    liste = [Nachricht(m, eigene) for m in thread.get("messages", [])]
    liste = [n for n in liste if not n.entwurf]
    return sorted(liste, key=lambda n: n.zeit)


def posteingang_kandidat(thread: dict, eigene: set, jetzt: datetime):
    """Prüft einen Thread aus dem Posteingang. Liefert (letzte eingehende Nachricht, Antwort auf eigene Mail?) oder None."""
    liste = _nachrichten(thread, eigene)
    if not liste:
        return None
    letzte = liste[-1]
    if letzte.eigen:                     # er hat schon geantwortet (oder die Mail kommt von ihm selbst)
        return None
    if letzte.zeit < jetzt - timedelta(hours=FENSTER_STUNDEN):
        return None
    if "INBOX" not in letzte.labels:
        return None
    antwort_auf_eigene = any(n.eigen for n in liste[:-1])
    kurz = letzte.betreff + " " + letzte.snippet
    # Rechnungen und Fristen auch aus "Benachrichtigungen" und "Foren" (Rechnung seit 1.4.0), nie aus Werbung
    rechnung_oder_frist = "CATEGORY_PROMOTIONS" not in letzte.labels and (
        frist_regel(kurz) or bool(RECHNUNG.search(kurz.casefold())) or bool(OFFEN.search(kurz.casefold())))
    if letzte.labels & ANDERE_KATEGORIEN and not antwort_auf_eigene \
            and not immer_wichtig(letzte.von_adresse + " " + letzte.von_name) and not rechnung_oder_frist:
        return None                      # nur Kategorie "Allgemein", außer es ist eine Antwort an ihn
    return letzte, antwort_auf_eigene


def abgelegt_kandidat(thread: dict, eigene: set, jetzt: datetime):
    """Ungelesene Mail, die ein Gmail-Filter am Posteingang vorbei einsortiert hat (seit 1.4.0).

    Nur mögliche Rechnungen und Fristen, und nur ungelesene: Was du gelesen und abgelegt hast, gilt wie bei
    archivierten Mails als erledigt. Die genaue Prüfung mit dem ganzen Text folgt im Brieflauf."""
    liste = _nachrichten(thread, eigene)
    if not liste:
        return None
    letzte = liste[-1]
    if letzte.eigen or "INBOX" in letzte.labels or "UNREAD" not in letzte.labels:
        return None
    if letzte.labels & {"SPAM", "TRASH", "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"}:
        return None
    if letzte.zeit < jetzt - timedelta(hours=ABGELEGT_STUNDEN):
        return None
    if not (immer_wichtig(letzte.von_adresse + " " + letzte.von_name)
            or VORFILTER.search((letzte.betreff + " " + letzte.snippet).casefold())):
        return None
    return letzte


def zahlungen_bestaetigt(opt: dict, eigene: set) -> set:
    """Rechnungsnummern aus Zahlungsbestätigungen der letzten drei Wochen, auch abgelegte (seit 1.4.0).

    Beispiel: "Ihre Zahlung ist eingegangen (Rechnung Nr. 12345678)". Nur ausdrücklich genannte Nummern."""
    nummern = set()
    try:
        for tid in g.gmail_threads(opt, ZAHLUNG_SUCHE, 30):
            for n in _nachrichten(g.gmail_thread(opt, tid, voll=False), eigene):
                text = n.betreff + " " + n.snippet
                if not n.eigen and ZAHLUNG_BESTAETIGT.search(text.casefold()):
                    nummern |= rechnungsnummern("", text)
    except g.GoogleFehler as fehler:
        if fehler.art == "anmeldung":
            raise
        melde(f"Zahlungsbestätigungen nicht lesbar: {fehler}")
    return nummern


def wartet_kandidat(thread: dict, eigene: set, jetzt: datetime):
    """Prüft einen Thread mit gesendeter Mail. Liefert seine letzte Mail, wenn keine menschliche Antwort kam."""
    liste = _nachrichten(thread, eigene)
    meine = [n for n in liste if n.eigen]
    if not meine:
        return None
    letzte_eigene = meine[-1]
    alter = jetzt - letzte_eigene.zeit
    if alter < timedelta(days=WARTET_MIN_TAGE) or alter > timedelta(days=WARTET_MAX_TAGE):
        return None
    fremde = [(n, a) for n, a in letzte_eigene.empfaenger if a not in eigene and not re.search(r"no-?reply|do-?not-?reply", a)]
    if not fremde:                       # nur an eigene Adressen
        return None
    danach = [n for n in liste if n.zeit > letzte_eigene.zeit and not n.eigen]
    if any(not n.automatisch() for n in danach):
        return None                      # es kam eine menschliche Antwort
    return letzte_eigene


ANTWORT_TAGE = 7  # seit 1.6.2: so alt darf eine abgelegte Antwort sein, um noch einmal gemeldet zu werden


def antwort_abgelegt(thread: dict, eigene: set, jetzt: datetime):
    """Menschliche Antwort auf eine eigene Mail, die ein Gmail-Filter am Posteingang vorbei abgelegt hat (seit
    1.6.2, z. B. eine Antwort, die ein Filter direkt ins Label schiebt). Liegt sie im Posteingang, ordnet sie der normale Weg ein. Liefert
    (Antwort, eigene Mail davor) oder None."""
    liste = _nachrichten(thread, eigene)
    if len(liste) < 2:
        return None
    letzte = liste[-1]
    if letzte.eigen or letzte.automatisch() or "INBOX" in letzte.labels:
        return None
    if letzte.zeit < jetzt - timedelta(days=ANTWORT_TAGE):
        return None
    meine = [n for n in liste[:-1] if n.eigen]
    return (letzte, meine[-1]) if meine else None


# -------------------------------------------------------------- Kalender

def _termin_zeiten(ev: dict):
    s, e = ev.get("start", {}), ev.get("end", {})
    if "date" in s:
        start = datetime.combine(date.fromisoformat(s["date"]), datetime.min.time(), TZ)
        ende = datetime.combine(date.fromisoformat(e.get("date", s["date"])), datetime.min.time(), TZ)
        if ende <= start:
            ende = start + timedelta(days=1)
        return start, ende, True
    start = datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00")).astimezone(TZ)
    ende = datetime.fromisoformat(e.get("dateTime", s["dateTime"]).replace("Z", "+00:00")).astimezone(TZ)
    return start, ende, False


def _abgelehnt(ev: dict) -> bool:
    return any(a.get("self") and a.get("responseStatus") == "declined" for a in ev.get("attendees", []))


def _todo_notiz(ev: dict) -> str:
    """Text nach der Marke 'Aus der To-do-Liste:' als kurze Notiz."""
    text = sauber(html_zu_text(ev.get("description") or ""))
    if text.casefold().startswith(TODO_MARKE):
        text = text[len(TODO_MARKE):].strip(" :-")
        if text.startswith("(") and ")" in text:
            # "(nach der Alexa-Auswertung am 14.11.): Update ..." -> "Nach der Alexa-Auswertung am 14.11.: Update ..."
            zusatz, rest = text[1:].split(")", 1)
            rest = rest.strip(" :-")
            zusatz = zusatz.strip()
            text = (zusatz[:1].upper() + zusatz[1:] + (": " + rest if rest else "")) if zusatz else rest
    return kuerzen(text, TEXT_TODO_NOTIZ)


def _ist_todo(ev: dict) -> bool:
    beschreibung = html_zu_text(ev.get("description") or "").strip().casefold()
    return beschreibung.startswith(TODO_MARKE)


def termine_laden(opt, heute: date) -> list:
    """Alle Termine aus allen Kalendern: überfällige To-dos, heute und bis DEMNAECHST_TAGE voraus."""
    von = datetime.combine(heute - timedelta(days=TODO_UEBERFAELLIG_TAGE), datetime.min.time(), TZ)
    bis = datetime.combine(heute, datetime.min.time(), TZ) + timedelta(days=DEMNAECHST_TAGE + 1)
    gesehen, ergebnis = set(), []
    for kal in g.kalender_liste(opt):
        if kal.get("hidden") or kal.get("deleted") or (kal.get("summary") or "") == g.ABLAGE_NAME:
            continue  # die eigene Ablage (seit 1.5.0) ist kein Termin
        for ev in g.kalender_termine(opt, kal["id"], von.isoformat(), bis.isoformat()):
            if ev.get("status") == "cancelled" or _abgelehnt(ev) or "start" not in ev:
                continue
            try:
                start, ende, ganztag = _termin_zeiten(ev)
            except (KeyError, ValueError):
                continue
            schluessel = (ev.get("iCalUID") or ev.get("id"), start.isoformat())
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            ergebnis.append({
                "titel": sauber(ev.get("summary")) or "(ohne Titel)",
                "start": start, "ende": ende, "ganztag": ganztag, "id": ev.get("id", ""),
                "ort": sauber(ev.get("location")),  # seit 1.5.0 für Fahrten
                "link": ev.get("htmlLink", ""), "todo": _ist_todo(ev),
                "notiz": _todo_notiz(ev) if _ist_todo(ev) else "",
                "beschreibung": kuerzen(sauber(html_zu_text(ev.get("description") or "")), 200),
                "kalender": sauber(kal.get("summaryOverride") or kal.get("summary")),
                # seit 1.6.2: Serie, als "frei" markiert und letzte Änderung (Nächste Tage, überholte Einträge)
                "serie": bool(ev.get("recurringEventId")), "frei_markiert": ev.get("transparency") == "transparent",
                "geaendert": ev.get("updated", ""),
            })
    return ergebnis


def am_tag(termine: list, tag: date) -> list:
    a = datetime.combine(tag, datetime.min.time(), TZ)
    b = a + timedelta(days=1)
    treffer = [t for t in termine if t["start"] < b and t["ende"] > a]
    return sorted(treffer, key=lambda t: (not t["ganztag"], t["start"], t["titel"]))


def zeit_text(t: dict, tag: date) -> str:
    if t["ganztag"]:
        letzter = (t["ende"] - timedelta(days=1)).date()
        if letzter > tag:
            return f"ganztägig, bis {tage.datum_kurz(letzter)}"
        return "ganztägig"
    a = datetime.combine(tag, datetime.min.time(), TZ)
    b = a + timedelta(days=1)
    beginnt_heute, endet_heute = t["start"] >= a, t["ende"] <= b
    if beginnt_heute and endet_heute:
        if t["ende"] == t["start"]:
            return t["start"].strftime("%H:%M")
        return f"{t['start']:%H:%M} bis {t['ende']:%H:%M}"
    if beginnt_heute:
        return f"ab {t['start']:%H:%M}"
    if endet_heute:
        return f"bis {t['ende']:%H:%M}"
    return "ganztägig"


def _fuer_seite(t: dict, tag: date) -> dict:
    return {"zeit": zeit_text(t, tag), "titel": t["titel"], "link": t["link"]}



def _uhr(zeit: datetime) -> str:
    return f"{zeit.hour}:{zeit:%M}"


def _kurz(t: dict, tag: date) -> str:
    """Für Morgen-Zeile und Unterzeile: nur Startzeit, Titel unverändert."""
    if t["ganztag"]:
        letzter = (t["ende"] - timedelta(days=1)).date()
        return t["titel"] + (f" (bis {tage.datum_kurz(letzter)})" if letzter > tag else "")
    if t["start"].date() == tag:
        return f"{_uhr(t['start'])} {t['titel']}"
    return f"{zeit_text(t, tag)} {t['titel']}"


def _feierabend(status: dict, tag: date) -> datetime:
    return datetime.combine(tag, datetime.min.time(), TZ) + timedelta(hours=15 if status.get("kurz") else 17)


def morgen_zeile(status: dict, liste: list, tag: date, nur_status: bool = False) -> str:
    """'Morgen (Mi) frei: 10:00 Sauna, 17:00 Rechnungs-Backup.' oder 'Morgen (Do) Arbeit 7:30 bis 17:00, danach: ...'"""
    wt = tage.WOCHENTAGE_KURZ[tag.weekday()]
    if status.get("arbeit"):
        ende = _feierabend(status, tag)
        kopf = f"Morgen ({wt}) Arbeit 7:30 bis {_uhr(ende)}" + (" (Kurztag)" if status.get("kurz") else "")
        verbinder = ", danach: " if all(not t["ganztag"] and t["start"] >= ende for t in liste) else ": "
    else:
        # seit 1.6.0 "keine Arbeit" statt "frei", die Termine danach als eigener Satz (vorher mehrdeutig:
        # "Morgen (So) frei: 12:00 Essen mit Freunden")
        grund = status.get("zeile", "")
        grund = grund[len("Frei: "):] if grund.startswith("Frei: ") else ""
        grund = grund.split(",")[0].strip()
        kopf = f"Morgen ({wt}) keine Arbeit" + (f" ({grund})" if grund and grund not in ("Mittwoch", "Wochenende")
                                                else "")
        verbinder = ". Im Kalender: "
    if nur_status:
        return kopf + "."
    if not liste:
        return kopf + "." + (" Nichts im Kalender." if not status.get("arbeit") else "")
    teile = [_kurz(t, tag) for t in liste[:5]]
    rest = f" und {len(liste) - 5} weitere" if len(liste) > 5 else ""
    return kopf + verbinder + ", ".join(teile) + rest + "."


def unterzeile(status: dict, liste: list, tag: date, status_morgen: dict) -> str:
    """Satz unter der Überschrift: wiederholt nicht die Arbeitszeit, sondern nennt, was danach kommt."""
    zeitlich = [t for t in liste if not t["ganztag"]]
    if status.get("arbeit"):
        ende = _feierabend(status, tag)
        nach = [t for t in zeitlich if t["start"] >= ende]
        if nach:
            return f"Nach Feierabend: {_kurz(nach[0], tag)}."
        return "Nach Feierabend nichts im Kalender, " + ("morgen Arbeit." if status_morgen.get("arbeit") else "morgen frei.")
    if zeitlich:
        return f"Erster Termin: {_kurz(zeitlich[0], tag)}."
    return "Der ganze Tag ist frei."


# ------------------------------------------------------------- Der Brief

def verkehr_pruefen(opt: dict, status: dict, jetzt: datetime, pfad: str, hinweise: list):
    """Abfahrtszeit mit Verkehr (seit 1.3.6), nur an Arbeitstagen und nur mit TomTom-Schlüssel und Adressen."""
    if not (status.get("arbeit") and pfad and opt.get("tomtom_api_key")
            and (opt.get("verkehr_start") or "").strip() and (opt.get("verkehr_ziel") or "").strip()):
        return None
    t0 = time.monotonic()
    try:
        v = verkehr.abfahrt(opt, jetzt, pfad)
    except verkehr.VerkehrFehler as e:
        melde(f"Verkehr ohne Ergebnis: {e}")
        hinweise.append(f"Verkehr nicht abrufbar: {e}.")
        return None
    except Exception as e:  # der Verkehr ist Zugabe, der Brief darf daran nicht scheitern
        melde(f"Verkehr ohne Ergebnis: {type(e).__name__}")
        hinweise.append("Verkehr nicht abrufbar.")
        return None
    melde(f"Verkehr gelesen: {v['fahrt_min']} Min., +{v['extra_min']} Min., "
          f"{len(v['meldungen'])} Meldungen, {'Prognose zur Abfahrt' if v.get('prognose') else 'Verkehr von jetzt'} "
          f"in {time.monotonic() - t0:.0f} s")
    return v


# ------------------------------------------------------------ Termine aus Mails (seit 1.5.0)
TERMIN_TEXT = re.compile(r"\btermin(?:e|s)?\b[^.\n]{0,40}?\b(?:am|für den|für)\s+(?:[a-zäöü]+,?\s+)?(?:den\s+)?"
                         r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})?(?:[^\d\n]{0,25}?(?:um|ab|gegen)\s+(\d{1,2})"
                         r"(?:[:.](\d{2}))?\s*uhr)?")
TERMIN_GEMINI = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}):(\d{2}))?")


def termin_lesen(e: dict, text: str, heute: date):
    """Termin aus der Gemini-Einordnung ("termin", "ort") oder aus dem Text ("Termin am Mittwoch, den 14.04.2031
    um 08:45 Uhr"). Liefert (datum, uhrzeit oder None, ort) oder None, wenn keiner da ist oder er vorbei ist."""
    datum = zeit = None
    ort = sauber((e or {}).get("ort"))
    m = TERMIN_GEMINI.match(str((e or {}).get("termin") or "").strip())
    if m:
        try:
            datum = date.fromisoformat(m.group(1))
            if m.group(2):
                zeit = datetime.min.time().replace(hour=int(m.group(2)) % 24, minute=int(m.group(3)) % 60)
        except ValueError:
            datum = None
    if datum is None:
        m = TERMIN_TEXT.search((text or "").casefold())
        if not m:
            return None
        jahr = int(m.group(3)) if m.group(3) else heute.year
        jahr += 2000 if jahr < 100 else 0
        try:
            datum = date(jahr, int(m.group(2)), int(m.group(1)))
            if m.group(4):
                zeit = datetime.min.time().replace(hour=int(m.group(4)) % 24, minute=int(m.group(5) or 0) % 60)
        except ValueError:
            return None
        if not m.group(3) and datum < heute - timedelta(days=60):
            datum = datum.replace(year=jahr + 1)
    if datum < heute:
        return None
    return datum, zeit, ort


def termin_im_kalender(opt, datum: date, zeit, woerter: set, termine: list, heute: date) -> bool:
    """Steht der Termin schon im Kalender? Gleiche Uhrzeit (plus/minus 60 Min.) oder ein Stichwort am selben Tag."""
    if datum <= heute + timedelta(days=DEMNAECHST_TAGE):
        am = [t for t in am_tag(termine, datum) if not t["todo"]]
    else:  # weiter voraus als die geladenen Termine: diesen Tag eigens abfragen
        am = []
        try:
            von = datetime.combine(datum, datetime.min.time(), TZ)
            for kal in g.kalender_liste(opt):
                if kal.get("hidden") or kal.get("deleted") or (kal.get("summary") or "") == g.ABLAGE_NAME:
                    continue
                for ev in g.kalender_termine(opt, kal["id"], von.isoformat(), (von + timedelta(days=1)).isoformat()):
                    if ev.get("status") != "cancelled" and "start" in ev:
                        s, en, ganz = _termin_zeiten(ev)
                        am.append({"titel": sauber(ev.get("summary")), "start": s, "ganztag": ganz})
        except (g.GoogleFehler, KeyError, ValueError):
            return False
    for t in am:
        if zeit and not t["ganztag"]:
            soll = datetime.combine(datum, zeit, TZ)
            if abs((t["start"] - soll).total_seconds()) <= 3600:
                return True
        if woerter and woerter & woerter_von(t["titel"]):
            return True
    return False


def woerter_von(text: str) -> set:
    return {w for w in woerter(text) if len(w) >= 4 and w not in STOPPWOERTER and w not in ALLGEMEINE_WOERTER}


def kalender_vorlage(titel: str, datum: date, zeit, ort: str, details: str) -> str:
    """Link zu Google Kalender mit vorausgefülltem Termin. Eintragen tust du selbst (seit 1.5.0)."""
    from urllib.parse import urlencode
    if zeit:
        beginn = datetime.combine(datum, zeit)
        daten = f"{beginn:%Y%m%dT%H%M%S}/{beginn + timedelta(hours=1):%Y%m%dT%H%M%S}"
    else:
        daten = f"{datum:%Y%m%d}/{datum + timedelta(days=1):%Y%m%d}"
    return "https://calendar.google.com/calendar/render?" + urlencode(
        {"action": "TEMPLATE", "text": titel[:100], "dates": daten, "ctz": "Europe/Berlin", "location": ort[:150],
         "details": details[:500]})


# ------------------------------------------------------------ Fahrten (seit 1.5.0)
FAHRT = re.compile(r"^\s*(?:auto)?fahrt\s+(?:nach|zu[rm]?|ins?)\s+(.+?)\s*$|^\s*nach\s+(.+?)\s+fahren\s*$", re.I)
OHNE_FAHRT = re.compile(r"https?://|zoom|teams|meet\.google|online|telefon|anruf|webex|videokonferenz", re.I)
FAHRTEN_HOECHSTENS = 3


def _dauer(minuten: int) -> str:
    return f"{minuten // 60}:{minuten % 60:02d} Std." if minuten >= 60 else f"{minuten} Min."


def fahrten_planen(opt: dict, tag_termine: list, jetzt: datetime, pfad: str, hinweise: list) -> list:
    """Abfahrtszeiten für Fahrten und Termine mit Ort an einem Tag (TomTom).

    "Fahrt nach München" 10:00 bis 11:00 (seit 1.6.0): Der Termin ist die Fahrt selbst, los geht es zu seinem
    Beginn. Der Brief nennt Fahrzeit und Ankunft, warnt, wenn die Ankunft nach dem geplanten Ende liegt, und nennt
    eine spätere oder etwas frühere Abfahrt nur, wenn sie deutlich Zeit spart (bis 1.5.0 wurde die Startzeit wie
    eine Wunschzeit behandelt und z. B. "am besten 9:00 los" empfohlen).
    Termin mit Ort (z. B. Zahnarzt in Musterstadt um 8:45): spätestens losfahren, Ankunft 5 Minuten vorher."""
    if not (pfad and opt.get("tomtom_api_key") and (opt.get("verkehr_start") or "").strip()):
        return []
    zuhause = (opt.get("verkehr_start") or "").split(",")[0].strip().casefold()
    arbeit = (opt.get("verkehr_ziel") or "").split(",")[0].strip().casefold()
    ergebnis = []
    for t in tag_termine:
        if t["ganztag"] or t["todo"] or t["start"] < jetzt + timedelta(minutes=10):
            continue
        m = FAHRT.match(t["titel"])
        ort = (t.get("ort") or "").strip()
        if m:
            modus, ziel = "fahrt", ort or (m.group(1) or m.group(2))
        elif ort and not OHNE_FAHRT.search(ort) and not (zuhause and zuhause in ort.casefold()) \
                and not (arbeit and arbeit in ort.casefold()):
            modus, ziel = "ankunft", ort
        else:
            continue
        try:
            v = verkehr.fahrt_planen(opt, pfad, jetzt, ziel, t["start"], modus)
        except verkehr.VerkehrFehler as e:
            hinweise.append(f"Fahrt zu „{t['titel']}“ nicht berechnet: {e}.")
            continue
        except Exception as e:  # Zugabe, der Brief darf daran nicht scheitern
            melde(f"Fahrt ohne Ergebnis: {type(e).__name__}")
            continue
        los = v["losfahren"]
        uber = (", über " + ", ".join(v["strassen"])) if v.get("strassen") else ""
        if modus == "fahrt":
            name = (m.group(1) or m.group(2)) if m else ziel
            an = los + timedelta(minutes=v["fahrt_min"])
            zeile = (f"Fahrt nach {name}: los um {verkehr.uhr(los)}, an etwa {verkehr.uhr(an)} "
                     f"({_dauer(v['fahrt_min'])}{uber})")
            if t["ende"] > t["start"] and an > t["ende"] + timedelta(minutes=5):
                zeile += f". Das ist später als das geplante Ende um {verkehr.uhr(t['ende'])}"
            alt = v.get("alternative")
            if alt:
                zeile += (f". Um {verkehr.uhr(alt['losfahren'])} los wären es nur {_dauer(alt['fahrt_min'])}")
            kurz = f"{verkehr.uhr(los)} los nach {name}"
        else:
            zeile = f"Losfahren bis {verkehr.uhr(los)} zu {t['titel']} ({_dauer(v['fahrt_min'])}{uber})"
            kurz = f"{verkehr.uhr(los)} los zu {t['titel']}"
        ergebnis.append({"titel": t["titel"], "zeile": zeile, "kurz": kurz, "modus": modus,
                         "losfahren": los.isoformat(timespec="minutes"), "termin": t["start"].isoformat(timespec="minutes"),
                         "push_um": (los - timedelta(minutes=20)).isoformat(timespec="minutes"),
                         "ziel": list(v["ziel_pos"]), "link": verkehr.karten_link(v["ziel_pos"]),
                         "schluessel": kal_schluessel(t)})
        melde(f"Fahrt geplant: {v['fahrt_min']} Min., {v.get('abfragen', 0)} Abfragen")
        if len(ergebnis) >= FAHRTEN_HOECHSTENS:
            break
    return ergebnis


def fahrten_fuer_tag(opt: dict, tag: date, jetzt: datetime, pfad: str) -> list:
    """Für den Abend-Push: Fahrten von morgen (lädt den Kalender neu)."""
    termine = termine_laden(opt, jetzt.date())
    return fahrten_planen(opt, am_tag(termine, tag), jetzt, pfad, [])


# ------------------------------------------------------------ Überschneidungen, Woche, Geburtstage (seit 1.6.0)
KONFLIKT_TAGE = 7       # so weit voraus prüft der Brief Überschneidungen
KONFLIKTE_HOECHSTENS = 6
WOCHE_TAGE = 2          # "Nächste Tage" im Kalenderblock: morgen bis heute + WOCHE_TAGE (1.6.1: 2 statt 7)
WICHTIG_TAGE = 2        # 1.6.2: einmalige feste Termine bis heute + 7 zusätzlich; 1.6.3 wieder aus (Wunsch: nur
                        # morgen und übermorgen). Größer als WOCHE_TAGE schaltet die Erweiterung wieder ein.
DOPPELT_ANTEIL = 0.6    # seit 1.6.2: so viele Schlüsselwörter gemeinsam (vom kürzeren Titel): vermutlich derselbe Eintrag
ABGESAGT = re.compile(r"^\s*(abgesagt|fällt aus|entfällt|storniert|cancelled)\b", re.I)
GEBURTSTAG = re.compile(r"geburtstag|\bgeb\.|birthday", re.I)


def _zaehlt_als_termin(t: dict) -> bool:
    titel = t["titel"]
    return not (titel.lstrip().startswith("✓") or tage.ist_statusmarke(titel) or ABGESAGT.match(titel)
                or titel.startswith(HERZSCHLAG_TITEL))


def _zeitraum(t: dict, tag: date) -> str:
    if t["start"].date() == tag and t["ende"].date() == tag and t["ende"] > t["start"]:
        return f"{_uhr(t['start'])} bis {_uhr(t['ende'])}"
    return _uhr(t["start"]) if t["start"].date() == tag else zeit_text(t, tag)


def vermutlich_doppelt(a: dict, b: dict, tag: date):
    """Zwei sich überschneidende Einträge zur selben Sache (seit 1.6.2), z. B. „HA: Better Thermostat 2.0.0 erneut
    prüfen“ und „HA: Better Thermostat 2.0.1 Update“. Der zuletzt geänderte gilt als aktuell, der andere als
    vermutlich überholt. Liefert den Eintrag für "Braucht dich" oder None."""
    wa, wb = schluesselwoerter(a["titel"]), schluesselwoerter(b["titel"])
    if not wa or not wb or len(wa & wb) < 2 and min(len(wa), len(wb)) > 1:
        return None
    if len(wa & wb) / min(len(wa), len(wb)) < DOPPELT_ANTEIL:
        return None
    neu, alt = (a, b) if (a.get("geaendert") or "") >= (b.get("geaendert") or "") else (b, a)
    geaendert = ""
    try:
        geaendert = tage.datum_kurz(datetime.fromisoformat(neu["geaendert"].replace("Z", "+00:00")).astimezone(TZ).date())
    except (KeyError, ValueError, AttributeError):
        pass
    return {"titel": f"Eintrag vermutlich überholt: {alt['titel']}",
            "quelle": f"Kalender, {tage.datum_kurz(tag)} {_uhr(alt['start'])}.",
            "satz": f"Zur selben Zeit steht „{neu['titel']}“" + (f" (zuletzt geändert {geaendert})" if geaendert else "")
                    + ". Einen der beiden löschen?",
            "link": alt["link"] or neu["link"], "art": "doppelt", "_tag": tag}


def konflikte(termine: list, heute: date, jetzt: datetime, arbeit_ort: str = "") -> list:
    """Überschneidungen im Kalender und mit der Arbeitszeit, heute bis heute + KONFLIKT_TAGE.

    Zählen nur Einträge mit Uhrzeit und Dauer (auch To-dos mit Uhrzeit), keine ganztägigen, keine ✓, keine
    Statusmarken (Kurztag, Urlaub), keine abgesagten. Arbeitszeit wie im Tagesstatus: Mo/Di/Do/Fr 7:30 bis 17:00
    bzw. 15:00 bei Kurztag, nicht an Feiertagen, im Urlaub, am 24. und 31.12."""
    ergebnis = []
    arbeit_ort = (arbeit_ort or "").split(",")[0].strip().casefold()
    for n in range(KONFLIKT_TAGE + 1):
        tag = heute + timedelta(days=n)
        alle = am_tag(termine, tag)
        liste = [t for t in alle if not t["ganztag"] and t["ende"] > t["start"] and t["ende"] > jetzt
                 and t["start"].date() == tag and _zaehlt_als_termin(t)]
        liste.sort(key=lambda t: t["start"])
        wann = "heute" if n == 0 else "morgen" if n == 1 else tage.datum_kurz(tag)
        for i, a in enumerate(liste):
            for b in liste[i + 1:]:
                if b["start"] < a["ende"] and a["start"] < b["ende"]:
                    doppelt = vermutlich_doppelt(a, b, tag)
                    if doppelt:
                        ergebnis.append(doppelt)
                        continue
                    ergebnis.append({
                        "titel": f"Überschneidung {wann}: {a['titel']} und {b['titel']}",
                        "quelle": "Kalender.",
                        "satz": f"{a['titel']} {_zeitraum(a, tag)}, {b['titel']} {_zeitraum(b, tag)}.",
                        "link": b["link"] or a["link"], "art": "konflikt", "_tag": tag})
        status = tage.tagesstatus(tag, [t["titel"] for t in alle])
        if status.get("arbeit"):
            beginn = datetime.combine(tag, datetime.min.time(), TZ) + timedelta(hours=7, minutes=30)
            ende = _feierabend(status, tag)
            for t in liste:
                if t["start"] < ende and beginn < t["ende"] and not (arbeit_ort and arbeit_ort in (t.get("ort") or "").casefold()):
                    ergebnis.append({
                        "titel": f"In der Arbeitszeit {wann}: {t['titel']}",
                        "quelle": "Kalender.",
                        "satz": f"{_zeitraum(t, tag)}, Arbeit {_uhr(beginn)} bis {_uhr(ende)}. Urlaub, Gleitzeit "
                                "oder Verschieben klären.",
                        "link": t["link"], "art": "konflikt", "_tag": tag})
    return ergebnis[:KONFLIKTE_HOECHSTENS]


def _einzeltermin(t: dict) -> bool:
    """Einmaliger fester Termin (seit 1.6.2): mit Uhrzeit, keine Serie, nicht als "frei" markiert."""
    return not t["ganztag"] and not t.get("serie") and not t.get("frei_markiert")


def woche_termine(termine: list, heute: date) -> list:
    """Echte Termine von morgen bis heute + WOCHE_TAGE für den Kalenderblock (seit 1.6.0, vorher fehlten
    normale Termine nach morgen ganz). Seit 1.6.1 nur morgen und übermorgen (sonst zu viel), die
    Morgen-Zeile nennt dann nur noch den Tagesstatus. To-dos stehen unter "Offene To-dos".

    Seit 1.6.2 zusätzlich bis heute + WICHTIG_TAGE die einmaligen festen Termine (z. B. Behörde, Werkstatt), keine
    Serien wie Yoga oder Sauna, keine als "frei" markierten Erinnerungen. Abgesagte Termine von morgen und
    übermorgen stehen als "X entfällt" da, statt still zu fehlen."""
    ergebnis = []
    for n in range(1, WICHTIG_TAGE + 1):
        tag = heute + timedelta(days=n)
        status = tage.tagesstatus(tag, [t["titel"] for t in am_tag(termine, tag)])
        for t in am_tag(termine, tag):
            if t["todo"] or t["start"].date() != tag:
                continue
            titel = t["titel"]
            m = ABGESAGT.match(titel)
            if m and n <= WOCHE_TAGE and not t["ganztag"]:
                titel = (titel[m.end():].strip(" :-,") or "Termin") + " entfällt"
            elif not _zaehlt_als_termin(t):
                continue
            elif n > WOCHE_TAGE and not _einzeltermin(t):
                continue
            zeit = tage.datum_kurz(tag) + ("" if t["ganztag"] else f" {t['start']:%H:%M}")
            ergebnis.append({"zeit": zeit, "titel": titel, "link": t["link"],
                             "frei": "" if status.get("arbeit") else status.get("push", "")})
    return ergebnis


def gratulieren(heute_alle: list, heute: date, erledigt: dict) -> list:
    """Geburtstag heute (ganztägiger Eintrag) als Aufgabe unter "Braucht dich" (seit 1.6.0)."""
    ergebnis = []
    for t in heute_alle:
        if not t["ganztag"] or t["todo"] or not GEBURTSTAG.search(t["titel"]) or t["start"].date() != heute:
            continue
        schluessel = f"geb:{t.get('id') or t['titel']}:{heute.isoformat()}"
        if schluessel in erledigt:
            continue
        m = re.match(r"^\s*(.+?)\s+(?:hat|feiert)\s+geburtstag", t["titel"], re.I) or \
            re.match(r"^\s*geburtstag(?:\s+(?:von|:))?\s+(.+?)\s*$", t["titel"], re.I)
        name = m.group(1).strip() if m else ""
        ergebnis.append({"titel": f"{name} gratulieren" if name else f"Gratulieren: {t['titel']}",
                         "quelle": "Kalender, heute.", "satz": t["titel"] + ".", "link": t["link"],
                         "schluessel": schluessel, "art": "geburtstag"})
    return ergebnis


def einordnung_holen(opt, pfad, posteingang, gesendet, termine_pruefen, status, heute, jetzt, hinweise):
    """Einordnung aus der Merkliste, nur Neues geht an Gemini (seit 1.4.0).

    Liefert (post, gesendet, termine, info): je ein dict von der Kurz-ID ("p3", "g1", "k2") zur Einordnung.
    Mails ohne Einordnung (Gemini nicht erreichbar oder Grenze erreicht) fehlen in post. info["tokens"] nennt
    den Verbrauch der Anfrage laut Gemini."""
    info = {"genutzt": True, "modell": "", "fehler": "", "tokens": 0, "neu": 0}
    post, ges, term = {}, {}, {}
    db = None
    if pfad:
        try:
            db = gedaechtnis.Gedaechtnis(pfad)
        except Exception as fehler:  # ohne Merkliste geht eben alles an Gemini
            melde(f"Merkliste nicht nutzbar: {type(fehler).__name__}")
    try:
        if db:
            alt = db.einordnungen(EINORDNUNG_ART["post"], [p["mid"] for p in posteingang])
            post = {p["id"]: alt[p["mid"]] for p in posteingang if p["mid"] in alt}
            alt = db.einordnungen(EINORDNUNG_ART["gesendet"], [s["mid"] for s in gesendet])
            ges = {s["id"]: alt[s["mid"]] for s in gesendet if s["mid"] in alt}
            alt = db.einordnungen(EINORDNUNG_ART["termin"], [k["schluessel"] for k in termine_pruefen])
            term = {k["id"]: alt[k["schluessel"]] for k in termine_pruefen if k["schluessel"] in alt}
        neu_post = [p for p in posteingang if p["id"] not in post][:MAX_NEU_AN_GEMINI]
        neu_ges = [s for s in gesendet if s["id"] not in ges]
        neu_term = [k for k in termine_pruefen if k["id"] not in term]
        if not (neu_post or neu_ges or neu_term):
            info["modell"] = "keine Anfrage nötig"
            return post, ges, term, info
        if not opt.get("gemini_api_key"):
            info["fehler"] = "Kein Gemini-Schlüssel eingetragen"
            return post, ges, term, info
        t0 = time.monotonic()
        anfrage = {
            "heute": f"{tage.datum_lang(heute)}, {jetzt:%H:%M} Uhr",
            "tagesstatus": status["zeile"] + (" (Arbeitstag, Feierabend " + _uhr(_feierabend(status, heute)) + ")"
                                              if status.get("arbeit") else " (freier Tag)"),
            "posteingang": [{
                "id": p["id"], "von": f"{p['von']} <{p['adresse']}>", "betreff": p["betreff"],
                "eingang": relativ(p["zeit"], heute), "antwort_auf_eigene_mail": p["antwort"],
                "text": p["text"]} for p in neu_post],
            "gesendet": [{
                "id": s["id"], "an": s["an"], "betreff": s["betreff"],
                "gesendet_am": f"{tage.datum_kurz(s['zeit'].date())}", "text": s["text"]} for s in neu_ges],
            "termine_heute_morgen": [{"id": k["id"], "tag": k["tag"], "titel": k["titel"], "zeit": k["zeit"],
                                      "beschreibung": k["beschreibung"]} for k in neu_term],
        }
        try:
            modell = gemini.modell_waehlen(opt["gemini_api_key"], opt.get("gemini_modell", "auto"))
            info["modell"] = modell
            try:
                gemini.ZEITLIMIT = gemini.ZEITLIMIT_HAUPT
                antwort = gemini.einordnen(opt["gemini_api_key"], modell, anfrage)
            except gemini.GeminiFehler as e:
                # Limit erreicht oder Modell nicht verfügbar: einmal das kleinere Flash-Lite-Modell versuchen
                melde(f"Gemini ({modell}) nach {time.monotonic() - t0:.0f} s ohne Ergebnis: {e}")
                ersatz = gemini.ersatzmodell(opt["gemini_api_key"], modell) if e.status in (404, 429, 503, 598) else ""
                if not ersatz:
                    raise
                gemini.ZEITLIMIT = gemini.ZEITLIMIT_ERSATZ
                antwort = gemini.einordnen(opt["gemini_api_key"], ersatz, anfrage)
                info["modell"] = ersatz
                hinweise.append(f"Gemini: {modell} war nicht verfügbar ({e.status}), eingeordnet hat {ersatz}.")
        except gemini.GeminiFehler as e:
            info["fehler"] = str(e)
            melde(f"Gemini ohne Ergebnis nach {time.monotonic() - t0:.0f} s: {e}")
            return post, ges, term, info
        nutzung = gemini.LETZTE_NUTZUNG or {}
        info["tokens"] = int(nutzung.get("totalTokenCount") or 0)
        info["neu"] = len(neu_post) + len(neu_ges) + len(neu_term)
        melde(f"Gemini ({info['modell']}) hat {len(neu_post)} Mails, {len(neu_ges)} gesendete und {len(neu_term)} "
              f"Termine eingeordnet: {info['tokens']} Tokens ({nutzung.get('promptTokenCount', 0)} rein, "
              f"{nutzung.get('candidatesTokenCount', 0)} raus), {time.monotonic() - t0:.0f} s")
        nach_post = {p["id"]: p for p in neu_post}
        for e in antwort.get("posteingang") or []:
            if isinstance(e, dict) and e.get("id") in nach_post and e["id"] not in post:
                daten = {k: e.get(k) or "" for k in ("liste", "titel", "satz", "frist", "termin", "ort", "folge")}
                post[e["id"]] = daten
                if db:
                    db.einordnung_merken(EINORDNUNG_ART["post"], nach_post[e["id"]]["mid"], daten, heute)
        for p in neu_post:  # von Gemini vergessen: lieber zeigen als verschlucken (wird nicht gemerkt)
            post.setdefault(p["id"], {"liste": "braucht_dich", "titel": "", "satz": "", "frist": ""})
        nach_ges = {s["id"]: s for s in neu_ges}
        for e in antwort.get("gesendet") or []:
            if isinstance(e, dict) and e.get("id") in nach_ges and e["id"] not in ges:
                daten = {"erwartet_antwort": e.get("erwartet_antwort"), "thema": e.get("thema") or ""}
                ges[e["id"]] = daten
                if db:
                    db.einordnung_merken(EINORDNUNG_ART["gesendet"], nach_ges[e["id"]]["mid"], daten, heute)
        gemeldet = {e.get("id"): e for e in antwort.get("termine") or [] if isinstance(e, dict)}
        for k in neu_term:  # nicht gemeldete Einträge brauchen keine Warnung, auch das wird gemerkt
            e = gemeldet.get(k["id"]) or {}
            daten = {"titel": e.get("titel") or "", "satz": e.get("satz") or ""}
            term[k["id"]] = daten
            if db:
                db.einordnung_merken(EINORDNUNG_ART["termin"], k["schluessel"], daten, heute)
        return post, ges, term, info
    finally:
        if db:
            db.schliessen()


def antworten_melden(antworten: list, pfad: str, konto: str, heute: date) -> list:
    """Einträge für "Schon geklärt" aus abgelegten Antworten (seit 1.6.2). Jede Antwort erscheint nur an dem Tag,
    an dem ein Brief sie zuerst gesehen hat (Merkliste, Art "gemeldet"); weitere Läufe am selben Tag zeigen sie
    wieder. Ohne Merkliste: nur Antworten der letzten FRISCH_STUNDEN."""
    if not antworten:
        return []
    db = None
    if pfad:
        try:
            db = gedaechtnis.Gedaechtnis(pfad)
        except Exception as fehler:
            melde(f"Merkliste nicht nutzbar: {type(fehler).__name__}")
    ergebnis = []
    try:
        alt = db.einordnungen("gemeldet", [n.roh.get("id") for _, n, _ in antworten]) if db else {}
        for tid, n, meine in sorted(antworten, key=lambda a: a[1].zeit, reverse=True):
            mid = n.roh.get("id") or tid
            if db:
                if mid in alt and alt[mid].get("datum") != heute.isoformat():
                    continue
                if mid not in alt:
                    db.einordnung_merken("gemeldet", mid, {"datum": heute.isoformat()}, heute)
            elif n.zeit.date() < heute - timedelta(days=FRISCH_STUNDEN // 24):
                continue
            ergebnis.append({
                "titel": f"Antwort von {n.von_name}: {meine.betreff}",
                "quelle": f"Antwort auf deine Mail vom {tage.datum_kurz(meine.zeit.date())}, eingegangen "
                          f"{tage.datum_kurz(n.zeit.date())}, abgelegt (nicht im Posteingang).",
                "satz": kuerzen(n.snippet, 200), "link": thread_link(konto, tid)})
    finally:
        if db:
            db.schliessen()
    return ergebnis


def erzeuge_brief(opt: dict, jetzt: datetime = None, gedaechtnis_pfad: str = None, verkehr_pfad: str = None,
                  erledigt: dict = None) -> dict:
    """erledigt (seit 1.5.0): im Brief als erledigt oder bezahlt markierte Punkte {schluessel: {...}}."""
    jetzt = jetzt or datetime.now(TZ)
    erledigt = erledigt or {}
    heute = jetzt.date()
    morgen = heute + timedelta(days=1)
    hinweise = []

    # --- Kalender
    t0 = time.monotonic()
    termine = termine_laden(opt, heute)
    melde(f"Kalender gelesen: {len(termine)} Termine in {time.monotonic() - t0:.0f} s")
    waechter = herzschlag_pruefen(opt, jetzt)
    heute_alle = am_tag(termine, heute)
    morgen_alle = am_tag(termine, morgen)
    status = tage.tagesstatus(heute, [t["titel"] for t in heute_alle])
    status_morgen = tage.tagesstatus(morgen, [t["titel"] for t in morgen_alle])

    def sichtbar(liste):
        # ganztägige To-do-Einträge stehen nur unter "Offene To-dos"
        return [t for t in liste if not (t["todo"] and t["ganztag"]) and not tage.ist_statusmarke(t["titel"])]

    # erledigte To-dos markiert die nächtliche Aufräumaufgabe mit "✓" vor dem Titel,
    # seit 1.5.0 fehlen auch die im Brief erledigten (bis der Nachtlauf das ✓ setzt)
    def offen(t):
        return not t["titel"].lstrip().startswith("✓") and kal_schluessel(t) not in erledigt

    todos = sorted([t for t in termine if t["todo"] and offen(t)
                    and heute - timedelta(days=TODO_UEBERFAELLIG_TAGE) <= t["start"].date() <= heute + timedelta(days=7)],
                   key=lambda t: (t["start"], t["titel"]))
    # Rechnungs-To-dos (seit 1.3.7) gehen nach "Braucht dich"
    rechnung_nah = [t for t in todos if rechnung_zu_zahlen(t["titel"] + " " + t.get("notiz", ""))]
    todos = [t for t in todos if t not in rechnung_nah]
    # seit 1.4.0 alle To-dos bis heute + 7 Tage (vorher höchstens drei)
    if len(todos) > MAX_TODOS:
        hinweise.append(f"Unter 'Offene To-dos' stehen die ersten {MAX_TODOS} von {len(todos)} To-dos.")
    todo_liste = []
    for nr, t in enumerate(todos[:MAX_TODOS], 1):
        wann = tage.datum_kurz(t["start"].date())
        ueberfaellig = (heute - t["start"].date()).days
        if ueberfaellig > 0:
            wann = f"Überfällig seit {ueberfaellig} {'Tag' if ueberfaellig == 1 else 'Tagen'} ({wann})"
        if t["start"].date() == heute:
            wann = "heute, " + wann
        elif t["start"].date() == morgen:
            wann = "morgen, " + wann
        if not t["ganztag"]:
            wann += f" {t['start']:%H:%M}"
        # Hintergrundsatz seit 1.4.0 ohne Gemini: erster Notizsatz, der mehr sagt als der Titel.
        # Seit 1.6.0 ohne Befehle (die stehen unter "Werkzeuge") und ohne Knopf bei reinen Hinweisen
        notiz_ohne, befehle = befehle_trennen(t.get("notiz", ""))
        eintrag = {"id": f"t{nr}", "wann": wann, "titel": t["titel"], "link": t["link"],
                   "ueberfaellig": ueberfaellig > 0, "notiz": t.get("notiz", ""),
                   "satz": hintergrund("", t["titel"], notiz_ohne),
                   "datum": t["start"].date().isoformat(), "schluessel": kal_schluessel(t), "_frist": t["start"].date(),
                   "_woerter": schluesselwoerter(t["titel"])}
        if befehle:
            eintrag["befehle"] = befehle
        if passiv(t["titel"], t.get("notiz", "")):
            eintrag["passiv"] = True
            eintrag.pop("schluessel")
        todo_liste.append(eintrag)

    # Spätere To-dos (nach heute + 7 bis DEMNAECHST_TAGE) für "Demnächst"
    spaeter = sorted([t for t in termine if t["todo"] and offen(t)
                      and heute + timedelta(days=7) < t["start"].date() <= heute + timedelta(days=DEMNAECHST_TAGE)],
                     key=lambda t: (t["start"], t["titel"]))
    demnaechst_kalender = [{"titel": t["titel"], "quelle": f"Bis {tage.datum_kurz(t['start'].date())} Aus der To-do-Liste.",
                            "satz": "", "link": t["link"], "_frist": t["start"].date(), "frist": t["start"].date().isoformat(),
                            "_woerter": schluesselwoerter(t["titel"]), "_notiz": t.get("notiz", ""),
                            "notiz": t.get("notiz", ""), "schluessel": kal_schluessel(t)} for t in spaeter]
    for k in demnaechst_kalender:  # seit 1.6.0: reine Hinweise ohne Knopf
        if passiv(k["titel"], k["_notiz"]):
            k["passiv"] = True
            k["satz"] = "Nur zur Info, nichts zu erledigen."
            k.pop("schluessel")

    # --- Mails
    t0 = time.monotonic()
    konto = g.gmail_profil(opt)
    eigene = {konto.lower()} | {a.lower() for a in g.gmail_absenderadressen(opt)}
    eigene |= {a.strip().lower() for a in opt.get("weitere_eigene_adressen", []) if a.strip()}
    eigene.discard("")

    kandidaten, im_fenster = [], 0
    for tid in g.gmail_threads(opt, POSTEINGANG_SUCHE, 100):
        thread = g.gmail_thread(opt, tid, voll=False)
        alle = _nachrichten(thread, eigene)
        if alle and alle[-1].zeit >= jetzt - timedelta(hours=FENSTER_STUNDEN):
            im_fenster += 1  # alle Posteingangs-Threads im Zeitfenster, vor jedem Filter
        treffer = posteingang_kandidat(thread, eigene, jetzt)
        if treffer:
            kandidaten.append((tid, treffer[0], treffer[1], False))
    # seit 1.4.0: Rechnungen und Fristen, die ein Gmail-Filter ungelesen am Posteingang vorbei einsortiert hat
    schon = {k[0] for k in kandidaten}
    try:
        for tid in g.gmail_threads(opt, ABGELEGT_SUCHE, 40):
            if tid not in schon:
                n = abgelegt_kandidat(g.gmail_thread(opt, tid, voll=False), eigene, jetzt)
                if n:
                    kandidaten.append((tid, n, False, True))
    except g.GoogleFehler as fehler:
        if fehler.art == "anmeldung":
            raise
        melde(f"Abgelegte Mails nicht lesbar: {fehler}")
    kandidaten.sort(key=lambda k: k[1].zeit, reverse=True)
    if len(kandidaten) > MAX_KANDIDATEN:
        hinweise.append(f"Es gab {len(kandidaten)} neue Mails, geprüft wurden die {MAX_KANDIDATEN} neuesten.")
        kandidaten = kandidaten[:MAX_KANDIDATEN]

    posteingang, abgelegt_zahl = [], 0
    for nr, (tid, n, antwort, abgelegt) in enumerate(kandidaten, 1):
        voll = g.gmail_thread(opt, tid, voll=True)
        passend = [m for m in voll.get("messages", []) if m.get("id") == n.roh.get("id")]
        payload = passend[0].get("payload") if passend else {}
        text = nachricht_text(payload)
        regeltext = n.betreff + " " + text[:TEXT_REGEL]
        anhang = hat_anhang(payload)
        if abgelegt and not (immer_wichtig(n.von_adresse + " " + n.von_name) or rechnung_offen(regeltext, anhang)
                             or frist_regel(regeltext)):
            continue  # abgelegt und weder Rechnung noch Frist: bleibt wie bisher draußen
        abgelegt_zahl += abgelegt
        posteingang.append({
            "id": f"p{nr}", "mid": n.roh.get("id") or tid, "thread": tid, "von": n.von_name,
            "adresse": n.von_adresse, "betreff": n.betreff, "zeit": n.zeit, "antwort": antwort,
            "abgelegt": abgelegt, "anhang": anhang, "text": kuerzen(text, TEXT_POSTEINGANG),
            "regeltext": regeltext, "snippet": n.snippet, "nummern": rechnungsnummern(n.betreff, text[:TEXT_REGEL]),
        })

    wartet, antworten = [], []
    schon = {p["thread"] for p in posteingang}  # diese Mails ordnet der normale Weg ein
    for tid in g.gmail_threads(opt, f"in:sent newer_than:{WARTET_MAX_TAGE + 1}d", 80):
        thread = g.gmail_thread(opt, tid, voll=False)
        n = wartet_kandidat(thread, eigene, jetzt)
        if n:
            wartet.append((tid, n))
        elif tid not in schon:
            a = antwort_abgelegt(thread, eigene, jetzt)
            if a:
                antworten.append((tid, a[0], a[1]))
    wartet.sort(key=lambda w: w[1].zeit)             # die am längsten offenen zuerst
    wartet = wartet[:MAX_WARTET_KANDIDATEN]

    gesendet = []
    for nr, (tid, n) in enumerate(wartet, 1):
        voll = g.gmail_thread(opt, tid, voll=True)
        passend = [m for m in voll.get("messages", []) if m.get("id") == n.roh.get("id")]
        text = nachricht_text(passend[0].get("payload")) if passend else ""
        fremde = [(name, adr) for name, adr in n.empfaenger if adr not in eigene]
        an = ", ".join((name or adr) for name, adr in fremde[:2]) + (" und weitere" if len(fremde) > 2 else "")
        gesendet.append({
            "id": f"g{nr}", "mid": n.roh.get("id") or tid, "thread": tid, "an": an, "betreff": n.betreff,
            "zeit": n.zeit, "text": kuerzen(text, TEXT_GESENDET),
        })

    bezahlt = zahlungen_bestaetigt(opt, eigene)
    melde(f"Mails gelesen: {len(posteingang)} neue (davon {abgelegt_zahl} ungelesen abgelegt), {len(gesendet)} "
          f"gesendete ohne Antwort, {len(bezahlt)} Zahlungsbestätigungen in {time.monotonic() - t0:.0f} s")

    # --- Einordnung: Gemerktes aus der Merkliste, nur Neues an Gemini (seit 1.4.0)
    termine_pruefen = []
    for tag_name, tag_datum, tag_liste in (("heute", heute, heute_alle), ("morgen", morgen, morgen_alle)):
        for t in sichtbar(tag_liste):
            if not t["todo"]:
                termine_pruefen.append({"id": f"k{len(termine_pruefen) + 1}", "tag": tag_name, "titel": t["titel"],
                                        "zeit": zeit_text(t, tag_datum), "beschreibung": t.get("beschreibung", ""),
                                        "link": t["link"],
                                        "schluessel": f"{t['link'] or t['titel']}|{tag_datum.isoformat()}|{tag_name}"})
    post_urteil, ges_urteil, term_urteil, gemini_info = einordnung_holen(
        opt, gedaechtnis_pfad, posteingang, gesendet, termine_pruefen, status, heute, jetzt, hinweise)

    braucht, geklaert, weggelassen, neue_mails, demnaechst_mails = [], [], [], [], []
    gemerkt, abgeschlossen = [], []  # fürs Gedächtnis: (Mail, Eintrag, Frist) und geklärte Threads
    heute_weg = []                   # seit 1.4.1: heute ohne Handlungsbedarf, ein gemerkter Punkt dazu schließt sich

    def quelle(p):
        return f"Mail von {absender(p)}, {relativ(p['zeit'], heute)}."

    # seit 1.5.0: im Brief erledigt oder bezahlt markiert (kommt im Thread eine neuere Mail, zählt sie wieder)
    im_brief_erledigt = []
    manuell_bezahlt = {n for v in erledigt.values() for n in (v.get("nummern") or [])}

    def _im_brief_erledigt(p):
        marke = erledigt.get("mail:" + p["thread"])
        if not marke:
            return False
        try:
            return p["zeit"] <= datetime.fromisoformat(marke.get("zeit") or "")
        except ValueError:
            return True

    for p in posteingang:
        if _im_brief_erledigt(p):
            im_brief_erledigt.append(p["thread"])
            continue
        e = post_urteil.get(p["id"])
        link = thread_link(konto, p["thread"])
        regel = immer_wichtig(p["adresse"] + " " + p["von"]) or rechnung_offen(p["regeltext"], p["anhang"])
        frist_treffer = frist_regel(p["regeltext"])
        termin = termin_lesen(e, p["regeltext"], heute)
        if e is None:
            # nicht eingeordnet (Gemini nicht erreichbar oder Grenze erreicht): die festen Regeln gelten trotzdem
            if not (regel or frist_treffer or termin) or verdaechtig(p["regeltext"]):
                neue_mails.append({"titel": p["betreff"], "quelle": quelle(p), "satz": kuerzen(p["snippet"], 160),
                                   "link": link, "_thread": p["thread"]})
                continue
            e = {"liste": "braucht_dich", "titel": "", "satz": "", "frist": ""}
        eintrag = {"titel": sauber(e.get("titel")) or p["betreff"], "quelle": quelle(p),
                   "satz": sauber(e.get("satz")), "link": link,
                   "_woerter": schluesselwoerter(" ".join((p["von"], p["adresse"].split("@")[-1],
                                                           p["betreff"], sauber(e.get("titel"))))),
                   "schluessel": "mail:" + p["thread"], "rechnung": bool(regel), "nummern": sorted(p["nummern"])}
        liste = e.get("liste")
        if liste not in ("braucht_dich", "geklaert", "weglassen"):
            liste = "braucht_dich"  # unbekannte Antwort: lieber zeigen als verschlucken
        if liste == "weglassen" and frist_treffer:
            liste = "braucht_dich"  # Frist- und Abo-Regel steht über Gemini
        if regel:
            eintrag["_wichtig"] = True
            liste = "braucht_dich"  # zu überweisende Rechnung, nie weglassen
        if liste == "braucht_dich" and not eintrag["satz"]:
            eintrag["satz"] = kuerzen(p["snippet"], 160)
        folge = sauber(e.get("folge"))
        if folge and liste == "braucht_dich":  # seit 1.6.0: was passiert, wenn du nicht handelst
            eintrag["satz"] = (eintrag["satz"].rstrip(". ") + ". " if eintrag["satz"] else "") + "Folge: " + folge
        frist = frist_lesen(e.get("frist"))
        if not frist and (regel or frist_treffer):
            frist = frist_aus_text(p["regeltext"], heute)  # seit 1.4.0 aus dem Text, wenn Gemini keine nennt
        if frist:
            eintrag["frist"] = frist.isoformat()
        if liste == "geklaert" and ((frist and frist >= heute) or rechnung_offen(p["regeltext"], p["anhang"])):
            liste = "braucht_dich"  # offene Frist oder offene Rechnung ist nie erledigt (seit 1.3.2)
        quittung = bool(ZAHLUNG_BESTAETIGT.search((p["betreff"] + " " + p["snippet"]).casefold())) \
            and not OFFEN.search(p["regeltext"].casefold())
        if quittung:
            # seit 1.6.0: die Zahlungsbestätigung selbst ist eine Quittung ohne Handlungsbedarf ("Weggelassen").
            # Sie schließt weiter die passende Rechnung (bezahlt), ein eigener Punkt "Schon geklärt" wird sie nicht
            liste = "weglassen"
            eintrag.pop("_wichtig", None)
            regel = False
        elif p["nummern"] & (bezahlt | manuell_bezahlt):
            # Zahlungsbestätigung (seit 1.4.0) oder im Brief bezahlt (seit 1.5.0), gleiche Rechnungsnummer
            liste = "geklaert"
            eintrag.pop("_wichtig", None)
            eintrag["satz"] = ("Zahlung ist laut Bestätigungsmail eingegangen." if p["nummern"] & bezahlt
                               else "Im Brief als bezahlt markiert.")
        frisch = p["zeit"] >= jetzt - timedelta(hours=FRISCH_STUNDEN)
        termin_neu = False
        if termin and liste != "weglassen" and not verdaechtig(p["regeltext"]):
            # Termin aus der Mail (seit 1.5.0): steht er nicht im Kalender, mit Knopf zum Eintragen
            t_datum, t_zeit, t_ort = termin
            if not termin_im_kalender(opt, t_datum, t_zeit, woerter_von(p["von"] + " " + p["betreff"]), termine, heute):
                termin_neu = True
                liste = "braucht_dich"
                wann = tage.datum_kurz(t_datum) + (f" {t_zeit:%H:%M}" if t_zeit else "")
                eintrag["titel"] = "Termin: " + eintrag["titel"]
                eintrag["marke"] = "nicht im Kalender"
                eintrag["satz"] = f"{wann}{', ' + t_ort if t_ort else ''}. " + (eintrag["satz"] or "")
                eintrag["kalender_link"] = kalender_vorlage(
                    sauber(e.get("titel")) or p["betreff"], t_datum, t_zeit, t_ort, f"Aus der Mail von {absender(p)}: "
                    f"{p['betreff']}")
                eintrag["_termin"] = {"datum": t_datum.isoformat(), "zeit": f"{t_zeit:%H:%M}" if t_zeit else "",
                                      "ort": t_ort, "vorlage": eintrag["kalender_link"]}
                frist = frist or t_datum
        if verdaechtig(p["regeltext"]):
            liste = "weglassen"  # Mail mit Anweisungen an eine KI: nie oben einordnen
            p = dict(p, betreff="Verdacht auf Anweisungen an eine KI: " + p["betreff"])
        if liste == "braucht_dich" and frist and not termin_neu:
            # Über die Karte entscheidet die Frist: bald "Braucht dich", später "Demnächst"
            grenze = heute + timedelta(days=IMMER_WICHTIG_TAGE if regel else BRAUCHT_DICH_TAGE)
            if frist > heute + timedelta(days=DEMNAECHST_TAGE):
                liste = "weglassen"
            elif frist > grenze:
                liste = "demnaechst"
        if liste == "braucht_dich":
            if frist and frist < heute:
                eintrag["marke"] = "überfällig"
            braucht.append(eintrag)
            gemerkt.append((p, eintrag, frist))
        elif liste == "demnaechst":
            eintrag["quelle"] = f"Bis {tage.datum_kurz(frist)} " + eintrag["quelle"]
            eintrag["_frist"] = frist
            demnaechst_mails.append(eintrag)
            gemerkt.append((p, eintrag, frist))
        elif liste == "geklaert":
            if frisch:  # seit 1.6.0: ältere geklärte Mails nicht jeden Tag wieder zeigen
                geklaert.append(eintrag)
            abgeschlossen.append(p["thread"])
        else:
            if frisch:
                weggelassen.append({"von": p["von"], "betreff": p["betreff"], "link": link})
            heute_weg.append(p["thread"])

    warnungen = []
    for k in termine_pruefen:
        u = term_urteil.get(k["id"]) or {}
        if sauber(u.get("satz")) and k["link"] not in {w["link"] for w in warnungen}:
            warnungen.append({"titel": sauber(u.get("titel")) or k["titel"],
                              "quelle": f"Kalender, {k['tag']} {k['zeit']}.", "satz": sauber(u.get("satz")),
                              "link": k["link"]})
    braucht[:0] = warnungen[:3]  # zeitgebunden, darum vor die Mails

    # Gedächtnis (seit 1.3.0, seit 1.4.0 auch ohne Gemini): offene Punkte bleiben, bis sie erledigt sind
    gedaechtnis_info = {}
    if gedaechtnis_pfad:
        try:
            heute_gemerkt = {p["thread"] for p, _, _ in gemerkt}
            zurueck, gedaechtnis_info = _gedaechtnis_abgleich(
                opt, gedaechtnis_pfad, gemerkt, abgeschlossen, termine, eigene, heute, bezahlt,
                heute_gezeigt={m["_thread"] for m in neue_mails}, heute_weggelassen=set(heute_weg),
                im_brief_erledigt={k[5:] for k in erledigt if k.startswith("mail:")} - heute_gemerkt,
                termin_pruefer=lambda d, z, w: termin_im_kalender(opt, d, z, w, termine, heute))
        except Exception as fehler:  # das Gedächtnis ist Zugabe, der Brief darf daran nicht scheitern
            melde(f"Gedächtnis nicht nutzbar: {type(fehler).__name__}")
            zurueck = []
        for pk in zurueck:
            frist = pk["frist"]
            wichtig = immer_wichtig(pk["von"]) or rechnung_offen(pk["titel"] + " " + pk["satz"])
            eintrag = {"titel": pk["titel"], "satz": pk["satz"], "link": pk["link"], "_woerter": pk["woerter"],
                       "_wichtig": wichtig, "schluessel": "mail:" + pk["thread"], "rechnung": bool(wichtig),
                       "nummern": sorted(pk["nummern"]),
                       "quelle": (f"Bis {tage.datum_kurz(frist)} " if frist and not pk.get("termin") else "")
                       + f"Offen seit {tage.datum_kurz(pk['erstmals'])}, Mail von {pk['von']}."}
            if pk.get("termin"):  # Termin aus Mail, noch nicht im Kalender (seit 1.5.0)
                eintrag["marke"] = "nicht im Kalender"
                eintrag["kalender_link"] = pk["termin"].get("vorlage", "")
                braucht.append(eintrag)
                continue
            if frist:
                eintrag["frist"] = frist.isoformat()
            grenze = heute + timedelta(days=IMMER_WICHTIG_TAGE if eintrag["_wichtig"] else BRAUCHT_DICH_TAGE)
            if frist and frist > grenze:
                eintrag["_frist"] = frist
                demnaechst_mails.append(eintrag)
            else:
                if frist and frist < heute:
                    eintrag["marke"] = "überfällig"
                braucht.append(eintrag)

    # Rechnungs-To-dos mit Zahlungsbestätigung (seit 1.4.0): nicht mehr offen zeigen, einmal unter "Schon geklärt".
    # Im Brief schon bezahlt (seit 1.5.0, gleiche Rechnungsnummer): still weglassen, der Nachtlauf hakt sie ab.
    def _nummern_todo(titel, notiz):
        return rechnungsnummern(titel, notiz)

    for liste_k, notiz_feld in ((rechnung_nah, "notiz"), (demnaechst_kalender, "_notiz")):
        for k in list(liste_k):
            nummern = _nummern_todo(k["titel"], k.get(notiz_feld, ""))
            if nummern & manuell_bezahlt:
                liste_k.remove(k)
            elif nummern & bezahlt:
                liste_k.remove(k)
                geklaert.append({"titel": k["titel"], "quelle": "Aus der To-do-Liste.", "link": k["link"],
                                 "satz": "Zahlung ist laut Bestätigungsmail eingegangen. In der To-do-Liste noch "
                                         "offen.", "schluessel": k.get("schluessel", ""), "rechnung": True,
                                 "nummern": sorted(nummern)})

    # Doppelt vorhanden (seit 1.3.2): Mail und Kalender-To-do zur selben Sache erscheinen nur einmal, als
    # Kalenderpunkt (To-dos oder "Demnächst"). Ausnahme: zu überweisende Rechnungen (IMMER_WICHTIG) bleiben als
    # Mail unter "Braucht dich", dann fällt der Kalenderpunkt weg.
    def _gleich(a, b):
        return bool(a and b and a & b)

    gezeigt_vorher = {x.get("link") for x in braucht + geklaert + demnaechst_mails if x.get("link")}
    wichtig_woerter = [x["_woerter"] for x in braucht if x.get("_wichtig") and x.get("_woerter")]
    # Frist steht oft nur im PDF: dann das Datum aus dem passenden Kalender-To-do übernehmen (seit 1.3.4)
    for x in braucht:
        if x.get("_wichtig") and x.get("_woerter") and not x.get("frist"):
            daten = [k["_frist"] for k in demnaechst_kalender if _gleich(k["_woerter"], x["_woerter"])]
            daten += [date.fromisoformat(td["datum"]) for td in todo_liste
                      if _gleich(schluesselwoerter(td["titel"]), x["_woerter"])]
            daten += [t["start"].date() for t in rechnung_nah  # seit 1.3.7 nicht mehr in todo_liste
                      if _gleich(schluesselwoerter(t["titel"]), x["_woerter"])]
            if daten:
                x["frist"] = min(daten).isoformat()
                x["quelle"] = f"Bis {tage.datum_kurz(min(daten))} " + x["quelle"]
    todo_liste[:] = [td for td in todo_liste
                     if not any(_gleich(schluesselwoerter(td["titel"]), w) for w in wichtig_woerter)]
    demnaechst_kalender = [k for k in demnaechst_kalender if not any(_gleich(k["_woerter"], w) for w in wichtig_woerter)]
    # Rechnungs-To-dos aus dem Kalender (seit 1.3.7): wie Rechnungs-Mails immer unter "Braucht dich", solange die
    # Frist bis heute + IMMER_WICHTIG_TAGE reicht, nie zusätzlich unter "Demnächst" oder "Offene To-dos"
    rechnung_kalender = rechnungs_todos(rechnung_nah, demnaechst_kalender, heute, wichtig_woerter)
    braucht += rechnung_kalender
    kalender_woerter = ([k["_woerter"] for k in demnaechst_kalender] + [schluesselwoerter(td["titel"]) for td in todo_liste]
                        + [r["_woerter"] for r in rechnung_kalender])

    def _doppelt(x):
        return not x.get("_wichtig") and any(_gleich(x.get("_woerter"), w) for w in kalender_woerter)

    # seit 1.6.0: Mail und Kalenderpunkt zur selben Sache werden zusammengeführt, statt die Mail still zu streichen.
    # Der Kalenderpunkt bekommt den Inhalt der Mail (Gemini-Satz mit Folge) und einen Link zur Mail. Reicht seine
    # Frist bis heute + IMMER_WICHTIG_TAGE, steht er unter "Braucht dich" (z. B. Stellungnahme mit
    # Frist aus einer Mail)
    kalender_punkte = todo_liste + demnaechst_kalender
    for x in braucht + demnaechst_mails:
        if not _doppelt(x) or not x.get("schluessel", "").startswith("mail:"):
            continue
        for k in kalender_punkte:
            if "_mail" not in k and _gleich(k.get("_woerter"), x.get("_woerter")):
                k["_mail"] = x
                break
    nach_oben = []
    for k in kalender_punkte:
        x = k.get("_mail")
        if not x:
            continue
        mail_quelle = re.sub(r"^Bis \S+ \d\d\.\d\d\. ", "", x.get("quelle", ""))
        k["mail_link"] = x.get("link", "")
        if k["_frist"] <= heute + timedelta(days=IMMER_WICHTIG_TAGE) and not k.get("passiv"):
            nach_oben.append(k)
            braucht.append({"titel": k["titel"], "link": k.get("link", ""), "mail_link": x.get("link", ""),
                            "quelle": f"Bis {tage.datum_kurz(k['_frist'])}, aus der To-do-Liste. Dazu: {mail_quelle}",
                            "satz": x.get("satz") or k.get("satz", ""), "frist": k["_frist"].isoformat(),
                            "_frist": k["_frist"], "schluessel": k.get("schluessel", ""),
                            "notiz": k.get("notiz", ""), "befehle": k.get("befehle") or [],
                            "marke": "überfällig" if k["_frist"] < heute else ""})
        else:
            k["satz"] = k.get("satz") or x.get("satz", "")
            k["quelle"] = (k.get("quelle") or "") + (" " if k.get("quelle") else "") + "Dazu: " + mail_quelle
    todo_liste[:] = [td for td in todo_liste if td not in nach_oben]
    demnaechst_kalender = [k for k in demnaechst_kalender if k not in nach_oben]

    braucht = [x for x in braucht if not _doppelt(x)]
    geklaert = [x for x in geklaert if not _doppelt(x)]
    # seit 1.6.2: abgelegte Antworten auf eigene Mails einmal melden (am Tag des ersten Briefs, der sie sieht)
    geklaert += antworten_melden(antworten, gedaechtnis_pfad, konto, heute)
    geklaert = geklaert[:MAX_GEKLAERT]
    demnaechst_mails = [m for m in demnaechst_mails if not _doppelt(m)]
    # Was als offener Punkt oder im Kalender steht, nicht zusätzlich unter "Weggelassen"
    weggelassen = [w for w in weggelassen if w.get("link") not in gezeigt_vorher]
    # seit 1.4.0 ohne Höchstzahl, die Seite klappt lange Listen zusammen
    demnaechst = sorted(demnaechst_mails + demnaechst_kalender, key=lambda x: x["_frist"])

    # seit 1.6.0 gewichtet: Kalender-Warnungen zuerst, dann nach Frist (ohne Frist wie in drei Tagen)
    vorne = [x for x in braucht if x.get("quelle", "").startswith("Kalender, ")]
    rest = [x for x in braucht if x not in vorne]

    def _gewicht(x):
        f = x.get("_frist") or frist_lesen(x.get("frist"))
        return f or heute + timedelta(days=3)

    # seit 1.6.2 eine gemeinsame Reihenfolge nach Datum: Geburtstag und Kalender-Warnungen zählen als heute,
    # Überschneidungen und Arbeitszeit-Konflikte mit ihrem Tag, Mails und To-dos mit ihrer Frist. So steht eine
    # Frist vor einer Überschneidung in sechs Tagen. Vermutlich überholte Einträge kommen ans Ende.
    # (bis 1.6.1 standen alle Überschneidungen ganz oben)
    alle_konflikte = konflikte(termine, heute, jetzt, opt.get("verkehr_ziel", ""))
    gesamt = ([(heute, x) for x in gratulieren(heute_alle, heute, erledigt)] + [(heute, x) for x in vorne]
              + [(x["_tag"], x) for x in alle_konflikte if x.get("art") != "doppelt"]
              + [(_gewicht(x), x) for x in rest])
    gesamt.sort(key=lambda p: max(p[0], heute))  # stabil: bei gleichem Tag bleibt die Reihenfolge oben
    braucht = [x for _, x in gesamt] + [x for x in alle_konflikte if x.get("art") == "doppelt"]

    def ohne_intern(liste):
        return [{k: v for k, v in x.items() if not k.startswith("_") and v not in ("", [], None)
                 or k in ("titel", "quelle", "satz", "link")} for x in liste]

    braucht, geklaert, demnaechst = ohne_intern(braucht), ohne_intern(geklaert), ohne_intern(demnaechst)
    neue_mails = ohne_intern(neue_mails)
    todo_liste = ohne_intern(todo_liste)
    # unter "Schon geklärt" nur Rechnungs-To-dos mit Knopf (seit 1.5.0): bezahlt laut Mail, im Doc noch offen
    geklaert = [x if x.get("schluessel", "").startswith("kal:") else {k: v for k, v in x.items() if k != "schluessel"}
                for x in geklaert]
    # Verkehr (seit 1.3.6): Störung auf dem Arbeitsweg steht ganz oben unter "Braucht dich"
    verkehr_info = verkehr_pruefen(opt, status, jetzt, verkehr_pfad, hinweise)
    if verkehr_info and verkehr_info["stoerung"]:
        braucht.insert(0, verkehr.braucht_eintrag(verkehr_info))
    # Fahrten und Termine mit Ort von heute (seit 1.5.0)
    fahrten = fahrten_planen(opt, heute_alle, jetzt, verkehr_pfad, hinweise)
    # Kalender-Warnungen unter "Braucht dich" nicht noch einmal im Kalenderblock zeigen
    warn_links = {x["link"] for x in braucht if x.get("quelle", "").startswith("Kalender, ") and x.get("link")}
    # seit 1.6.0 ohne To-dos (die stehen unter "Offene To-dos", vorher dreifach) und ohne abgesagte Termine
    heute_liste = [t for t in sichtbar(heute_alle) if t["link"] not in warn_links and not t["todo"]
                   and not ABGESAGT.match(t["titel"])]
    morgen_liste = [t for t in sichtbar(morgen_alle) if t["link"] not in warn_links and not t["todo"]
                    and not ABGESAGT.match(t["titel"])]
    # Wetter (seit 1.6.0) aus Home Assistant, Glätte-Hinweis bei Fahrt oder Arbeitsweg
    wetter_info = wetter.vorhersage(opt, jetzt)
    if wetter_info and wetter_info.get("glaette") and (fahrten or status.get("arbeit")):
        braucht.insert(0, {"titel": "Glätte möglich", "quelle": "Wetter aus Home Assistant.",
                           "satz": wetter_info["glaette"] + " Etwas mehr Zeit für die Fahrt einplanen.", "link": "",
                           "art": "wetter"})
    wartet_liste = []
    for s in gesendet:
        u = ges_urteil.get(s["id"], {})
        if u.get("erwartet_antwort") is False:
            continue
        tage_offen = (heute - s["zeit"].date()).days
        wartet_liste.append({
            "titel": sauber(u.get("thema")) or s["betreff"],
            "quelle": f"An {s['an']}, gesendet {tage.datum_kurz(s['zeit'].date())}, offen seit {tage_offen} Tagen.",
            "satz": "", "link": thread_link(konto, s["thread"]),
        })
    wartet_liste = wartet_liste[:MAX_WARTET]

    gemini_info["genutzt"] = not neue_mails  # alle Mails eingeordnet (aus der Merkliste oder neu)
    if gemini_info["fehler"]:
        hinweise.append("Gemini nicht erreichbar: " + gemini_info["fehler"] + (
            f". {len(neue_mails)} Mails sind noch nicht eingeordnet. Rechnungen und Fristen darunter stehen "
            "trotzdem oben, gemerkte offene Punkte auch." if neue_mails else "."))
    elif neue_mails:
        hinweise.append(f"{len(neue_mails)} Mails werden erst beim nächsten Lauf eingeordnet.")

    return {
        "datum": heute.isoformat(),
        "erzeugt": jetzt.isoformat(timespec="minutes"),
        "datum_text": tage.datum_lang(heute),
        "status": status,
        "ablauf": tagessatz_regel(status, heute_liste, heute, status_morgen, jetzt),  # seit 1.4.0 ohne Gemini
        "termine_heute": [_fuer_seite(t, heute) for t in heute_liste],
        "termine_bogen": [_fuer_seite(t, heute) for t in sichtbar(heute_alle)],
        "morgen": {"status": status_morgen["zeile"],
                   "termine": [_fuer_seite(t, morgen) for t in morgen_liste],
                   # seit 1.6.1 nur der Status, die Termine von morgen stehen unter "Nächste Tage"
                   "zeile": morgen_zeile(status_morgen, [], morgen, nur_status=True)},
        # seit 1.6.0; seit 1.6.2 ohne Einträge, die "Braucht dich" als vermutlich überholt meldet
        "woche": [t for t in woche_termine(termine, heute)
                  if not (t["link"] and t["link"] in {x["link"] for x in alle_konflikte if x.get("art") == "doppelt"})],
        "wetter": wetter_info,  # seit 1.6.0
        "befehle": list(dict.fromkeys(b for x in todo_liste + braucht for b in x.get("befehle") or [])),
        "demnaechst": demnaechst,
        "waechter": waechter,
        "verkehr": verkehr_info,
        "fahrten": fahrten,
        "gedaechtnis": gedaechtnis_info,
        "braucht_dich": braucht,
        "geklaert": geklaert,
        "neue_mails": neue_mails,
        "wartet": wartet_liste,
        "todos": todo_liste,
        "weggelassen": weggelassen,
        "gemini": gemini_info,
        "hinweise": hinweise,
        "zahlen": {"geprueft": len(posteingang), "im_fenster": im_fenster, "abgelegt": abgelegt_zahl,
                   "fenster_tage": FENSTER_STUNDEN // 24,
                   "neu_eingeordnet": gemini_info["neu"], "bezahlt_gefunden": len(bezahlt)},
    }


def push_text(brief: dict) -> str:
    """Nur Zahlen und Tagesstatus, keine Mail-Inhalte (steht auf dem Sperrbildschirm)."""
    teile = [brief["status"]["push"]]
    zusatz = verkehr.push_zusatz(brief.get("verkehr"))
    if zusatz:
        teile.append(zusatz)
    if brief.get("waechter"):
        teile.append("Nachtlauf prüfen")
    # seit 1.4.0 immer "braucht dich" (Rechnungen und gemerkte Punkte gibt es auch ohne Gemini)
    n = len([x for x in brief["braucht_dich"] if x.get("art") not in ("verkehr", "wetter")])
    teile.append("1 braucht dich" if n == 1 else f"{n} brauchen dich" if n else "nichts braucht dich")
    n = len([x for x in brief["braucht_dich"] if x.get("art") == "konflikt"])
    if n:
        teile.append("1 Überschneidung" if n == 1 else f"{n} Überschneidungen")
    n = len(brief.get("neue_mails") or [])
    if n:
        teile.append("1 Mail nicht eingeordnet" if n == 1 else f"{n} Mails nicht eingeordnet")
    n = len(brief["wartet"])
    if n:
        teile.append(f"{n} warten auf Antwort" if n > 1 else "1 wartet auf Antwort")
    # To-dos seit 1.4.0 getrennt nach heute (mit überfälligen) und den nächsten sieben Tagen
    heute_n = len([t for t in brief["todos"] if (t.get("datum") or brief["datum"]) <= brief["datum"]])
    woche_n = len(brief["todos"]) - heute_n
    if heute_n:
        teile.append(f"{heute_n} To-do{'s' if heute_n > 1 else ''} heute")
    if woche_n:
        teile.append(f"{woche_n} diese Woche" if heute_n else f"{woche_n} To-do{'s' if woche_n > 1 else ''} diese Woche")
    n = len(brief["termine_heute"])
    if n:
        teile.append(f"{n} Termine" if n > 1 else "1 Termin")
    return ", ".join(teile)


BETRAG = re.compile(r"\s*[:,(-]?\s*(?:€\s*\d[\d.]*(?:,\d{1,2})?|\d[\d.]*(?:,\d{1,2})?\s*(?:€|eur(?:o)?\b))\)?",
                    re.I)
NUMMER_KLAMMER = re.compile(r"\s*\((?:rechnung|re\.?|nr\.?|kunden)[^)]*\)|\s*#?\b[a-z]{0,4}\d{5,}\b", re.I)


def kurztitel(titel: str, laenge: int = 40) -> str:
    """Titel für den Push (seit 1.5.0): ohne Beträge und lange Nummern, gekürzt."""
    t = NUMMER_KLAMMER.sub("", BETRAG.sub("", titel or ""))
    t = re.sub(r"\s{2,}", " ", t).strip(" :,-")
    return t if len(t) <= laenge else t[:laenge].rsplit(" ", 1)[0].rstrip(" :,-") + " …"


def push_inhalt(brief: dict) -> tuple:
    """Titel und Text des Morgen-Pushs mit Inhalten (seit 1.5.0, bewusst: Titel ohne Beträge).

    Steht auf dem Sperrbildschirm, darum keine Beträge, keine Absender, keine Mailtexte."""
    kopf = [brief["status"]["push"]]
    v = brief.get("verkehr")
    if v:
        uhr = v["losfahren"][1:] if v["losfahren"].startswith("0") else v["losfahren"]
        kopf.append(f"{uhr} los" + (f", Stau +{v['extra_min']}" if v.get("stoerung") and v.get("extra_min") else "")
                    + (", Sperrung" if v.get("gesperrt") else ""))
    if (brief.get("wetter") or {}).get("glaette"):  # seit 1.6.0
        kopf.append("Glätte möglich")
    zeilen = []
    if brief.get("waechter"):
        zeilen.append("Nachtlauf prüfen.")
    braucht = [kurztitel(x["titel"], 60 if x.get("art") == "konflikt" else 40)
               for x in brief["braucht_dich"] if x.get("art") not in ("verkehr", "wetter")]
    if braucht:
        zeilen.append("Braucht dich: " + ", ".join(braucht[:4]) + (f" und {len(braucht) - 4} weitere" if len(braucht) > 4 else ""))
    heute = [t for t in brief["todos"] if (t.get("datum") or brief["datum"]) <= brief["datum"]]
    woche = len(brief["todos"]) - len(heute)
    if heute:
        zeilen.append("Heute: " + ", ".join(kurztitel(t["titel"]) for t in heute[:4])
                      + (f" und {len(heute) - 4} weitere" if len(heute) > 4 else ""))
    if woche:
        zeilen.append(f"Diese Woche: {woche} To-do{'s' if woche > 1 else ''}")
    for f in brief.get("fahrten") or []:
        zeilen.append(f["kurz"])
    n = len(brief.get("neue_mails") or [])
    if n:
        zeilen.append("1 Mail nicht eingeordnet" if n == 1 else f"{n} Mails nicht eingeordnet")
    n = len(brief["wartet"])
    if n:
        zeilen.append(f"{n} warten auf Antwort" if n > 1 else "1 wartet auf Antwort")
    if not zeilen:
        zeilen.append("Nichts braucht dich, keine To-dos.")
    return " · ".join(kopf), "\n".join(zeilen)[:600]


def fristen_morgen_titel(brief: dict, heute: date) -> list:
    """Titel der Punkte im Brief von heute, deren Frist morgen abläuft (seit 1.5.0 für den Abend-Push)."""
    morgen = (heute + timedelta(days=1)).isoformat()
    titel = [x["titel"] for x in brief.get("braucht_dich", []) + brief.get("demnaechst", []) if x.get("frist") == morgen]
    titel += [t["titel"] for t in brief.get("todos", []) if t.get("datum") == morgen]
    return list(dict.fromkeys(titel))


def fristen_morgen(brief: dict, heute: date) -> int:
    """Anzahl der Punkte im Brief von heute, deren Frist morgen abläuft (für den Abend-Push)."""
    return len(fristen_morgen_titel(brief, heute))
