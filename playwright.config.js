// Tests gegen site/ (vorher: make web). Mobiler Viewport, simulierte Geolocation.
const { defineConfig, devices } = require("@playwright/test");
module.exports = defineConfig({
  testDir: "tests",
  timeout: 90_000,
  use: { ...devices["Pixel 7"], launchOptions: process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {}, baseURL: "http://127.0.0.1:8123", serviceWorkers: "allow" },
  webServer: { command: "python3 -m http.server 8123 --bind 127.0.0.1 -d site 2>/dev/null", url: "http://127.0.0.1:8123/index.json", reuseExistingServer: true },
});
