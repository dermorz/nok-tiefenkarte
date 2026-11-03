const { test, expect } = require("@playwright/test");
const fs = require("fs");

const index = JSON.parse(fs.readFileSync("site/index.json", "utf8"));
const S = index.sections.find((s) => s.koten) || index.sections[0];
const centroid = (s) => ({ latitude: s.poly.reduce((a, p) => a + p[0], 0) / 4, longitude: s.poly.reduce((a, p) => a + p[1], 0) / 4 });
const koten = JSON.parse(fs.readFileSync(`site/koten/${S.id}.json`, "utf8"));
const C0 = centroid(S);
const kote = koten.reduce((b, k) => Math.hypot(k[0] - C0.latitude, (k[1] - C0.longitude) * 0.6) <
  Math.hypot(b[0] - C0.latitude, (b[1] - C0.longitude) * 0.6) ? k : b);    // [lat, lon, tiefe] nahe Blattmitte
const offset = (p, dn, de) => ({ latitude: p.latitude + dn / 111200, longitude: p.longitude + de / (111320 * Math.cos(p.latitude * Math.PI / 180)) });

async function open(page) {
  await page.addInitScript(() => { localStorage.setItem("disclaimer", "true"); localStorage.removeItem("view"); });
  await page.goto("/");
  await page.waitForFunction(() => window.app?.map);
}
const center = (page) => page.evaluate(() => { const c = app.map.getCenter(); return { latitude: c.lat, longitude: c.lng }; });
const dist = (page, a, b) => page.evaluate(([a, b]) => app.map.distance([a.latitude, a.longitude], [b.latitude, b.longitude]), [a, b]);
async function swipe(page, x0, y0, x1, y1) {           // echte Touch-Geste (Leaflet-Drag)
  const cdp = await page.context().newCDPSession(page);
  const ev = (type, x, y) => cdp.send("Input.dispatchTouchEvent", { type, touchPoints: type === "touchEnd" ? [] : [{ x, y }] });
  await ev("touchStart", x0, y0);
  for (let i = 1; i <= 8; i++) { await ev("touchMove", x0 + (x1 - x0) * i / 8, y0 + (y1 - y0) * i / 8); await page.waitForTimeout(20); }
  await ev("touchEnd");
}
async function tapAt(page, lat, lng) {
  const p = await page.evaluate(([lat, lng]) => app.map.latLngToContainerPoint([lat, lng]), [lat, lng]);
  await page.touchscreen.tap(p.x, p.y);
}

test.describe("mit GPS", () => {
  test.use({ geolocation: centroid(S), permissions: ["geolocation"] });

  test("Folgen: zentriert, folgt, Verschieben schaltet aus, erneut Tippen zentriert", async ({ page, context }) => {
    await open(page);
    const A = centroid(S);
    await page.tap("#btn-follow");
    await expect(page.locator("#btn-follow")).toHaveAttribute("aria-pressed", "true");
    await expect.poll(async () => dist(page, await center(page), A)).toBeLessThan(3);   // Leaflet rundet die Mitte auf Pixel (z16 ≈ 1,4 m)
    const B = offset(A, 80, 60);
    await context.setGeolocation(B);
    await expect.poll(async () => dist(page, await center(page), B)).toBeLessThan(3);   // Leaflet rundet die Mitte auf Pixel (z16 ≈ 1,4 m)
    await expect(page.locator("#where")).toContainText("GPS ±");
    await page.waitForFunction(() => !document.querySelector(".leaflet-zoom-anim"));   // Leaflet ignoriert Drags während Zoom-Animation
    await swipe(page, 200, 450, 280, 330);
    await expect(page.locator("#btn-follow")).toHaveAttribute("aria-pressed", "false");
    const C = offset(A, -120, -90);
    await context.setGeolocation(C);
    await page.waitForTimeout(500);
    expect(await dist(page, await center(page), C)).toBeGreaterThan(50);
    await page.tap("#btn-follow");
    await expect.poll(async () => dist(page, await center(page), C)).toBeLessThan(3);   // Leaflet rundet die Mitte auf Pixel (z16 ≈ 1,4 m)
  });

  test("Abschnittsanzeige wechselt mit der Position, außerhalb mit Entfernung", async ({ page, context }) => {
    await open(page);
    await page.tap("#btn-follow");
    for (const s of index.sections.slice(0, 3)) {
      await context.setGeolocation(centroid(s));
      await expect(page.locator("#where")).toContainText(`Messung ${s.date}`);
      await expect(page.locator("#where")).toHaveAttribute("data-section", s.id);
    }
    await context.setGeolocation(offset(centroid(S), 0, 5000));     // weit neben dem Kanal
    await expect(page.locator("#where")).toContainText("Außerhalb der Abdeckung");
    await expect(page.locator("#where")).toContainText(/Nächster Abschnitt: .* \d+,\d\d km/);
  });

  test("Messen von der eigenen Position: Entfernung und Tiefe am Ziel", async ({ page }) => {
    await open(page);
    await page.tap("#btn-follow");                                     // Karte folgt der Position (Blattmitte)
    await expect.poll(() => page.evaluate(() => !!app.pos)).toBe(true);
    await page.evaluate(() => app.map.setZoom(17));
    await page.tap("#btn-measure");
    await expect(page.locator("#readout")).toContainText("Ziel antippen");
    await tapAt(page, kote[0], kote[1]);
    const expected = await dist(page, centroid(S), { latitude: kote[0], longitude: kote[1] });
    const shown = Number(await page.locator("#readout [data-dist]").getAttribute("data-dist"));
    expect(Math.abs(shown - expected)).toBeLessThan(0.5);
    await expect(page.locator("#readout")).toContainText(`${kote[2].toFixed(1).replace(".", ",")} m`);
  });

  test("Antippen zeigt nächste Kote im 6-m-Umkreis, sonst Hinweis", async ({ page }) => {
    await open(page);
    await page.evaluate(([lat, lng]) => app.map.setView([lat, lng], 19), kote);
    const near = offset({ latitude: kote[0], longitude: kote[1] }, 0.6, 0.4);   // näher an dieser Kote als an Nachbarn
    await tapAt(page, near.latitude, near.longitude);
    await expect(page.locator("#readout")).toContainText(`${kote[2].toFixed(1).replace(".", ",")} m`);
    await page.evaluate(() => app.map.setView(app.map.getCenter(), 17));
    const far = offset(centroid(S), 0, 3000);
    await page.evaluate(([la, lo]) => app.map.setView([la, lo], 17), [far.latitude, far.longitude]);
    await tapAt(page, far.latitude, far.longitude);
    await expect(page.locator("#readout")).toContainText("Keine Tiefenkote im Umkreis von 6 m");
  });

  test("Offline speichern, offline neu laden, löschen", async ({ page, context }) => {
    await open(page);
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.tap("#btn-list");
    const row = page.locator(`.sec[data-id="${S.id}"]`);
    await expect(row.locator(".off")).toContainText("MB");
    await row.locator(".off").tap();
    await expect(row.locator(".off")).toHaveText("✓ Löschen", { timeout: 60_000 });
    await page.locator("#dlg-list .close").tap();
    await context.setOffline(true);
    await page.reload();
    await page.waitForFunction(() => window.app?.map);
    await page.evaluate(([lat, lng]) => app.map.setView([lat, lng], 18), kote);
    await expect.poll(() => page.locator(".chart-tiles img.leaflet-tile-loaded").count()).toBeGreaterThan(4);
    await tapAt(page, kote[0], kote[1]);
    await expect(page.locator("#readout")).toContainText(`${kote[2].toFixed(1).replace(".", ",")} m`);
    await context.setOffline(false);
    await page.tap("#btn-list");
    await row.locator(".off").tap();
    await expect(row.locator(".off")).toContainText("Offline (");
    expect(await page.evaluate((id) => caches.has(`sec-${id}`), S.id)).toBe(false);
  });
});

test.describe("ohne GPS", () => {
  test.use({ permissions: [] });
  test("Messen mit zwei Punkten", async ({ page }) => {
    await open(page);
    const A = centroid(S), B = offset(A, 30, 40);
    await page.evaluate(([la, lo]) => app.map.setView([la, lo], 18), [A.latitude, A.longitude]);
    await page.tap("#btn-measure");
    await expect(page.locator("#readout")).toContainText("Ersten Punkt antippen");
    await tapAt(page, A.latitude, A.longitude);
    await expect(page.locator("#readout")).toContainText("Zweiten Punkt antippen");
    await tapAt(page, B.latitude, B.longitude);
    const shown = Number(await page.locator("#readout [data-dist]").getAttribute("data-dist"));
    expect(Math.abs(shown - 50)).toBeLessThan(0.6);   // 30 m N, 40 m O
  });
});
