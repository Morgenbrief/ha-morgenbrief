# Morgenbrief

Erzeugt jeden Morgen eine Übersicht aus Google Kalender und Gmail und schickt einen Push aufs Handy.

## Zeiten
- Arbeitstage (im Code: Mo, Di, Do, Fr): `zeit_arbeitstage` (Standard 06:54)
- Mittwoch, Samstag, Sonntag: `zeit_freie_tage` (Standard 06:54)
- War der Pi zur Sollzeit aus, wird der Brief bis vier Stunden danach nachgeholt.

## Inhalt
- Statuszeile: Arbeit 7:30 bis 17:00, Kurztag (Eintrag "Kurztag") bis 15:00, frei bei "Urlaub" im Titel (Schulferien zählen nicht),
  an bayerischen Feiertagen, am 24.12. und 31.12., mittwochs und am Wochenende.
- Termine heute und eine Zeile zu morgen, aus allen Kalendern des Kontos, seit 1.6.0 darunter "Nächste Tage" (seit 1.6.1 normale Termine von morgen und übermorgen, freie Tage markiert; die Morgen-Zeile nennt dann nur den Status). To-dos stehen nur unter "Offene To-dos". Was unter "Braucht dich" steht, erscheint nicht noch einmal im Kalenderblock.
- Überschneidungen (seit 1.6.0): Termine mit Uhrzeit, die sich heute bis in 7 Tagen überschneiden oder in die Arbeitszeit fallen, ganz oben unter "Braucht dich".
- Wetter (seit 1.6.0): aus der Wetter-Entität von Home Assistant (Option wetter_entitaet, Standard weather.forecast_home). Glätte bei Fahrt oder Arbeitstag unter "Braucht dich".
- Geburtstage (seit 1.6.0): ganztägiger Eintrag mit "Geburtstag" heute als "X gratulieren" unter "Braucht dich".
- Braucht dich / Schon geklärt: Posteingang der letzten 7 Tage (seit 1.6.0, vorher 48 Stunden; geklärte und weggelassene Mails nur aus den letzten 48 Stunden; Kategorie Allgemein, Antworten auf eigene Mails,
  dazu Rechnungen und Fristen aus Benachrichtigungen und Foren) und, seit 1.4.0, Rechnungen und Fristen, die ein
  Gmail-Filter ungelesen am Posteingang vorbei einsortiert hat (72 Stunden). Anhänge werden nie gelesen oder gesendet,
  nur ob ein PDF dabei ist, wird geprüft.
- Einordnung (seit 1.4.0): Jede Mail geht nur einmal an Gemini (höchstens 20 neue je Lauf, je 3.000 Zeichen), danach
  gilt das gemerkte Ergebnis. Feste Regeln stehen über Gemini und gelten auch ohne Gemini: zu zahlende Rechnungen
  (mit Zahlungsaufforderung oder PDF, nicht Lastschrift, nicht "zur Information"), Mahnungen, Frist- und Abo-Mails,
  Absender aus IMMER_WICHTIG. Eine Zahlungsbestätigung mit derselben Rechnungsnummer schließt die Rechnung.
- Wartet auf Antwort: gesendete Mails, 3 bis 30 Tage alt, ohne menschliche Antwort, nicht an noreply-Adressen.
- Offene To-dos: Kalendereinträge, deren Beschreibung mit "Aus der To-do-Liste:" beginnt, alle von heute (mit überfälligen der letzten 14 Tage) bis in sieben Tagen, gegliedert in "Heute" und "Nächste 7 Tage". Rechnungs-To-dos stehen unter "Braucht dich".
- Demnächst: Mails mit Frist nach heute plus 7 Tagen (Rechnungen: plus 14) bis 120 Tage voraus und spätere To-dos aus dem Kalender, nach Frist sortiert, ohne Höchstzahl (acht sichtbar, der Rest zum Aufklappen). Gibt es zu einer Mail schon einen Kalendereintrag, steht nur dieser da, seit 1.6.0 mit dem Inhalt der Mail und "Mail öffnen"; reicht seine Frist bis in 14 Tagen, unter "Braucht dich". Reine Hinweise ("abwarten") ohne Erledigt-Knopf.
- Gedächtnis: Mails unter "Braucht dich" oder "Demnächst" merkt sich das Add-on (Datei gedaechtnis.sqlite im Datenordner) und zeigt sie weiter, auch wenn Gemini ausfällt, bis sie erledigt sind: eigene Antwort im Thread (dann "wartet"), Mail archiviert oder gelöscht, passender Kalendereintrag mit ✓, Zahlungsbestätigung mit derselben Rechnungsnummer, neue Antwort, die Gemini als geklärt oder ohne Handlungsbedarf einordnet. Ungelesen abgelegte Mails lagen nie im Posteingang, für sie zählt "archiviert" nicht. Ohne Frist verschwinden Punkte nach 30 Tagen, mit Frist 14 Tage nach der Frist.
- Wächter: Die nächtliche Claude-Aufgabe "ToDo-Liste: Aufräumen + Termine in Kalender" aktualisiert jede Nacht den Kalendereintrag "MB-Herzschlag (Morgenbrief-Wächter, nicht löschen)" am 01.01.2026. Ist er älter als 26 Stunden oder fehlt er, steht oben ein roter Hinweis.
- Verkehr (seit 1.3.6): an Arbeitstagen "Losfahren bis HH:MM (X Min. Fahrt)" aus TomTom-Routing mit Live-Verkehr, zurückgerechnet von verkehr_ankunft. Störung (Mehrzeit ab verkehr_schwelle_min gegenüber freier Fahrt oder gemeldete Sperrung auf der normalen Strecke) steht oben unter "Braucht dich", der Push bekommt "Stau +X Min.". Adressen und normale Strecke liegen in verkehr.json im Datenordner (30 Tage, bei Adressänderung neu).
- Abend-Push: zur Zeit zeit_abend, nur wenn morgen eine Frist abläuft (Punkte mit Frist und To-dos) oder eine Fahrt ansteht. Seit 1.5.0 mit Titeln ohne Beträge und der besten Abfahrt.
- Erledigt/Bezahlt (seit 1.5.0): Knopf an jedem Punkt im Brief von heute. Der Punkt verschwindet sofort, bleibt 60 Tage gemerkt (erledigt.json) und steht im eigenen Kalender "Morgenbrief-Ablage", aus dem die nächtliche Claude-Aufgabe ihn im To-do-Doc abhakt. "Rückgängig" unten auf der Seite.
- Termine aus Mails (seit 1.5.0): fester Termin in einer Mail, der nicht im Kalender steht, unter "Braucht dich" mit Knopf "In Kalender eintragen".
- Fahrten (seit 1.5.0, seit 1.6.0 neu): Kalendertermin "Fahrt nach <Ort>" ist die Fahrt selbst: los zum Beginn, mit Ankunft, Warnung bei Ankunft nach dem Ende, andere Abfahrt nur bei mindestens 10 Minuten Ersparnis. Termin mit Ort: spätestens losfahren, 5 Minuten vorher da. Push 20 Minuten vor der Abfahrt. Ziele in DE, AT, CH, IT, gemerkt in orte.json.
- Morgen-Push (seit 1.5.0): Titel ohne Beträge und Rechnungsnummern, Abfahrt, To-dos heute, Zahl der To-dos dieser Woche, Fahrten.
- Arbeitsweg-Nachprüfung (seit 1.5.0): 20 Minuten vor der Abfahrt, Push nur bei Stau oder Sperrung.
- Google-Berechtigungen: gmail.readonly, calendar.readonly und seit 1.5.0 calendar.app.created (schreibt nur in Kalender, die das Add-on selbst angelegt hat, also "Morgenbrief-Ablage"). Links führen zu Gmail, Google Kalender und, für Fahrten, zu Google Maps mit den Koordinaten des Ziels.
- Schutz: Gemini darf nur feste Kategorien liefern (JSON-Schema). Regeln stehen über Gemini: Absender aus IMMER_WICHTIG, Frist- und Abo-Mails (nicht bei Lastschrift), Mails mit Anweisungen an eine KI (unter "Weggelassen" mit "Verdacht"). Neben dem Absender steht die echte Domain. Links führen nur zu Gmail und Google Kalender, nie zu Adressen aus Mails oder von Gemini.

## Konstanten (in app/brief.py)
| Konstante | Wert | Bedeutung |
|---|---|---|
| BRAUCHT_DICH_TAGE | 7 | Frist bis heute plus so viele Tage: "Braucht dich" |
| IMMER_WICHTIG_TAGE | 14 | dasselbe für IMMER_WICHTIG (Absender-Stichwörter, Standard leer) |
| DEMNAECHST_TAGE | 120 | so weit voraus zeigt "Demnächst" Fristen und To-dos |
| DEMNAECHST_SICHTBAR | 8 | (app/seite.py) so viele Punkte unter "Demnächst" offen, der Rest zum Aufklappen |
| SATZ_UEBERLAPPUNG | 0.7 | ab diesem Anteil an Titelwörtern gilt ein Hintergrundsatz als Wiederholung der Aufgabe |
| MAX_TODOS | 25 | Sicherheitsgrenze für "Offene To-dos" (heute bis plus 7 Tage), mit Hinweis |
| MAX_KANDIDATEN, MAX_NEU_AN_GEMINI | 40, 40 | so viele Mails je Lauf geprüft, so viele neue an Gemini (seit 1.6.0) |
| FENSTER_STUNDEN, FRISCH_STUNDEN | 168, 48 | Posteingang so weit zurück; geklärte und weggelassene Mails nur so weit |
| KONFLIKT_TAGE, WOCHE_TAGE | 7, 2 | so weit voraus prüft der Brief Überschneidungen bzw. zeigt "Nächste Tage" |
| ALTERNATIVEN_MIN, SPAREN_MIN | -30 bis +60, 10 | (app/verkehr.py) Vergleichsabfahrten bei Fahrten, nötige Ersparnis |
| ABGELEGT_STUNDEN | 72 | so alt dürfen ungelesen abgelegte Rechnungen und Fristen sein |
| EINORDNUNG_TAGE | 45 | (app/gedaechtnis.py) so lange bleibt eine Einordnung gemerkt |
| WARTET_MAX_TAGE | 30 | so alt dürfen gesendete Mails ohne Antwort höchstens sein |
| HERZSCHLAG_STUNDEN | 26 | so lange darf die nächtliche Aufräumaufgabe schweigen |
| OHNE_FRIST_TAGE, NACH_FRIST_TAGE | 30, 14 | (app/gedaechtnis.py) wann gemerkte Punkte von selbst verschwinden |

## Optionen
| Option | Bedeutung |
|---|---|
| `google_client_id`, `google_client_secret` | OAuth-Client (Typ Desktop-App) aus dem eigenen Google-Cloud-Projekt |
| `gemini_api_key` | Schlüssel aus Google AI Studio. Leer: Brief kommt als Regel-Fassung ohne Einordnung |
| `gemini_modell` | `auto` wählt das neueste stabile Flash-Lite-Modell (Zeitlimit 150 Sekunden), sonst fester Modellname. Antwortet Gemini nicht, kommt die Regel-Fassung |
| `zeit_arbeitstage`, `zeit_freie_tage` | Uhrzeiten im Format HH:MM |
| `zeit_abend` | Uhrzeit für den Abend-Push (HH:MM, Standard 19:00) oder `aus` |
| `push_dienst` | Benachrichtigungsdienst ohne `notify.`, z. B. `mobile_app_mein_handy` |
| `push_klick_pfad` | Seite, die beim Antippen des Push aufgeht, Standard `/app/local_morgenbrief` |
| `weitere_eigene_adressen` | Eigene Adressen, die Gmail nicht als Absenderadresse kennt |
| `tomtom_api_key` | Schlüssel von developer.tomtom.com (Routing, Traffic und Search aktiv). Leer: keine Abfahrtszeit |
| `verkehr_start`, `verkehr_ziel` | Adresse oder Koordinaten `lat,lon` |
| `verkehr_ankunft` | Ankunftszeit HH:MM, Standard 07:25 |
| `verkehr_schwelle_min` | Ab so vielen Minuten Mehrzeit gilt es als Störung, Standard 3 |
| `wetter_entitaet` | Wetter-Entität in Home Assistant (seit 1.6.0). Leer: weather.forecast_home, sonst die erste weather.* |

Nach einer Änderung der Optionen das Add-on neu starten.

## Verhalten bei Fehlern
- Gemini nicht erreichbar oder Limit erreicht: Schon eingeordnete Mails, gemerkte Punkte, Rechnungen und Fristen stehen wie immer da. Nur die übrigen neuen Mails stehen unter "Noch nicht eingeordnete Mails", mit orangem Hinweis. Beim nächsten Lauf werden sie nachgeholt.
- Push nicht angenommen: zwei weitere Versuche nach zwei und vier Minuten.
- Google nicht erreichbar: drei Versuche über zehn Minuten, dann Push mit dem Grund.
- Google-Anmeldung abgelaufen: Push mit Hinweis, auf der Seite "Einrichtung" neu verbinden.
- Der Push kommt jeden Tag. Bleibt er aus, läuft das Add-on nicht.

## Demo
`python3 demo/demo.py` erzeugt einen Brief aus erfundenen Daten (ohne Google, Gemini, TomTom, Home Assistant) in `demo/ausgabe/brief.html`.
