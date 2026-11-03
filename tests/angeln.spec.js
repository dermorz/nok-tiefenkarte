const { test, expect } = require("@playwright/test");

// Farben je Uferabschnitt an einem Prüfdatum (?datum=...), ausgewertet mit der App-Logik
async function statuses(page, datum, sheet) {
  await page.addInitScript(() => localStorage.setItem("disclaimer", "true"));
  await page.goto(`/?datum=${datum}`);
  await page.waitForFunction(() => window.app?.map);
  if (await page.locator("#btn-angel").getAttribute("aria-pressed") !== "true") await page.tap("#btn-angel");
  await expect(page.locator("#angel-note")).toBeVisible();
  return page.evaluate(async (sheet) => {
    const gj = await (await fetch(`ufer/${sheet}.geojson`)).json();
    return gj.features.map((f) => ({ ...f.properties, st: shoreStatus(f.properties, today()) }));
  }, sheet);
}
const at = (fs, ufer, km) => fs.find((f) => f.ufer === ufer && Math.min(...f.km) <= km && km <= Math.max(...f.km));

test("Sehestedt: Fähre rot, westlich in der Zanderschonzeit orange, sonst grün", async ({ page }) => {
  let fs = await statuses(page, "2027-04-15", "20250703-NOK-74-76_p7");
  for (const u of ["Nord", "Süd"]) {
    expect(at(fs, u, 75.33).st).toBe("rot");      // Fähranleger ± 50 m
    expect(at(fs, u, 75.0).st).toBe("orange");    // Kunstköderverbot westlich km 75,3
    expect(at(fs, u, 76.0).st).toBe("gruen");
  }
  fs = await statuses(page, "2027-07-01", "20250703-NOK-74-76_p7");
  expect(at(fs, "Nord", 75.0).st).toBe("gruen");
  expect(at(fs, "Nord", 75.33).st).toBe("rot");
});

test("Borgstedter See: Nordufer östlich A7 und Südufer östlich der westlichen Leitung rot", async ({ page }) => {
  const fs = await statuses(page, "2027-07-01", "20250703-Borgstedter-See_p7");
  expect(at(fs, "Nord", 1.0).st).toBe("rot");
  expect(at(fs, "Nord", 2.5).st).toBe("gruen");    // westlich der Rader Hochbrücke (km 2,12)
  expect(at(fs, "Süd", 1.0).st).toBe("rot");
  expect(at(fs, "Süd", 1.8).st).toBe("gruen");     // westlich der Leitung (km 1,57)
});

test("Antippen einer Uferlinie zeigt Regeltext und Stand", async ({ page }) => {
  await statuses(page, "2027-04-15", "20250703-NOK-74-76_p7");
  await page.evaluate(() => app.map.setView([54.3645, 9.8193], 18));
  await expect.poll(() => page.locator("path.leaflet-interactive").count()).toBeGreaterThan(3);
  await page.evaluate(() => app.shoreGroup.eachLayer((g) => g.eachLayer((l) => {
    if (l.feature.properties.rules.includes("anleger_faehren") && !window._tapped) { window._tapped = 1; l.fire("click", { latlng: l.getLatLngs()[0] }); }
  })));
  await expect(page.locator("#readout")).toContainText("Ausgenommen");
  await expect(page.locator("#readout")).toContainText("Fähranlagen");
  await expect(page.locator("#readout")).toContainText("Stand Jahresschein Mitglieder LAV-SH, 2026-11");
});
