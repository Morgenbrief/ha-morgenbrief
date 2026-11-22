"""Kalenderlogik: Feiertage in Bayern, Arbeitszeit, Tagesstatus, deutsche Datumstexte."""
from datetime import date, timedelta

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WOCHENTAGE_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]

# Montag, Dienstag, Donnerstag, Freitag
ARBEITSTAGE = {0, 1, 3, 4}


def ostersonntag(jahr: int) -> date:
    """Gregorianischer Osteralgorithmus (Meeus/Jones/Butcher)."""
    a = jahr % 19
    b, c = divmod(jahr, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    monat = (h + l - 7 * m + 114) // 31
    tag = (h + l - 7 * m + 114) % 31 + 1
    return date(jahr, monat, tag)


def feiertage_bayern(jahr: int) -> dict:
    """Gesetzliche Feiertage in Bayern, einschließlich Mariä Himmelfahrt (15.8.)."""
    ostern = ostersonntag(jahr)
    return {
        date(jahr, 1, 1): "Neujahr",
        date(jahr, 1, 6): "Heilige Drei Könige",
        ostern - timedelta(days=2): "Karfreitag",
        ostern + timedelta(days=1): "Ostermontag",
        date(jahr, 5, 1): "Tag der Arbeit",
        ostern + timedelta(days=39): "Christi Himmelfahrt",
        ostern + timedelta(days=50): "Pfingstmontag",
        ostern + timedelta(days=60): "Fronleichnam",
        date(jahr, 8, 15): "Mariä Himmelfahrt",
        date(jahr, 10, 3): "Tag der Deutschen Einheit",
        date(jahr, 11, 1): "Allerheiligen",
        date(jahr, 12, 25): "1. Weihnachtstag",
        date(jahr, 12, 26): "2. Weihnachtstag",
    }


def datum_lang(d: date) -> str:
    return f"{WOCHENTAGE[d.weekday()]}, {d.day}. {MONATE[d.month - 1]} {d.year}"


def datum_kurz(d: date) -> str:
    return f"{WOCHENTAGE_KURZ[d.weekday()]} {d.day:02d}.{d.month:02d}."


def ist_urlaub(titel: str) -> bool:
    """Eintrag mit 'Urlaub' im Titel zählt als frei, Schulferien-Einträge nicht."""
    t = titel.casefold()
    return "urlaub" in t and "ferien" not in t


def ist_kurztag(titel: str) -> bool:
    return "kurztag" in titel.casefold()


def tagesstatus(d: date, titel_des_tages: list) -> dict:
    """Bestimmt, ob gearbeitet wird, und liefert die Statuszeile.

    titel_des_tages: Titel aller Kalendereinträge, die diesen Tag berühren.
    """
    feiertag = feiertage_bayern(d.year).get(d)
    urlaub = any(ist_urlaub(t) for t in titel_des_tages)
    kurz = any(ist_kurztag(t) for t in titel_des_tages)
    wt = d.weekday()

    def frei(zeile, push):
        return {"arbeit": False, "kurz": False, "zeile": zeile, "push": push}

    if feiertag:
        return frei(f"Frei: Feiertag ({feiertag})", f"Feiertag ({feiertag})")
    if (d.month, d.day) == (12, 24):
        return frei("Frei: Heiligabend, Firma geschlossen", "Heiligabend, frei")
    if (d.month, d.day) == (12, 31):
        return frei("Frei: Silvester, Firma geschlossen", "Silvester, frei")
    if urlaub:
        return frei("Frei: Urlaub", "Urlaub")
    if wt == 2:
        return frei("Frei: Mittwoch", "frei")
    if wt in (5, 6):
        return frei("Frei: Wochenende", "frei")
    if wt in ARBEITSTAGE:
        if kurz:
            return {"arbeit": True, "kurz": True,
                    "zeile": "Kurztag: Arbeit 7:30 bis 15:00", "push": "Feierabend 15:00"}
        return {"arbeit": True, "kurz": False,
                "zeile": "Arbeit 7:30 bis 17:00", "push": "Arbeit bis 17:00"}
    return frei("Frei", "frei")


def ist_statusmarke(titel: str) -> bool:
    """Einträge, die nur den Tagesstatus steuern und schon in der Überschrift stehen."""
    return ist_kurztag(titel) or ist_urlaub(titel)


def ablauf_text(status: dict) -> str:
    """Ein Satz zum Tagesablauf unter der Überschrift."""
    if status.get("arbeit"):
        ende = "15:00" if status.get("kurz") else "17:00"
        satz = f"Arbeit von 7:30 bis {ende}, ab {ende} Uhr frei."
        if status.get("kurz"):
            satz += " Der Kurztag zieht den Feierabend zwei Stunden vor."
        return satz
    return "Der ganze Tag ist frei."
