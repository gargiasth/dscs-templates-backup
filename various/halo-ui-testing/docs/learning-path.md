# Learning path

Use this after you have completed the steps in `START-HERE.md`. Each block is something you already did, named in developer language.

## Week 1 — run the loop

You opened a folder, ran `npm start`, generated files, recorded clicks, and ran tests.

| You did this | The development word |
|---|---|
| Opened this project folder | **repository** (a project saved as files) |
| Typed `npm start` | **command** / **script** (an instruction the computer runs) |
| Pasted App URL and saved it | **configuration** — a setting the rest of the tools read (`config.json`) |
| Used the control panel in the browser | **user interface (UI)** — here, a small local **app** |
| Clicked Generate | **code generation** — a program wrote starter files for you |
| Clicked through the site in the recorder | **browser automation** — Playwright is driving the browser |
| Saw pass or fail | **test result** |

The control panel is Python (`app/streamlit_app.py`). The tests themselves are JavaScript (`tests/*.spec.js`). You only need the panel at this stage.

## Week 2 — the backlog is data

Open `backlog/playwright-test-backlog.xlsx`. Each row is one test case: an ID, steps, and what “good” looks like.

| You did this | The development word |
|---|---|
| Edited a row in Excel | **structured data** (same columns every time) |
| Kept Test ID unique (`GDC-001`) | **primary key** — the ID that other files refer to |
| Generated again after an edit | **source of truth** — Excel is canonical; `tests/` is produced from it |

Add or clarify **Precondition**, **Steps**, and **Expected** on one row, then generate. If that case was already recorded, the tools leave the recording in place.

## Week 3 — read a recorded test

Open a file in `tests/` that you recorded. You should be able to match each click you made to a line such as `await page.getByRole(...).click()`.

| In the file | Meaning |
|---|---|
| `test('GDC-001 …', …)` | “Here is one check to run.” |
| `await page.goto('/')` | Open the App URL from `config.json`. |
| `await page.getBy…().click()` | Find something on the page and click it. |
| `expect(…).toBeVisible()` | **Assertion** — the pass/fail check. |

Recording fills in the clicks. It does not write a real assertion. That last line is the one to pair on: replace `expect(true).toBeTruthy()` with a check of the Expected result from Excel.

## Week 4 — save history with git

When this folder is its own git repository (ask a colleague if you are unsure):

```bash
git status          # what changed
git diff            # the actual edits
git add tests/GDC-001.spec.js
git commit -m "Record GDC-001 logo click"
```

| You did this | The development word |
|---|---|
| `git status` | See unsaved-to-history changes |
| `git commit` | Snapshot of this work, with a short message |

Recorded tests belong in git. Generated-but-empty skeletons are less important; recordings are the work.

## When you are curious

`tools/` is the engine. `docs/how-it-works.md` explains how Excel, codegen, and the reporter fit together. You do not need it to record or run cases.
