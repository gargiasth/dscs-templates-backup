"""
Orion Launchpad — ETL-CMS Intake (Databricks POC)

Sections:
  1. File Upload
  2. Language Detection
  3. Unity Catalog Configuration
  4. Medallion Layers (Bronze / Silver / Gold)
"""

import io
import re
import zipfile
from datetime import date

import streamlit as st
import yaml


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", text.strip().lower()).strip("-") or "unnamed"


EXT_TO_LANGUAGE = {
    ".py":    "Python",
    ".r":     "R",
    ".R":     "R",
    ".scala": "Scala",
    ".sql":   "SQL",
    ".ipynb": "Python",
}

VERSION_OPTIONS = {
    "Python": ["3.9", "3.10", "3.11", "3.12"],
    "R":      ["4.2", "4.3", "4.4"],
    "SQL":    ["Spark SQL"],
    "Scala":  ["2.12", "2.13"],
}


def detect_languages(filenames: list) -> dict:
    detected = {}
    for name in filenames:
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        lang = EXT_TO_LANGUAGE.get(ext) or EXT_TO_LANGUAGE.get(ext.lower())
        if lang:
            detected[lang] = True
    return detected


def parse_table_names(sql_bytes: bytes) -> list:
    text = sql_bytes.decode("utf-8", errors="ignore")
    return re.findall(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\"\w.]+)", text, re.IGNORECASE)


def init_state():
    if "src_files" not in st.session_state:
        st.session_state.src_files = {}
    if "src_zip_map" not in st.session_state:
        st.session_state.src_zip_map = {}  # flat filename -> zip it came from
    if "preview_file" not in st.session_state:
        st.session_state.preview_file = None
    if "sql_files" not in st.session_state:
        st.session_state.sql_files = {}
    if "detected_languages" not in st.session_state:
        st.session_state.detected_languages = {}
    if "language_versions" not in st.session_state:
        st.session_state.language_versions = {}
    if "gold_tables" not in st.session_state:
        st.session_state.gold_tables = []
    if "bronze_data_files" not in st.session_state:
        st.session_state.bronze_data_files = {}


def file_uploader_section(label, key, types, store, parse_fn=None):
    uploaded = st.file_uploader(label, type=types, accept_multiple_files=True, key=key)
    newly_added = []
    if uploaded:
        for f in uploaded:
            if f.name.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(f.read())) as zf:
                    for name in zf.namelist():
                        if not name.endswith("/"):
                            flat = name.split("/")[-1]
                            if flat and flat not in store:
                                store[flat] = zf.read(name)
                                newly_added.append(flat)
            else:
                if f.name not in store:
                    store[f.name] = f.read()
                    newly_added.append(f.name)
        if parse_fn and newly_added:
            for name in newly_added:
                parse_fn(name, store[name])
    return newly_added


def build_zip(yaml_str: str, project: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{project}/orion.yaml", yaml_str)
        for filename, content in st.session_state.src_files.items():
            zf.writestr(f"{project}/src/{filename}", content)
        for filename, content in st.session_state.sql_files.items():
            zf.writestr(f"{project}/sql/{filename}", content)
        for filename, content in st.session_state.bronze_data_files.items():
            zf.writestr(f"{project}/data/bronze/{filename}", content)
    buf.seek(0)
    return buf.read()


def render():
    init_state()

    st.markdown("""
<style>
.block-container { padding-left: 2rem !important; padding-right: 2rem !important; max-width: 100% !important; }
</style>
""", unsafe_allow_html=True)

    st.title("Orion Launchpad")
    st.caption("ETL-CMS pipeline intake — Databricks POC")

    # ── Project name ─────────────────────────────────────────────────────
    project_name = st.text_input(
        "Project name *",
        placeholder="e.g. etl-cms-ohdsi",
    )
    # subfolder fallbacks — default to layer name if left blank
    bronze_manual_sub = (bronze_manual_subfolder or "bronze").strip()
    bronze_script_sub = (bronze_script_subfolder or "bronze").strip()
    silver_sub        = (silver_subfolder or "silver").strip()

    project_slug = slug(project_name) if project_name else "unnamed"

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 1 — File Upload
    # ══════════════════════════════════════════════════════════════════════
    st.subheader("1. Source files *")
    st.caption("Upload your pipeline scripts (.py, .ipynb) or zip your src/ folder.")

    def on_src_added(name, content):
        st.session_state.detected_languages.update(detect_languages([name]))

    uploaded = st.file_uploader(
        "Upload scripts or zip your src/ folder",
        type=["py", "ipynb", "r", "scala", "sql", "zip"],
        accept_multiple_files=True,
        key="src_upload",
    )

    # track which zip filenames are currently in the uploader widget
    current_uploaded_zips = {f.name for f in (uploaded or []) if f.name.endswith(".zip")}
    current_uploaded_plain = {f.name for f in (uploaded or []) if not f.name.endswith(".zip")}

    # remove files from a zip that was removed from the uploader
    previously_seen_zips = set(st.session_state.src_zip_map.values())
    for removed_zip in previously_seen_zips - current_uploaded_zips:
        to_remove = [k for k, v in st.session_state.src_zip_map.items() if v == removed_zip]
        for f in to_remove:
            st.session_state.src_files.pop(f, None)
            st.session_state.src_zip_map.pop(f, None)
        st.session_state.detected_languages = detect_languages(list(st.session_state.src_files.keys()))

    # remove plain files removed from the uploader
    tracked_plain = {k for k in st.session_state.src_files if k not in st.session_state.src_zip_map}
    for removed_plain in tracked_plain - current_uploaded_plain:
        st.session_state.src_files.pop(removed_plain, None)
        st.session_state.detected_languages = detect_languages(list(st.session_state.src_files.keys()))

    # add newly uploaded files
    if uploaded:
        newly_added = []
        for f in uploaded:
            if f.name.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(f.read())) as zf:
                    for name in zf.namelist():
                        if not name.endswith("/"):
                            flat = name.split("/")[-1]
                            if flat and flat not in st.session_state.src_files:
                                st.session_state.src_files[flat] = zf.read(name)
                                st.session_state.src_zip_map[flat] = f.name
                                newly_added.append(flat)
            else:
                if f.name not in st.session_state.src_files:
                    st.session_state.src_files[f.name] = f.read()
                    newly_added.append(f.name)
        for name in newly_added:
            on_src_added(name, st.session_state.src_files[name])

    if st.session_state.src_files:
        st.caption(f"{len(st.session_state.src_files)} file(s) staged for src/")
        preview = st.session_state.get("preview_file")
        col_files, col_preview = st.columns([1, 2])

        with col_files:
            with st.container(height=300, border=True):
                for filename in list(st.session_state.src_files.keys()):
                    c1, c2, c3 = st.columns([6, 1, 1])
                    with c1:
                        st.caption(filename)
                    with c2:
                        if st.button("Preview", key=f"prev_{filename}"):
                            st.session_state.preview_file = filename
                            st.rerun()
                    with c3:
                        if st.button("✕", key=f"rm_src_{filename}"):
                            zip_origin = st.session_state.src_zip_map.get(filename)
                            if zip_origin:
                                to_remove = [k for k, v in st.session_state.src_zip_map.items() if v == zip_origin]
                                for f in to_remove:
                                    st.session_state.src_files.pop(f, None)
                                    st.session_state.src_zip_map.pop(f, None)
                            else:
                                del st.session_state.src_files[filename]
                            if st.session_state.preview_file == filename:
                                st.session_state.preview_file = None
                            st.session_state.detected_languages = detect_languages(
                                list(st.session_state.src_files.keys())
                            )
                            st.rerun()

        with col_preview:
            with st.container(height=300, border=True):
                if preview and preview in st.session_state.src_files:
                    pc1, pc2 = st.columns([5, 1])
                    with pc1:
                        st.caption(f"Previewing: {preview}")
                    with pc2:
                        if st.button("✕ Close", key="close_preview"):
                            st.session_state.preview_file = None
                            st.rerun()
                    try:
                        code = st.session_state.src_files[preview].decode("utf-8", errors="replace")
                        ext = preview.rsplit(".", 1)[-1] if "." in preview else "text"
                        lang_map = {"py": "python", "sql": "sql", "r": "r", "scala": "scala", "ipynb": "json"}
                        st.code(code, language=lang_map.get(ext, "text"))
                    except Exception:
                        st.warning("Cannot preview this file.")
                else:
                    st.caption("Click Preview next to a file to view it here.")
    else:
        st.caption("No files uploaded yet.")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 2 — Language Detection
    # ══════════════════════════════════════════════════════════════════════
    st.subheader("2. Languages")
    st.caption("Detected from uploaded files — adjust if needed.")

    all_languages = ["Python", "R", "SQL", "Scala"]
    detected = st.session_state.detected_languages
    default_langs = [l for l in all_languages if detected.get(l)] or ["Python"]

    selected_languages = st.multiselect(
        "Languages *",
        options=all_languages,
        default=default_langs,
    )

    if selected_languages:
        cols = st.columns(len(selected_languages))
        for col, lang in zip(cols, selected_languages):
            with col:
                opts = VERSION_OPTIONS.get(lang, ["N/A"])
                saved = st.session_state.language_versions.get(lang, opts[0])
                idx = opts.index(saved) if saved in opts else 0
                st.session_state.language_versions[lang] = st.selectbox(
                    f"{lang} version", options=opts, index=idx, key=f"ver_{lang}",
                )

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 3 — Environment
    # ══════════════════════════════════════════════════════════════════════
    st.subheader("3. Environment")

    col1, col2 = st.columns(2)
    with col1:
        platform = st.selectbox(
            "Platform *",
            options=["databricks", "snowflake", "foundry"],
            format_func=lambda x: {
                "databricks": "Databricks",
                "snowflake":  "Snowflake",
                "foundry":    "Palantir Foundry",
            }[x],
            help="This POC supports Databricks only — other options coming soon.",
        )
    with col2:
        orchestrator = st.selectbox(
            "Orchestrator *",
            options=["dagster", "databricks_jobs"],
            format_func=lambda x: {
                "dagster":         "Dagster",
                "databricks_jobs": "Databricks Jobs / Tasks",
            }[x],
        )

    workspace_url = st.text_input(
        "Databricks workspace URL *",
        placeholder="e.g. https://dbc-085b91a0-8021.cloud.databricks.com",
    )

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 4 — Unity Catalog Configuration
    # ══════════════════════════════════════════════════════════════════════
    st.subheader("4. Unity Catalog configuration")

    has_existing_catalog = st.radio(
        "Does your pipeline use an existing Unity Catalog namespace?",
        options=["Yes", "No"],
        horizontal=True,
        key="has_existing_catalog",
    )

    uc_catalog = ""
    uc_schema  = ""
    uc_volume  = ""

    if has_existing_catalog == "Yes":
        st.caption(
            "In Databricks, your data lives in a three-level namespace: "
            "**Catalog** (top-level container) → **Schema** (grouping of tables and volumes) → "
            "**Table** (structured data) or **Volume** (file storage). "
            "Fill in the names for your existing namespace below."
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            uc_catalog = st.text_input("Catalog *", placeholder="e.g. etl_cms",
                                       help="Top-level container in Unity Catalog.")
        with col2:
            uc_schema = st.text_input("Schema *", placeholder="e.g. ohdsi_cdm",
                                      help="Grouping of tables and volumes within the catalog.")
        with col3:
            uc_volume = st.text_input("Volume *", placeholder="e.g. ohdsi_raw",
                                      help="File storage area within the schema.")
    else:
        st.caption("Orion will scaffold new Catalog, Schema, and Volume names based on your project name.")

    st.markdown("**Gold table definitions**")
    has_db = st.radio(
        "Do you have DDL SQL files that define your gold tables?",
        options=["Yes", "No"],
        horizontal=True,
        key="has_db",
    )

    if has_db == "Yes":
        st.caption(
            "Select the SQL files from your Section 1 uploads that define your gold tables. "
            "All detected tables will be available as gold destinations in Section 5."
        )

        # filter src_files to .sql only
        sql_files_available = [f for f in st.session_state.src_files if f.endswith(".sql")]

        if sql_files_available:
            selected_sql = st.multiselect(
                "Select DDL SQL file(s)",
                options=sql_files_available,
                key="selected_sql_files",
                placeholder="Select SQL files from your uploaded scripts...",
            )

            # parse tables from selected files
            st.session_state.gold_tables = []
            for fname in (selected_sql or []):
                for t in parse_table_names(st.session_state.src_files[fname]):
                    t_clean = t.strip('`"').split(".")[-1]
                    if t_clean and t_clean not in st.session_state.gold_tables:
                        st.session_state.gold_tables.append(t_clean)

            if st.session_state.gold_tables:
                st.success(
                    f"Detected {len(st.session_state.gold_tables)} gold table(s): "
                    + ", ".join(f"`{t}`" for t in st.session_state.gold_tables)
                )
            elif selected_sql:
                st.caption("No CREATE TABLE statements found in selected files.")
        else:
            st.caption("No .sql files found — upload SQL scripts in Section 1 first.")


    else:
        st.session_state.gold_tables = []
        st.caption("Orion will create new gold tables based on the silver output schema.")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 4 — Medallion Layers
    # ══════════════════════════════════════════════════════════════════════
    st.subheader("5. Medallion layers")
    available_files = list(st.session_state.src_files.keys())

    # show constructed volume base path as reference
    if uc_catalog and uc_schema and uc_volume:
        base_path = f"/Volumes/{uc_catalog}/{uc_schema}/{uc_volume}"
        st.caption(f"All pipeline data lives under: `{base_path}/` — subfolders per layer below.")

    # helper: prints the full destination path for a subfolder
    def volume_path(subfolder):
        if uc_catalog and uc_schema and uc_volume:
            base = f"/Volumes/{uc_catalog}/{uc_schema}/{uc_volume}"
            return f"{base}/{subfolder}" if subfolder else base
        return None

    # helper: reusable optional script selector
    def script_selector(key, placeholder="Select script(s) from Section 1 uploads..."):
        st.caption(
            "Optional — add a script only if this layer transforms the data. "
            "Leave empty and Orion will generate a plain transfer step."
        )
        if available_files:
            return st.multiselect("Script(s) (optional)", options=available_files, key=key, placeholder=placeholder)
        st.caption("Upload scripts in Section 1 to map them here.")
        return None

    # ── BRONZE ────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**Bronze — Raw landing**")
        st.caption("All bronze data lands in one volume with subfolders per source.")

        # -- Source 1: manual upload (bronze only) --
        st.markdown("**Source — Manual file upload**")
        bronze_manual = st.checkbox("Include manual file upload (e.g. OMOP vocabulary CSVs)")
        bronze_manual_subfolder = ""
        if bronze_manual:
            bronze_data_upload = st.file_uploader(
                "Upload data files (zip large files — 200MB limit per file)",
                accept_multiple_files=True,
                key="bronze_data_upload",
            )
            if bronze_data_upload:
                for f in bronze_data_upload:
                    if f.name.endswith(".zip"):
                        with zipfile.ZipFile(io.BytesIO(f.read())) as zf:
                            for name in zf.namelist():
                                if not name.endswith("/"):
                                    flat = name.split("/")[-1]
                                    if flat:
                                        st.session_state.bronze_data_files[flat] = zf.read(name)
                    else:
                        st.session_state.bronze_data_files[f.name] = f.read()
            if st.session_state.bronze_data_files:
                st.caption(f"{len(st.session_state.bronze_data_files)} file(s) staged")
                with st.container(height=150, border=True):
                    for fname in list(st.session_state.bronze_data_files.keys()):
                        c1, c2 = st.columns([6, 1])
                        with c1:
                            st.caption(fname)
                        with c2:
                            if st.button("✕", key=f"rm_bronze_{fname}"):
                                del st.session_state.bronze_data_files[fname]
                                st.rerun()
            bronze_manual_subfolder = st.text_input(
                "Output subfolder name", value="omop_vocabulary", key="bronze_manual_subfolder",
            )
            p = volume_path(bronze_manual_subfolder)
            if p:
                st.info(f"Destination: `{p}/`")

        # -- Source 2: script-based pull --
        st.markdown("**Source — Script-based pull**")
        bronze_script = None
        bronze_script_subfolder = ""
        use_script = st.checkbox("Include script-based data pull (e.g. API)")
        if use_script:
            bronze_script = script_selector("bronze_scripts")
            bronze_script_subfolder = st.text_input(
                "Output subfolder name", value="synpuf_raw", key="bronze_script_subfolder",
            )
            p = volume_path(bronze_script_subfolder)
            if p:
                st.info(f"Destination: `{p}/`")

    # ── SILVER ────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**Silver — ETL transformation**")

        st.markdown("**Source**")
        st.caption("Auto-set to bronze Volume subfolders.")

        silver_script = script_selector("silver_scripts", "Select ETL transformation scripts...")

        silver_subfolder = st.text_input(
            "Output subfolder name", value="silver_output", key="silver_subfolder",
        )
        p = volume_path(silver_subfolder)
        if p:
            st.info(f"Destination: `{p}/`")

    # ── GOLD ──────────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**Gold — OMOP CDM tables**")

        st.markdown("**Source**")
        st.caption("Auto-set to silver Volume output.")

        gold_script = script_selector("gold_scripts", "Select load scripts (e.g. load_omop_output.py)...")

        st.markdown("**Destination — Unity Catalog tables**")
        if st.session_state.gold_tables:
            gold_dest_tables = st.multiselect(
                "Select tables *",
                options=st.session_state.gold_tables,
                key="gold_dest_tables",
                placeholder="Select tables defined in Section 4...",
            )
            if uc_catalog and uc_schema and gold_dest_tables:
                st.info(f"Destination: `{uc_catalog}.{uc_schema}.<table>` for each selected table.")
        else:
            st.warning("No tables available — select DDL SQL files in Section 4.")
            gold_dest_tables = []


    st.markdown("---")

    # ── Validation ────────────────────────────────────────────────────────
    required = {
        "Project name":                   project_name,
        **({"Unity Catalog catalog": uc_catalog,
            "Unity Catalog schema":  uc_schema,
            "Unity Catalog volume":  uc_volume,
        } if has_existing_catalog == "Yes" else {}),
        "At least one language":           "ok" if selected_languages else "",
        "Source code":  "ok" if st.session_state.src_files else "",
    }
    missing = [label for label, val in required.items() if not str(val).strip()]

    if missing:
        st.warning("Required before generating: " + ", ".join(missing))

    languages_yaml = [
        {"language": lang, "version": st.session_state.language_versions.get(lang, "")}
        for lang in selected_languages
    ]

    spec = {
        "apiVersion": "orion/v1",
        "project": project_slug,
        "platform": platform,
        "runtime": {
            "languages":   languages_yaml,
            "orchestrator": "dagster",

        },
        "unity_catalog": {
            "catalog":     uc_catalog,
            "schema":      uc_schema,
            "volume":      uc_volume,
            "ddl_files":   list(st.session_state.sql_files.keys()) or None,
            "gold_tables": st.session_state.gold_tables or None,
        },
        "stages": [
            {
                "layer": "bronze",
                "source": {
                    "manual_upload": {
                        "enabled":   bronze_manual,
                        "subfolder": bronze_manual_sub,
                        "files":     list(st.session_state.bronze_data_files.keys()) or None,
                    },
                    "script_pull": {
                        "enabled":   use_script,
                        "subfolder": bronze_script_sub,
                        "scripts":   bronze_script or None,
                    },
                },
                "destination": {
                    "type":   "Databricks Volume",
                    "volume": uc_volume,
                    "path":   f"/Volumes/{uc_catalog}/{uc_schema}/{uc_volume}" if uc_catalog and uc_schema and uc_volume else None,
                },
            },
            {
                "layer":  "silver",
                "source": "bronze Volume subfolders (auto)",
                "script": silver_script or None,
                "destination": {
                    "type":      "Databricks Volume",
                    "volume":    uc_volume,
                    "subfolder": silver_sub,
                    "path":      f"/Volumes/{uc_catalog}/{uc_schema}/{uc_volume}/{silver_sub}" if uc_catalog and uc_schema and uc_volume else None,
                },
            },
            {
                "layer":  "gold",
                "source": "silver Volume output (auto)",
                "script": gold_script or None,
                "destination": {
                    "type":    "Databricks Delta table (Unity Catalog)",
                    "catalog": uc_catalog,
                    "schema":  uc_schema,
                    "tables":  gold_dest_tables or None,
                },
            },
        ],
        "generated": str(date.today()),
    }

    st.subheader("orion.yaml preview")
    yaml_str = yaml.dump(spec, sort_keys=False, default_flow_style=False, width=100)
    st.code(yaml_str, language="yaml")

    zip_bytes = build_zip(yaml_str, project_slug)
    has_src = bool(st.session_state.src_files)

    st.download_button(
        f"Download {project_slug}.zip  ({'orion.yaml + src/ + sql/' if has_src else 'orion.yaml only'})",
        data=zip_bytes,
        file_name=f"{project_slug}.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True,
        disabled=bool(missing),
    )