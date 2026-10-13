# HALO UI testing

A Playwright toolkit for UI regression tests, driven from an Excel backlog. Point it at **any web app** by setting App URL (`config.json` → `appUrl`, or the control-panel sidebar). The GDC Data Portal value and `GDC-*` cases shipped in this folder are an example only.

**If you are learning this toolkit, start at [`START-HERE.md`](START-HERE.md).** This file is the technical overview.

A printable runbook and a one-page briefing live in `docs/`.

## What's in the folder

| Path | What it is |
|---|---|
| `START-HERE.md` | Daily path for a non-technical operator / learner |
| `config.json` | **Which website to test** (`appUrl`). The control panel Save URL button writes this file |
| `config.example.json` | Template if you want a clean `config.json` |
| `app/streamlit_app.py` | Control panel: generate, record, run, write results back |
| `backlog/playwright-test-backlog.xlsx` | Test-case store. The `Test backlog` sheet is the source of truth |
| `backlog/halo.xlsx` | Extra workbook (not read by the tools) |
| `tests/` | One Playwright spec per UI-testable row. Recorded clicks live here |
| `tools/app-config.js` | Reads/writes `config.json`; also honors `APP_URL` / `HALO_URL` |
| `tools/read-backlog.js` | Shared Excel reader used by the other tools |
| `tools/generate-tests.js` | Writes skeleton `.spec.js` files into `tests/` |
| `tools/record-case.js` | Records one case with codegen and splices it into its skeleton |
| `tools/codegen-launcher.js` | Optional local dropdown UI for recording (port 5599) |
| `tools/backlog-reporter.js` | Playwright reporter — appends each run to `test-executions.csv` |
| `tools/update-backlog-status.js` | Writes latest pass/fail back into the Excel Status column |
| `playwright.config.js` | Browser project, base URL, trace capture, reporter wiring |
| `docs/learning-path.md` | Maps each action to a development concept |
| `docs/glossary.md` | Plain-language definitions |
| `docs/how-it-works.md` | Design notes |

## Prerequisites

- Node.js LTS (18+). On a secured machine, IT may need to install it and confirm the npm registry is reachable.
- Python 3 with pip (for the control panel).
- One-time install:

  ```bash
  npm run setup                 # npm install + Playwright Chromium
  pip install -r requirements.txt
  ```

## Daily workflow (control panel)

```bash
npm start                       # streamlit run app/streamlit_app.py
```

Set the app address in the sidebar (**App URL** → Save URL). That writes `config.json`. Then use the **Record** and **Run & results** tabs.

## Terminal equivalents

The URL is read from `config.json` (`appUrl`). You can override it per session:

```bash
# Windows:  set APP_URL=https://your-web-app.example/
# bash:     export APP_URL=https://your-web-app.example/
```

(`HALO_URL` is still accepted as an older name for the same setting.)

**1. Generate skeletons from the backlog**

```bash
npm run generate                # node tools/generate-tests.js
```

One skeleton per UI-testable row lands in `tests/`. Backend and desktop-client rows are skipped. Already-recorded specs are left alone unless you pass `--force`.

**2. Record with codegen (supplies the selectors)**

Prefer the Streamlit **Record** tab. From the terminal, one case:

```bash
node tools/record-case.js GDC-001 --url "$APP_URL"
```

Optional dropdown UI (advanced; not needed if Streamlit is running):

```bash
npm run record-ui               # then open http://127.0.0.1:5599
```

Codegen records clicks only — it does **not** write the pass/fail check.

**3. Write the assertion, then run**

Replace each skeleton's placeholder assertion with a real check of the Expected result, then:

```bash
npm test                        # npx playwright test
npm run report                  # npx playwright show-report
npm run update-status           # write Status back into the backlog
```

Close the workbook in Excel before `update-status`; Excel locks the file while it is open.

## Where results go

- `test-executions.csv` — appended once per run: Test ID, area, pass/fail, duration, first error line, and the path to that run's trace.
- `playwright-report/` — the browsable HTML report with per-step screenshots.
- `test-results/` — per-test artifacts including `trace.zip` (`npx playwright show-trace`).

## Design notes

See `docs/how-it-works.md`. Short version: the Excel backlog is the test-**case** store; `test-executions.csv` is the execution history; the Test ID (e.g. `GDC-001`) is the spine that ties them together.

## Secured-environment notes

- Streamlit (and the optional codegen launcher) start a localhost-only web server. On a hardened VM this may need sign-off.
- Codegen opens a real browser window, so it needs an interactive desktop session — schedule any automated runs "at log on", not "at startup".
- `playwright.config.js` sets `ignoreHTTPSErrors: true` for internal self-signed certificates.
