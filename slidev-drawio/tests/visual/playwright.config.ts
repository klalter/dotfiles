import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  timeout: 45000,
  retries: process.env.CI ? 2 : 0,
  reporter: [['list'], ['html', { outputFolder: '../../playwright-report', open: 'never' }]],
  use: {
    headless: true,
    viewport: { width: 1280, height: 720 },
    screenshot: 'only-on-failure',
    // The Slidev example server — start with: cd example && npm run dev
    baseURL: process.env.SLIDEV_URL || 'http://localhost:3030',
    // Chromium executable path (set for CI environments with pre-installed browsers)
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : {}),
  },
  // Snapshot directory for baseline screenshots
  snapshotDir: './snapshots',
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // Override executable path for CI/embedded environments
        ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
          ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
          : {}),
      },
    },
  ],
  // Optionally launch the Slidev dev server before running tests
  // Uncomment if you want auto-start:
  // webServer: {
  //   command: 'cd ../../example && npm run dev',
  //   url: 'http://localhost:3030',
  //   timeout: 120000,
  //   reuseExistingServer: !process.env.CI,
  // },
})
