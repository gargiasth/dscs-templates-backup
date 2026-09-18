/*
 * app-config.js  —  which website to test
 * ---------------------------------------
 * Resolution order:
 *   1) an explicit URL (CLI --url)
 *   2) APP_URL environment variable
 *   3) HALO_URL environment variable (older name, still accepted)
 *   4) config.json → appUrl
 *
 * There is no hardcoded product URL. If nothing is set, callers should error
 * and point the operator at the control panel or config.json.
 */

const fs = require('fs');
const path = require('path');

const PROJECT_ROOT = path.join(__dirname, '..');
const CONFIG_PATH = path.join(PROJECT_ROOT, 'config.json');

function normalizeUrl(url) {
  let u = String(url == null ? '' : url).trim();
  if (!u) return '';
  if (!/^https?:\/\//i.test(u)) u = 'https://' + u;
  return u;
}

function isValidUrl(url) {
  return /^https?:\/\/[^/\s]+/i.test(url || '');
}

function readFileConfig() {
  try {
    const raw = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    return normalizeUrl(raw.appUrl || raw.APP_URL || '');
  } catch {
    return '';
  }
}

function getAppUrl(explicit) {
  const fromArg = normalizeUrl(explicit);
  if (fromArg) return fromArg;
  const fromEnv = normalizeUrl(process.env.APP_URL || process.env.HALO_URL || '');
  if (fromEnv) return fromEnv;
  return readFileConfig();
}

function missingUrlMessage() {
  return 'No web app URL set. Paste it in the control panel (App URL), or set "appUrl" in config.json, or set the APP_URL environment variable. See START-HERE.md.';
}

function requireAppUrl(explicit) {
  const url = getAppUrl(explicit);
  if (!isValidUrl(url)) throw new Error(missingUrlMessage());
  return url;
}

function saveAppUrl(url) {
  const appUrl = normalizeUrl(url);
  if (!isValidUrl(appUrl)) throw new Error(missingUrlMessage());
  let existing = {};
  try { existing = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); } catch { existing = {}; }
  if (typeof existing !== 'object' || existing === null || Array.isArray(existing)) existing = {};
  existing.appUrl = appUrl;
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(existing, null, 2) + '\n');
  return appUrl;
}

module.exports = {
  PROJECT_ROOT,
  CONFIG_PATH,
  normalizeUrl,
  isValidUrl,
  getAppUrl,
  requireAppUrl,
  saveAppUrl,
  missingUrlMessage,
};
