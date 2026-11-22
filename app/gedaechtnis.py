"""Gedächtnis des Morgenbriefs: offene Punkte aus Mails über mehrere Tage (SQLite im Datenordner des Add-ons).

Status: offen (wird angezeigt), wartet (du hast geantwortet), erledigt, alt (Frist lange vorbei oder zu alt).

Seit 1.4.0 zusätzlich die Merkliste der Einordnungen (Tabelle "einordnung"): Jede Mail, jede gesendete Mail und
jeder Kalendereintrag geht nur einmal an Gemini, danach gilt das gemerkte Ergebnis.
"""
import json
import sqlite3
from datetime import date, timedelta

OHNE_FRIST_TAGE = 30  # Punkte ohne Frist verschwinden nach so vielen Tagen von selbst
NACH_FRIST_TAGE = 14  # Punkte mit Frist bleiben so lange nach der Frist sichtbar (überfällig)
LOESCHEN_TAGE = 90  # abgeschlossene Punkte so lange aufheben, dann aus der Datei entfernen
EINORDNUNG_TAGE = 45  # gemerkte Einordnungen so lange aufheben (gesendete Mails warten bis zu 30 Tage)


class Gedaechtnis:
    def __init__(self, pfad):
        self.db = sqlite3.connect(pfad, timeout=10)
        self.db.execute("""CREATE TABLE IF NOT EXISTS punkte (
            thread TEXT PRIMARY KEY, status TEXT NOT NULL, titel TEXT, satz TEXT, von TEXT, link TEXT,
            frist TEXT, woerter TEXT, erstmals TEXT NOT NULL, zuletzt TEXT NOT NULL, geaendert TEXT, grund TEXT)""")
        spalten = {r[1] for r in self.db.execute("PRAGMA table_info(punkte)")}
        for name in ("quelle", "nummern", "termin"):  # seit 1.4.0 bzw. 1.5.0 (termin), ältere Dateien bekommen sie dazu
            if name not in spalten:
                self.db.execute(f"ALTER TABLE punkte ADD COLUMN {name} TEXT")
        self.db.execute("""CREATE TABLE IF NOT EXISTS einordnung (
            art TEXT NOT NULL, schluessel TEXT NOT NULL, daten TEXT NOT NULL, datum TEXT NOT NULL,
            PRIMARY KEY (art, schluessel))""")
        self.db.commit()

    def merken(self, thread, eintrag, frist, woerter, von, heute, quelle="posteingang", nummern=(), termin=None):
        """Heute eingeordnete Mail anlegen oder auffrischen (Status wieder 'offen').

        termin (seit 1.5.0): {"datum", "zeit", "ort", "vorlage"} eines Termins, der noch nicht im Kalender stand."""
        self.db.execute(
            """INSERT INTO punkte (thread, status, titel, satz, von, link, frist, woerter, erstmals, zuletzt,
                                   quelle, nummern, termin)
               VALUES (?, 'offen', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(thread) DO UPDATE SET status = 'offen', titel = excluded.titel, satz = excluded.satz,
               von = excluded.von, link = excluded.link, frist = excluded.frist, woerter = excluded.woerter,
               zuletzt = excluded.zuletzt, geaendert = NULL, grund = NULL, quelle = excluded.quelle,
               nummern = excluded.nummern, termin = excluded.termin""",
            (thread, eintrag.get("titel", ""), eintrag.get("satz", ""), von, eintrag.get("link", ""),
             frist.isoformat() if frist else None, json.dumps(sorted(woerter)), heute.isoformat(), heute.isoformat(),
             quelle, json.dumps(sorted(nummern)), json.dumps(termin, ensure_ascii=False) if termin else None))
        self.db.commit()

    def offene(self) -> list:
        zeilen = self.db.execute(
            "SELECT thread, titel, satz, von, link, frist, woerter, erstmals, quelle, nummern, termin "
            "FROM punkte WHERE status = 'offen'")
        ergebnis = []
        for r in zeilen.fetchall():
            try:
                termin = json.loads(r[10]) if r[10] else None
            except ValueError:
                termin = None
            ergebnis.append({"thread": r[0], "titel": r[1] or "", "satz": r[2] or "", "von": r[3] or "",
                             "link": r[4] or "", "frist": date.fromisoformat(r[5]) if r[5] else None,
                             "woerter": set(json.loads(r[6] or "[]")), "erstmals": date.fromisoformat(r[7]),
                             "quelle": r[8] or "posteingang", "nummern": set(json.loads(r[9] or "[]")),
                             "termin": termin})
        return ergebnis

    def setzen(self, thread, status, grund, heute):
        self.db.execute("UPDATE punkte SET status = ?, grund = ?, geaendert = ? WHERE thread = ?",
                        (status, grund, heute.isoformat(), thread))
        self.db.commit()

    # ------------------------------------------------------- Merkliste der Einordnungen (seit 1.4.0)

    def einordnungen(self, art: str, schluessel: list) -> dict:
        """Gemerkte Einordnungen zu diesen Schlüsseln (Mail-ID, gesendete Mail-ID oder Kalendereintrag)."""
        ergebnis = {}
        liste = [s for s in dict.fromkeys(schluessel) if s]
        for i in range(0, len(liste), 200):
            teil = liste[i:i + 200]
            zeilen = self.db.execute(
                f"SELECT schluessel, daten FROM einordnung WHERE art = ? AND schluessel IN ({','.join('?' * len(teil))})",
                [art] + teil)
            for s, daten in zeilen.fetchall():
                try:
                    ergebnis[s] = json.loads(daten)
                except ValueError:
                    pass
        return ergebnis

    def einordnung_merken(self, art: str, schluessel: str, daten: dict, heute):
        self.db.execute("INSERT OR REPLACE INTO einordnung (art, schluessel, daten, datum) VALUES (?, ?, ?, ?)",
                        (art, schluessel, json.dumps(daten, ensure_ascii=False), heute.isoformat()))
        self.db.commit()

    def aufraeumen(self, heute):
        grenze = (heute - timedelta(days=LOESCHEN_TAGE)).isoformat()
        self.db.execute("DELETE FROM punkte WHERE status != 'offen' AND geaendert < ?", (grenze,))
        self.db.execute("DELETE FROM einordnung WHERE datum < ?",
                        ((heute - timedelta(days=EINORDNUNG_TAGE)).isoformat(),))
        self.db.commit()

    def zaehlen(self) -> dict:
        return dict(self.db.execute("SELECT status, COUNT(*) FROM punkte GROUP BY status").fetchall())

    def schliessen(self):
        self.db.close()
