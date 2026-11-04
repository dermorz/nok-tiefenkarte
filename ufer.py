"""Uferlinien + Kilometrierung aus den Vektor-PDFs und Einfärbung nach rules.yaml.

    python ufer.py extract [--only X]   # out/ufer/<blatt>.json: Uferlinien, km-Punkte, Achse (lon/lat)
    python ufer.py osm                  # data/osm/nok.json: Fähren, Brücken, Freileitungen, Anleger, Häfen (Overpass, ODbL)
    python ufer.py build [--only X]     # site/ufer.geojson + site/rules.json

PDF-Ebenen (geprüft an NOK-74-76, Borgstedter See): Uferlinie = hellblau (0.286, 0.608, 0.996) 0,85 pt
(NOK-80-82/82-83: petrol 1,41 pt);
Kanalachse = dunkelblau (0, 0, 0.753); km-Linien = Beschriftung "dd,ddd" je Ufer.
"""
import argparse, json, math, re, sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pymupdf
import requests

import build
from tiles import sheet_model, TO_UTM, UTM

SHORE = [((0.286, 0.608, 0.996), 0.85),   # Standard-Zeichenvorlage
         ((0.169, 0.541, 0.682), 1.41)]   # NOK-80-82, NOK-82-83 (andere Basiskarte)
AXIS = (0.0, 0.0, 0.753)
OUT = Path("out/ufer")
OSM = Path("data/osm/nok.json")


def close(c, ref, tol=0.01):
    return c is not None and len(c) == 3 and all(abs(a - b) < tol for a, b in zip(c, ref))


def flatten(items):
    """PDF-Pfad -> Liste von Polylinien (Seitenkoordinaten), Bezierkurven mit 8 Stützpunkten."""
    lines, cur = [], []
    for it in items:
        if it[0] == "l":
            a, b = it[1], it[2]
            seg = [(a.x, a.y), (b.x, b.y)]
        elif it[0] == "c":
            p0, p1, p2, p3 = it[1:5]
            t = np.linspace(0, 1, 9)[:, None]
            P = ((1 - t) ** 3 * np.array([p0.x, p0.y]) + 3 * (1 - t) ** 2 * t * np.array([p1.x, p1.y])
                 + 3 * (1 - t) * t ** 2 * np.array([p2.x, p2.y]) + t ** 3 * np.array([p3.x, p3.y]))
            seg = [tuple(p) for p in P]
        else:
            continue
        if cur and math.dist(cur[-1], seg[0]) < 0.05:
            cur.extend(seg[1:])
        else:
            if len(cur) > 1:
                lines.append(cur)
            cur = list(seg)
    if len(cur) > 1:
        lines.append(cur)
    return lines


def extract(r):
    pg = pymupdf.open(Path("data/pdf") / r["pdf"])[r["page"] - 1]
    fwd, _, _ = sheet_model(r)
    x0, y0, x1, y1 = r["frame"]
    inside = lambda p: x0 < p[0] < x1 and y0 < p[1] < y1
    shore, axis = [], []
    for d in pg.get_drawings():
        if d["type"] != "s":
            continue
        if any(close(d.get("color"), c) and abs((d.get("width") or 0) - w) < 0.1 for c, w in SHORE):
            shore += flatten(d["items"])
        elif close(d.get("color"), AXIS):
            axis += flatten(d["items"])
    clip = lambda ls: [[p for p in l if inside(p)] for l in ls]
    shore = [l for l in clip(shore) if len(l) > 1]
    axis = [l for l in clip(axis) if len(l) > 1]
    kms = []
    for b in pg.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                t = s["text"].strip()
                bb = s["bbox"]
                c = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
                if re.fullmatch(r"-?\d{1,3},\d{3}", t) and inside(c):
                    kms.append((float(t.replace(",", ".")), c))
    ll = lambda line: [[round(v, 7) for v in fwd(x, y)] for x, y in line]
    return dict(id=r["id"], km=r["km"], folder=build.folder_of(r), date=r["date"],
                shore=[ll(l) for l in shore], axis=[ll(l) for l in axis],
                km_labels=[[k, *[round(v, 7) for v in fwd(*c)]] for k, c in kms])


def pixel_lines(m, min_px=200):
    """Dünne Linienmaske -> Polylinien (Pixel): je Komponente spaltenweise Mitte (Linien laufen etwa waagerecht)."""
    from scipy import ndimage
    lab, n = ndimage.label(ndimage.binary_dilation(m, iterations=2))
    out = []
    for i, sl in enumerate(ndimage.find_objects(lab)):
        ys, xs = np.nonzero((lab[sl] == i + 1) & m[sl])
        if xs.size == 0 or xs.max() - xs.min() < min_px:
            continue
        cols = np.unique(xs)[::3]
        out.append([(sl[1].start + x, sl[0].start + ys[xs == x].mean()) for x in cols])
    return out


def extract_scan(r, neighbours):
    """Gescannter Band: Uferlinie/Achse aus den Pixelfarben, km aus der Bogenlänge der Achse, verankert an den
    km-Labels der Nachbarblätter (Vektor), die ins Blatt reichen."""
    K = 3
    fwd, _, _ = sheet_model(r)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        a = np.asarray(build.ppm(Path("data/pdf") / r["pdf"], r["page"], r["frame"], K, f"{td}/o")).astype(np.int16)
    ox, oy = int(r["frame"][0] * K) / K, int(r["frame"][1] * K) / K
    ll = lambda line: [[round(v, 7) for v in fwd(ox + x / K, oy + y / K)] for x, y in line]
    shore = [ll(l) for l in pixel_lines(np.abs(a - (73, 155, 254)).max(2) < 30)]
    # Achse: im Scan in Stücke zerfallen (JPEG) -> alle Stücke nach x aneinanderhängen
    parts = sorted(pixel_lines(np.abs(a - (0, 0, 192)).max(2) < 90, 100), key=lambda l: l[0][0])
    if not parts:
        raise ValueError(f"{r['id']}: keine Achse im Scan")
    axis = [ll([p for l in parts for p in l])]
    A = utm(axis[0])
    s = np.r_[0, np.cumsum(np.hypot(*np.diff(A, axis=0).T))]
    from scipy.spatial import cKDTree
    t = cKDTree(A)
    anchors = []
    for e in neighbours:
        by = {}
        for k, lon, lat in e["km_labels"]:
            by.setdefault(k, []).append((lon, lat))
        for k, v in by.items():
            if len(v) == 2:
                d, j = t.query(utm(v).mean(0))
                if d < 30 and 0 < j < len(A) - 1:
                    anchors.append((s[j], k))
    if len(anchors) < 2:
        raise ValueError(f"{r['id']}: zu wenige km-Anker aus Nachbarblättern ({len(anchors)})")
    S, Kk = np.array(anchors).T
    b, c = np.polyfit(S, Kk, 1) if np.ptp(S) > 500 else (np.sign(np.polyfit(S, Kk, 1)[0]) / 1000, 0)
    if np.ptp(S) <= 500:
        c = np.mean(Kk - b * S)
    print(f"  {r['id']}: {len(anchors)} km-Anker, {b * 1000:.4f} km/km, Rest {np.abs(Kk - b * S - c).max() * 1000:.1f} m")
    kms = []
    for k in np.arange(math.ceil(min(c, c + b * s[-1]) * 10) / 10, max(c, c + b * s[-1]), 0.1):
        x, y = np.interp((k - c) / b, s, A[:, 0]), np.interp((k - c) / b, s, A[:, 1])
        lon, lat = UTM.transform(x, y)
        kms += [[round(float(k), 1), round(lon, 7), round(lat, 7)]] * 2   # Paar wie "ein Label je Ufer"
    return dict(id=r["id"], km=r["km"], folder=build.folder_of(r), date=r["date"],
                shore=shore, axis=axis, km_labels=kms)


def cmd_extract(a):
    OUT.mkdir(parents=True, exist_ok=True)
    scans = []
    for p in sorted(Path("out/sheets").glob("*.json")):
        r = json.loads(p.read_text())
        if not r["status"].startswith("OK") or (a.only and a.only not in r["id"]):
            continue
        if r["source"] == "scan":
            scans.append(r)
            continue
        e = extract(r)
        (OUT / f"{r['id']}.json").write_text(json.dumps(e))
        print(f"{r['id']:34s} Ufer {len(e['shore']):3d} Linien {sum(map(len, e['shore'])):6d} Pkt  "
              f"Achse {len(e['axis']):3d}  km-Labels {len(e['km_labels'])}")
    vec = [json.loads(p.read_text()) for p in sorted(OUT.glob("*.json"))]
    for r in scans:                         # nach den Vektorblättern: deren km-Labels verankern die Scans
        e = extract_scan(r, [v for v in vec if v["id"] != r["id"] and group_of(v) == "NOK"])
        (OUT / f"{r['id']}.json").write_text(json.dumps(e))
        print(f"{r['id']:34s} Ufer {len(e['shore']):3d} Linien {sum(map(len, e['shore'])):6d} Pkt  (Scan)")


def cmd_osm(_):
    q = """[out:json][timeout:120];
    (way["route"="ferry"](53.85,9.10,54.40,10.20);
     node["amenity"="ferry_terminal"](53.85,9.10,54.40,10.20);
     way["bridge"]["highway"](53.85,9.10,54.40,10.20);
     way["bridge"]["railway"](53.85,9.10,54.40,10.20);
     way["power"="line"](54.25,9.55,54.40,9.85);
     way["man_made"="pier"](53.85,9.10,54.40,10.20);
     way["landuse"="harbour"](53.85,9.10,54.40,10.20);
     way["landuse"="industrial"]["industrial"~"^(port|shipyard)$"](53.85,9.10,54.40,10.20);
  way(id:{extra}););
    out geom tags;"""
    extra = ",".join(str(e["osm"]) for e in __import__("yaml").safe_load(Path("rules.yaml").read_text()).get("extra_ufer", []))
    q = q.replace("{extra}", extra or "0")
    for url in ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"):
        r = requests.post(url, data={"data": q}, headers={"User-Agent": "nok-tiefenkarte/1.0"}, timeout=180)
        if r.ok:
            break
        print(f"{url}: HTTP {r.status_code}")
    r.raise_for_status()
    OSM.parent.mkdir(parents=True, exist_ok=True)
    d = r.json()
    d["_abgerufen"] = date.today().isoformat()
    OSM.write_text(json.dumps(d))
    print(f"{len(d['elements'])} OSM-Objekte -> {OSM}")


# --------------------------------------------------------------------------- Linearreferenz
# Bände außerhalb der Weststrecke/Oststrecke-Ordner, deren Plankopf trotzdem Kanal-km angibt
KANAL_KM = ("NOK-Weststrecke", "Vorhaefen-Brunsbuettel", "Vorhaefen-Kiel")


def group_of(e):
    """Bezugssystem der km: Kanal-km für Kanalblätter, sonst die km-Teilung des Bandes."""
    band = re.sub(r"^\d{8}-", "", e["id"].rsplit("_p", 1)[0])
    return "NOK" if e["folder"] in ("Weststrecke", "Oststrecke") or band in KANAL_KM else band


def utm(lonlat):
    a = np.asarray(lonlat, float)
    return np.c_[TO_UTM.transform(a[:, 0], a[:, 1])]


NOK_OVERLAP_M = 12   # See-Ufer näher als das an einem Kanal-Ufer -> Kanal-Ufer (Kanalblatt zählt)
# Ufer fremder Gewässer, die ein Band mitzeichnet (eigener Erlaubnisschein): Gewässer, km von–bis (Median
# der Linie), Seite, Achsabstand (Median) darüber fällt die ganze Linie weg.
FREMDE_UFER = [("NOK", 55.5, 60.0, "Nord", 118),            # Eider nördlich vom Kanal (Kanalufer ≤ 112 m, Eider ≥ 121 m)
               ("NOK", 44.0, 47.7, "Süd", 120)]             # Nebengewässer km 44,8 und 46,55 (Kanalufer ≤ 97 m, dort ≥ 146 m)
# wie FREMDE_UFER, aber je Punkt (Kanal- und See-Ufer in einer Linie): Punkte über dem Achsabstand fallen weg
FREMDE_UFERPUNKTE = [("NOK", 85.15, 85.40, "Süd", 120),     # Einfahrt Flemhuder See (Kanalufer dort ≤ 113 m)
                     ("NOK", 15.25, 15.65, "Süd", 100)]   # Wilsterau (Schöpfwerk), Kanalufer dort ≤ 95 m
# Ufer, die der Atlas ohne blaue Linie zeichnet (Kaimauer, Steinpackung): (km von, bis), Linie lon/lat.
# Wird jedem Kanalblatt gegeben, dessen km-Bereich sie berührt; jedes behält seinen Teil.
UFER_ERGAENZT = [((61.70, 61.89), [(9.6689895, 54.2905442), (9.6716957, 54.2909406)]),   # Rendsburg Süd, Steinpackung
                 ((63.54, 63.73), [(9.6960766, 54.2954272), (9.6985298, 54.2961508)])]   # Saatsee Süd, Atlas ohne Uferlinie


class Sheet:
    def __init__(self, e, groups):
        self.e, self.id, self.group = e, e["id"], group_of(e)
        self.exclude = None
        by = {}
        for k, lon, lat in e["km_labels"]:
            by.setdefault(k, []).append((lon, lat))
        pairs = sorted((k, v) for k, v in by.items() if len(v) == 2)   # ein Label je Ufer
        self.akm = np.array([k for k, _ in pairs])
        self.axis = np.array([utm(v).mean(0) for _, v in pairs])     # Mittelpunkte = Achse
        d = self.axis[-1] - self.axis[0]
        if self.group == "NOK":
            self.left = "Nord"          # Kanal: Nordufer liegt links in km-Richtung (Richtung Kiel)
        else:                           # Seen: geometrisch, welche Seite liegt nördlich
            self.left = "Nord" if d[0] > 0 else "Süd"
            if abs(d[0]) < 0.3 * np.hypot(*d):
                print(f"  WARNUNG {self.id}: Band verläuft etwa Nord-Süd, Nord/Süd-Zuordnung unsicher")
        lo, hi = e["km"] or (-np.inf, np.inf)
        others = [g for g in groups[self.group] if g is not e and g["km"]]
        self.lo = lo if any(o["km"][0] < lo for o in others) else -np.inf   # am Bandrand offen
        self.hi = hi if any(o["km"][1] > hi for o in others) else np.inf

    def locate(self, P):
        """Punkte (UTM) -> km (auf der Achse interpoliert, an den Enden extrapoliert), Seite."""
        A, B = self.axis[:-1], self.axis[1:]
        AB = B - A
        L2 = (AB ** 2).sum(1)
        t = ((P[:, None, :] - A[None]) * AB[None]).sum(2) / L2[None]
        n = len(A)
        tc = np.clip(t, 0, 1)
        tc[:, 0] = np.minimum(t[:, 0], 1)           # vor dem ersten Label extrapolieren
        tc[:, n - 1] = np.maximum(t[:, n - 1], 0)   # hinter dem letzten Label extrapolieren
        F = A[None] + tc[..., None] * AB[None]
        dist = np.hypot(*(P[:, None, :] - F).transpose(2, 0, 1))
        j = dist.argmin(1)
        i = np.arange(len(P))
        km = self.akm[j] + tc[i, j] * (self.akm[j + 1] - self.akm[j])
        cross = AB[j, 0] * (P[:, 1] - A[j, 1]) - AB[j, 1] * (P[:, 0] - A[j, 0])
        side = np.where(cross > 0, self.left, "Süd" if self.left == "Nord" else "Nord")
        return km, side, dist[i, j]

    def shores(self, step=2.0):
        """Uferlinien verdichtet (≤ step m), mit km/Seite, auf den eigenen km-Bereich beschnitten."""
        for line in self.e["shore"]:
            P = utm(line)
            seg = np.hypot(*np.diff(P, axis=0).T)
            Q = [P[0]]
            for p0, p1, s in zip(P[:-1], P[1:], seg):
                k = max(1, int(math.ceil(s / step)))
                Q += [p0 + (p1 - p0) * (i / k) for i in range(1, k + 1)]
            Q = np.array(Q)
            km, side, d = self.locate(Q)
            keep = (km >= self.lo) & (km < self.hi)
            if keep.any():
                k, sd, dm = np.median(km[keep]), side[keep][0], np.median(d[keep])
                if any(g == self.group and a <= k <= b and sd == u and dm > m for g, a, b, u, m in FREMDE_UFER):
                    keep[:] = False
            for g, a, b, u, m in FREMDE_UFERPUNKTE:
                if g == self.group:
                    keep &= ~((km >= a) & (km <= b) & (side == u) & (d > m))
            if self.exclude is not None:   # Kanalufer, die ein See-Band mitzeichnet, gehören zum NOK
                keep &= self.exclude.query(Q)[0] > NOK_OVERLAP_M
            yield Q, km, side, keep


def seg_intersections(P, Q):
    """Schnittpunkte zweier Polylinien (UTM) -> Liste (Punkt, Index in P)."""
    out = []
    for i in range(len(P) - 1):
        p, r = P[i], P[i + 1] - P[i]
        for j in range(len(Q) - 1):
            q, s = Q[j], Q[j + 1] - Q[j]
            den = r[0] * s[1] - r[1] * s[0]
            if abs(den) < 1e-9:
                continue
            t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / den
            u = ((q[0] - p[0]) * r[1] - (q[1] - p[1]) * r[0]) / den
            if 0 <= t <= 1 and 0 <= u <= 1:
                out.append((p + t * r, i))
    return out


def osm_ways(osm, tags):
    """Ways, deren Tags passen (Wert oder Liste möglicher Werte), mit Geometrie in UTM."""
    for el in osm["elements"]:
        t = el.get("tags", {})
        if el["type"] == "way" and all(t.get(k) in (v if isinstance(v, list) else [v]) for k, v in tags.items()):
            yield el, utm([(g["lon"], g["lat"]) for g in el["geometry"]])


def inside(poly, P, res=2.0):
    """Punkte P in geschlossener Polylinie poly (UTM, Raster 2 m)."""
    from PIL import Image, ImageDraw
    lo = poly.min(0)
    W, H = (np.ceil((poly.max(0) - lo) / res) + 2).astype(int)
    im = Image.new("1", (int(W), int(H)))
    ImageDraw.Draw(im).polygon([tuple(v) for v in (poly - lo) / res], fill=1)
    a, ij = np.asarray(im), ((P - lo) / res).astype(int)
    ok = (ij[:, 0] >= 0) & (ij[:, 0] < W) & (ij[:, 1] >= 0) & (ij[:, 1] < H)
    r = np.zeros(len(P), bool)
    r[ok] = a[ij[ok, 1], ij[ok, 0]]
    return r


def near_objects(spec, osm, shore, tree):
    """Uferpunkte (Indizes) an OSM-Objekten: Enden (Fähren), Stützpunkte im Abstand, Flächen innen."""
    P = shore[0]
    for el, W in osm_ways(osm, spec["osm"]):
        if el["id"] in spec.get("ausser", ()):
            continue
        if spec.get("enden"):
            pts = [W[0], W[-1]]
        else:                                                   # Kanten auf ≤ 5 m verdichten
            pts = [W[0]] + [a + (b - a) * t for a, b in zip(W[:-1], W[1:])
                            for t in np.linspace(0, 1, max(2, int(np.hypot(*(b - a)) / 5) + 1))[1:]]
        idx = set()
        for p in pts:
            idx.update(tree.query_ball_point(p, spec.get("abstand_m", 30)))
        if not spec.get("enden") and len(W) > 3 and np.allclose(W[0], W[-1]):
            lo, hi = W.min(0), W.max(0)
            cand = np.where(((P >= lo) & (P <= hi)).all(1))[0]
            idx.update(cand[inside(W, P[cand])])
        if idx:
            yield el, sorted(idx)


# --------------------------------------------------------------------------- Regeln
def resolve(rules, sheets, osm):
    """Regeln -> Intervalle (rule_id, gruppe, seiten, km_lo, km_hi) + Protokoll."""
    iv, log, open_, frei = [], [], [], []
    def bei(st, d):
        """Linie(n) durch st["bei"] (lat, lon), verdichtet -> (Baum, Radius m, bei_m überschreibt); None ohne bei."""
        if "bei" not in st:
            return None
        lines = st["bei"] if isinstance(st["bei"][0][0], list) else [st["bei"]]   # eine oder mehrere Linien
        B = [utm([q[::-1] for q in ln]) for ln in lines]
        B = np.vstack([a + (b - a) * t for L in B for a, b in zip(L[:-1], L[1:]) for t in np.linspace(0, 1, 30)])
        return cKDTree(B), st.get("bei_m", d)
    shore_cache = {s.id: list(s.shores()) for s in sheets}
    # alle gültigen Uferpunkte flach (für Objektregeln): Punkt, Gewässer, Seite, km
    flat = [(Q[keep], [s.group] * int(keep.sum()), sd[keep], km[keep])
            for s in sheets for Q, km, sd, keep in shore_cache[s.id]]
    shore = (np.vstack([f[0] for f in flat]), np.array([g for f in flat for g in f[1]]),
             np.concatenate([f[2] for f in flat]), np.concatenate([f[3] for f in flat]))
    from scipy.spatial import cKDTree
    tree = cKDTree(shore[0])
    def objects(r, g):
        """Regel aus OSM-Objekten: je Objekt die berührten Uferstücke (Lücke > 30 m trennt) ± Puffer."""
        n = 0
        for spec in g["objekte"]:
            dk = spec.get("puffer_m", 0) / 1000
            for el, idx in near_objects(spec, osm, shore, tree):
                for grp, sd in {(shore[1][i], shore[2][i]) for i in idx}:
                    ks = np.sort([shore[3][i] for i in idx if shore[1][i] == grp and shore[2][i] == sd])
                    lim = spec.get("km")
                    if lim and not (grp == "NOK" and lim[0] <= ks.mean() <= lim[1]):   # km gilt nur für den Kanal
                        continue
                    sel = [i for i in idx if shore[1][i] == grp and shore[2][i] == sd]
                    for run in np.split(ks, np.where(np.diff(ks) > 0.03)[0] + 1):
                        # nur Ufer nahe am Objekt: gleiche km/Seite gibt es sonst auch an anderen Ufern (Enge, Inseln)
                        pts = shore[0][[i for i in sel if run[0] <= shore[3][i] <= run[-1]]]
                        iv.append((r["id"], grp, [sd], run[0] - dk, run[-1] + dk, (cKDTree(pts), dk * 1000 + 30)))
                        n += 1
                        name = el["tags"].get("name") or "/".join(f"{k}={v}" for k, v in spec["osm"].items() if not isinstance(v, list)) or "OSM"
                        log.append(f"{r['id']}: {name} (way/{el['id']}) -> {grp} {sd} km {run[0] - dk:.3f}–{run[-1] + dk:.3f}")
        if not n:
            log.append(f"{r['id']}: keine OSM-Objekte am Ufer")
    def bound(spec, group, side, other_km=None):
        if "km" in spec:
            return spec["km"], f"km {spec['km']}"
        hits = []
        for el, W in osm_ways(osm, spec["osm"]):
            for s in sheets:
                if s.group != group:
                    continue
                for Q, km, sd, keep in shore_cache[s.id]:
                    for pt, i in seg_intersections(Q, W):
                        if sd[i] == side and keep[i]:
                            hits.append((float(km[i]), pt, el))
        if not hits:
            raise ValueError(f"OSM {spec['osm']} schneidet das {side}ufer von {group} nicht")
        if spec.get("wahl") == "westlichste":
            k, pt, el = min(hits, key=lambda h: h[1][0])
        else:   # mehrere Schnitte (z. B. zwei Richtungsfahrbahnen): die vom anderen Ende entferntere
            k, pt, el = max(hits, key=lambda h: abs(h[0] - (other_km or 0)))
        lon, lat = UTM.transform(*pt)
        name = el["tags"].get("name") or el["tags"].get("bridge:name") or el["tags"].get("ref", "")
        alle = ", ".join(sorted({f"{h[0]:.3f}" for h in hits}))
        return k, f"OSM way/{el['id']} ({name}) bei km {k:.3f} ({lat:.5f}, {lon:.5f}); alle Schnitte: {alle}"
    for art in ("ausgenommen", "einschraenkungen"):
        for r in rules.get(art, []):
            g, sides = r.get("geometrie", {}), {"Nord": ["Nord"], "Süd": ["Süd"], "beide": ["Nord", "Süd"]}.get(r.get("ufer"), ["Nord", "Süd"])
            try:
                if r["typ"] == "km":
                    iv.append((r["id"], "NOK", sides, r["von_km"], r["bis_km"], None))
                    log.append(f"{r['id']}: NOK {'/'.join(sides)} km {r['von_km']}–{r['bis_km']}")
                elif r["typ"] == "ort" and "von" in g:
                    side = sides[0]
                    bis_k, bis_t = bound(g["bis"], g["gewaesser"], side)
                    von_k, von_t = bound(g["von"], g["gewaesser"], side, bis_k)
                    lo, hi = sorted((von_k, bis_k))
                    if g["bis"].get("offen"):
                        lo, hi = (-np.inf, hi) if bis_k <= von_k else (lo, np.inf)
                    iv.append((r["id"], g["gewaesser"], sides, lo, hi, None))
                    log.append(f"{r['id']}: {g['gewaesser']} {side} von {von_t} bis {bis_t}{' (offen)' if g['bis'].get('offen') else ''}")
                elif "objekte" in g or "abschnitte" in g:
                    objects(r, g) if "objekte" in g else None
                    for st in g.get("abschnitte", []):   # von Hand: km, Seite; bei: nur Ufer ≤ 60 m an dieser Linie
                        iv.append((r["id"], st.get("gewaesser", "NOK"), [st["ufer"]], *st["km"], bei(st, 60)))
                        log.append(f"{r['id']}: {st.get('gewaesser', 'NOK')} {st['ufer']} km {st['km'][0]}–{st['km'][1]} (von Hand{', ' + st['grund'] if 'grund' in st else ''})")
                    for st in g.get("frei", []):         # von Hand ausgenommen: schneidet die Intervalle der Regel
                        a, b = st["km"]
                        gw = st.get("gewaesser", "NOK")
                        if "bei" in st:                  # nur Ufer ≤ 10 m an der Linie (Mole: Becken gleiche km/Seite)
                            frei.append((r["id"], gw, st["ufer"], a, b, bei(st, 10)))
                            log.append(f"{r['id']}: {gw} {st['ufer']} km {a}–{b} frei an Linie (von Hand, {st.get('grund', '')})")
                            continue
                        cut = [x for x in iv if x[0] == r["id"] and x[1] == gw and st["ufer"] in x[2] and x[3] < b and x[4] > a]
                        for x in cut:
                            iv.remove(x)
                            iv += [(*x[:4], a, x[5])] * bool(x[3] < a) + [(*x[:3], b, x[4], x[5])] * bool(x[4] > b)
                        log.append(f"{r['id']}: {gw} {st['ufer']} km {a}–{b} frei (von Hand{', ' + st['grund'] if 'grund' in st else ''})")
                elif r["typ"] != "nicht_kartierbar":
                    open_.append(r["id"])
            except ValueError as ex:
                open_.append(r["id"]); log.append(f"{r['id']}: FEHLER {ex}")
    return iv, log, open_, frei


def extra_lines(rules, osm):
    """extra_ufer -> GeoJSON-Features: Ringstück von 'von' nach 'bis' in der Richtung, die über 'ueber' führt."""
    ways = {el["id"]: el for el in osm["elements"] if el["type"] == "way"}
    feats = []
    for e in rules.get("extra_ufer", []):
        g = [(p["lon"], p["lat"]) for p in ways[e["osm"]]["geometry"]]
        n = len(g) - 1 if g[0] == g[-1] else len(g)
        P = utm(g[:n])
        i, j, k = (int(np.hypot(*(P - utm([e[x][::-1]])[0]).T).argmin()) for x in ("von", "ueber", "bis"))
        fwd = [(i + t) % n for t in range((k - i) % n + 1)]
        path = fwd if j in fwd else [(i - t) % n for t in range((i - k) % n + 1)]
        feats.append(dict(type="Feature", geometry=dict(type="LineString", coordinates=[list(g[t]) for t in path]),
                          properties=dict(ufer=e["ufer"], rules=e["regeln"], geltung=True, gewaesser=e["gewaesser"],
                                          quelle="OpenStreetMap")))
    return feats


def cmd_build(a):
    rules = __import__("yaml").safe_load(Path("rules.yaml").read_text())
    osm = json.loads(OSM.read_text())
    exts = [json.loads(p.read_text()) for p in sorted(OUT.glob("*.json"))]
    groups = {}
    for e in exts:
        groups.setdefault(group_of(e), []).append(e)
    for (k0, k1), line in UFER_ERGAENZT:
        for e in groups["NOK"]:
            if e["km"] and e["km"][0] < k1 and e["km"][1] > k0:
                e["shore"].append(line)
    sheets = [Sheet(e, groups) for e in exts]
    nok = [Q for s in sheets if s.group == "NOK" for Q, *_ in s.shores()]
    if nok:
        from scipy.spatial import cKDTree
        tree = cKDTree(np.vstack(nok))
        for s in sheets:
            if s.group != "NOK":
                s.exclude = tree
    iv, log, open_, frei = resolve(rules, sheets, osm)
    print("\n".join(log))
    gb = rules["geltungsbereich"]
    dest = Path("site/ufer"); dest.mkdir(parents=True, exist_ok=True)
    for s in sheets:
        if a.only and a.only not in s.id:
            continue
        feats = []
        for Q, km, side, keep in s.shores():
            def key(i):
                if not keep[i]:
                    return None
                ids = tuple(sorted(rid for rid, g, sides, lo, hi, near in iv
                                   if g == s.group and side[i] in sides and lo <= km[i] <= hi
                                   and (near is None or near[0].query(Q[i])[0] <= near[1])
                                   and not any(f[0] == rid and f[1] == g and f[2] == side[i] and f[3] <= km[i] <= f[4]
                                               and f[5][0].query(Q[i])[0] <= f[5][1] for f in frei)))
                inside = s.group != "NOK" or gb["von_km"] <= km[i] <= gb["bis_km"] or any(r in gb.get("auch", ()) for r in ids)
                return str(side[i]), ids, bool(inside)
            run, cur = [], None
            for i in range(len(Q) + 1):
                k = key(i) if i < len(Q) else None
                if k != cur and run:
                    if cur and len(run) > 1:
                        ll = [[round(v, 7) for v in UTM.transform(*Q[j])] for j in run]
                        feats.append(dict(type="Feature", geometry=dict(type="LineString", coordinates=ll),
                                          properties=dict(ufer=cur[0], rules=list(cur[1]), geltung=cur[2],
                                                          km=[round(float(km[run[0]]), 3), round(float(km[run[-1]]), 3)],
                                                          gewaesser=s.group)))
                    run = [run[-1]] if k and cur and k[0] == cur[0] else []   # lückenlos anschließen
                cur = k
                if k:
                    run.append(i)
        (dest / f"{s.id}.geojson").write_text(json.dumps(dict(type="FeatureCollection", features=feats), separators=(",", ":")))
        print(f"{s.id:34s} {len(feats):4d} Uferabschnitte, Nord=links: {s.left == 'Nord'}, km {s.lo}–{s.hi}")
    flat = {}
    for art in ("ausgenommen", "einschraenkungen"):
        for r in rules.get(art, []):
            flat[r["id"]] = dict(art=art, text=" ".join(r["text"].split()), zeitraum=r.get("zeitraum"),
                                 anzeige=r.get("anzeige"), typ=r["typ"])
    Path("site/rules.json").write_text(json.dumps(dict(
        quelle=rules["quelle"], geltungsbereich=gb, rules=flat,
        nicht_kartierbar=[flat[k]["text"] for k in flat if flat[k]["typ"] == "nicht_kartierbar"],
        allgemein=rules.get("allgemein", []), offen=open_, osm_abgerufen=osm.get("_abgerufen")),
        ensure_ascii=False, indent=1))
    (dest / "extra.geojson").write_text(json.dumps(dict(type="FeatureCollection", features=extra_lines(rules, osm)),
                                                   separators=(",", ":")))
    idx = Path("site/index.json")   # neuer Datenstand, sonst liefert der Service Worker alte Uferlinien (?v=)
    if idx.exists():
        idx.write_text(json.dumps(json.loads(idx.read_text()) | dict(version=datetime.now().strftime("%Y%m%d%H%M"))))
    print("nicht (noch) gezeichnet:", ", ".join(open_) or "–")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["extract", "osm", "build"])
    ap.add_argument("--only")
    a = ap.parse_args()
    {"extract": cmd_extract, "osm": cmd_osm, "build": cmd_build}[a.cmd](a)
