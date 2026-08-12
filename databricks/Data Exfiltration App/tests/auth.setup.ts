import { test as setup } from '@playwright/test';
import { copyFileSync, existsSync, mkdirSync } from 'node:fs';

/**
 * Provisions per-role authenticated storage states for the deployed-app run
 * mode (docs/TEST-PLAN.md §0.2). Databricks sign-in is a federated OAuth flow
 * that cannot be scripted generically here, so this setup does NOT invent a
 * login. Instead, for each role it either:
 *   1. reuses an already-captured `.auth/<role>.json`, or
 *   2. copies one from DLP_<ROLE>_STORAGE if that path is provided, else
 *   3. fails with instructions to capture it once via codegen.
 *
 * Capture a state manually (one time per role):
 *   npx playwright codegen "$DLP_BASE_URL" --save-storage=.auth/analyst.json
 *   npx playwright codegen "$DLP_BASE_URL" --save-storage=.auth/steward.json
 */
const AUTH_DIR = '.auth';

function provision(role: 'analyst' | 'steward') {
  const dest = `${AUTH_DIR}/${role}.json`;
  if (existsSync(dest)) return;
  mkdirSync(AUTH_DIR, { recursive: true });

  const src = process.env[`DLP_${role.toUpperCase()}_STORAGE`];
  if (src && existsSync(src)) {
    copyFileSync(src, dest);
    return;
  }

  throw new Error(
    `Missing auth storage for "${role}". Provide DLP_${role.toUpperCase()}_STORAGE=<path> ` +
      `or capture it once:\n  npx playwright codegen "${process.env.DLP_BASE_URL}" --save-storage=${dest}`,
  );
}

setup('provision analyst auth', async () => {
  provision('analyst');
});

setup('provision steward auth', async () => {
  provision('steward');
});
