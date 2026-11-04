"""python3 -I tests/test_elwis.py – Abgleich ELWIS-Seite/veröffentlichter Stand ohne Netz."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elwis

page = ('<nav><a class="Publication" href="https://x/Alt?nn=1"></a></nav><div id="content">'
        '<a class="link Publication" href="https://x/20260101-NOK-01-02?nn=1&amp;v=2"></a>'
        '<a class="Publication" href="https://x/20250703-Flemhuder-See?nn=1"></a>')
found = elwis.names(page)
assert found == ["20260101-NOK-01-02", "20250703-Flemhuder-See"], found          # Navigation ignoriert
assert elwis.report(found, {"20260101-NOK-01-02"}) is None                      # ausgelassene Bände zählen nicht
r = elwis.report(found, {"20250101-NOK-01-02"})
assert "`20260101-NOK-01-02`" in r and "`20250101-NOK-01-02`" in r, r           # neu und ersetzt
print("ok")
