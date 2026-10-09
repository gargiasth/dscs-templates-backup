# Start here

This folder runs automated clicks against **any website you choose** and records whether each check passed. You work in **Excel** and a **control panel** in your browser. You do not need to write code to record a case.

The GDC Data Portal URL and backlog shipped with this folder are only an **example**. Swap the URL (and later the Excel rows) for the app you actually test.

## One-time setup

### Install Node.js and Python (if you do not have them yet)

You need **Node.js** (this project's tests) and **Python 3** (the control panel). Installers on the official sites detect Windows, macOS, or Linux for you — pick the default / LTS download.

1. See whether they are already installed. Open a terminal (Command Prompt or PowerShell on Windows; Terminal on macOS or Linux) and run:

   ```bash
   node -v
   npm -v
   python3 --version
   ```

   On Windows, if `python3` is not recognized, try `python --version` or `py --version`.

   You want Node **18 or newer** and Python **3.10 or newer**. If both commands print a version, skip to [Install this project's tools](#install-this-projects-tools).

2. **Node.js:** go to [https://nodejs.org](https://nodejs.org) and download the **LTS** installer. Run it and accept the defaults (on Windows, leave npm included).

3. **Python:** go to [https://www.python.org/downloads](https://www.python.org/downloads/) and download the latest **Python 3** installer.
   - Windows: check **Add python.exe to PATH** before you click Install.
   - macOS / Linux: accept the defaults. If the site offers a package for your OS, use that.

4. **Close the terminal completely and open a new one**, then run the version commands from step 1 again. A new window is required so it can see the programs you just installed.

On a locked-down work machine, IT may need to install these and confirm that `npm` and `pip` can reach the internet.

### Install this project's tools

In a terminal opened **at this folder**:

```bash
npm run setup
pip install -r requirements.txt
```

If `pip` is not recognized, try `pip3 install -r requirements.txt` or `python3 -m pip install -r requirements.txt` (Windows: `py -m pip install -r requirements.txt`).

## Every day

1. Open the control panel:

   ```bash
   npm start
   ```

   A browser tab should open (usually http://localhost:8501). If it does not, copy that address into your browser.

2. In the sidebar, paste **App URL** — the website you are testing, including `https://`. Click **Save URL**.
   (You can also edit `config.json` → `appUrl`. Same field.)
3. Open the **Record** tab → **Generate / refresh skeletons from backlog**.
4. Pick one test case, follow the listed steps in the recorder window, then **close that window**.
5. Open **Run & results** → **Run all tests** (or run the one you just recorded).
6. Open the HTML report from that same tab to see screenshots of what happened.

Recording captures clicks. It does **not** write the pass/fail check. For that last line, pair with a colleague — see `docs/learning-path.md`.

If you change App URL away from the example GDC Portal, record new cases against *your* site. The sample `GDC-*` tests were recorded on the example site and will not match a different app.

## What you edit

| You want to… | Open this |
|---|---|
| Set which website to test | control panel **App URL**, or `config.json` |
| Add or change a test case | `backlog/playwright-test-backlog.xlsx` (sheet **Test backlog**) |
| Generate / record / run | the control panel (`npm start`) |
| See the clicks you recorded | a file in `tests/` |

Leave `tools/` and `node_modules/` alone until you are curious. `docs/glossary.md` explains the words used here.
