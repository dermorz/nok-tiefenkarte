"""Web-Daten aus den georeferenzierten Blättern (out/sheets/*.json von build.py):

  site/tiles/plan/{z}/{x}/{y}.webp          XYZ-Kacheln EPSG:3857, 256 px, z10..19 (Planzeichnung,
                                            Papierweiß transparent)
  site/koten/<blatt>.json                   Tiefenkoten [[lat, lon, tiefe], ...]
  site/sections/<blatt>.json                Offline-Manifest (Kachel-URLs + Bytes)
  site/index.json                           Abschnitte: Name, km, Messdatum, Umriss, Bounds

    python tiles.py [--only NOK-74-76]

Kacheln werden direkt aus dem Vektor-PDF gerendert (eine Resampling-Stufe, Affine je Kachel aus
exakt transformierten Stützpunkten). Überlappende Blätter: neuere Messung liegt oben.
"""
import argparse, json, math, re, shutil, time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image
from pyproj import Transformer

import build

Image.MAX_IMAGE_PIXELS = None
ZMAX, ZMIN = 19, 10          # z19 ≈ 0,17 m/px am NOK, also feiner als die ~0,3 m der Vorlage
SITE, WORK = Path("site"), Path("out/web")
TO_UTM = Transformer.from_crs(4326, 25832, always_xy=True)
UTM = Transformer.from_crs(25832, 4326, always_xy=True)
WEBP = dict(format="WEBP", quality=82, alpha_quality=90, method=5)


def tile_lonlat(z, x, y):
    n = 2 ** z
    return x / n * 360 - 180, np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * y / n))))


def lonlat_tile(z, lon, lat):
    n = 2 ** z
    return (lon + 180) / 360 * n, (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * n


def sheet_model(r):
    th, c, f = r["p"][:3]
    s = r["p"][3] if len(r["p"]) > 3 else r["scale"] * build.PT
    A, B = s * math.cos(th), s * math.sin(th)
    fwd = lambda x, y: UTM.transform(A * x + B * y + c, B * x - A * y + f)
    def inv(lon, lat):
        e, n = TO_UTM.transform(lon, lat)
        return (A * (e - c) + B * (n - f)) / s**2, (B * (e - c) - A * (n - f)) / s**2
    return fwd, inv, s


def plan_alpha(rgb):
    """Weiß -> transparent, alles andere deckend (Pastellflächen sollen nicht verblassen)."""
    return np.clip((255 - rgb.min(2).astype(np.int16)) * 25, 0, 255).astype(np.uint8)


def koten(pdf, pno, frame, fwd, mess_alpha_at, mesh):
    """Tiefenkoten: schwarze, waagerechte Zahlen 'd,d' im Rahmen, Lage = Mitte der Textbox (liegt
    nachweislich auf dem Modellgitter). Liefert Koten + Gitter-Kohärenz als Lagekontrolle."""
    x0, y0, x1, y1 = frame
    pts = []
    for b in pymupdf.open(pdf)[pno - 1].get_text("rawdict")["blocks"]:
        for l in b.get("lines", []):
            if abs(l["dir"][1]) > 0.01 or l["dir"][0] < 0:
                continue
            spans = [s for s in l["spans"] if s["color"] == 0]
            t = "".join(ch["c"] for s in spans for ch in s["chars"]).strip()
            if not spans or not re.fullmatch(r"-?\d{1,2},\d", t):
                continue
            bx0 = min(s["bbox"][0] for s in spans); bx1 = max(s["bbox"][2] for s in spans)
            by0 = min(s["bbox"][1] for s in spans); by1 = max(s["bbox"][3] for s in spans)
            cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
            if x0 < cx < x1 and y0 < cy < y1 and mess_alpha_at(cx, cy):
                pts.append((cx, cy, float(t.replace(",", "."))))
    if not pts:
        return [], None
    p = np.array(pts)
    lon, lat = fwd(p[:, 0], p[:, 1])
    e, n = TO_UTM.transform(lon, lat)
    ze, zn = np.exp(2j * np.pi * e / mesh).mean(), np.exp(2j * np.pi * n / mesh).mean()
    lattice = dict(mesh=mesh, coh=float(min(abs(ze), abs(zn))),
                   dE=float(np.angle(ze) / 2 / np.pi * mesh), dN=float(np.angle(zn) / 2 / np.pi * mesh))
    if lattice["coh"] > 0.8:   # auf Gitterpunkte einrasten (Textbox-Mitte streut um ~0,2 m)
        e, n = np.round(e / mesh) * mesh, np.round(n / mesh) * mesh
        lon, lat = UTM.transform(e, n)
    return [[round(a, 6), round(o, 6), d] for a, o, d in zip(lat, lon, p[:, 2])], lattice


def render_sheet(r):
    """Rendert ein Blatt in z19-Quellkacheln (PNG, verlustfrei) für beide Layer + Koten."""
    sid, pdf, pno = r["id"], Path("data/pdf") / r["pdf"], r["page"]
    out = WORK / "src" / sid
    done = out / "done.json"
    newest = max((WORK.parent / "sheets" / f"{sid}.json").stat().st_mtime, Path(__file__).stat().st_mtime)
    if done.exists() and done.stat().st_mtime > newest:
        return json.loads(done.read_text())
    shutil.rmtree(out, ignore_errors=True)
    fwd, inv, s = sheet_model(r)
    x0, y0, x1, y1 = r["frame"]
    inner = (x0 + 1.2, y0 + 1.2, x1 - 1.2, y1 - 1.2)          # Rahmenlinie selbst weglassen
    lon_c, lat_c = fwd((x0 + x1) / 2, (y0 + y1) / 2)
    res = 156543.034 / 2**ZMAX * math.cos(math.radians(lat_c))
    k = s / res * 1.5                                          # px/pt, 1,5x überabgetastet
    im, (ox, oy), k = build.render(pdf, pno, inner, 72 * k)
    rgb = np.asarray(im)
    # Messflächen-Maske wie in der KMZ (nur noch als Filter für die Koten): Parameter bei 170 dpi
    km = build.DPI / 72
    small = np.asarray(im.resize((round(im.width * km / k), round(im.height * km / k)), Image.BOX))
    m_small = build.survey_mask(small, s / km)
    # Farbe und Alpha getrennt transformieren: Pillow rechnet RGBA vormultipliziert, dabei wird das
    # Papierweiß (Alpha 0) schwarz - und der Messflächen-Saum würde dieses Schwarz zeigen.
    plan_a = Image.fromarray(plan_alpha(rgb))
    del rgb, small
    at = lambda x, y: m_small[min(int((y - oy) * km), m_small.shape[0] - 1), min(int((x - ox) * km), m_small.shape[1] - 1)] > 0.5
    mesh = float((re.search(r"Maschenweite\s*([\d,]+)", pymupdf.open(pdf)[pno - 1].get_text()) or [0, "2"])[1].replace(",", "."))
    kt, lattice = koten(pdf, pno, inner, fwd, at, mesh) if r["source"] == "vector" else ([], None)
    # Kachelbereich aus dem Rahmenumriss
    cx, cy = [x0, x1, x1, x0], [y0, y0, y1, y1]
    lon, lat = fwd(np.array(cx), np.array(cy))
    tx, ty = lonlat_tile(ZMAX, lon, lat)
    tiles = []
    for X in range(int(tx.min()), int(tx.max()) + 1):
        for Y in range(int(ty.min()), int(ty.max()) + 1):
            u, v = np.meshgrid(np.linspace(0, 256, 5), np.linspace(0, 256, 5))
            lo, la = tile_lonlat(ZMAX, X + u.ravel() / 256, Y + v.ravel() / 256)
            px, py = inv(lo, la)
            if px.max() < x0 or px.min() > x1 or py.max() < y0 or py.min() > y1:
                continue
            G = np.c_[u.ravel(), v.ravel(), np.ones(25)]
            ax = np.linalg.lstsq(G, (px - ox) * k, rcond=None)[0]
            ay = np.linalg.lstsq(G, (py - oy) * k, rcond=None)[0]
            coeffs = (*ax, *ay)
            rgb_t = im.transform((256, 256), Image.AFFINE, coeffs, Image.BILINEAR, fillcolor=(255, 255, 255))
            pt = rgb_t.copy(); pt.putalpha(plan_a.transform((256, 256), Image.AFFINE, coeffs, Image.BILINEAR, fillcolor=0))
            if not pt.getchannel("A").getbbox():
                continue
            (out / "plan").mkdir(parents=True, exist_ok=True)
            pt.save(out / "plan" / f"{X}_{Y}.png")
            tiles.append((X, Y))
    poly = [list(map(lambda v: round(float(v), 7), fwd(px_, py_)))[::-1] for px_, py_ in zip(cx, cy)]
    res_ = dict(id=sid, tiles=tiles, koten=kt, lattice=lattice, poly=poly)
    out.mkdir(parents=True, exist_ok=True)
    done.write_text(json.dumps(res_))
    return res_


def date_key(r):
    return datetime.strptime(r["date"], "%d.%m.%Y") if r.get("date") else datetime.min


def build_tiles(rows, rendered):
    """z19 zusammensetzen (neueste Messung oben), dann Pyramide bis ZMIN durch 2x2-Verkleinern.
    Zwischenstufen als PNG auf Platte, damit der RAM-Bedarf nicht mit der Kanallänge wächst."""
    order = {r["id"]: i for i, r in enumerate(sorted(rows, key=date_key))}
    manifests = {r["id"]: set() for r in rows}
    shutil.rmtree(SITE / "tiles" / "mess", ignore_errors=True)   # Layer "Messfläche" entfallen
    for layer in ("plan",):
        shutil.rmtree(SITE / "tiles" / layer, ignore_errors=True)
        shutil.rmtree(WORK / "merged" / layer, ignore_errors=True)
        srcs = {}                                    # (x, y) -> [png, ...] in Datumsreihenfolge
        owners = {}                                  # (x, y) -> {sid}
        for sid, rs in sorted(rendered.items(), key=lambda kv: order[kv[0]]):
            for X, Y in rs["tiles"]:
                f = WORK / "src" / sid / layer / f"{X}_{Y}.png"
                if f.exists():
                    srcs.setdefault((X, Y), []).append(f)
                    owners.setdefault((X, Y), set()).add(sid)
        def emit(z, X, Y, img):
            m = WORK / "merged" / layer / str(z)
            m.mkdir(parents=True, exist_ok=True)
            img.save(m / f"{X}_{Y}.png", compress_level=1)
            d = SITE / "tiles" / layer / str(z) / str(X)
            d.mkdir(parents=True, exist_ok=True)
            img.save(d / f"{Y}.webp", **WEBP)
            for sid in owners[(X, Y)]:
                manifests[sid].add(f"tiles/{layer}/{z}/{X}/{Y}.webp")
        for (X, Y), fs in srcs.items():
            img = Image.open(fs[0]).convert("RGBA")
            for f in fs[1:]:
                img.alpha_composite(Image.open(f).convert("RGBA"))
            emit(ZMAX, X, Y, img)
        for z in range(ZMAX - 1, ZMIN - 1, -1):
            children, owners_c = {}, owners
            for X, Y in owners_c:
                children.setdefault((X // 2, Y // 2), []).append((X, Y))
            owners = {P: set().union(*(owners_c[c] for c in cs)) for P, cs in children.items()}
            for (PX, PY), cs in children.items():
                canvas = Image.new("RGBA", (512, 512), (255, 255, 255, 0))
                for X, Y in cs:
                    canvas.paste(Image.open(WORK / "merged" / layer / str(z + 1) / f"{X}_{Y}.png"),
                                 ((X % 2) * 256, (Y % 2) * 256))
                emit(z, PX, PY, canvas.reduce(2))
    return manifests


def copy_app():
    """App-Hülle aus web/ nach site/; Service-Worker-Version = Datenstand, damit Updates greifen."""
    version = json.loads((SITE / "index.json").read_text())["version"]
    shutil.copytree("web", SITE, dirs_exist_ok=True)
    sw = SITE / "sw.js"
    sw.write_text(sw.read_text().replace("__VERSION__", version + "-" + str(int(time.time()))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--app", action="store_true", help="nur App-Hülle neu kopieren")
    ap.add_argument("-j", type=int, default=4)
    a = ap.parse_args()
    if a.app:
        return copy_app()
    rows = [json.loads(p.read_text()) for p in sorted((WORK.parent / "sheets").glob("*.json"))]
    rows = [r for r in rows if r["status"].startswith("OK") and (not a.only or any(o in r["id"] for o in a.only.split(",")))]
    t0 = time.time()
    with ProcessPoolExecutor(a.j) as ex:
        rendered = {r["id"]: x for r, x in zip(rows, ex.map(render_sheet, rows))}
    print(f"gerendert: {len(rows)} Blätter in {time.time() - t0:.0f} s")
    manifests = build_tiles(rows, rendered)
    version = datetime.now().strftime("%Y%m%d%H%M")
    for d in ("koten", "sections"):
        shutil.rmtree(SITE / d, ignore_errors=True)
        (SITE / d).mkdir(parents=True)
    sections, total = [], 0
    for r in sorted(rows, key=lambda r: (["Weststrecke", "Oststrecke", "Seen und Häfen"].index(build.folder_of(r)),
                                         (r["km"] or [999])[0])):
        rs = rendered[r["id"]]
        files = sorted(manifests[r["id"]])
        if (SITE / "ufer" / f"{r['id']}.geojson").exists():
            files.append(f"ufer/{r['id']}.geojson")
        if rs["koten"]:
            (SITE / "koten" / f"{r['id']}.json").write_text(json.dumps(rs["koten"], separators=(",", ":")))
            files.append(f"koten/{r['id']}.json")
        size = sum((SITE / f).stat().st_size for f in files)
        total += size
        (SITE / "sections" / f"{r['id']}.json").write_text(json.dumps(dict(files=files, bytes=size)))
        lats = [p[0] for p in rs["poly"]]; lons = [p[1] for p in rs["poly"]]
        sections.append(dict(id=r["id"], name=build.name_of(r), folder=build.folder_of(r), km=r["km"],
                             date=r["date"], date_last=r.get("date_last"), scale=r["scale"],
                             poly=rs["poly"], bounds=[[min(lats), min(lons)], [max(lats), max(lons)]],
                             koten=len(rs["koten"]), ufer=(SITE / "ufer" / f"{r['id']}.geojson").exists(),
                             bytes=size, files=len(files)))
        lat = rs["lattice"]
        print(f"{r['id']:34s} {len(files):6d} Dateien {size / 1e6:7.1f} MB  Koten {len(rs['koten']):6d}"
              + (f"  Gitter {lat['mesh']:g} m: Kohärenz {lat['coh']:.2f}, Versatz E {lat['dE']:+.2f} N {lat['dN']:+.2f} m" if lat else "  (keine Koten)"))
    (SITE / "index.json").write_text(json.dumps(dict(version=version, zmin=ZMIN, zmax=ZMAX, sections=sections),
                                                ensure_ascii=False, separators=(",", ":")))
    for layer in ("plan",):
        b = sum(f.stat().st_size for f in (SITE / "tiles" / layer).rglob("*.webp"))
        n = sum(1 for _ in (SITE / "tiles" / layer).rglob("*.webp"))
        print(f"Layer {layer}: {n} Kacheln, {b / 1e6:.1f} MB")
    print(f"Summe aller Abschnitte (inkl. Doppelzählung an Grenzen): {total / 1e6:.1f} MB")
    copy_app()


if __name__ == "__main__":
    main()
