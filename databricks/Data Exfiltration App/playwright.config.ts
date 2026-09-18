import { defineConfig, devices } from '@playwright/test';

// Two run modes (see docs/TEST-PLAN.md §0.1):
//   * Deployed, per-user auth  — set DLP_BASE_URL to the deployed app URL. Role
//     projects (analyst/steward) use captured storageState and the setup project
//     provisions it. No dev webServer is started.
//   * Local dev (default)      — no DLP_BASE_URL; `npm run dev` is started and a
//     single ambient identity is used. Only role-agnostic suites (smoke) are
//     meaningful; role-sensitive specs skip themselves.
const PORT = process.env.DATABRICKS_APP_PORT || process.env.PORT || 8000;
const baseURL = process.env.DLP_BASE_URL || `http://localhost:${PORT}`;
const deployed = !!process.env.DLP_BASE_URL;

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  expect: {
    timeout: 15_000,
  },
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: deployed
    ? [
        { name: 'setup', testMatch: /auth\.setup\.ts/ },
        {
          name: 'analyst',
          dependencies: ['setup'],
          use: { ...devices['Desktop Chrome'], storageState: '.auth/analyst.json' },
        },
        {
          name: 'steward',
          dependencies: ['setup'],
          use: { ...devices['Desktop Chrome'], storageState: '.auth/steward.json' },
        },
      ]
    : [{ name: 'analyst', use: { ...devices['Desktop Chrome'] } }],
  webServer: deployed
    ? undefined
    : {
        command: 'npm run dev',
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120 * 1000,
      },
});
