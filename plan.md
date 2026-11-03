# Plan

Stand: 03.11.2026. Später als GitHub-Issues anlegen.

## Jetzt
- [x] Uferlinien für NOK-80-82 und NOK-82-83: andere Zeichenvorlage (Ufer petrol, 1,41 pt), ergänzt
- [ ] Vollausbau: `make ufer web` für alle 49 Blätter, QA (Linienversatz benachbarter Blätter,
      Vorschauen, Angel-Übersicht), Playwright gegen den vollen Datensatz
- [ ] Hosting auf GitHub Pages: Repo anlegen, `site/` lokal bauen und auf `gh-pages` veröffentlichen

## Später
- [ ] Angel-Sperrzonen nachschärfen (`rules.yaml`, macht der Nutzer):
  - noch nicht kartiert: Betriebs-/Ölhafen Brunsbüttel; Gieselaukanal, Audorfer See, Flemhuder See,
    Achterwehrer Kanal (Grenzpunkte von Hand); Kiel-Holtenau (Olympiabrücke–Schleuse)
  - Anlegebrücken und Umschlagstellen digitalisieren (bisher nur Fähren aus OSM, Puffer 50 m prüfen)
  - Mündung der Borgstedter Enge: ~80 m Südufer zählen als NOK (grün) – soll die Enge-Regel gelten?
  - Flemhuder See, Zufahrt Obereider: Band verläuft Nord–Süd, Nord/Süd-Zuordnung prüfen
- [ ] Gescannte Bände (NOK-37-39, NOK-86-88): Koten und Uferlinien fehlen (nur Bild im PDF);
      bisher bewusst weggelassen
- [ ] Update-Ablauf bei neuem ELWIS-Stand: `make all`, neu veröffentlichen; App bietet für offline
      gespeicherte Abschnitte „Aktualisieren“ an. Ablauf dokumentieren/automatisieren
      (z. B. regelmäßiger Check der ELWIS-Seite auf neue Bände).

## Zuletzt
- [ ] Dunkelmodus überarbeiten: Karte wird derzeit invertiert (Tiefenfarben werden dunkel).
      Alternative: Farben behalten, nur abdunkeln. Entscheidung mit Screenshots.
