# PDFs laden -> georeferenzieren (KMZ) -> Kacheln + Koten + index.json -> App
PY = .venv/bin/python

all: kmz ufer web

.venv:
	python3 -m venv .venv && $(PY) -m pip install -q -r requirements.txt

kmz: .venv            ## lädt neue ELWIS-Stände, georeferenziert, baut out/*.kmz + out/report.md
	$(PY) build.py

ufer: .venv           ## Uferlinien + Angelregeln (rules.yaml) -> site/ufer/, site/rules.json
	$(PY) ufer.py extract
	test -f data/osm/nok.json || $(PY) ufer.py osm
	$(PY) ufer.py build

osm: .venv            ## OSM-Grenzobjekte (Fähren, Brücken, Leitungen) neu abrufen
	$(PY) ufer.py osm

web: .venv            ## site/ aus den georeferenzierten Blättern (ONLY=NOK-74-76 für einen Band)
	$(PY) tiles.py $(if $(ONLY),--only $(ONLY))

app:                  ## nur App-Hülle (web/) nach site/ kopieren
	$(PY) tiles.py --app

test: node_modules
	CHROMIUM=$$(command -v chromium) npx playwright test

node_modules:
	npm install && npx playwright install chromium

serve:                ## lokal testen: http://localhost:8000 (localhost gilt als sicherer Kontext)
	python3 -m http.server 8000 -d site

.PHONY: all kmz ufer osm web app test serve
