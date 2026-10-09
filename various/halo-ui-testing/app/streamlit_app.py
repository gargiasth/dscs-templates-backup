"""
app/streamlit_app.py  —  control panel for the Playwright UI-testing toolkit
===========================================================================
A local dashboard that orchestrates the Node tools in ../tools. Point it at
any website via App URL (saved to config.json). It reads the Excel backlog
and shells out to:

  * tools/generate-tests.js         build skeletons from the backlog
  * tools/record-case.js            record one case with codegen and splice it in
  * npx playwright test             run the tests
  * tools/update-backlog-status.js  write results back into the backlog

From the project folder (the one with package.json):

    pip install -r requirements.txt
    npm start
    # or: streamlit run app/streamlit_app.py

Notes for a secured VM:
  * Streamlit starts a local web server (default port 8501) — this may need
    sign-off.
  * Recording opens codegen in a SEPARATE browser window and needs an
    interactive desktop session. The app blocks while codegen is open; close
    the codegen window to continue.
  * Node must be on PATH (the app calls node / npx).
"""

import json
import os
import re
import shutil
import subprocess
import pandas as pd
import streamlit as st

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(APP_DIR)
TOOLS_DIR = os.path.join(PROJECT_DIR, "tools")
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")
DEFAULT_BACKLOG = os.path.join(PROJECT_DIR, "backlog", "playwright-test-backlog.xlsx")
DEFAULT_SHEET = "Test backlog"
EXEC_LOG = os.path.join(PROJECT_DIR, "test-executions.csv")
TESTS_DIR = os.path.join(PROJECT_DIR, "tests")
UI_FLAGS = {"web ui - good candidate", "web ui - needs sample images"}


def normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u


def url_ok(url: str) -> bool:
    return bool(re.match(r"^https?://[^/\s]+", url or "", re.I))


def load_saved_url() -> str:
    env = os.environ.get("APP_URL") or os.environ.get("HALO_URL")
    if env:
        return normalize_url(env)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return normalize_url(str(data.get("appUrl") or data.get("APP_URL") or ""))
        except (OSError, json.JSONDecodeError, TypeError):
            return ""
    return ""


def save_url(url: str) -> str:
    url = normalize_url(url)
    data = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    data["appUrl"] = url
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    return url


def _find(cols_lower, *prefixes):
    for p in prefixes:
        for lc, orig in cols_lower.items():
            if lc.startswith(p):
                return orig
    return None


def load_backlog(path: str, sheet: str):
    """Read the backlog sheet into a normalized DataFrame + the column map."""
    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl", dtype=str).fillna("")
    cols_lower = {c.lower(): c for c in df.columns}
    m = {
        "test_id": _find(cols_lower, "test id"),
        "code": _find(cols_lower, "indica code", "ref"),
        "product": _find(cols_lower, "product"),
        "area": _find(cols_lower, "area"),
        "testability": _find(cols_lower, "testability"),
        "priority": _find(cols_lower, "priority"),
        "desc": _find(cols_lower, "bug", "behaviour", "test case", "description"),
        "pre": _find(cols_lower, "precondition"),
        "steps": _find(cols_lower, "steps"),
        "exp": _find(cols_lower, "expected"),
        "status": _find(cols_lower, "status"),
    }
    out = pd.DataFrame()
    for key, orig in m.items():
        out[key] = df[orig] if orig else ""
    out["ui_candidate"] = out["testability"].str.lower().isin(UI_FLAGS)
    out["file"] = out["test_id"].map(lambda i: f"{i}.spec.js")
    out["skeleton"] = out["file"].apply(skeleton_state)
    return out, m


def skeleton_state(file: str) -> str:
    """missing | skeleton (not yet recorded) | recorded"""
    p = os.path.join(TESTS_DIR, file)
    if not os.path.exists(p):
        return "missing"
    try:
        src = open(p, encoding="utf-8").read()
    except OSError:
        return "missing"
    mt = re.search(r"// <<<CODEGEN>>>\n([\s\S]*?)\n\s*// <<<END CODEGEN>>>", src)
    body = (mt.group(1) if mt else "").strip()
    if not body or body.startswith("// TODO"):
        return "skeleton"
    return "recorded"


def load_results(csv_path: str):
    """Latest execution per Test ID from the run log."""
    if not os.path.exists(csv_path):
        return pd.DataFrame()
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    if df.empty:
        return df
    ts_col = next((c for c in df.columns if c.lower().startswith("run timestamp")), df.columns[0])
    id_col = next((c for c in df.columns if c.lower().startswith("test id")), None)
    if id_col is None:
        return df
    df = df.sort_values(ts_col)
    return df.groupby(id_col, as_index=False).last()


def which(exe: str) -> str:
    return shutil.which(exe) or exe


def run_cmd(args, timeout=None, extra_env=None):
    """Run a subprocess in the project dir; return (rc, combined_output)."""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    try:
        p = subprocess.run(
            args, cwd=PROJECT_DIR, capture_output=True, text=True, timeout=timeout, env=env
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError as e:
        return 127, f"Command not found: {args[0]} — is Node on PATH?\n{e}"
    except subprocess.TimeoutExpired:
        return 124, f"Timed out after {timeout}s."


def tool(name: str) -> str:
    return os.path.join(TOOLS_DIR, name)


def main():
    st.set_page_config(page_title="UI test control panel", layout="wide")
    ss = st.session_state
    ss.setdefault("out", {})
    if "app_url" not in ss:
        ss.app_url = load_saved_url()

    st.title("UI test control panel")
    st.caption("Point this at any website, then generate, record, and run UI tests from the Excel backlog.")

    with st.sidebar:
        st.header("Which website?")
        st.text_input(
            "App URL",
            key="app_url",
            placeholder="https://your-web-app.example/",
            help="Saved to config.json so Record, Run, and the terminal tools all use the same address.",
        )
        app_url = normalize_url(ss.app_url)
        save = st.button("Save URL")
        if save:
            if not url_ok(app_url):
                st.error("Enter a full address starting with http:// or https://")
            else:
                save_url(app_url)
                st.success(f"Saved. Testing {app_url}")
        elif url_ok(app_url) and app_url != load_saved_url():
            st.caption("URL changed — click Save URL, or it will be saved when you Record or Run.")
        elif url_ok(app_url):
            st.caption(f"Using {app_url}")
        st.caption("The GDC Portal address in config.json is only an example. Replace it with your own site.")
        with st.expander("Advanced"):
            backlog = st.text_input("Backlog file", value=DEFAULT_BACKLOG)
            sheet = st.text_input("Sheet name", value=DEFAULT_SHEET)
        st.caption(
            "Recording opens a separate browser window. Close that window when you finish the steps. "
            "This panel is local (port 8501)."
        )

    if not os.path.exists(backlog):
        st.error(f"Backlog not found: {backlog}")
        st.stop()

    try:
        df, _ = load_backlog(backlog, sheet)
    except Exception as e:  # noqa: BLE001
        st.error(f"Could not read the backlog: {e}")
        st.stop()

    extra_env = {"APP_URL": app_url, "HALO_URL": app_url, "BACKLOG": backlog}

    def persist_url():
        if not url_ok(app_url):
            st.error("Set App URL in the sidebar first (a full http:// or https:// address).")
            return False
        save_url(app_url)
        extra_env["APP_URL"] = app_url
        extra_env["HALO_URL"] = app_url
        return True

    tab_backlog, tab_record, tab_run = st.tabs(["Backlog", "Record", "Run & results"])

    with tab_backlog:
        c1, c2, c3 = st.columns(3)
        prio = c1.multiselect("Priority", sorted(x for x in df["priority"].unique() if x))
        test = c2.multiselect("Testability", sorted(x for x in df["testability"].unique() if x))
        stat = c3.multiselect("Status", sorted(x for x in df["status"].unique() if x))
        view = df.copy()
        if prio:
            view = view[view["priority"].isin(prio)]
        if test:
            view = view[view["testability"].isin(test)]
        if stat:
            view = view[view["status"].isin(stat)]
        st.write(f"{len(view)} of {len(df)} cases  ·  "
                 f"{(df['skeleton']=='recorded').sum()} recorded, "
                 f"{(df['skeleton']=='skeleton').sum()} skeleton-only, "
                 f"{(df['skeleton']=='missing').sum()} not generated")
        st.dataframe(
            view[["test_id", "area", "testability", "priority", "status", "skeleton", "desc"]],
            use_container_width=True, hide_index=True,
        )

    with tab_record:
        st.subheader("1 · Generate skeletons")
        st.caption("Creates a starter file in tests/ for each UI case. Already-recorded files are left alone.")
        if st.button("Generate / refresh skeletons from backlog"):
            with st.spinner("Generating from the backlog…"):
                rc, out = run_cmd([which("node"), tool("generate-tests.js"), backlog], timeout=120, extra_env=extra_env)
            ss.out["gen"] = out
            (st.success if rc == 0 else st.error)(f"generate-tests.js exited {rc}")
        if ss.out.get("gen"):
            st.code(ss.out["gen"])

        st.divider()
        st.subheader("2 · Record a case")
        ui = df[df["ui_candidate"]]
        if ui.empty:
            st.info("No UI-candidate cases in this backlog.")
        else:
            labels = {f"{r.test_id} — {r.desc[:70]}": r.test_id for r in ui.itertuples()}
            pick = st.selectbox("Test case", list(labels.keys()))
            row = df[df["test_id"] == labels[pick]].iloc[0]
            st.markdown(f"**Precondition:** {row['pre'] or '_not filled_'}")
            st.markdown(f"**Steps:** {row['steps'] or '_not filled_'}")
            st.markdown(f"**Expected:** {row['exp'] or '_not filled_'}")
            st.caption(f"Writes to tests/{row['file']}  ·  current: {row['skeleton']}")
            if st.button("Record this case", type="primary"):
                if not persist_url():
                    pass
                elif row["skeleton"] == "missing":
                    st.warning("No skeleton yet — click 'Generate skeletons' above first.")
                else:
                    st.info("A recorder window is opening. Perform the steps, then close it to continue.")
                    with st.spinner("Recording — waiting for the recorder window to close…"):
                        rc, out = run_cmd(
                            [which("node"), tool("record-case.js"), row["test_id"], "--backlog", backlog, "--url", app_url],
                            extra_env=extra_env,
                        )
                    ss.out["rec"] = out
                    (st.success if rc == 0 else st.error)(out.strip() or f"record-case.js exited {rc}")

    with tab_run:
        st.subheader("Run tests")
        recorded_files = df[df["skeleton"] == "recorded"]["file"].tolist()
        colr1, colr2 = st.columns([1, 2])
        run_all = colr1.button("Run all tests", type="primary")
        sel = colr2.multiselect("…or run selected spec files", recorded_files)
        run_sel = colr2.button("Run selected") if sel else False

        if run_all or run_sel:
            if not persist_url():
                pass
            else:
                cmd = [which("npx"), "playwright", "test"]
                if run_sel:
                    cmd += [os.path.join("tests", f) for f in sel]
                with st.spinner("Running Playwright…"):
                    rc, out = run_cmd(cmd, timeout=3600, extra_env=extra_env)
                ss.out["run"] = out
                with st.spinner("Writing results back into the backlog…"):
                    rc2, out2 = run_cmd([which("node"), tool("update-backlog-status.js"), backlog], timeout=120, extra_env=extra_env)
                ss.out["upd"] = out2
                st.success("Run complete.") if rc == 0 else st.warning(f"Playwright exited {rc} (failures are normal here).")

        if ss.out.get("run"):
            with st.expander("Playwright output", expanded=False):
                st.code(ss.out["run"])
        if ss.out.get("upd"):
            st.caption(ss.out["upd"].strip())

        st.divider()
        st.subheader("Latest results")
        res = load_results(EXEC_LOG)
        if res.empty:
            st.info("No runs yet. Results appear here after the first run.")
        else:
            status_col = next((c for c in res.columns if c.lower() == "status"), None)
            if status_col:
                counts = res[status_col].str.lower().value_counts()
                m1, m2, m3 = st.columns(3)
                m1.metric("Passed", int(counts.get("passed", 0)))
                m2.metric("Failed", int(counts.get("failed", 0)) + int(counts.get("timedout", 0)))
                m3.metric("Skipped", int(counts.get("skipped", 0)))
            st.dataframe(res, use_container_width=True, hide_index=True)
            if st.button("Open HTML report"):
                subprocess.Popen([which("npx"), "playwright", "show-report"], cwd=PROJECT_DIR)
                st.caption("Opening the Playwright HTML report in your browser…")


if __name__ == "__main__":
    main()
