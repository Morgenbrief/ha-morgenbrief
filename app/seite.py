"""HTML-Seiten des Add-ons. Alle Inhalte aus Mails und Kalender werden als Text maskiert ausgegeben."""
from datetime import date, datetime
from html import escape as e
from zoneinfo import ZoneInfo

import tage
import wetter

DEMNAECHST_SICHTBAR = 8  # seit 1.4.0: so viele Punkte unter "Demnächst" offen, der Rest zum Aufklappen

CSS = """
:root{--bg:#fbfaf7;--fg:#23221f;--soft:#6b6962;--line:#e6e3db;--accent:#b5562f;--card:#f4f1ea;--warn:#c0392b;
--himmel1:#fbdcc4;--himmel2:#fdf4ea;--huegel1:#ecd9c4;--huegel2:#dfc6ad;--sonne:#ea8a3e;--fahrt:#f8e1d3}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--fg:#eceae4;--soft:#a3a199;--line:#33312c;--accent:#e58e68;
--card:#211f1c;--warn:#e07060;--himmel1:#3a2a22;--himmel2:#1f1b18;--huegel1:#3b3029;--huegel2:#4a3b31;--sonne:#f2a464;
--fahrt:#3a251b}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:720px;margin:0 auto;padding:18px 16px 48px}
nav{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;margin-bottom:16px}
nav.unten{margin:22px 0 8px;padding-top:12px;border-top:1px solid var(--line)}
nav a{color:var(--soft);text-decoration:none}
nav a.aktiv{color:var(--fg);font-weight:600}
.gruss{color:var(--accent);font-weight:600;font-size:14px;margin:0}
.datum{color:var(--soft);font-size:14px;margin:0}
h1{font-family:Georgia,"Noto Serif","Times New Roman",serif;font-size:30px;line-height:1.2;margin:4px 0 12px;font-weight:700}
.ablauf{margin:-4px 0 8px;font-family:Georgia,"Noto Serif","Times New Roman",serif;font-size:18px;line-height:1.4}
.verkehr{display:flex;align-items:center;gap:10px;margin:2px 0 10px;padding:10px 14px;border-radius:12px;
background:var(--fahrt);color:var(--accent);font-weight:700;font-size:17px;line-height:1.3}
.verkehr .symbol{width:26px;height:26px;stroke-width:2}
.verkehr.stau{background:var(--warn);color:#fff}
.verkehr.stau .symbol{stroke:#fff}
h2{font-size:15px;margin:26px 0 8px;font-weight:650;letter-spacing:.01em}
.tagesbogen{display:block;width:100%;max-width:560px;height:auto;margin:8px auto 6px}
.tagesbogen .bogen{fill:none;stroke:var(--soft);stroke-width:2;stroke-dasharray:2 8;stroke-linecap:round;opacity:.75}
.tagesbogen .arbeit{fill:none;stroke:var(--accent);stroke-width:9;stroke-linecap:round;opacity:.9}
.tagesbogen .sonne circle{fill:var(--sonne)}
.tagesbogen .strahlen line{stroke:var(--sonne);stroke-width:3;stroke-linecap:round}
.tagesbogen .huegel1{fill:var(--huegel1)}
.tagesbogen .huegel2{fill:var(--huegel2)}
.tagesbogen .punkt{fill:var(--fg);stroke:var(--himmel2);stroke-width:3}
.tagesbogen .vogel{fill:none;stroke:var(--soft);stroke-width:2;stroke-linecap:round}
.tagesbogen text{font:600 25px -apple-system,"Segoe UI",Roboto,sans-serif;fill:var(--soft)}
.tagesbogen text.stark{fill:var(--fg)}
.karte{background:var(--card);border-radius:14px;padding:2px 16px 10px;margin:14px 0}
.karte.wichtig{box-shadow:inset 4px 0 0 var(--accent)}
.karte h2{display:flex;align-items:center;gap:8px;margin:12px 0 6px}
.symbol{width:19px;height:19px;flex:0 0 auto;fill:none;stroke:var(--accent);stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
ul.termine{list-style:none;margin:0;padding:0}
ul.termine li{display:flex;gap:12px;padding:6px 0;border-bottom:1px solid var(--line)}
ul.termine .zeit{flex:0 0 auto;min-width:118px;white-space:nowrap;color:var(--soft);font-variant-numeric:tabular-nums}
ol.liste{margin:0;padding-left:22px}
ol.liste li{padding:8px 0;border-bottom:1px solid var(--line)}
ol.liste li:last-child,ul.termine li:last-child{border-bottom:0}
ol.liste li::marker{color:var(--soft);font-size:13px}
.titel{font-weight:600}
a{color:inherit}
.titel a{text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
.satz{color:var(--soft);display:block}
.pille{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:#fff;
background:var(--warn);border-radius:999px;padding:1px 8px;margin-left:8px;vertical-align:2px}
.morgen{color:var(--soft);margin:8px 0 4px;font-size:15px}
h3.unter{font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--soft);margin:10px 0 0}
.aktionen{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.knopfform{display:inline;margin:0}
button.klein,.knopf.klein{font-size:13px;padding:4px 12px;margin:0;border-radius:999px}
.verkehr a{color:inherit;text-decoration:none}
.wetter{display:flex;align-items:center;gap:10px;margin:2px 0 10px;color:var(--soft);font-size:15px}
ul.erledigt{list-style:none;padding:0;margin:6px 0}
ul.erledigt li{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:4px 0}
.ruhig{color:var(--soft)}
.hinweis{display:flex;gap:10px;align-items:flex-start;background:var(--card);border-left:3px solid var(--accent);
border-radius:6px;padding:8px 12px;margin:10px 0;font-size:14px}
.hinweis .symbol{margin-top:1px}
.fehler{border-left-color:var(--warn)}
footer{margin-top:30px;color:var(--soft);font-size:13px}
details{margin-top:14px}
summary{cursor:pointer;color:var(--soft);font-size:13px}
button,.knopf{font:inherit;font-size:14px;padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer;text-decoration:none;display:inline-block;margin:6px 6px 0 0}
button.haupt,.knopf.haupt{background:var(--accent);border-color:var(--accent);color:#fff}
input[type=text]{font:inherit;font-size:14px;width:100%;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--fg)}
table{border-collapse:collapse;font-size:14px}
td{padding:3px 14px 3px 0;vertical-align:top}
td:first-child{color:var(--soft)}
code{background:var(--card);padding:1px 5px;border-radius:4px;font-size:13px}
ol.schritte li{margin:6px 0}
@media (max-width:480px){ul.termine .zeit{min-width:92px}h1{font-size:25px}}
"""


def _rahmen(titel: str, inhalt: str, neu_laden: int = 0) -> str:
    meta = f'<meta http-equiv="refresh" content="{neu_laden}">' if neu_laden else ""
    return ("<!DOCTYPE html><html lang=\"de\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"{meta}<title>{e(titel)}</title><style>{CSS}</style></head>"
            f"<body><main>{inhalt}</main></body></html>")


def _link(text: str, url: str) -> str:
    if url and url.startswith("https://"):
        return f'<a href="{e(url, quote=True)}" target="_blank" rel="noopener noreferrer">{e(text)}</a>'
    return e(text)


def _navigation(basis: str, tage_liste: list, aktiv: str, heute: date) -> str:
    teile = []
    for t in tage_liste:
        d = date.fromisoformat(t)
        name = "Heute" if d == heute else tage.datum_kurz(d)
        klasse = ' class="aktiv"' if t == aktiv else ""
        teile.append(f'<a{klasse} href="{e(basis)}/tag/{t}">{e(name)}</a>')
    teile.append(f'<a href="{e(basis)}/einrichtung">Einrichtung</a>')
    return "<nav>" + "".join(teile) + "</nav>"


import math
import re


def _termine(liste: list) -> str:
    if not liste:
        return ""
    zeilen = "".join(f'<li><span class="zeit">{e(t["zeit"])}</span><span>{_link(t["titel"], t.get("link", ""))}</span></li>'
                     for t in liste)
    return f'<ul class="termine">{zeilen}</ul>'


def _knopf(basis: str, x: dict) -> str:
    """Erledigt- bzw. Bezahlt-Knopf (seit 1.5.0)."""
    if not x.get("schluessel"):
        return ""
    wort = "Bezahlt" if x.get("rechnung") else "Erledigt"
    return (f'<form class="knopfform" method="post" action="{e(basis)}/erledigt">'
            f'<input type="hidden" name="s" value="{e(x["schluessel"], quote=True)}">'
            f'<button class="klein">{wort}</button></form>')


def _eintraege(liste: list, basis: str = None) -> str:
    """basis gesetzt: Knöpfe zeigen (nur im Brief von heute)."""
    zeilen = []
    for x in liste:
        text = " ".join(s for s in (x.get("quelle", ""), x.get("satz", "")) if s)
        marke = f'<span class="pille">{e(x["marke"])}</span>' if x.get("marke") else ""
        aktionen = ""
        if x.get("kalender_link", "").startswith("https://calendar.google.com/"):
            aktionen += (f'<a class="knopf klein" href="{e(x["kalender_link"], quote=True)}" target="_blank" '
                         'rel="noopener noreferrer">In Kalender eintragen</a>')
        if x.get("mail_link", "").startswith("https://mail.google.com/"):  # seit 1.6.0
            aktionen += (f'<a class="knopf klein" href="{e(x["mail_link"], quote=True)}" target="_blank" '
                         'rel="noopener noreferrer">Mail öffnen</a>')
        if basis is not None:
            aktionen += _knopf(basis, x)
        zeilen.append(f'<li><span class="titel">{_link(x["titel"], x.get("link", ""))}</span>{marke}'
                      f'<span class="satz">{e(text)}</span>'
                      + (f'<span class="aktionen">{aktionen}</span>' if aktionen else "") + "</li>")
    return '<ol class="liste">' + "".join(zeilen) + "</ol>"


def _werkzeuge(basis: str, befehle: list = None) -> str:
    """Seit 1.6.0 mit den Befehlen aus To-do-Notizen (zum Kopieren ins HA-Terminal)."""
    zusatz = ""
    if befehle:
        zusatz = ('<p class="ruhig">Befehle aus den To-dos, für das HA-Terminal:</p>'
                  + "".join(f'<p><code>{e(b)}</code></p>' for b in befehle))
    return (f'<details><summary>Werkzeuge</summary>'
            f'<form method="post" action="{e(basis)}/erzeugen">'
            f'<button name="push" value="0">Jetzt erzeugen (ohne Push)</button>'
            f'<button name="push" value="1">Jetzt erzeugen und Push senden</button></form>{zusatz}</details>')


def _laufmeldung(lauf: dict) -> str:
    if lauf.get("laeuft"):
        return '<div class="hinweis">Der Brief wird gerade erzeugt. Die Seite lädt von selbst neu.</div>'
    if lauf.get("fehler"):
        return f'<div class="hinweis fehler">Letzter Lauf fehlgeschlagen: {e(lauf["fehler"])}</div>'
    return ""


def _morgen_eintrag(t: dict) -> str:
    zeit = t["zeit"]
    if zeit.startswith("ganztägig"):
        rest = zeit[len("ganztägig"):].strip(", ")
        return t["titel"] + (f" ({rest})" if rest else "")
    return zeit + " " + t["titel"]


# Einfache Strich-Symbole (24er Raster), Farbe kommt aus dem CSS
SYMBOLE = {
    "glocke": "M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9 M10.3 21a1.94 1.94 0 0 0 3.4 0",
    "haken": "M22 11.08V12a10 10 0 1 1-5.93-9.14 M22 4 12 14.01l-3-3",
    "sanduhr": "M5 22h14 M5 2h14 M17 22v-4.17a2 2 0 0 0-.59-1.42L12 12l-4.41 4.41A2 2 0 0 0 7 17.83V22 "
               "M7 2v4.17a2 2 0 0 0 .59 1.42L12 12l4.41-4.41A2 2 0 0 0 17 6.17V2",
    "liste": "M9 11l3 3L22 4 M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11",
    "post": "M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z M22 6l-10 7L2 6",
    "kalender": "M8 2v4 M16 2v4 M3 10h18 M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
    "info": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M12 16v-4 M12 8h.01",
    "auto": "M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5"
            "c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2 M9 17h6 "
            "M5 17a2 2 0 1 0 4 0a2 2 0 1 0-4 0 M15 17a2 2 0 1 0 4 0a2 2 0 1 0-4 0",
    "wolke": "M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9z",
}


def _symbol(name: str) -> str:
    return f'<svg class="symbol" viewBox="0 0 24 24" aria-hidden="true"><path d="{SYMBOLE[name]}"/></svg>'


def _karte(symbol: str, titel: str, inhalt: str, klasse: str = "") -> str:
    k = "karte" + (" " + klasse if klasse else "")
    return f'<section class="{k}"><h2>{_symbol(symbol)}{e(titel)}</h2>{inhalt}</section>'


# ------------------------------------------------------------ Tagesbogen
_UHR = re.compile(r"^(?:ab )?(\d{1,2}):(\d{2})")


def _punkt(stunde: float):
    """Stelle auf dem Tagesbogen von 6 bis 22 Uhr."""
    t = min(max((stunde - 6) / 16, 0), 1)
    w = math.pi * (1 - t)
    return 300 + 262 * math.cos(w), 166 - 118 * math.sin(w)


def _bogen(von: float, bis: float) -> str:
    x0, y0 = _punkt(von)
    x1, y1 = _punkt(bis)
    return f"M{x0:.1f},{y0:.1f} A262,118 0 0 1 {x1:.1f},{y1:.1f}"


def _tagesbogen(brief: dict) -> str:
    """Kopfbild: Sonne über Hügeln, Bogen von 6 bis 22 Uhr mit Arbeitszeit und Terminen."""
    status = brief.get("status") or {}
    arbeit = status.get("arbeit")
    t = ['<svg class="tagesbogen" viewBox="0 0 600 200" role="img" aria-label="Tagesverlauf">',
         '<defs><linearGradient id="mb-himmel" x1="0" y1="0" x2="0" y2="1">'
         '<stop offset="0" style="stop-color:var(--himmel1)"/><stop offset="1" style="stop-color:var(--himmel2)"/>'
         '</linearGradient><clipPath id="mb-rahmen"><rect width="600" height="200" rx="18"/></clipPath></defs>',
         '<g clip-path="url(#mb-rahmen)"><rect width="600" height="200" fill="url(#mb-himmel)"/>']
    # Sonne beim Aufgang, an freien Tagen etwas größer
    sx, sy = _punkt(6.9)
    r = 19 if arbeit else 23
    strahlen = "".join(
        f'<line x1="{sx + (r + 7) * math.cos(a):.1f}" y1="{sy + (r + 7) * math.sin(a):.1f}" '
        f'x2="{sx + (r + 15) * math.cos(a):.1f}" y2="{sy + (r + 15) * math.sin(a):.1f}"/>'
        for a in (i * math.pi / 4 for i in range(8)))
    t.append(f'<g class="sonne"><circle cx="{sx:.1f}" cy="{sy:.1f}" r="{r}"/><g class="strahlen">{strahlen}</g></g>')
    if not arbeit:
        t.append('<path class="vogel" d="M505,32 q8,-8 16,0 q8,-8 16,0"/>'
                 '<path class="vogel" d="M548,20 q6,-6 12,0 q6,-6 12,0"/>')
    # Vögel seit 1.3.5 oben rechts: dort liegt keine Uhrzeit (Beschriftungen ab x 500 erst unter y 70)
    # Hügel vor der Sonne, damit sie am Morgen aufgeht
    t.append('<path class="huegel1" d="M0,166 C90,146 190,154 290,162 C400,172 500,148 600,156 L600,200 L0,200 Z"/>'
             '<path class="huegel2" d="M0,184 C130,170 250,188 380,180 C480,174 550,182 600,178 L600,200 L0,200 Z"/>')
    t.append(f'<path class="bogen" d="{_bogen(6, 14)} {_bogen(14, 22)[_bogen(14, 22).index("A"):]}"/>')
    if arbeit:
        ende = 15 if status.get("kurz") else 17
        t.append(f'<path class="arbeit" d="{_bogen(7.5, ende)}"/>')
        mx, my = _punkt((7.5 + ende) / 2)
        t.append(f'<text class="stark" x="{mx:.1f}" y="{my - 18:.1f}" text-anchor="middle">Arbeit</text>')
        ex, ey = _punkt(ende)
        t.append(f'<text x="{ex:.1f}" y="{ey - 18:.1f}" text-anchor="middle">{ende}:00</text>')
    # Beschriftung im Bogen seit 1.3.2 nur noch Uhrzeiten, der Termin steht darunter im Kalenderblock
    belegt = [_punkt((7.5 + ende) / 2)[0], _punkt(ende)[0]] if arbeit else []
    for termin in brief.get("termine_bogen", brief.get("termine_heute")) or []:
        m = _UHR.match(termin.get("zeit", ""))
        if not m:
            continue
        stunde = int(m.group(1)) + int(m.group(2)) / 60
        if not 6 <= stunde <= 22:
            continue
        px, py = _punkt(stunde)
        t.append(f'<circle class="punkt" cx="{px:.1f}" cy="{py:.1f}" r="7"/>')
        if all(abs(px - b) > 80 for b in belegt):
            anker = "end" if px > 520 else ("start" if px < 80 else "middle")
            t.append(f'<text class="stark" x="{px:.1f}" y="{py - 18:.1f}" text-anchor="{anker}">'
                     f'{e(m.group(1) + ":" + m.group(2))}</text>')
            belegt.append(px)
    t.append("</g></svg>")
    return "".join(t)


def brief_seite(brief: dict, basis: str, tage_liste: list, lauf: dict, heute: date, erledigt_heute: list = None,
                ablage_fehler: str = "") -> str:
    ist_heute = brief["datum"] == heute.isoformat()
    knopf_basis = basis if ist_heute else None  # Knöpfe nur im Brief von heute (seit 1.5.0)
    teile = [_laufmeldung(lauf)]  # seit 1.6.3 steht die Navigation (frühere Briefe, Einrichtung) ganz unten
    if brief["datum"] != heute.isoformat():
        teile.append('<div class="hinweis">Das ist ein älterer Brief, nicht der von heute.</div>')
    teile.append(f'<p class="gruss">Guten Morgen</p><p class="datum">{e(brief["datum_text"])}</p>'
                 f'<h1>{e(brief["status"]["zeile"])}</h1>')
    if brief.get("ablauf"):
        teile.append(f'<p class="ablauf">{e(brief["ablauf"])}</p>')
    verkehr = brief.get("verkehr")
    if verkehr:  # seit 1.3.6
        zusatz = f', Stau +{verkehr["extra_min"]} Min.' if verkehr.get("stoerung") and verkehr.get("extra_min") else ""
        klasse = "verkehr stau" if verkehr.get("stoerung") else "verkehr"
        teile.append(f'<p class="{klasse}">{_symbol("auto")}<span>{e(verkehr["zeile"] + zusatz)}</span></p>')
    for f in brief.get("fahrten") or []:  # seit 1.5.0: Fahrten und Termine mit Ort
        teile.append(f'<p class="verkehr">{_symbol("auto")}<span>{_link(f["zeile"], f.get("link", ""))}</span></p>')
    wetter_info = brief.get("wetter") or {}
    if wetter_info.get("zeile"):  # seit 1.6.0
        zeile = wetter_info["zeile"]
        if ist_heute and wetter_info.get("teile"):  # seit 1.6.2: nur was ab jetzt noch kommt
            zeile = wetter.zeile_bauen(wetter_info["teile"], wetter_info.get("zusatz") or [],
                                       datetime.now(ZoneInfo("Europe/Berlin")))
        teile.append(f'<p class="wetter">{_symbol("wolke")}<span>{e(zeile)}</span></p>')
    teile.append(_tagesbogen(brief))
    if brief.get("waechter"):
        teile.append(f'<div class="hinweis fehler">{_symbol("info")}<span>{e(brief["waechter"])}</span></div>')

    morgen = brief["morgen"]
    morgen_text = morgen.get("zeile") or ""
    if not morgen_text:  # Briefe vor 1.2.2
        morgen_text = "Morgen: " + morgen["status"]
        if morgen["termine"]:
            morgen_text += ". " + "; ".join(_morgen_eintrag(t) for t in morgen["termine"][:5])
            if len(morgen["termine"]) > 5:
                morgen_text += f" und {len(morgen['termine']) - 5} weitere"
    kalender = (_termine(brief["termine_heute"]) if brief["termine_heute"]
                else '<p class="ruhig">Keine Termine im Kalender.</p>')
    kalender += f'<p class="morgen">{e(morgen_text)}</p>'
    woche = brief.get("woche") or []
    if woche:  # seit 1.6.0: normale Termine bis heute + 7 (vorher fehlten sie ganz)
        zeilen = [dict(t, titel=t["titel"] + (f" ({t['frei']})" if t.get("frei") and t["frei"] != "frei" else ""))
                  for t in woche]
        kalender += f'<h3 class="unter">Nächste Tage</h3>{_termine(zeilen)}'
    teile.append(_karte("kalender", "Heute im Kalender", kalender))

    # Seit 1.4.0 dieselben Karten mit und ohne Gemini: Rechnungen, Fristen und gemerkte Punkte gibt es immer
    if brief["braucht_dich"]:
        teile.append(_karte("glocke", "Braucht dich", _eintraege(brief["braucht_dich"], knopf_basis), "wichtig"))
    if brief["geklaert"]:
        teile.append(_karte("haken", "Schon geklärt", _eintraege(brief["geklaert"], knopf_basis)))
    if brief.get("neue_mails"):
        teile.append(_karte("post", "Noch nicht eingeordnete Mails", _eintraege(brief["neue_mails"])))
    if not brief["braucht_dich"] and not brief["geklaert"] and not brief.get("neue_mails"):
        teile.append(_karte("haken", "Mails", '<p class="ruhig">Nichts braucht dich heute Morgen.</p>'))

    if brief["wartet"]:
        teile.append(_karte("sanduhr", "Wartet auf Antwort", _eintraege(brief["wartet"])))
    if brief["todos"]:
        heute_text, woche = [], []
        for t in brief["todos"]:
            wann = t["wann"].rstrip(".")
            if t.get("ueberfaellig"):
                quelle = (wann[len("Überfällig s"):] and "S" + wann[len("Überfällig s"):]) + "."
            else:
                quelle = "Fällig: " + wann + "."
            satz = t.get("satz", "")
            if t.get("passiv"):  # seit 1.6.0: reiner Hinweis, ohne Knopf
                satz = "Nur zur Info, nichts zu erledigen." + (" " + satz if satz else "")
            zeile = {"titel": t["titel"], "link": t["link"], "quelle": quelle, "satz": satz,
                     "marke": "überfällig" if t.get("ueberfaellig") else "", "schluessel": t.get("schluessel", ""),
                     "mail_link": t.get("mail_link", "")}
            (heute_text if (t.get("datum") or brief["datum"]) <= brief["datum"] else woche).append(zeile)
        if heute_text and woche:  # seit 1.4.0 gegliedert, alle To-dos bis heute + 7 Tage
            inhalt = (f'<h3 class="unter">Heute</h3>{_eintraege(heute_text, knopf_basis)}'
                      f'<h3 class="unter">Nächste 7 Tage</h3>{_eintraege(woche, knopf_basis)}')
        else:
            inhalt = _eintraege(heute_text or woche, knopf_basis)
        teile.append(_karte("liste", "Offene To-dos", inhalt))
    if brief.get("demnaechst"):
        liste = brief["demnaechst"]
        inhalt = _eintraege(liste[:DEMNAECHST_SICHTBAR], knopf_basis)
        if len(liste) > DEMNAECHST_SICHTBAR:  # seit 1.4.0 nichts mehr abgeschnitten, nur eingeklappt
            rest = liste[DEMNAECHST_SICHTBAR:]
            bis = rest[-1].get("frist", "")
            bis_text = f" bis {tage.datum_kurz(date.fromisoformat(bis))}" if bis else ""
            inhalt += (f'<details><summary>{len(rest)} weitere{e(bis_text)}</summary>'
                       f'{_eintraege(rest, knopf_basis)}</details>')
        teile.append(_karte("kalender", "Demnächst", inhalt))
    if ist_heute and erledigt_heute:  # seit 1.5.0
        zeilen_erl = "".join(
            f'<li><span>{e(x.get("titel", ""))}{" (bezahlt)" if x.get("art") == "bezahlt" else ""}</span>'
            f'<form class="knopfform" method="post" action="{e(basis)}/rueckgaengig">'
            f'<input type="hidden" name="s" value="{e(x["schluessel"], quote=True)}">'
            f'<button class="klein">Rückgängig</button></form></li>' for x in erledigt_heute)
        hinweis = ("Die nächtliche Aufräumaufgabe hakt sie im To-do-Doc ab." if not ablage_fehler
                   else "Weitergabe an die nächtliche Aufräumaufgabe fehlt: " + ablage_fehler)
        teile.append(f'<details><summary>Heute im Brief erledigt ({len(erledigt_heute)})</summary>'
                     f'<ul class="erledigt">{zeilen_erl}</ul><p class="ruhig">{e(hinweis)}</p></details>')

    # oranger Kasten, wenn Mails nicht eingeordnet sind, sonst stehen Hinweise in der Fußzeile
    regel = bool(brief["gemini"].get("fehler")) or bool(brief.get("neue_mails"))
    if regel:
        for h in brief.get("hinweise", []):
            teile.append(f'<div class="hinweis">{_symbol("info")}<span>{e(h)}</span></div>')

    weg = brief.get("weggelassen", [])
    if weg:
        zeilen_weg = "".join(f'<li>{e(w["von"])}: {_link(w["betreff"], w.get("link", ""))}</li>' for w in weg)
        teile.append(f'<details><summary>Weggelassen, weil ohne Handlungsbedarf ({len(weg)})</summary>'
                     f'<ul>{zeilen_weg}</ul></details>')

    erzeugt = datetime.fromisoformat(brief["erzeugt"])
    zahlen = brief.get("zahlen", {})
    if "im_fenster" not in zahlen:  # Briefe vor 1.2.2
        fuss = f"Erzeugt um {erzeugt:%H:%M} Uhr. Geprüfte Mails: {zahlen.get('geprueft', 0)}."
    elif "fenster_tage" in zahlen:  # seit 1.6.0 mit Erklärung
        posteingang = zahlen["geprueft"] - zahlen.get("abgelegt", 0)
        fuss = (f"Erzeugt um {erzeugt:%H:%M} Uhr. Im Posteingang liegen {zahlen['im_fenster']} Mails der letzten "
                f"{zahlen['fenster_tage']} Tage, davon wurden {posteingang} als möglicherweise wichtig geprüft "
                "(keine Werbung, keine Benachrichtigungen ohne Frist oder Rechnung)"
                + (f". Dazu {zahlen['abgelegt']} ungelesen von einem Gmail-Filter abgelegte Mail"
                   + ("s" if zahlen["abgelegt"] > 1 else "") if zahlen.get("abgelegt") else "") + ".")
    elif "neu_eingeordnet" in zahlen:  # seit 1.4.0
        fuss = (f"Erzeugt um {erzeugt:%H:%M} Uhr. Mails: {zahlen['geprueft']} geprüft"
                + (f" (davon {zahlen['abgelegt']} ungelesen abgelegt)" if zahlen.get("abgelegt") else "")
                + f", {zahlen['im_fenster']} im Posteingang der letzten 48 Stunden.")
    elif regel:
        fuss = f"Erzeugt um {erzeugt:%H:%M} Uhr. Mails: {zahlen['im_fenster']} im Zeitfenster, nicht eingeordnet."
    else:
        fuss = f"Erzeugt um {erzeugt:%H:%M} Uhr. Mails: {zahlen['geprueft']} von {zahlen['im_fenster']} eingeordnet."
    g_info = brief["gemini"]
    if "tokens" in g_info and "fenster_tage" in zahlen:  # seit 1.6.0 mit Erklärung
        if g_info.get("tokens"):
            fuss += (f" Gemini ({g_info.get('modell')}) hat {g_info.get('neu', 0)} Mails zum ersten Mal eingeordnet "
                     f"({g_info['tokens']} Tokens), die übrigen waren schon eingeordnet und gemerkt.")
        elif not g_info.get("fehler"):
            fuss += " Alle waren schon eingeordnet, Gemini wurde nicht gefragt."
    elif "tokens" in g_info:  # seit 1.4.0: nur Neues geht an Gemini, die Zahl zeigt den Verbrauch des Laufs
        if g_info.get("tokens"):
            fuss += f" Gemini ({g_info.get('modell')}): {g_info.get('neu', 0)} neu eingeordnet, {g_info['tokens']} Tokens."
        elif not g_info.get("fehler"):
            fuss += " Gemini: keine Anfrage nötig."
    elif g_info["genutzt"] and g_info["modell"]:
        fuss += f" Einordnung: {g_info['modell']}."
    if not regel and brief.get("hinweise"):
        fuss += " " + " ".join(brief["hinweise"])
    offen = (brief.get("gedaechtnis") or {}).get("offen")
    if offen and "fenster_tage" in zahlen:  # seit 1.6.0 mit Erklärung
        fuss += (f" Gedächtnis: {offen} {'offener Vorgang' if offen == 1 else 'offene Vorgänge'} aus früheren Mails "
                 "werden weiter verfolgt, bis sie erledigt, archiviert oder beantwortet sind.")
    elif offen:
        fuss += f" Gedächtnis: {offen} offen."
    teile.append(f"<footer>{e(fuss)}</footer>")
    teile.append(_werkzeuge(basis, brief.get("befehle")))
    teile.append(_navigation(basis, tage_liste, brief["datum"], heute).replace("<nav>", '<nav class="unten">', 1))
    return _rahmen("Morgenbrief", "".join(teile), neu_laden=5 if lauf.get("laeuft") else 0)



def leere_seite(basis: str, tage_liste: list, lauf: dict, heute: date, verbunden: bool) -> str:
    teile = [_navigation(basis, tage_liste, "", heute), _laufmeldung(lauf),
             f'<p class="datum">{e(tage.datum_lang(heute))}</p><h1>Noch kein Brief für heute</h1>']
    if verbunden:
        teile.append('<p class="ruhig">Der nächste Brief kommt zur eingestellten Zeit. '
                     'Für einen Test gibt es unten die Werkzeuge.</p>')
        teile.append(_werkzeuge(basis))
    else:
        teile.append(f'<p>Google ist noch nicht verbunden. <a href="{e(basis)}/einrichtung">Zur Einrichtung</a></p>')
    return _rahmen("Morgenbrief", "".join(teile), neu_laden=5 if lauf.get("laeuft") else 0)


def einrichtung_seite(basis: str, opt: dict, info: dict, meldung: str = "", fehler: str = "") -> str:
    """info: verbunden, verbunden_am, konto, auth_url, zustand, naechster_lauf, modell"""
    teile = [f'<nav><a href="{e(basis)}/">Zum Brief</a></nav><h1>Einrichtung</h1>']
    if meldung:
        teile.append(f'<div class="hinweis">{e(meldung)}</div>')
    if fehler:
        teile.append(f'<div class="hinweis fehler">{e(fehler)}</div>')

    ja, nein = "ja", "fehlt"
    zeilen = [
        ("Google-Client-ID", ja if opt["google_client_id"] else nein),
        ("Google-Client-Secret", ja if opt["google_client_secret"] else nein),
        ("Gemini-Schlüssel", ja if opt["gemini_api_key"] else "fehlt (Brief kommt dann als Regel-Fassung)"),
        ("Gemini-Modell", (info.get("modell") or opt.get("gemini_modell", "auto"))
         + (" (zuletzt genutzt)" if info.get("modell") else "")),
        ("Gemini-Tokens", f"{info.get('tokens_monat', 0)} in diesem Monat (nur neue Mails gehen an Gemini)"),
        ("Weitergabe an den Nachtlauf", info.get("ablage", "")),
        ("Google verbunden", ("ja, seit " + info["verbunden_am"]) if info.get("verbunden") else "nein"),
        ("Konto", info.get("konto") or "noch unbekannt"),
        ("Zeiten", f"Mo/Di/Do/Fr {opt['zeit_arbeitstage']}, Mi/Sa/So {opt['zeit_freie_tage']}"),
        ("Abend-Push", "aus" if opt.get("zeit_abend") == "aus"
         else f"{opt.get('zeit_abend') or '19:00'}, nur wenn morgen eine Frist abläuft oder eine Fahrt ansteht"),
        ("TomTom-Schlüssel", ja if opt.get("tomtom_api_key") else "fehlt (keine Abfahrtszeit)"),
        ("Arbeitsweg", f"{opt.get('verkehr_start', '')} nach {opt.get('verkehr_ziel', '')}, Ankunft "
                       f"{opt.get('verkehr_ankunft') or '07:25'}, Störung ab {opt.get('verkehr_schwelle_min') or 3} Min. "
                       "oder bei Sperrung"),
        ("Nächster Lauf", info.get("naechster_lauf", "")),
        ("Push an", "notify." + opt["push_dienst"]),
        ("Letzter Lauf", info.get("letzter_lauf") or "noch keiner"),
    ]
    teile.append("<h2>Stand</h2><table>" + "".join(
        f"<tr><td>{e(a)}</td><td>{e(str(b))}</td></tr>" for a, b in zeilen) + "</table>")
    teile.append('<p class="ruhig">Schlüssel werden in den Add-on-Optionen eingetragen '
                 '(Einstellungen, Apps, Morgenbrief, Konfiguration). Nach dem Speichern das Add-on neu starten.</p>')

    teile.append("<h2>Mit Google verbinden</h2>")
    if not (opt["google_client_id"] and opt["google_client_secret"]):
        teile.append('<p class="ruhig">Zuerst Client-ID und Client-Secret in den Optionen eintragen.</p>')
    else:
        teile.append(
            '<ol class="schritte">'
            f'<li><a class="knopf haupt" href="{e(info["auth_url"], quote=True)}" target="_blank" '
            'rel="noopener noreferrer">Mit Google verbinden</a><br>Es öffnet sich ein neuer Tab. Dort das Konto '
            'wählen und den Lesezugriff auf Gmail und Kalender erlauben. Bei der Warnung "Google hat diese App '
            'nicht überprüft" auf "Erweitert" und dann auf "Weiter" klicken.</li>'
            '<li>Danach zeigt der Browser eine Fehlerseite ("Die Website ist nicht erreichbar", Adresse beginnt mit '
            '<code>http://127.0.0.1:8765/</code>). Das ist richtig so. Die komplette Adresse aus der Adresszeile kopieren.</li>'
            f'<li>Hier einfügen und absenden:<form method="post" action="{e(basis)}/google/code">'
            '<input type="text" name="adresse" placeholder="http://127.0.0.1:8765/?state=...&code=..." autocomplete="off">'
            '<button class="haupt">Verbindung abschließen</button></form></li></ol>')
        if info.get("verbunden"):
            teile.append(f'<form method="post" action="{e(basis)}/google/test">'
                         '<button>Verbindung testen</button></form>')

    teile.append("<h2>Test</h2>" + _werkzeuge(basis).replace("<details>", "<details open>"))
    teile.append(f'<form method="post" action="{e(basis)}/push/test"><button>Nur Test-Push senden</button></form>')
    return _rahmen("Morgenbrief Einrichtung", "".join(teile))
