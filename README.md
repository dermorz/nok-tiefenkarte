# NOK-Tiefenkarte

Alle Tiefenkarten des Nord-Ostsee-Kanals aus dem
[ELWIS-Tiefenatlas](https://www.elwis.de/DE/Service/Tiefenatlas-BWaStr/Nord-Ostsee-Kanal/Nord-Ostsee-Kanal-node)
als georeferenzierte, nordausgerichtete Overlays in einer KMZ für Google Earth. Nur die gemessene
Fläche ist sichtbar.

Daten: Wasserstraßen- und Schifffahrtsverwaltung des Bundes, Datenlizenz Deutschland – Zero – 2.0.
Nicht zur Navigation.

## Lauf

```sh
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # + poppler (pdftoppm), tesseract
.venv/bin/python build.py            # lädt neue Stände, baut out/nok-tiefenkarte.kmz + out/report.md
.venv/bin/python build.py --offline --only NOK-74-76 # einzelner Band, ohne Download
```

Ergebnisse pro Blatt werden in `out/sheets/` gecacht und nur neu gerechnet, wenn sich PDF oder Code ändern.
Bei einem neuen Stand auf ELWIS werden ersetzte PDFs automatisch gelöscht und die neuen geladen.

## Verfahren

- **Kartenblätter**: alle Seiten größer als A4 quer (Seiten 1–6 sind Deckblatt/Legende).
- **Plankopf** (aus dem PDF, nicht aus den Linktexten): Abschnitt, km-Bereich, Maßstab (1:1000/2000/3000
  kommen vor), Rotation, Datum der ersten/letzten Messung.
- **Passpunkte**: Gitterticks (schwarze Striche außen am Rahmen) → Schnittpunkt auf der inneren
  Rahmenkante, zugeordnet zum nächsten Gitterlabel (ETRS89/UTM32, `32xxxxxx`/`59xxxxx`/`60xxxxx`);
  nach einem ersten Fit wird die Zuordnung über das Residuum verfeinert. WGS84-Eckwerte dienen als
  schwach gewichtete Zusatzpunkte und zur Kontrolle.
- **Modell**: Ähnlichkeitstransformation mit festem Plan-Maßstab, unbekannt nur θ, c, f.
- **Gescannte Bände** (Kartenblatt nur als JPEG, z. B. NOK-37-39, NOK-86-88): Rahmen/Ticks aus den Pixeln,
  Labels und Plankopf per Tesseract-OCR (`scan.py`); dort wird der Maßstab mitgeschätzt und muss auf
  0,3 % zum Plan passen.
- **QA**: Tick-RMS < 0,3 m, Eckwerte < 2,5 m (auf 0,1" gerundet), Kachel-Affine < 0,2 m.
  `OK (Ecken)`: eine Gitterrichtung hat keine Ticks und stützt sich nur auf die Eckwerte (~1–2 m).
  Blätter, die das nicht schaffen, kommen nicht in die KMZ, sondern stehen im Report.
- **Tiefenfarben**: Die Bände haben fünf verschiedene Legenden (Kanal 8 Klassen, Weststrecke, Seen,
  Kiel, Obereider). Einheitlich neu eingefärbt (`DEPTH_SCALE`, 1-m-Stufen 0–16 m, Farbton rot → violett,
  Helligkeit wechselt je Meter, damit Kolke/Rinnen auffallen): die
  Tiefenflächen werden im PDF-Inhaltsstrom weiß gesetzt (`rg` bzw. ICC-`scn`) (Linien, Zahlen bleiben), die Tiefe wird aus den
  Tiefenkoten linear interpoliert, eingefärbt, geschummert und mit der Planzeichnung multipliziert. Aus
  der Farbe allein geht es nicht: durch die Schummerung sind Kanal-Klassen zu ~38 % nicht eindeutig.
  Gescannte Bände: Tiefenkoten über Ziffern-Vorlagen gelesen (Vorlagen aus den Zeichen eines Vektorblatts
  gleicher Schrift, Tesseract scheitert an den kursiven, eng stehenden Zahlen), Ausreißer gegen Farbklasse
  und Nachbarn raus; Tiefenfläche aus den Legendenfarben. Uferlinie/Achse dort aus den Pixelfarben, km
  über die Bogenlänge der Achse an den km-Labels der Nachbarblätter verankert.
- **Raster**: Rahmen mit pdftoppm, ~0,3 m/px (1:2000), Maske „farbig & hell“ (Sättigung > 22,
  Helligkeit > 150), Opening ×4 gegen Linien der Basiskarte, Closing, Löcher füllen, kleine
  Komponenten weg, 3 m Dilatation, 1 m weicher Rand. Warp je Kachel (≤ 4096 px) nach Lon/Lat,
  PNG mit 256 Farben ohne Dithering.

## Web-App

Live: <https://nok.morz.me/>

Statische App in `web/` (Leaflet im Repo, keine Drittserver außer der optionalen Hintergrundkarte
basemap.de). `make ufer web` baut `site/`: Kacheln `tiles/plan/{z}/{x}/{y}.webp` (z10–19, Papierweiß
transparent; reine Bildlayer ohne Tiefendaten), Uferlinien `ufer/<blatt>.geojson`, Offline-Manifeste
`sections/`, `index.json`, `rules.json`. `make serve` → http://localhost:8000, `make test` (Playwright,
mobiler Viewport, simulierte Geolocation).

- **Angeln**: Uferlinien (hellblau, 0,85 pt) und km-Labels aus dem PDF; km und Ufer (Nord/Süd) über die
  Achse aus den Label-Paaren. Regeln in `rules.yaml`, Grenzobjekte aus OSM (`make osm`, ODbL): Brücken/Leitungen als Grenzpunkte,
  Fähren (Endpunkte), Hafen- und Werftflächen als `objekte` (berührte Uferstücke ± Puffer, nur nahe am
  Objekt; `ausser` für einzelne OSM-IDs), Stege mit `bauwerk: true` nur selbst rot (Ufer davor frei), dazu von
  Hand `abschnitte` (rot) und `frei`, beide optional mit `bei` (nur Ufer an einer Linie; Abgleich hejfish/vor Ort).
  Fremde Gewässer (Eider, Achterwehrer Kanal, Wilsterau u. a.) per `FREMDE_UFER*` in `ufer.py` ausgeblendet. Ufer, die der
  Atlas nicht zeichnet (Rendsburger Hafen, Schirnau), als `extra_ufer` aus dem Rand einer OSM-Wasserfläche. Farbe
  wird in der App nach dem aktuellen Datum bestimmt (`?datum=JJJJ-MM-TT` zum Prüfen); Ausnahmen mit Zeitraum außerhalb davon gelb.

Neuer ELWIS-Stand: die GitHub Action `.github/workflows/elwis.yml` prüft montags (`elwis.py`) und öffnet
bei Änderungen ein Issue mit Label `elwis`.

Veröffentlichen: `make deploy` (GitHub Pages, Branch `gh-pages` wird jedes Mal ersetzt).

Offene Punkte: [Issues](https://github.com/dermorz/nok-tiefenkarte/issues).
