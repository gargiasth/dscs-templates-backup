# How it works

Technical design notes. Daily use is `START-HERE.md` and the Streamlit control panel.

## Which website is tested

`config.json` → `appUrl` is the address Playwright opens. The control panel **Save URL** button writes that field. `APP_URL` (or the older `HALO_URL`) overrides the file. Specs call `page.goto('/')` so they pick up whatever base URL is configured — they do not hardcode a product.

The GDC Portal value shipped in `config.json` is an example so the sample backlog can run. Point `appUrl` at your own site before recording cases for that site.

## Cases vs executions

The Excel backlog is the test-**case** store. `tools/backlog-reporter.js` never writes to it — that keeps formatting intact and mirrors how a test-management system separates cases from executions. Results accumulate in `test-executions.csv`. After a run, `tools/update-backlog-status.js` copies the *latest* result per Test ID into the sheet’s Status column (close Excel first; it locks the file).

## The Test ID is the spine

A row’s Test ID (for example `GDC-001` or `UI-005`) flows from the backlog into the generated spec’s title. The reporter reads that ID back to map each result to its case. To move off Excel later (for example to Kiwi TCMS), swap the CSV append in `backlog-reporter.js` for an API call — nothing else has to change.

## Generate → record → assert → run

1. `generate-tests.js` writes one skeleton per UI-testable row (`web ui - good candidate` or `web ui - needs sample images`). Recorded specs are skipped unless `--force` is passed.
2. `record-case.js` launches Playwright codegen, then splices the recorded body between `<<<CODEGEN>>>` markers. The Streamlit panel calls this per case. `codegen-launcher.js` is the same idea with a small local dropdown on port 5599; it is optional.
3. Codegen cannot be modified, and it does not write assertions. Someone who knows the app replaces the placeholder `expect(true)` with a real check of the Expected result.
4. `npx playwright test` runs the specs. The HTML reporter, traces, and `test-executions.csv` are the evidence trail.

## Two languages on purpose

The control panel is Python so a non-developer can click Generate / Record / Run. The tests are JavaScript because that is what Playwright specs are. The panel does not re-implement the Node tools; it runs them.

## Secured environments

Streamlit (port 8501) and the optional codegen launcher (port 5599) bind to localhost only. A hardened VM may still need sign-off for a new listening service. Codegen needs an interactive desktop session.
