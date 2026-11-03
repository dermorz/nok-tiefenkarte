const { test, expect } = require("@playwright/test");
const fs = require("fs");

const index = JSON.parse(fs.readFileSync("site/index.json", "utf8"));
const S = index.sections.find((s) => s.id.includes("NOK-74-76")) || index.sections[0];
const centroid = (s) => ({ latitude: s.poly.reduce((a, p) => a + p[0], 0) / 4, longitude: s.poly.reduce((a, p) => a + p[1], 0) / 4 });
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
    const before = await center(page);
    const C = offset(A, -120, -90);
    await context.setGeolocation(C);
    await page.waitForTimeout(1500);
    expect(await dist(page, await center(page), before)).toBeLessThan(0.5);   // folgt nicht mehr
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
    await expect(page.locator("#where")).toContainText(/Nächster Abschnitt: .* · [\d.,]+ k?m$/);
  });

  test("Messen von der eigenen Position: Entfernung zum Ziel", async ({ page }) => {
    await open(page);
    await page.tap("#btn-follow");                                     // Karte folgt der Position (Blattmitte)
    await expect.poll(() => page.evaluate(() => !!app.pos)).toBe(true);
    await page.evaluate(() => app.map.setZoom(17));
    await page.tap("#btn-measure");
    await expect(page.locator("#readout")).toContainText("Ziel antippen");
    const T = offset(centroid(S), 60, 80);                               // 100 m entfernt
    await tapAt(page, T.latitude, T.longitude);
    const shown = Number(await page.locator("#readout [data-dist]").getAttribute("data-dist"));
    expect(Math.abs(shown - 100)).toBeLessThan(1.5);                     // Tipp trifft auf ±1 px genau
    await expect(page.locator("#readout")).not.toContainText("Tiefe");
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
    const C = centroid(S);
    await page.evaluate(([lat, lng]) => app.map.setView([lat, lng], 18), [C.latitude, C.longitude]);
    await expect.poll(() => page.locator(".chart-tiles img.leaflet-tile-loaded").count()).toBeGreaterThan(4);
    const broken = await page.evaluate(() => [...document.querySelectorAll(".chart-tiles img.leaflet-tile-loaded")]
      .filter((i) => i.src.includes("/tiles/") && !i.naturalWidth).length);
    expect(broken).toBe(0);                                              // Kacheln kommen aus dem Cache
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
  test("Info zeigt die einheitliche Tiefenlegende", async ({ page }) => {
    await open(page);
    await page.tap("#btn-info");
    const items = page.locator("#legend li");
    await expect(items).toHaveCount(18);
    await expect(items.first()).toHaveText("< 0 m");
    await expect(items.nth(11)).toHaveText("10–11 m");
    await expect(items.last()).toHaveText("> 16 m");
  });
});
