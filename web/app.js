/* NOK Tiefenkarte – statische Web-App. Daten: index.json, tiles/, ufer/, sections/, rules.json (tiles.py, ufer.py). */
"use strict";

const $ = (s) => document.querySelector(s);
const fmt = (v, d = 1) => v.toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtKm = (km) => km ? `km ${fmt(km[0], km[0] % 1 ? 1 : 0)}–${fmt(km[1], km[1] % 1 ? 1 : 0)}`.replace(/,(\d)0\b/g, ",$1") : "";
const fmtDist = (m) => m < 1000 ? `${fmt(m, m < 10 ? 1 : 0)} m` : `${fmt(m / 1000, 2)} km`;
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* privater Modus */ } },
};

const app = window.app = {
  index: null, map: null,
  follow: false, pos: null, measure: null,
};

// ---------------------------------------------------------------- Geometrie (lokal eben, reicht für < 50 km)
function toXY(ll, ref) {
  const k = Math.cos(ref.lat * Math.PI / 180) * 111320;
  return [(ll.lng - ref.lng) * k, (ll.lat - ref.lat) * 110574];
}
function inPoly(ll, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [yi, xi] = poly[i], [yj, xj] = poly[j];
    if ((yi > ll.lat) !== (yj > ll.lat) && ll.lng < (xj - xi) * (ll.lat - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function polyDist(ll, poly) {
  if (inPoly(ll, poly)) return 0;
  let best = Infinity;
  for (let i = 0; i < poly.length; i++) {
    const [ax, ay] = toXY(L.latLng(poly[i]), ll), [bx, by] = toXY(L.latLng(poly[(i + 1) % poly.length]), ll);
    const dx = bx - ax, dy = by - ay, t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy)));
    best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
  }
  return best;
}
const dateVal = (d) => d ? d.split(".").reverse().join("") : "";

// ---------------------------------------------------------------- Karte
function chartLayer(name) {
  const sections = app.index.sections.map((s) => L.latLngBounds(s.bounds));
  const Layer = L.TileLayer.extend({
    createTile(coords, done) {   // keine Anfragen außerhalb der Abdeckung (spart 404 und Funklast)
      const b = this._tileCoordsToBounds(coords);
      if (!sections.some((s) => s.intersects(b))) {
        const t = document.createElement("img");
        setTimeout(() => done(null, t));
        return t;
      }
      return L.TileLayer.prototype.createTile.call(this, coords, done);
    },
  });
  return new Layer(`tiles/${name}/{z}/{x}/{y}.webp?v=${app.index.version}`, {
    minZoom: 8, maxZoom: 21, minNativeZoom: app.index.zmin, maxNativeZoom: app.index.zmax,
    className: "chart-tiles", attribution: 'Tiefenatlas NOK: © WSV, <a href="https://www.govdata.de/dl-de/zero-2-0">dl-de/zero-2-0</a>, aufbereitet',
    errorTileUrl: "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==",
  });
}

function initMap() {
  const map = app.map = L.map("map", { zoomControl: false, minZoom: 8, maxZoom: 21, zoomSnap: 0.5, tap: false });
  L.control.zoom({ position: "topright" }).addTo(map);
  map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
  const year = new Date().getFullYear();
  $("#bkg-year").textContent = year;
  app.base = L.tileLayer("https://sgx.geodatenzentrum.de/wmts_basemapde/tile/1.0.0/de_basemapde_web_raster_grau/default/GLOBAL_WEBMERCATOR/{z}/{y}/{x}.png", {
    maxNativeZoom: 18, maxZoom: 21, className: "base-tiles", opacity: 0.6,
    attribution: `Hintergrund: © GeoBasis-DE / BKG (${year}) <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>`,
  });
  if (store.get("base", true)) app.base.addTo(map);
  chartLayer("plan").addTo(map);
  for (const s of app.index.sections)
    L.polygon(s.poly, { color: "#0b6fa4", weight: 1, opacity: 0.6, fill: false, interactive: false }).addTo(map);
  const all = L.latLngBounds(app.index.sections.flatMap((s) => s.bounds));
  const last = store.get("view", null);
  if (last) map.setView(last.c, last.z); else map.fitBounds(all);
  map.on("moveend", () => { store.set("view", { c: map.getCenter(), z: map.getZoom() }); updateWhere(); loadShores(); });
  app.shoreGroup = L.layerGroup();
  app.shoreLoaded = new Set();
  map.on("dragstart", () => setFollow(false));
  // Während ein Finger auf der Karte liegt nicht nachzentrieren, sonst bricht setView den Drag ab
  const box = map.getContainer();
  box.addEventListener("pointerdown", () => { app.touching = true; });
  for (const t of ["pointerup", "pointercancel"]) window.addEventListener(t, () => { app.touching = false; });
  map.on("click", (e) => onTap(e.latlng));
}

// ---------------------------------------------------------------- Angel-Layer (Uferlinien nach rules.json)
const COLORS = { gruen: "#1e9e3a", rot: "#d0021b", orange: "#e08a00", grau: "#8a959c" };
// Prüfdatum per ?datum=JJJJ-MM-TT (zum Kontrollieren der Schonzeiten), sonst heute
const today = () => { const q = new URLSearchParams(location.search).get("datum"); return q ? new Date(q + "T12:00") : new Date(); };
const mmdd = (d) => `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function inPeriod(z, d) {
  if (!z) return true;
  const t = mmdd(d);
  return z.von <= z.bis ? z.von <= t && t <= z.bis : t >= z.von || t <= z.bis;   // auch über Jahreswechsel
}
const fmtPeriod = (z) => z ? `${z.von.slice(3)}.${z.von.slice(0, 2)}.–${z.bis.slice(3)}.${z.bis.slice(0, 2)}.` : "";
/** Status eines Uferabschnitts am Datum d: rot = Ausnahme gilt, orange = Einschränkung gilt, sonst grün. */
function shoreStatus(p, d) {
  if (!p.geltung) return "grau";
  const rs = p.rules.map((id) => app.rules.rules[id]).filter(Boolean);
  if (rs.some((r) => r.art === "ausgenommen" && inPeriod(r.zeitraum, d))) return "rot";
  if (rs.some((r) => r.art === "einschraenkungen" && inPeriod(r.zeitraum, d))) return "orange";
  return "gruen";
}
function shoreInfo(p) {
  const d = today(), st = shoreStatus(p, d);
  const head = { gruen: "Laut Schein nicht ausgenommen", rot: "Ausgenommen – Angeln vom Ufer nicht erlaubt",
    orange: "Erlaubt mit Einschränkung", grau: "Außerhalb des Geltungsbereichs" }[st];
  const km = `${p.gewaesser === "NOK" ? "NOK" : p.gewaesser.replace(/-/g, " ")} ${p.ufer}ufer` +
    (p.km ? ` km ${fmt(Math.min(...p.km), 2)}–${fmt(Math.max(...p.km), 2)}` : ` (Uferlinie aus ${p.quelle})`);
  const rules = p.rules.map((id) => {
    const r = app.rules.rules[id], on = inPeriod(r.zeitraum, d);
    const cls = !on ? "gruen" : r.art === "ausgenommen" ? "rot" : "orange";
    const per = r.zeitraum ? ` <span class="muted">(${fmtPeriod(r.zeitraum)}, ${on ? "gilt jetzt" : "gilt derzeit nicht"})</span>` : "";
    const div = document.createElement("div"); div.className = `rule ${cls}`; div.textContent = r.anzeige ? `${r.anzeige}: ${r.text}` : r.text;
    return div.outerHTML.replace("</div>", `${per}</div>`);
  }).join("");
  const q = app.rules.quelle;
  return `<span class="big" style="color:${COLORS[st]}">${head}</span><div class="muted">${km} · Stand ${q.schein}, ${q.abgerufen}` +
    `${new URLSearchParams(location.search).get("datum") ? ` · Prüfdatum ${d.toLocaleDateString("de-DE")}` : ""}</div>${rules}` +
    `<div class="muted">Nicht kartiert: Baustellen, Lebendverbau, Abbruchufer, Fischereianlagen, Pachtflächen. Maßgeblich ist der Erlaubnisschein.</div>`;
}
async function loadShores() {
  if (!app.angel || app.map.getZoom() < 12) return;
  const view = app.map.getBounds().pad(0.3);
  const ids = app.index.sections.filter((s) => s.ufer && view.intersects(s.bounds)).map((s) => s.id).concat("extra");
  for (const id of ids) {   // extra: Uferlinien, die der Atlas nicht zeichnet (aus OSM), immer mit
    if (app.shoreLoaded.has(id)) continue;
    app.shoreLoaded.add(id);
    fetch(`ufer/${id}.geojson?v=${app.index.version}`).then((r) => r.json()).then((gj) => {
      L.geoJSON(gj, {
        style: (f) => ({ color: COLORS[shoreStatus(f.properties, today())], weight: 6, opacity: 0.9, lineCap: "butt" }),
        onEachFeature: (f, layer) => layer.on("click", (e) => { L.DomEvent.stop(e); show(shoreInfo(f.properties)); }),
      }).addTo(app.shoreGroup);
    }).catch(() => app.shoreLoaded.delete(id));
  }
}
async function setAngel(on) {
  app.angel = on;
  $("#btn-angel").setAttribute("aria-pressed", on);
  $("#angel-note").hidden = !on;
  document.body.classList.toggle("angel", on);
  store.set("angel", on);
  if (on) {
    if (!app.rules) app.rules = await (await fetch(`rules.json?v=${app.index.version}`)).json();
    const q = new URLSearchParams(location.search).get("datum");
    $("#angel-date").textContent = q ? ` (Prüfdatum ${today().toLocaleDateString("de-DE")})` : "";
    app.shoreGroup.addTo(app.map);
    loadShores();
  } else app.shoreGroup.remove();
}

// ---------------------------------------------------------------- Abschnitt anzeigen
function sectionAt(ll) {
  const hits = app.index.sections.filter((s) => inPoly(ll, s.poly));
  return hits.sort((a, b) => dateVal(b.date).localeCompare(dateVal(a.date)))[0] || null;  // neueste Messung
}
function updateWhere() {
  if (!app.index) return;
  const ll = app.follow && app.pos ? app.pos.latlng : app.map.getCenter();
  const s = sectionAt(ll), el = $("#where");
  const lost = $("#where").dataset.gps === "lost";
  const acc = app.pos ? ` · GPS ±${fmt(app.pos.acc, 0)} m${lost ? " (Signal verloren)" : ""}` : "";
  if (s) {
    el.innerHTML = `<span class="name"></span><br><span class="muted">${fmtKm(s.km)} · Messung ${s.date}${acc}</span>`;
    el.querySelector(".name").textContent = s.name.replace(/ km .*$/, "").replace(/ \(Messung.*$/, "");
    el.dataset.section = s.id;
    return;
  }
  let best = null, d = Infinity;
  for (const x of app.index.sections) { const dd = polyDist(ll, x.poly); if (dd < d) { d = dd; best = x; } }
  el.dataset.section = "";
  el.innerHTML = `<span class="out">Außerhalb der Abdeckung</span>${acc ? `<span class="muted">${acc}</span>` : ""}<br>` +
    `<button type="button">Nächster Abschnitt: ${fmtKm(best.km) || best.name.replace(/ \(Messung.*$/, "")} · ${fmtDist(d)}</button>`;
  el.querySelector("button").onclick = () => { setFollow(false); app.map.fitBounds(best.bounds); };
}

// ---------------------------------------------------------------- Antippen / Messen
function show(html) { const r = $("#readout"); r.innerHTML = html; r.hidden = !html; }

function onTap(ll) {
  if (app.measure) return measureTap(ll);
  show("");   // Karte ist ein reiner Bildlayer; Antippen schließt nur die Info-Leiste
}

function measureTap(ll) {
  const m = app.measure;
  if (app.pos) { m.a = null; m.b = ll; }                     // Ziel relativ zur eigenen Position
  else if (!m.a || m.b) { m.a = ll; m.b = null; }            // ohne GPS: zwei Punkte
  else m.b = ll;
  drawMeasure();
}
function drawMeasure() {
  const m = app.measure;
  if (!m) return;
  m.group.clearLayers();
  const a = app.pos ? app.pos.latlng : m.a, b = m.b;
  if (!b) {
    if (a) L.circleMarker(a, { radius: 6, color: "#d0021b" }).addTo(m.group);
    show(app.pos ? "Ziel antippen" : (m.a ? "Zweiten Punkt antippen" : "Ersten Punkt antippen (kein GPS)"));
    return;
  }
  const d = app.map.distance(a, b);
  L.polyline([a, b], { color: "#d0021b", weight: 3, dashArray: "6 6" }).addTo(m.group);
  L.circleMarker(b, { radius: 7, color: "#d0021b", weight: 3 }).addTo(m.group);
  if (!app.pos) L.circleMarker(a, { radius: 6, color: "#d0021b" }).addTo(m.group);
  show(`<span class="big" data-dist="${d.toFixed(2)}">${fmtDist(d)}</span> ${app.pos ? "von deiner Position" : "zwischen den Punkten"}` +
    (app.pos ? ` <span class="muted">(GPS ±${fmt(app.pos.acc, 0)} m)</span>` : ""));
}
function toggleMeasure() {
  if (app.measure) { app.measure.group.remove(); app.measure = null; show(""); }
  else { app.measure = { a: null, b: null, group: L.layerGroup().addTo(app.map) }; drawMeasure(); }
  $("#btn-measure").setAttribute("aria-pressed", !!app.measure);
}

// ---------------------------------------------------------------- GPS
let watchId = null, posMarker = null, accCircle = null;
function startGps() {
  if (watchId !== null || !navigator.geolocation) return;
  watchId = navigator.geolocation.watchPosition((p) => {
    app.pos = { latlng: L.latLng(p.coords.latitude, p.coords.longitude), acc: p.coords.accuracy };
    $("#where").dataset.gps = "ok";
    if (!posMarker) {
      accCircle = L.circle(app.pos.latlng, { radius: app.pos.acc, color: "#1a73e8", weight: 1, fillOpacity: 0.12, interactive: false }).addTo(app.map);
      posMarker = L.circleMarker(app.pos.latlng, { radius: 8, color: "#fff", weight: 3, fillColor: "#1a73e8", fillOpacity: 1, interactive: false }).addTo(app.map);
    }
    posMarker.setLatLng(app.pos.latlng);
    accCircle.setLatLng(app.pos.latlng).setRadius(app.pos.acc);
    if (app.follow && !app.touching) app.map.setView(app.pos.latlng, Math.max(app.map.getZoom(), 16), { animate: false });
    updateWhere();
    drawMeasure();
  }, (err) => {
    if (err.code !== 1) {        // kurzzeitig kein Fix (Brücke, Abschattung): weiter beobachten
      $("#where").dataset.gps = "lost";
      return;
    }
    setFollow(false);
    show(`<span class="muted">GPS-Zugriff verweigert – in den Browser-Einstellungen erlauben.</span>`);
    navigator.geolocation.clearWatch(watchId); watchId = null;
  }, { enableHighAccuracy: true, maximumAge: 2000, timeout: 30000 });
}
function setFollow(on) {
  app.follow = on;
  $("#btn-follow").setAttribute("aria-pressed", on);
  if (on) { startGps(); if (app.pos) app.map.setView(app.pos.latlng, Math.max(app.map.getZoom(), 16)); }
  updateWhere();
}

// ---------------------------------------------------------------- Abschnittsliste + Offline
const offline = () => store.get("offline", {});
async function quotaText() {
  if (!navigator.storage?.estimate) return "";
  const { usage = 0, quota = 0 } = await navigator.storage.estimate();
  return `Speicher: ${fmt(usage / 1e6, 0)} MB belegt, ${fmt((quota - usage) / 1e6, 0)} MB frei`;
}
function renderList() {
  const box = $("#sections"), saved = offline();
  box.replaceChildren();
  let folder = null;
  for (const s of app.index.sections) {
    if (s.folder !== folder) { folder = s.folder; const h = document.createElement("h3"); h.className = "folder"; h.textContent = folder; box.append(h); }
    const row = document.createElement("div");
    row.className = "sec"; row.dataset.id = s.id;
    const jump = document.createElement("button");
    jump.className = "jump";
    jump.innerHTML = `<strong></strong><span class="muted">Messung ${s.date} · 1:${s.scale}</span>`;
    jump.querySelector("strong").textContent = s.name.replace(/ \(Messung.*$/, "");
    jump.onclick = () => { setFollow(false); $("#dlg-list").close(); app.map.fitBounds(s.bounds); };
    const off = document.createElement("button");
    off.className = "off";
    const st = saved[s.id];
    if (st && st.version === app.index.version) { off.classList.add("saved"); off.textContent = "✓ Löschen"; off.onclick = () => removeSection(s); }
    else { off.textContent = `${st ? "Aktualisieren" : "Offline"} (${fmt(s.bytes / 1e6, 1)} MB)`; off.onclick = () => saveSection(s, row, off); }
    row.append(jump, off);
    box.append(row);
  }
  quotaText().then((t) => { $("#quota").textContent = t; });
}
async function saveSection(s, row, btn) {
  if (!("caches" in window)) return alertRow(row, "Offline-Speicher wird von diesem Browser nicht unterstützt.");
  if (navigator.storage?.estimate) {
    const { usage = 0, quota = 0 } = await navigator.storage.estimate();
    if (quota && quota - usage < s.bytes * 1.2) return alertRow(row, `Nicht genug Speicher: ${fmt(s.bytes / 1e6, 1)} MB nötig, ${fmt((quota - usage) / 1e6, 0)} MB frei.`);
  }
  navigator.storage?.persist?.();
  btn.disabled = true;
  const bar = document.createElement("progress");
  row.append(bar);
  try {
    const man = await (await fetch(`sections/${s.id}.json?v=${app.index.version}`, { cache: "no-store" })).json();
    await caches.delete(`sec-${s.id}`);
    const cache = await caches.open(`sec-${s.id}`);
    bar.max = man.files.length; bar.value = 0;
    const queue = man.files.slice();
    const worker = async () => {
      while (queue.length) {
        const url = `${queue.shift()}?v=${app.index.version}`;
        const r = await fetch(url);
        if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
        await cache.put(url, r);
        bar.value++;
        btn.textContent = `${Math.round(100 * bar.value / bar.max)} %`;
      }
    };
    await Promise.all(Array.from({ length: 6 }, worker));
    const o = offline(); o[s.id] = { version: app.index.version, bytes: man.bytes }; store.set("offline", o);
  } catch (e) {
    await caches.delete(`sec-${s.id}`);
    alertRow(row, `Speichern fehlgeschlagen: ${e.message}`);
  }
  renderList();
}
async function removeSection(s) {
  await caches.delete(`sec-${s.id}`);
  const o = offline(); delete o[s.id]; store.set("offline", o);
  renderList();
}
function alertRow(row, msg) {
  const p = document.createElement("p"); p.className = "muted"; p.style.gridColumn = "1 / -1"; p.style.color = "var(--warn)";
  p.textContent = msg; row.append(p);
}
async function cleanupCaches() {   // Caches nicht mehr existierender Abschnitte (neuer ELWIS-Stand) entfernen
  if (!("caches" in window)) return;
  const ids = new Set(app.index.sections.map((s) => s.id)), o = offline();
  for (const k of await caches.keys()) {
    if (k.startsWith("sec-") && !ids.has(k.slice(4))) { await caches.delete(k); delete o[k.slice(4)]; }
  }
  store.set("offline", o);
}

// ---------------------------------------------------------------- Start
async function main() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  try {
    app.index = await (await fetch("index.json")).json();
  } catch {
    $("#where").textContent = "Keine Daten – bitte einmal online öffnen.";
    return;
  }
  let lo = null;  // Legende: [Obergrenze m | null, Farbe], 1-m-Stufen
  $("#legend").replaceChildren(...app.index.legend.map(([hi, c]) => {
    const li = document.createElement("li");
    const sw = document.createElement("i");
    sw.style.background = `#${c}`;
    li.append(sw);
    li.append(lo === null ? `< ${hi} m` : hi === null ? `> ${lo} m` : `${lo}–${hi} m`);
    lo = hi;
    return li;
  }));
  $("#data-version").textContent = app.index.version.replace(/(\d{4})(\d\d)(\d\d)(\d\d)(\d\d)/, "$3.$2.$1 $4:$5");
  initMap();
  updateWhere();
  cleanupCaches();
  navigator.permissions?.query({ name: "geolocation" }).then((p) => { if (p.state === "granted") startGps(); }).catch(() => {});
  $("#btn-follow").onclick = () => setFollow(true);   // erneutes Tippen zentriert wieder
  $("#btn-measure").onclick = toggleMeasure;
  $("#btn-list").onclick = () => { renderList(); $("#dlg-list").showModal(); };
  $("#btn-angel").onclick = () => setAngel(!app.angel);
  $("#btn-info").onclick = async () => {
    if (!app.rules) app.rules = await (await fetch(`rules.json?v=${app.index.version}`)).json().catch(() => null);
    if (app.rules) {
      $("#rules-src").textContent = `${app.rules.quelle.ausgeber}, ${app.rules.quelle.schein}, Stand ${app.rules.quelle.abgerufen}`;
      $("#osm-date").textContent = app.rules.osm_abgerufen || "–";
      $("#rules-unmapped").replaceChildren(...app.rules.nicht_kartierbar.map((t) => Object.assign(document.createElement("li"), { textContent: t })));
      $("#rules-general").replaceChildren(...app.rules.allgemein.map((t) => Object.assign(document.createElement("li"), { textContent: t })));
    }
    $("#dlg-info").showModal();
  };
  if (store.get("angel", false)) setAngel(true);
  for (const b of document.querySelectorAll("dialog .close")) b.onclick = () => b.closest("dialog").close();
  const chk = $("#chk-base");
  chk.checked = store.get("base", true);
  chk.onchange = () => { store.set("base", chk.checked); chk.checked ? app.base.addTo(app.map) : app.base.remove(); };
  if (!store.get("disclaimer", false)) { $("#dlg-first").showModal(); $("#dlg-first").onclose = () => store.set("disclaimer", true); }
}
main();
