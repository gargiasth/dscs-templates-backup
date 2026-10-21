"""
Orion Launchpad — ETL-CMS Intake (Databricks POC)

Sections:
  1. Source files
  2. Languages
  3. Environment
  4. Unity Catalog configuration
  5. Medallion layers (dynamic list)

Every layer (including the auto-generated table setup stages) is drawn by
render_layer() and converted by layer_to_stage(), so all layers share one format.

Run standalone:  streamlit run pages/minimal.py
"""

import io
import re
import json
import uuid
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


def new_layer(name, ltype, upstream_id=None):
    """A layer in the single format every layer uses (bronze, silver, gold, custom)."""
    return {
        "id":          uuid.uuid4().hex[:8],   # stable id: upstream links survive renames
        "name":        name,
        "type":        ltype,
        "inputs":      ([{"id": uuid.uuid4().hex[:8], "kind": "upstream", "layer_id": upstream_id}]
                        if upstream_id else []),
        "entry":       "",                     # the ONE script this layer runs
        "params":      [],
        "destination": {"type": "tables" if ltype == "gold" else "volume",
                        "subfolder": "", "tables": []},
    }


# ── Table setup stages ──────────────────────────────────────────────────────
# One setup stage per DDL file selected in Section 4. It uses the same layer
# format as everything else, with the entry point script, parameters and destination
# filled in and locked. Only its name and layer type are editable.

def setup_stage_default_name(ddl_file, n_files):
    stem = ddl_file.rsplit(".", 1)[0]
    return "table_setup" if n_files == 1 else f"table_setup_{var_safe(stem)}"


def setup_layer(ddl_file, cfg):
    return {
        "id":          f"setup_{var_safe(ddl_file)}",
        "name":        cfg["name"],
        "type":        cfg["type"],
        "locked":      True,
        "inputs":      [],
        "entry":       ddl_file,
        "entry_path":  f"sql/{ddl_file}",
        "params":      [],                    # catalog/schema are added by the jobs emitter
        "destination": {"type": "tables", "subfolder": "", "tables": cfg.get("tables", [])},
    }


def init_state():
    defaults = {
        "src_files": {}, "src_zip_map": {}, "preview_file": None, "sql_files": {},
        "detected_languages": {}, "language_versions": {}, "gold_tables": [],
        "data_files": {},       # {subfolder: {filename: bytes}} -- files uploaded into a folder
        "setup_stages": {},     # {ddl_file: {"name": ..., "type": ..., "tables": [...]}}
        "folders": [],          # [{"volume": ..., "subfolder": ...}]
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    if "layers" not in st.session_state:
        bronze = new_layer("bronze", "bronze")
        silver = new_layer("silver", "silver", upstream_id=bronze["id"])
        silver["destination"]["subfolder"] = "silver_output"
        gold   = new_layer("gold", "gold", upstream_id=silver["id"])
        st.session_state.layers = [bronze, silver, gold]


CUSTOM = "Custom value…"
ENV_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$")     # NAME=value
VAR_RE = re.compile(r"^\$\{var\.([a-z0-9_]+)\}$")     # ${var.name}


def render_script_params(script_names, params_dict, key_prefix, variables):
    """Per-script parameter editor.

    variables: {variable_name: resolved value} -- e.g.
        {"synpuf_raw_subfolder_path": "/Volumes/etl_cms/ohdsi_cdm/ohdsi_volume/synpuf_raw"}

    The dropdown shows variable names; the resolved value is shown read-only
    beside it. Only "Custom value…" is free text. Each param is stored as
    "${var.name}", a literal, or "NAME=<either>" when an env-var name is given.
    """
    choices = list(variables) + [CUSTOM]

    for script_name in script_names:
        params = params_dict.setdefault(script_name, [])

        with st.expander(f"Parameters for `{script_name}`", expanded=True):
            st.caption("Leave **Name** empty for a positional argument. Fill it in to pass "
                       "the value as an environment variable instead.")

            for pi in range(len(params)):
                # Split the stored string back into its parts for display.
                m = ENV_RE.match(params[pi])
                env_name, value = (m.group(1), m.group(2)) if m else ("", params[pi])
                vm = VAR_RE.match(value)
                is_known_var = bool(vm) and vm.group(1) in variables
                current = vm.group(1) if is_known_var else CUSTOM

                k = f"{key_prefix}_{script_name}_{pi}"
                c1, c2, c3, c4 = st.columns([3, 3, 5, 1])
                with c1:
                    env_name = st.text_input(
                        "Name", value=env_name, key=f"{k}_name",
                        placeholder="optional, e.g. BASE_OUTPUT_DIRECTORY",
                        label_visibility="collapsed").strip()
                with c2:
                    pick = st.selectbox(
                        "Value", choices, index=choices.index(current),
                        key=f"{k}_pick", label_visibility="collapsed")
                with c3:
                    if pick == CUSTOM:
                        value = st.text_input(
                            "Custom value", value="" if is_known_var else value,
                            key=f"{k}_custom", placeholder="e.g. 1  or  DE_{0}",
                            label_visibility="collapsed")
                    else:
                        value = "${var." + pick + "}"
                        st.text_input(
                            "Resolves to", value=variables[pick], disabled=True,
                            key=f"{k}_resolved_{pick}", label_visibility="collapsed")
                with c4:
                    if st.button("✕", key=f"{k}_rm"):
                        params.pop(pi)
                        st.rerun()

                if env_name and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env_name):
                    st.error(f"`{env_name}`: use UPPERCASE letters, digits and `_`, "
                             "not starting with a digit.")
                params[pi] = f"{env_name}={value}" if env_name else value

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
        for subfolder, files in st.session_state.data_files.items():
            for filename, content in files.items():
                zf.writestr(f"{project}/data/{subfolder}/{filename}", content)
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

    st.markdown("**Volumes and folders**")
    st.caption("Declare every folder the pipeline reads from or writes to, including ones "
               "no stage produces (e.g. reference data). They become selectable as task "
               "parameters in Section 5.")

    for fi, folder in enumerate(st.session_state.folders):
        c1, c2, c3 = st.columns([3, 3, 1])
        with c1:
            folder["volume"] = st.text_input(
                "Volume", value=folder.get("volume") or uc_volume, key=f"fld_vol_{fi}")
        with c2:
            folder["subfolder"] = st.text_input(
                "Subfolder", value=folder.get("subfolder", ""), key=f"fld_sub_{fi}")
        with c3:
            st.write("")
            st.write("")
            if st.button("✕", key=f"fld_rm_{fi}"):
                st.session_state.folders.pop(fi)
                st.rerun()

        sub = folder["subfolder"].strip()
        if sub and not re.fullmatch(r"[A-Za-z0-9_-]+", sub):
            st.error(f"`{sub}`: use only letters, digits, `_` and `-`.")
        elif sub and folder["volume"] and uc_catalog and uc_schema:
            st.caption(f"`/Volumes/{uc_catalog}/{uc_schema}/{folder['volume']}/{sub}`  →  "
                       f"`{var_safe(sub)}_subfolder_path`")

    names = [f["subfolder"].strip() for f in st.session_state.folders if f["subfolder"].strip()]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        st.error("Each subfolder name must be unique: " + ", ".join(f"`{d}`" for d in sorted(dupes)))

    if st.button("+ Add folder"):
        st.session_state.folders.append({"volume": uc_volume, "subfolder": ""})
        st.rerun()


    # ══════════════════════════════════════════════════════════════════════
    # Layer helpers -- shared by the table setup cards (Section 4) and the
    # medallion layers (Section 5), so every layer is drawn the same way.
    # ══════════════════════════════════════════════════════════════════════
    def volume_path(subfolder):
        if uc_catalog and uc_schema and uc_volume:
            vol = next((f["volume"].strip() for f in st.session_state.folders
                        if f["subfolder"].strip() == subfolder and f["volume"].strip()), uc_volume)
            base = f"/Volumes/{uc_catalog}/{uc_schema}/{vol}"
            return f"{base}/{subfolder}" if subfolder else base
        return None

    NEW_FOLDER = "+ New folder…"

    def folder_picker(label, current, key):
        """Pick a folder declared in Section 4, or define a new one here."""
        declared = [f["subfolder"].strip() for f in st.session_state.folders if f["subfolder"].strip()]
        options = declared + [NEW_FOLDER]
        current = (current or "").strip()
        if current in declared:
            index = declared.index(current)
        elif current:
            index = len(options) - 1          # existing name not in Section 4 -> "new"
        else:
            index = None                       # nothing chosen yet
        pick = st.selectbox(label, options, index=index, key=f"{key}_pick",
                            placeholder="Select a folder from Section 4, or create a new one")
        if pick == NEW_FOLDER:
            name = st.text_input("New folder name", value="" if current in declared else current,
                                 key=f"{key}_new").strip()
            if name and not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                st.error(f"`{name}`: use only letters, digits, `_` and `-`.")
            return name
        return pick or ""

    # Every variable a parameter can reference, with the value it resolves to.
    def _resolved(sub, vol=None):
        vol = (vol or uc_volume).strip()
        if uc_catalog and uc_schema and vol:
            return f"/Volumes/{uc_catalog}/{uc_schema}/{vol}/{sub}"
        return "(fill in Catalog / Schema / Volume in Section 4)"

    variables = {"catalog": uc_catalog or "(not set)", "schema": uc_schema or "(not set)"}
    for f in st.session_state.folders:
        sub = f["subfolder"].strip()
        if sub:
            variables[f"{var_safe(sub)}_subfolder_path"] = _resolved(sub, f["volume"])
    for _layer in st.session_state.layers:
        for _inp in _layer["inputs"]:
            sub = (_inp.get("subfolder") or "").strip()
            if _inp["kind"] == "folder" and sub:
                variables.setdefault(f"{var_safe(sub)}_subfolder_path", _resolved(sub))
        sub = (_layer["destination"].get("subfolder") or "").strip()
        if _layer["destination"]["type"] == "volume" and sub:
            variables.setdefault(f"{var_safe(sub)}_subfolder_path", _resolved(sub))

    runnable_files = [f for f in available_files if f.endswith((".py", ".sql"))]
    NO_ENTRY = "(none)"

    def stage_upload(subfolder, key):
        """Optional upload of data files into a folder (e.g. OMOP vocabulary CSVs)."""
        files = st.session_state.data_files.setdefault(subfolder, {})
        up = st.file_uploader(f"Upload files into `{subfolder}` (optional; zip large files)",
                              accept_multiple_files=True, key=key)
        for f in up or []:
            if f.name.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(f.read())) as zf:
                    for name in zf.namelist():
                        flat = name.split("/")[-1]
                        if flat and not name.endswith("/"):
                            files[flat] = zf.read(name)
            else:
                files[f.name] = f.read()
        if files:
            st.caption(f"{len(files)} file(s) staged for `{subfolder}`: "
                       + ", ".join(f"`{n}`" for n in list(files)[:8])
                       + (" …" if len(files) > 8 else ""))

    def render_layer(layer, layers_above, runs_after=()):
        """Draw one layer card. Same format for every layer; locked layers
        (table setup) show their filled-in values read-only."""
        lid, locked = layer["id"], layer.get("locked", False)
        with st.container(border=True):

            # ── HEADER ──
            h1, h2, h3 = st.columns([3, 2, 1])
            with h1:
                layer["name"] = st.text_input("Layer name", value=layer["name"], key=f"name_{lid}")
            with h2:
                layer["type"] = st.selectbox(
                    "Layer type", options=LAYER_TYPES,
                    index=LAYER_TYPES.index(layer["type"]) if layer["type"] in LAYER_TYPES else 0,
                    key=f"type_{lid}")
            with h3:
                if not locked:
                    st.write("")
                    st.write("")
                    if st.button("✕ Remove", key=f"rm_{lid}"):
                        st.session_state.layers = [l for l in st.session_state.layers if l["id"] != lid]
                        st.rerun()

            # ── INPUTS ──
            st.markdown("**Inputs**")
            if locked:
                st.caption("None. Runs before every pipeline layer.")
            else:
                above = {l["id"]: (l["name"] or l["type"]) for l in layers_above}
                for inp in list(layer["inputs"]):
                    iid = inp["id"]
                    c1, c2, c3 = st.columns([2, 6, 1])
                    with c1:
                        kinds = ["upstream", "folder"]
                        inp["kind"] = st.selectbox(
                            "Input type", kinds, index=kinds.index(inp["kind"]),
                            format_func=lambda k: {"upstream": "Upstream layer", "folder": "Folder"}[k],
                            key=f"in_kind_{lid}_{iid}")
                    with c2:
                        if inp["kind"] == "upstream":
                            if above:
                                ids = list(above)
                                cur = inp.get("layer_id")
                                inp["layer_id"] = st.selectbox(
                                    "Upstream layer", ids,
                                    index=ids.index(cur) if cur in ids else len(ids) - 1,
                                    format_func=lambda i: above[i], key=f"in_up_{lid}_{iid}")
                            else:
                                st.caption("No layers above this one to read from.")
                                inp["layer_id"] = None
                        else:
                            inp["subfolder"] = folder_picker(
                                "Folder", inp.get("subfolder", ""), key=f"in_fld_{lid}_{iid}")
                    with c3:
                        st.write("")
                        st.write("")
                        if st.button("✕", key=f"in_rm_{lid}_{iid}"):
                            layer["inputs"] = [i for i in layer["inputs"] if i["id"] != iid]
                            st.rerun()
                    if inp["kind"] == "folder" and inp.get("subfolder"):
                        p = volume_path(inp["subfolder"])
                        st.caption(f"Reads from: `{p}`" if p else
                                   "Reads from: fill in Catalog / Schema / Volume in Section 4.")
                        stage_upload(inp["subfolder"], key=f"in_up_files_{lid}_{iid}")
                if st.button("+ Add input", key=f"in_add_{lid}"):
                    layer["inputs"].append({
                        "id": uuid.uuid4().hex[:8],
                        "kind": "upstream" if above else "folder",
                        "layer_id": list(above)[-1] if above else None,
                    })
                    st.rerun()

            # ── ENTRY POINT ──
            st.markdown("**Entry point Script**")
            if locked:
                st.text_input("Entry point Script", value=layer["entry_path"], disabled=True,
                              key=f"entry_{lid}", label_visibility="collapsed")
            else:
                choices = [NO_ENTRY] + runnable_files
                cur = layer.get("entry") or NO_ENTRY
                pick = st.selectbox(
                    "Entry point Script", choices, index=choices.index(cur) if cur in choices else 0,
                    key=f"entry_{lid}", label_visibility="collapsed")
                layer["entry"] = "" if pick == NO_ENTRY else pick
                if not runnable_files:
                    st.caption("Upload .py or .sql scripts in Section 1 to choose one here.")

            # ── PARAMETERS ──
            entry = layer.get("entry")
            if entry and entry.endswith(".sql"):
                st.markdown("**Parameters**")
                st.caption(f"Passed automatically: catalog `{uc_catalog or '(not set)'}`, "
                           f"schema `{uc_schema or '(not set)'}`.")
            elif entry:
                render_script_params([entry], {entry: layer["params"]},
                                     key_prefix=f"params_{lid}", variables=variables)

            # ── DESTINATION ──
            dest = layer["destination"]
            st.markdown("**Destination**")
            if not locked:
                dest["type"] = st.selectbox(
                    "Destination type", ["volume", "tables"],
                    index=0 if dest["type"] == "volume" else 1,
                    format_func=lambda x: {"volume": "Volume folder",
                                           "tables": "Unity Catalog tables"}[x],
                    key=f"dest_type_{lid}")
            if dest["type"] == "volume":
                dest["subfolder"] = folder_picker("Output folder", dest.get("subfolder", ""),
                                                  key=f"dest_{lid}")
                p = volume_path(dest["subfolder"])
                st.caption(f"Output path: `{p}`" if p else
                           "Output path: fill in Catalog / Schema / Volume in Section 4.")
            elif locked:
                tables = dest.get("tables", [])
                st.caption(f"{len(tables)} table(s) in `{uc_catalog or 'catalog'}.{uc_schema or 'schema'}`: "
                           + ", ".join(f"`{t}`" for t in tables) if tables
                           else "No CREATE TABLE statements found in this file.")
            else:
                if st.session_state.gold_tables:
                    dest["tables"] = st.multiselect(
                        "Tables *", options=st.session_state.gold_tables,
                        default=[t for t in dest.get("tables", []) if t in st.session_state.gold_tables],
                        key=f"dest_tables_{lid}",
                        placeholder="Select tables defined in Section 4...")
                    if uc_catalog and uc_schema and dest["tables"]:
                        st.caption(f"Writes to `{uc_catalog}.{uc_schema}.<table>`.")
                else:
                    st.warning("No tables available — select DDL SQL files in Section 4.")
                    dest["tables"] = []
                if runs_after:
                    st.caption("Runs after: " + ", ".join(f"`{n}`" for n in runs_after))


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
            selected_sql = selected_sql or []
            # forget setup stages for files that were deselected
            for gone in set(st.session_state.setup_stages) - set(selected_sql):
                st.session_state.setup_stages.pop(gone)

            for fname in selected_sql:
                file_tables = []
                for t in parse_table_names(st.session_state.src_files[fname]):
                    tc = t.strip('`"').split(".")[-1]
                    if tc and tc not in file_tables:
                        file_tables.append(tc)
                for tc in file_tables:
                    if tc not in st.session_state.gold_tables:
                        st.session_state.gold_tables.append(tc)
                cfg = st.session_state.setup_stages.setdefault(fname, {
                    "name": setup_stage_default_name(fname, len(selected_sql)),
                    "type": "bronze",
                })
                cfg["tables"] = file_tables

            if st.session_state.gold_tables:
                st.success(f"Detected {len(st.session_state.gold_tables)} table(s): "
                           + ", ".join(f"`{t}`" for t in st.session_state.gold_tables))

                st.markdown("**Table setup stages**")
                st.caption("Each DDL file runs as its own stage before any pipeline layer, "
                           "creating its tables in the catalog and schema above.")
                for fname in selected_sql:
                    cfg = st.session_state.setup_stages[fname]
                    layer = setup_layer(fname, cfg)
                    render_layer(layer, layers_above=[])
                    cfg["name"], cfg["type"] = layer["name"], layer["type"]
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
        st.caption(f"All pipeline data lives under: `/Volumes/{uc_catalog}/{uc_schema}/{uc_volume}` "
                   "— folders per layer below.")

    setup_names = [cfg["name"].strip() for f, cfg in st.session_state.setup_stages.items()
                   if f in st.session_state.sql_files]

    for idx, layer in enumerate(st.session_state.layers):
        render_layer(layer, layers_above=st.session_state.layers[:idx], runs_after=setup_names)

    if st.button("+ Add layer"):
        last = st.session_state.layers[-1]["id"] if st.session_state.layers else None
        st.session_state.layers.append(new_layer("", "custom", upstream_id=last))
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

    all_names = setup_names + [(l["name"] or "").strip() for l in st.session_state.layers]
    if any(not n for n in all_names):
        missing.append("A name for every layer")
    dup_names = sorted({n for n in all_names if n and all_names.count(n) > 1})
    if dup_names:
        missing.append("Unique layer names (" + ", ".join(dup_names) + ")")

    if missing:
        st.warning("Required before generating: " + ", ".join(missing))

    # ══════════════════════════════════════════════════════════════════════
    # Build spec — every layer goes through the same function
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

    names_by_id = {l["id"]: (l["name"] or l["type"]).strip() for l in st.session_state.layers}

    def layer_to_stage(layer):
        locked = layer.get("locked", False)

        # sources: upstream layers (by id -> current name) and input folders
        src_out = []
        for inp in layer.get("inputs", []):
            if inp["kind"] == "upstream" and inp.get("layer_id") in names_by_id:
                src_out.append({"data_upload_type": "auto", "from": names_by_id[inp["layer_id"]]})
            elif inp["kind"] == "folder" and (inp.get("subfolder") or "").strip():
                sub = inp["subfolder"].strip()
                entry = {"data_upload_type": "manual", "subfolder_name": sub}
                files = list(st.session_state.data_files.get(sub, {}))
                if files:
                    entry["files"] = files
                src_out.append(entry)

        dest = layer["destination"]
        # table-writing layers run after every table setup stage
        if dest["type"] == "tables" and not locked:
            for sn in setup_names:
                if not any(s.get("from") == sn for s in src_out):
                    src_out.append({"data_upload_type": "auto", "from": sn})

        # entry point script: one script per layer
        if locked:
            entry_point = {"file": layer["entry"], "path": layer["entry_path"], "parameters": []}
        elif layer.get("entry"):
            entry_point = {
                "file":       layer["entry"],
                "path":       f"src/{layer['entry']}",
                "parameters": clean_params(layer["params"]),
            }
        else:
            entry_point = "entry_point_default"

        # destination
        if dest["type"] == "volume":
            dest_out = {"type": "volume"}
            if (dest.get("subfolder") or "").strip():
                dest_out["subfolder_name"] = dest["subfolder"].strip()
        else:
            dest_out = {
                "type":    "tables",
                "catalog": default_or(uc_catalog, "catalog"),
                "schema":  default_or(uc_schema, "schema"),
            }
            if not locked:
                dest_out["tables"] = default_or(dest.get("tables"), "tables")

        return {
            "name":        (layer["name"] or layer["type"]).strip(),
            "layer":       layer["type"],
            "sources":     src_out,
            "entry_point": entry_point,
            "destination": dest_out,
        }

    setup_layers = [setup_layer(f, cfg) for f, cfg in st.session_state.setup_stages.items()
                    if f in st.session_state.sql_files]
    stages = [layer_to_stage(l) for l in setup_layers + st.session_state.layers]

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
            "folders": [
                {"volume": f["volume"].strip(), "subfolder": f["subfolder"].strip()}
                for f in st.session_state.folders
                if f["volume"].strip() and f["subfolder"].strip()
            ],
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