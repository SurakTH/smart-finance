import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  retries: 0,
  reporter: "list",
  outputDir: "../artifacts/browser-tests",
  use: {
    baseURL: process.env.SF_BASE_URL || "http://localhost:8080",
    trace: "off",
    video: "off",
    screenshot: "off",
    launchOptions: process.env.SF_CHROME_PATH
      ? { executablePath: process.env.SF_CHROME_PATH }
      : {},
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1000 },
      },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 7"], defaultBrowserType: "chromium" },
    },
  ],
});
