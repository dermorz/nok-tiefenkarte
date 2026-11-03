# Plan

Stand: 03.11.2026. Später als GitHub-Issues anlegen.

## Jetzt
- [x] Uferlinien für NOK-80-82 und NOK-82-83: andere Zeichenvorlage (Ufer petrol, 1,41 pt), ergänzt
- [x] Vollausbau: 49 Blätter, 33 752 Kacheln, 354 MB. Linienversatz benachbarter Blätter Median 0,32 m,
      max. 1,3 m (82-83/83-86 und 79-80/80-82: andere Zeichenvorlage, Abgleich über Uferlinien 0,1–0,2 m)
- [x] Tiefenkoten entfernt: Karten sind reine Bildlayer
- [ ] Hosting auf GitHub Pages (Repo `nok-tiefenkarte`): erst nach Freigabe anlegen und veröffentlichen

## Später
- [ ] Angel-Sperrzonen nachschärfen (`rules.yaml`, macht der Nutzer):
  - noch nicht kartiert: Betriebs-/Ölhafen Brunsbüttel; Gieselaukanal, Audorfer See, Flemhuder See,
    Achterwehrer Kanal (Grenzpunkte von Hand); Kiel-Holtenau (Olympiabrücke–Schleuse)
  - Anlegebrücken und Umschlagstellen digitalisieren (bisher nur Fähren aus OSM, Puffer 50 m prüfen)
  - Mündung der Borgstedter Enge: ~80 m Südufer zählen als NOK (grün) – soll die Enge-Regel gelten?
  - Flemhuder See, Zufahrt Obereider: Band verläuft Nord–Süd, Nord/Süd-Zuordnung prüfen
- [ ] Gescannte Bände (NOK-37-39, NOK-86-88): Uferlinien fehlen (nur Bild im PDF), Angel-Layer hat
      dort Lücken
- [ ] Kanalfähre Brunsbüttel: Anleger landen bei km 2,02 (Nord) und 2,40 (Süd) – OSM-Linie prüfen
- [ ] Werft Saatsee: eigene km-Teilung oder Kanal-km? (derzeit eigene)
- [ ] Update-Ablauf bei neuem ELWIS-Stand: `make all`, neu veröffentlichen; App bietet für offline
      gespeicherte Abschnitte „Aktualisieren“ an. Ablauf dokumentieren/automatisieren
      (z. B. regelmäßiger Check der ELWIS-Seite auf neue Bände).

## Zuletzt
- [ ] Dunkelmodus überarbeiten: Karte wird derzeit invertiert (Tiefenfarben werden dunkel).
      Alternative: Farben behalten, nur abdunkeln. Entscheidung mit Screenshots.
