"""Wetter für den Brief aus Home Assistant (seit 1.6.0).

Liest die Vorhersage einer Wetter-Entität über die Supervisor-Schnittstelle (homeassistant_api), also aus dem
Wetterdienst, den Home Assistant ohnehin nutzt. Kein neuer externer Dienst, kein Schlüssel. Option
`wetter_entitaet` (leer: weather.forecast_home, sonst die erste weather.*-Entität). Fehlt etwas, gibt es eben kein
Wetter, der Brief läuft weiter.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta

BASIS = "http://supervisor/core/api"
ZEITLIMIT = 15
STANDARD = "weather.forecast_home"
GLAETTE_GRAD = 1.0       # so kalt (oder kälter) und dazu Niederschlag: Glätte möglich
STUNDEN = 14             # so weit voraus wertet der Brief die stündliche Vorhersage aus (5:55 bis ca. 20 Uhr)

ZUSTAND = {"clear-night": "klar", "cloudy": "bewölkt", "fog": "Nebel", "hail": "Hagel", "lightning": "Gewitter",
           "lightning-rainy": "Gewitter mit Regen", "partlycloudy": "teils bewölkt", "pouring": "Starkregen",
           "rainy": "Regen", "snowy": "Schnee", "snowy-rainy": "Schneeregen", "sunny": "sonnig", "windy": "windig",
           "windy-variant": "windig", "exceptional": "Unwetter"}
NASS = {"rainy", "pouring", "snowy", "snowy-rainy", "hail", "lightning-rainy"}
MELDEN = {"fog", "snowy", "snowy-rainy", "hail", "pouring", "lightning", "lightning-rainy", "exceptional"}


def melde(text):
    """Wird von brief.py ersetzt."""


def _holen(pfad: str, daten: dict = None):
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return None
    req = urllib.request.Request(BASIS + pfad, data=json.dumps(daten).encode() if daten is not None else None,
                                 method="POST" if daten is not None else "GET",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=ZEITLIMIT) as r:
        return json.loads(r.read().decode("utf-8"))


def _entitaet(opt: dict) -> str:
    wunsch = (opt.get("wetter_entitaet") or "").strip()
    if wunsch:
        return wunsch
    zustaende = _holen("/states") or []
    namen = [z.get("entity_id", "") for z in zustaende if z.get("entity_id", "").startswith("weather.")]
    return STANDARD if STANDARD in namen else (namen[0] if namen else "")


def _vorhersage(entitaet: str, art: str) -> list:
    antwort = _holen("/services/weather/get_forecasts?return_response", {"entity_id": entitaet, "type": art}) or {}
    antwort = antwort.get("service_response", antwort)
    return ((antwort.get(entitaet) or {}).get("forecast")) or []


def auswerten(stunden: list, jetzt: datetime) -> dict:
    """Aus der stündlichen Vorhersage: Spanne, Lage, Regen ab, Glätte. Reine Rechnung, ohne Zugriff."""
    bis = jetzt + timedelta(hours=STUNDEN)
    werte = []
    for s in stunden:
        try:
            zeit = datetime.fromisoformat(str(s["datetime"]).replace("Z", "+00:00")).astimezone(jetzt.tzinfo)
        except (KeyError, ValueError):
            continue
        if jetzt - timedelta(hours=1) <= zeit <= bis and s.get("temperature") is not None:
            werte.append((zeit, float(s["temperature"]), float(s.get("precipitation") or 0),
                          s.get("condition") or ""))
    if not werte:
        return {}
    temps = [w[1] for w in werte]
    lage = max((w[3] for w in werte if 7 <= w[0].hour <= 18) or [werte[0][3]],
               key=[w[3] for w in werte].count)
    # seit 1.6.2 jeder Teil mit "bis" (ISO-Zeit): danach zeigt die Seite stattdessen "sonst" (oder nichts).
    # Der Brief entsteht um 5:55, gelesen wird er später ("Nebel gegen 5 Uhr" ist um 9 Uhr vorbei).
    teile = [{"text": f"{round(min(temps))} bis {round(max(temps))} °C"},
             {"text": ZUSTAND.get(lage, lage) if lage else ""}]
    nass = [w for w in werte if w[2] > 0.1 or w[3] in NASS]
    if nass:
        art = "Schnee" if nass[0][3] in ("snowy", "snowy-rainy") else "Regen"
        if nass[0][0] > werte[0][0] + timedelta(minutes=30):
            teile.append({"text": f"{art} ab {nass[0][0].hour} Uhr", "bis": nass[0][0].isoformat(), "sonst": art})
        else:
            teile.append({"text": f"{art} schon am Morgen", "bis": (werte[0][0] + timedelta(hours=4)).isoformat(),
                          "sonst": art})
    besonders = [w for w in werte if w[3] in MELDEN and w[3] != lage and not (nass and w[3] == nass[0][3])
                 and w[0] >= jetzt - timedelta(minutes=30)]
    if besonders:
        teile.append({"text": f"{ZUSTAND.get(besonders[0][3], besonders[0][3])} gegen {besonders[0][0].hour} Uhr",
                      "bis": (besonders[0][0] + timedelta(hours=1)).isoformat()})
    glatt = [w for w in werte if w[1] <= GLAETTE_GRAD and (w[2] > 0.1 or w[3] in NASS)]
    frost_morgen = [w for w in werte if w[1] <= 0 and w[0].hour <= 9]
    glaette = ""
    if glatt:
        glaette = (f"Um {glatt[0][0].hour} Uhr {round(glatt[0][1])} °C und "
                   f"{ZUSTAND.get(glatt[0][3], 'Niederschlag') if glatt[0][3] in NASS else 'Niederschlag'}.")
    elif frost_morgen and any(w[3] == "fog" for w in werte[:6]):
        glaette = f"Frost ({round(min(w[1] for w in frost_morgen))} °C) und Nebel am Morgen, Reifglätte möglich."
    zusatz = []
    if frost_morgen and not glaette:
        zusatz.append({"text": f"Morgens Frost bis {round(min(w[1] for w in frost_morgen))} °C, Scheiben frei kratzen.",
                       "bis": jetzt.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()})
    return {"zeile": zeile_bauen(teile, zusatz), "teile": teile, "zusatz": zusatz, "glaette": glaette,
            "min": round(min(temps)), "max": round(max(temps))}


def zeile_bauen(teile: list, zusatz: list, jetzt: datetime = None) -> str:
    """Wetterzeile; mit jetzt ohne die Teile, deren Zeit schon vorbei ist (seit 1.6.2)."""
    def text(t):
        if jetzt and t.get("bis"):
            try:
                if datetime.fromisoformat(t["bis"]) < jetzt:
                    return t.get("sonst", "")
            except ValueError:
                pass
        return t.get("text", "")

    haupt = [s for s in (text(t) for t in teile) if s]
    rest = [s for s in (text(t) for t in zusatz) if s]
    return "Wetter: " + ", ".join(haupt) + "." + "".join(" " + s for s in rest)


def vorhersage(opt: dict, jetzt: datetime) -> dict:
    try:
        entitaet = _entitaet(opt)
        if not entitaet:
            return {}
        ergebnis = auswerten(_vorhersage(entitaet, "hourly"), jetzt)
        if ergebnis:
            ergebnis["quelle"] = entitaet
            melde(f"Wetter gelesen ({entitaet}): {ergebnis['min']} bis {ergebnis['max']} °C"
                  + (", Glätte möglich" if ergebnis["glaette"] else ""))
        return ergebnis
    except (urllib.error.URLError, OSError, ValueError, TypeError, AttributeError) as e:
        melde(f"Wetter nicht lesbar: {type(e).__name__}")
        return {}
