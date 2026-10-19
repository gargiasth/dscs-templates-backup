"""
Orion Launchpad — ETL-CMS Intake (Databricks POC)

Sections:
  1. Source files
  2. Languages
  3. Environment
  4. Unity Catalog configuration
  5. Medallion layers (dynamic list)

A `table_setup` stage is auto-prepended at build time when DDL files are
selected in Section 4 — users don't configure it manually in Section 5.

Run standalone:  streamlit run pages/minimal.py
"""

import io
import re
import json
import zipfile
from datetime import date

import streamlit as st


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", text.strip().lower()).strip("-") or "unnamed"


def var_safe(text: str) -> str:
    """Make a string safe to use as a bundle variable name segment."""
    return re.sub(r"[^a-z0-9_]+", "_", text.strip().lower()).strip("_") or "layer"


EXT_TO_LANGUAGE = {
    ".py": "Python", ".r": "R", ".R": "R",
    ".scala": "Scala", ".sql": "SQL", ".ipynb": "Python",
}

VERSION_OPTIONS = {
    "Python": ["3.9", "3.10", "3.11", "3.12"],
    "R":      ["4.2", "4.3", "4.4"],
    "SQL":    ["Spark SQL"],
    "Scala":  ["2.12", "2.13"],
}

LAYER_TYPES = ["bronze", "silver", "gold", "custom"]


def detect_languages(filenames):
    detected = {}
    for name in filenames:
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        lang = EXT_TO_LANGUAGE.get(ext) or EXT_TO_LANGUAGE.get(ext.lower())
        if lang:
            detected[lang] = True
    return detected


def parse_table_names(sql_bytes):
    text = sql_bytes.decode("utf-8", errors="ignore")
    return re.findall(r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:EXTERNAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\"\w.]+)",
                      text, re.IGNORECASE)


def default_layer(name, ltype):
    return {
        "name": name,
        "type": ltype,
        "sources": [],
        "destination": {"type": "volume", "subfolder": "", "tables": []},
        "script": [],
        "script_params": {},   # {script_filename: [param_string, ...]}
    }


# ── Auto-generated setup stage ──────────────────────────────────────────────
# When Section 4 has DDL files + detected tables, we prepend a `table_setup`
# stage to the output spec. The user never configures this in Section 5 —
# it's inferred from Section 4 and runs utilities/create_tables.py before
# any pipeline stage.

def build_table_setup_layer(ddl_files):
    """Return a table_setup layer in INPUT shape — the same shape user-facing
    layers in st.session_state.layers use.

    The main build-spec loop converts it to output shape alongside bronze/
    silver/gold, so there's one code path for all stages. No drift possible.

    The DDL files passed as script parameters are the setup stage's contract
    — the utility opens them and creates whatever tables they define. The
    destination intentionally has no `tables` list.
    """
    return {
        "name": "table_setup",
        "type": "setup",
        "sources": [],
        "destination": {
            "type": "tables",
            "subfolder": "",
            "tables": [],   # intentionally empty — DDL files are the contract
        },
        "script": ["create_tables.py"],
        "script_paths": {
            "create_tables.py": "utilities/create_tables.py",
        },
        "script_params": {
            "create_tables.py": [
                "${var.catalog}",
                "${var.schema}",
                *[f"sql/{f}" for f in ddl_files],
            ],
        },
    }


def inject_table_setup_dependency(input_layers):
    """Give every table-writing layer an auto source from `table_setup`.

    Operates on INPUT shape (st.session_state.layers), BEFORE the main loop
    converts to output. Uses the input `type` key, not `data_upload_type`.
    """
    for layer in input_layers:
        if layer["name"] == "table_setup":
            continue
        dest = layer.get("destination", {})
        if dest.get("type") == "tables":
            layer.setdefault("sources", [])
            already_depends = any(
                s.get("type") == "auto" and s.get("from") == "table_setup"
                for s in layer["sources"]
            )
            if not already_depends:
                layer["sources"].append({"type": "auto", "from": "table_setup"})


def init_state():
    if "src_files" not in st.session_state:
        st.session_state.src_files = {}
    if "src_zip_map" not in st.session_state:
        st.session_state.src_zip_map = {}
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
    if "layers" not in st.session_state:
        st.session_state.layers = [
            {
                "name": "bronze", "type": "bronze",
                "sources": [
                    {"type": "manual", "subfolder": "omop_vocabulary", "enabled": False, "scripts": [], "script_params": {}, "files_key": "bronze_data_files"},
                    {"type": "script", "subfolder": "synpuf_raw",      "enabled": False, "scripts": [], "script_params": {}},
                ],
                "destination": {"type": "volume", "subfolder": "", "tables": []},
                "script": [],
                "script_params": {},
            },
            {
                "name": "silver", "type": "silver",
                "sources": [{"type": "auto", "from": "bronze"}],
                "destination": {"type": "volume", "subfolder": "silver_output", "tables": []},
                "script": [],
                "script_params": {},
            },
            {
                "name": "gold", "type": "gold",
                "sources": [{"type": "auto", "from": "silver"}],
                "destination": {"type": "tables", "subfolder": "", "tables": []},
                "script": [],
                "script_params": {},
            },
        ]


def render_script_params(script_names, params_dict, key_prefix):
    """Render per-script parameter editors. Each param is a free-text string —
    user types ${var.foo} for a variable ref or a literal value directly."""
    for script_name in script_names:
        params = params_dict.setdefault(script_name, [])

        with st.expander(f"Parameters for `{script_name}` ({len(params)})"):
            for pi in range(len(params)):
                c1, c2 = st.columns([10, 1])
                with c1:
                    params[pi] = st.text_input(
                        "param",
                        value=params[pi],
                        key=f"{key_prefix}_val_{script_name}_{pi}",
                        placeholder='e.g. ${var.synpuf_raw_subfolder_path}  or  all',
                        label_visibility="collapsed",
                    )
                with c2:
                    if st.button("✕", key=f"{key_prefix}_rm_{script_name}_{pi}"):
                        params.pop(pi)
                        st.rerun()

            if st.button("+ Add parameter", key=f"{key_prefix}_add_{script_name}"):
                params.append("")
                st.rerun()


def build_zip(json_str, project):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{project}/orion.json", json_str)
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

    project_name = st.text_input("Project name *", placeholder="e.g. etl-cms-ohdsi")
    project_slug = slug(project_name) if project_name else "unnamed"

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 1 — Source files
    # ══════════════════════════════════════════════════════════════════════
    st.subheader("1. Source files *")
    st.caption("Upload individual scripts (.py, .ipynb, .sql) or zip your src/ folder.")

    uploaded = st.file_uploader(
        "Upload scripts or zip your src/ folder",
        type=["py", "ipynb", "r", "scala", "sql", "zip"],
        accept_multiple_files=True, key="src_upload",
    )

    current_zips  = {f.name for f in (uploaded or []) if f.name.endswith(".zip")}
    current_plain = {f.name for f in (uploaded or []) if not f.name.endswith(".zip")}

    for removed_zip in set(st.session_state.src_zip_map.values()) - current_zips:
        for k in [k for k, v in st.session_state.src_zip_map.items() if v == removed_zip]:
            st.session_state.src_files.pop(k, None)
            st.session_state.src_zip_map.pop(k, None)
        st.session_state.detected_languages = detect_languages(list(st.session_state.src_files.keys()))

    tracked_plain = {k for k in st.session_state.src_files if k not in st.session_state.src_zip_map}
    for removed_plain in tracked_plain - current_plain:
        st.session_state.src_files.pop(removed_plain, None)
        st.session_state.detected_languages = detect_languages(list(st.session_state.src_files.keys()))

    if uploaded:
        newly = []
        for f in uploaded:
            if f.name.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(f.read())) as zf:
                    for name in zf.namelist():
                        if not name.endswith("/"):
                            flat = name.split("/")[-1]
                            if flat and flat not in st.session_state.src_files:
                                st.session_state.src_files[flat] = zf.read(name)
                                st.session_state.src_zip_map[flat] = f.name
                                newly.append(flat)
            else:
                if f.name not in st.session_state.src_files:
                    st.session_state.src_files[f.name] = f.read()
                    newly.append(f.name)
        if newly:
            det = detect_languages(list(st.session_state.src_files.keys()))
            merged = dict(st.session_state.detected_languages); merged.update(det)
            st.session_state.detected_languages = merged

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
                            zo = st.session_state.src_zip_map.get(filename)
                            if zo:
                                for k in [k for k, v in st.session_state.src_zip_map.items() if v == zo]:
                                    st.session_state.src_files.pop(k, None)
                                    st.session_state.src_zip_map.pop(k, None)
                            else:
                                del st.session_state.src_files[filename]
                            if st.session_state.preview_file == filename:
                                st.session_state.preview_file = None
                            st.session_state.detected_languages = detect_languages(list(st.session_state.src_files.keys()))
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

    available_files = list(st.session_state.src_files.keys())

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 2 — Languages
    # ══════════════════════════════════════════════════════════════════════
    st.subheader("2. Languages")
    st.caption("Detected from uploaded files — adjust if needed.")

    all_languages = ["Python", "R", "SQL", "Scala"]
    detected = st.session_state.detected_languages
    default_langs = [l for l in all_languages if detected.get(l)] or ["Python"]

    selected_languages = st.multiselect("Languages *", options=all_languages, default=default_langs)

    if selected_languages:
        cols = st.columns(len(selected_languages))
        for col, lang in zip(cols, selected_languages):
            with col:
                opts = VERSION_OPTIONS.get(lang, ["N/A"])
                saved = st.session_state.language_versions.get(lang, opts[0])
                idx = opts.index(saved) if saved in opts else 0
                st.session_state.language_versions[lang] = st.selectbox(
                    f"{lang} version", options=opts, index=idx, key=f"ver_{lang}")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 3 — Environment
    # ══════════════════════════════════════════════════════════════════════
    st.subheader("3. Environment")

    col1, col2 = st.columns(2)
    with col1:
        platform = st.selectbox(
            "Platform *", options=["databricks", "snowflake", "foundry"],
            format_func=lambda x: {"databricks": "Databricks", "snowflake": "Snowflake",
                                   "foundry": "Palantir Foundry"}[x],
            help="This POC supports Databricks only — other options coming soon.")
    with col2:
        orchestrator = st.selectbox(
            "Orchestrator *", options=["dagster", "databricks_jobs"],
            format_func=lambda x: {"dagster": "Dagster", "databricks_jobs": "Databricks Jobs / Tasks"}[x])

    workspace_url = st.text_input(
        "Databricks workspace URL *",
        placeholder="e.g. https://dbc-1234.cloud.databricks.com")

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════
    # SECTION 4 — Unity Catalog configuration
    # ══════════════════════════════════════════════════════════════════════
    st.subheader("4. Unity Catalog configuration")

    has_existing_catalog = st.radio(
        "Does your pipeline use an existing Unity Catalog namespace?",
        options=["Yes", "No"], horizontal=True, key="has_existing_catalog")

    uc_catalog = uc_schema = uc_volume = ""
    if has_existing_catalog == "Yes":
        st.caption("Catalog (top-level) → Schema (grouping) → Volume (file storage). "
                   "One volume holds all pipeline data; subfolders separate the layers.")
        c1, c2, c3 = st.columns(3)
        with c1:
            uc_catalog = st.text_input("Catalog *", placeholder="e.g. etl_cms")
        with c2:
            uc_schema = st.text_input("Schema *", placeholder="e.g. ohdsi_cdm")
        with c3:
            uc_volume = st.text_input("Volume *", placeholder="e.g. ohdsi_volume")
    else:
        st.caption("Orion will scaffold new Catalog, Schema, and Volume names from your project name.")

    st.markdown("**Gold table definitions**")
    has_db = st.radio(
        "Do you have DDL SQL files that define your gold tables?",
        options=["Yes", "No"], horizontal=True, key="has_db")

    if has_db == "Yes":
        st.caption("Select the SQL files from Section 1 that define your gold tables.")
        sql_available = [f for f in st.session_state.src_files if f.endswith(".sql")]
        if sql_available:
            selected_sql = st.multiselect("Select DDL SQL file(s)", options=sql_available, key="selected_sql_files")
            st.session_state.sql_files = {f: st.session_state.src_files[f] for f in (selected_sql or [])}
            st.session_state.gold_tables = []
            for fname in (selected_sql or []):
                for t in parse_table_names(st.session_state.src_files[fname]):
                    tc = t.strip('`"').split(".")[-1]
                    if tc and tc not in st.session_state.gold_tables:
                        st.session_state.gold_tables.append(tc)
            if st.session_state.gold_tables:
                st.success(f"Detected {len(st.session_state.gold_tables)} table(s): "
                           + ", ".join(f"`{t}`" for t in st.session_state.gold_tables))
                st.info(
                    f"✓ A `table_setup` stage will be auto-generated to create these "
                    f"{len(st.session_state.gold_tables)} table(s) from "
                    f"{len(selected_sql)} DDL file(s), before any pipeline stage runs."
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
    # SECTION 5 — Medallion layers (dynamic)
    # ══════════════════════════════════════════════════════════════════════
    st.subheader("5. Medallion layers")

    if uc_catalog and uc_schema and uc_volume:
        base_path = f"/Volumes/{uc_catalog}/{uc_schema}/{uc_volume}"
        st.caption(f"All pipeline data lives under: `{base_path}/` — subfolders per layer below.")

    def volume_path(subfolder):
        if uc_catalog and uc_schema and uc_volume:
            base = f"/Volumes/{uc_catalog}/{uc_schema}/{uc_volume}"
            return f"{base}/{subfolder}" if subfolder else base
        return None

    def script_selector(key, placeholder):
        st.caption("Optional — add a script only if this layer transforms the data. "
                   "Leave empty and Orion generates a plain transfer step.")
        if available_files:
            return st.multiselect("Script(s) (optional)", options=available_files, key=key, placeholder=placeholder)
        st.caption("Upload scripts in Section 1 to map them here.")
        return []

    # render each layer in a loop
    for idx, layer in enumerate(st.session_state.layers):
        with st.container(border=True):
            h1, h2, h3 = st.columns([3, 2, 1])
            with h1:
                layer["name"] = st.text_input("Layer name", value=layer["name"], key=f"lyr_name_{idx}")
            with h2:
                layer["type"] = st.selectbox(
                    "Layer type", options=LAYER_TYPES,
                    index=LAYER_TYPES.index(layer["type"]) if layer["type"] in LAYER_TYPES else 3,
                    key=f"lyr_type_{idx}")
            with h3:
                st.write("")
                st.write("")
                core = {"bronze", "silver", "gold"}
                removable = layer["type"] not in core or sum(
                    1 for l in st.session_state.layers if l["type"] == layer["type"]) > 1
                if removable and st.button("✕ Remove", key=f"lyr_rm_{idx}"):
                    st.session_state.layers.pop(idx)
                    st.rerun()

            # ── SOURCES ──
            st.markdown("**Sources**")
            for si, src in enumerate(layer["sources"]):
                if src["type"] == "auto":
                    st.caption(f"Auto-set to {src.get('from', 'upstream')} layer output.")
                elif src["type"] == "manual":
                    src["enabled"] = st.checkbox(
                        "Manual file upload (e.g. OMOP vocabulary CSVs)",
                        value=src.get("enabled", False), key=f"src_manual_{idx}_{si}")
                    if src["enabled"]:
                        up = st.file_uploader(
                            "Upload data files (zip large files — 200MB limit per file)",
                            accept_multiple_files=True, key=f"src_manual_up_{idx}_{si}")
                        if up:
                            for f in up:
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
                                    fc1, fc2 = st.columns([6, 1])
                                    with fc1:
                                        st.caption(fname)
                                    with fc2:
                                        if st.button("✕", key=f"rm_data_{idx}_{si}_{fname}"):
                                            del st.session_state.bronze_data_files[fname]
                                            st.rerun()
                        src["subfolder"] = st.text_input(
                            "Output subfolder name", value=src.get("subfolder", ""),
                            key=f"src_manual_sub_{idx}_{si}")
                        p = volume_path(src["subfolder"])
                        st.caption(f"Output path: `{p}/`" if p else
                                   "Output path: fill in Catalog / Schema / Volume in Section 4.")
                elif src["type"] == "script":
                    src["enabled"] = st.checkbox(
                        "Script-based data pull (e.g. API)",
                        value=src.get("enabled", False), key=f"src_script_{idx}_{si}")
                    if src["enabled"]:
                        src["scripts"] = script_selector(f"src_script_sel_{idx}_{si}", "Select data pull script(s)...")
                        src["subfolder"] = st.text_input(
                            "Output subfolder name", value=src.get("subfolder", ""),
                            key=f"src_script_sub_{idx}_{si}")
                        p = volume_path(src["subfolder"])
                        st.caption(f"Output path: `{p}/`" if p else
                                   "Output path: fill in Catalog / Schema / Volume in Section 4.")

                        # Per-script parameters
                        if src.get("scripts"):
                            src.setdefault("script_params", {})
                            render_script_params(
                                script_names=src["scripts"],
                                params_dict=src["script_params"],
                                key_prefix=f"src_params_{idx}_{si}",
                            )

            # ── TRANSFORM SCRIPT (for auto-source layers like silver/gold) ──
            has_auto = any(s["type"] == "auto" for s in layer["sources"])
            if has_auto:
                layer["script"] = script_selector(f"lyr_script_{idx}", "Select transformation script(s)...")

                # Per-script parameters
                if layer["script"]:
                    layer.setdefault("script_params", {})
                    render_script_params(
                        script_names=layer["script"],
                        params_dict=layer["script_params"],
                        key_prefix=f"lyr_params_{idx}",
                    )

            # ── DESTINATION ──
            dest = layer["destination"]

            if layer["type"] == "gold":
                dest["type"] = "tables"
            elif layer["type"] in ("bronze", "silver"):
                dest["type"] = "volume"
            else:
                st.markdown("**Destination**")
                dest["type"] = st.selectbox(
                    "Destination type",
                    options=["volume", "tables"],
                    index=0 if dest.get("type", "volume") == "volume" else 1,
                    format_func=lambda x: {"volume": "Databricks Volume",
                                           "tables": "Unity Catalog Delta tables"}[x],
                    key=f"dest_type_{idx}")

            if dest["type"] == "volume":
                per_source_subs = [s for s in layer["sources"] if s["type"] in ("manual", "script") and s.get("enabled")]
                if not per_source_subs:
                    st.markdown("**Destination**")
                    dest["subfolder"] = st.text_input(
                        "Output subfolder name", value=dest.get("subfolder", ""),
                        key=f"dest_sub_{idx}")
                    p = volume_path(dest["subfolder"])
                    st.caption(f"Output path: `{p}/`" if p else
                               "Output path: fill in Catalog / Schema / Volume in Section 4.")
            else:
                st.markdown("**Destination — Unity Catalog tables**")
                if st.session_state.gold_tables:
                    dest["tables"] = st.multiselect(
                        "Select tables *", options=st.session_state.gold_tables,
                        default=[t for t in dest.get("tables", []) if t in st.session_state.gold_tables],
                        key=f"dest_tables_{idx}",
                        placeholder="Select tables defined in Section 4...")
                    if uc_catalog and uc_schema and dest["tables"]:
                        st.caption(f"Destination: `{uc_catalog}.{uc_schema}.<table>` per selected table.")
                else:
                    st.warning("No tables available — select DDL SQL files in Section 4.")
                    dest["tables"] = []

    if st.button("+ Add layer"):
        st.session_state.layers.append(default_layer("", "custom"))
        st.rerun()

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════
    # Validation
    # ══════════════════════════════════════════════════════════════════════
    required = {
        "Project name": project_name,
        **({"Catalog": uc_catalog, "Schema": uc_schema, "Volume": uc_volume}
           if has_existing_catalog == "Yes" else {}),
        "At least one language": "ok" if selected_languages else "",
        "Source code":           "ok" if st.session_state.src_files else "",
        "Workspace URL":         workspace_url,
    }
    missing = [label for label, val in required.items() if not str(val).strip()]
    if missing:
        st.warning("Required before generating: " + ", ".join(missing))

    # ══════════════════════════════════════════════════════════════════════
    # Build spec — dynamic from layers list
    # ══════════════════════════════════════════════════════════════════════
    def default_or(value, name):
        return value if value else f"{name}_default"

    def clean_params(raw_list):
        """Drop empty strings and whitespace-only values."""
        return [p.strip() for p in (raw_list or []) if p and p.strip()]

    languages_list = [
        {"language": lang, "version": st.session_state.language_versions.get(lang, "")}
        for lang in selected_languages
    ]

    # ── Prepend table_setup layer in INPUT shape, before the main loop ──
    # The main loop then converts it to output shape alongside bronze/silver/
    # gold, so there's one code path for all stages. No drift possible.
    input_layers = list(st.session_state.layers)
    if st.session_state.sql_files and st.session_state.gold_tables:
        setup_layer = build_table_setup_layer(
            ddl_files=list(st.session_state.sql_files.keys()),
        )
        input_layers = [setup_layer] + input_layers
        inject_table_setup_dependency(input_layers)

    stages = []
    for layer in input_layers:
        lname = layer["name"] or layer["type"]

        # build sources
        src_out = []
        for src in layer["sources"]:
            if src["type"] == "auto":
                src_out.append({"data_upload_type": "auto", "from": src.get("from")})
            elif src["type"] in ("manual", "script") and src.get("enabled"):
                sub = (src.get("subfolder") or lname).strip()
                entry = {
                    "data_upload_type": "manual" if src["type"] == "manual" else "custom_script",
                    "subfolder_name":   sub,
                }
                if src["type"] == "manual":
                    entry["files"] = default_or(list(st.session_state.bronze_data_files.keys()), "files")
                else:
                    # Each script is a dict with file + parameters list of strings
                    params_map = src.get("script_params", {})
                    scripts_with_params = [
                        {
                            "file":       s,
                            "parameters": clean_params(params_map.get(s)),
                        }
                        for s in src.get("scripts") or []
                    ]
                    entry["scripts"] = scripts_with_params or default_or(None, "scripts")
                src_out.append(entry)

        # build destination
        dest = layer["destination"]
        if dest["type"] == "volume":
            sub = (dest.get("subfolder") or "").strip()
            dest_out = {"type": "volume"}
            if sub:
                dest_out["subfolder_name"] = sub
        else:
            dest_out = {
                "type":    "tables",
                "catalog": default_or(uc_catalog, "catalog"),
                "schema":  default_or(uc_schema, "schema"),
            }
            # Setup layers define their tables via DDL files passed as script
            # parameters, so no `tables` field here. Every other layer type
            # must declare the specific tables it writes to — missing tables
            # gets a sentinel so the user sees the gap.
            if layer["type"] != "setup":
                dest_out["tables"] = default_or(dest.get("tables"), "tables")

        # Entry-point script for this stage. One stage = one entry point.
        # Preference order:
        #   1. Layer's transform script (silver/gold with auto source)
        #   2. Fallback: a single source script (bronze with one data-pull
        #      script — that script IS the stage's work, so promote it)
        # script_paths lets a layer override the default `src/<file>` path.
        params_map  = layer.get("script_params", {})
        paths_map   = layer.get("script_paths", {})
        script_list = layer.get("script") or []

        if script_list:
            entry_file = script_list[0]
            entry_point_out = {
                "file":       entry_file,
                "path":       paths_map.get(entry_file, f"src/{entry_file}"),
                "parameters": clean_params(params_map.get(entry_file)),
            }
        else:
            # Fall back to a source script if the stage has exactly one
            # enabled script source with exactly one script.
            enabled_script_sources = [
                s for s in layer["sources"]
                if s.get("type") == "script"
                and s.get("enabled")
                and s.get("scripts")
            ]
            if (len(enabled_script_sources) == 1
                    and len(enabled_script_sources[0]["scripts"]) == 1):
                source = enabled_script_sources[0]
                entry_file = source["scripts"][0]
                source_params = source.get("script_params", {}).get(entry_file, [])
                entry_point_out = {
                    "file":       entry_file,
                    "path":       paths_map.get(entry_file, f"src/{entry_file}"),
                    "parameters": clean_params(source_params),
                }
            else:
                entry_point_out = "entry_point_default"

        stages.append({
            "name":        lname,
            "layer":       layer["type"],
            "sources":     src_out,
            "entry_point": entry_point_out,
            "destination": dest_out,
        })

    spec = {
        "apiVersion": "orion/v1",
        "project":    project_slug,
        "platform":   platform,
        "runtime": {
            "languages":     languages_list,
            "orchestrator":  orchestrator,
            "workspace_url": default_or(workspace_url, "workspace_url"),
        },
        "unity_catalog": {
            "catalog":     default_or(uc_catalog, "catalog"),
            "schema":      default_or(uc_schema, "schema"),
            "volume":      default_or(uc_volume, "volume"),
            "ddl_files":   default_or(list(st.session_state.sql_files.keys()), "ddl_files"),
            "gold_tables": default_or(st.session_state.gold_tables, "gold_tables"),
        },
        "stages":    stages,
        "generated": str(date.today()),
    }

    st.subheader("orion.json preview")
    json_str = json.dumps(spec, indent=2)
    st.code(json_str, language="json")

    zip_bytes = build_zip(json_str, project_slug)
    has_src = bool(st.session_state.src_files)

    st.download_button(
        f"Download {project_slug}.zip  ({'orion.json + src/ + sql/' if has_src else 'orion.json only'})",
        data=zip_bytes, file_name=f"{project_slug}.zip", mime="application/zip",
        type="primary", use_container_width=True, disabled=bool(missing))


if __name__ == "__main__":
    try:
        st.set_page_config(page_title="Orion Launchpad", layout="wide")
    except Exception:
        pass
    render()