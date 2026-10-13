const { defineConfig, devices } = require('@playwright/test');
const { requireAppUrl } = require('./tools/app-config');

const appUrl = requireAppUrl();

module.exports = defineConfig({
  testDir: './tests',

  // list = console output; html = browsable report; backlog-reporter = writes
  // executions back against the Excel backlog by Test ID.
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
    ['./tools/backlog-reporter.js'],
  ],

  use: {
    baseURL: appUrl,
    trace: 'on',                 // full trace every run — the per-case evidence trail
    screenshot: 'only-on-failure',
    ignoreHTTPSErrors: true,     // self-signed certs are common on internal deployments
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    // add when you need cross-engine coverage:
    // { name: 'webkit',  use: { ...devices['Desktop Safari'] } },
    // { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
  ],
});
