# Plan

Stand: 03.11.2026. Später als GitHub-Issues anlegen.

## Jetzt
- [x] Uferlinien für NOK-80-82 und NOK-82-83: andere Zeichenvorlage (Ufer petrol, 1,41 pt), ergänzt
- [x] Vollausbau: 49 Blätter, 33 752 Kacheln, 354 MB. Linienversatz benachbarter Blätter Median 0,32 m,
      max. 1,3 m (82-83/83-86 und 79-80/80-82: andere Zeichenvorlage, Abgleich über Uferlinien 0,1–0,2 m)
- [x] Tiefenkoten entfernt: Karten sind reine Bildlayer
- [x] Tiefenfarben vereinheitlicht: 1-m-Stufen 0–16 m für alle Vektorblätter, Legende im Info-Dialog
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
- [ ] Angeln, Abgleich mit der hejfish-Gewässerkarte (https://www.hejfish.com/d/12543-nord-ostsee-kanal):
      Übersicht zeigt rot an beiden Enden (Brunsbüttel, Kiel-Holtenau) und bei Rendsburg/Rader Hochbrücke,
      orange etwa km 85–90 (Landwehr/Flemhude) – Grund prüfen. Laut Seitentext gesperrt bis zur Instandsetzung:
      barrierefreie Angelplätze Weiche Kudensee und Oldenbüttel (Gieselau-Mündung) – fehlt in `rules.yaml`.
      Feinabgleich: selbst reinzoomen (Tab hing beim automatischen Zoomen)
- [ ] Gescannte Bände: Tiefenfarben noch in Originallegende (keine Koten im PDF)
- [ ] Flemhuder See: Bezugshorizont PN 5,00 m statt 4,80 m wie im Kanal – Tiefen 0,2 m anders bezogen
- [ ] Kanalfähre Brunsbüttel: Anleger landen bei km 2,02 (Nord) und 2,40 (Süd) – OSM-Linie prüfen
- [ ] Werft Saatsee: eigene km-Teilung oder Kanal-km? (derzeit eigene)
- [ ] Update-Ablauf bei neuem ELWIS-Stand: `make all`, neu veröffentlichen; App bietet für offline
      gespeicherte Abschnitte „Aktualisieren“ an. Ablauf dokumentieren/automatisieren
      (z. B. regelmäßiger Check der ELWIS-Seite auf neue Bände).

## Zuletzt
- [ ] Dunkelmodus überarbeiten: Karte wird derzeit invertiert (Tiefenfarben werden dunkel).
      Alternative: Farben behalten, nur abdunkeln. Entscheidung mit Screenshots.
      Mit der einheitlichen Legende passt die invertierte Karte nicht mehr zur Legende.
