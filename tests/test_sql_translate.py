r"""
Tests for the psql \COPY -> COPY INTO rule in utilities/sql_translate.py

Run from the repo root:
    pytest tests/test_sql_translate_copy.py
"""

from utilities.sql_translate import translate


# ── psql \COPY → COPY INTO ───────────────────────────────────────────────────

COPY_LINE = r"\COPY CARE_SITE FROM 'care_site.csv' WITH DELIMITER E',' CSV HEADER QUOTE E'\b';"
DATA_DIR  = "/Volumes/cat/sch/vol/silver_output"


class TestPsqlCopy:
    def test_happy_becomes_copy_into(self):
        """Happy path: \\COPY turns into COPY INTO from data_dir, by position, header skipped."""
        [r] = translate(COPY_LINE, read="postgres", dialect="databricks", params={"data_dir": DATA_DIR})
        assert r["unsupported_reason"] is None
        sql = r["sql"]
        assert sql.startswith("COPY INTO care_site BY POSITION FROM '/Volumes/cat/sch/vol/silver_output'")
        assert "PATTERN = 'care_site{.csv,_[0-9]*.csv}'" in sql
        assert "'skipRows' = '1'" in sql and "'header' = 'false'" in sql
        assert "'delimiter' = ','" in sql and "'quote' = ''" in sql

    def test_happy_column_list_kept(self):
        """Happy path: a column list loads into those columns instead of by position."""
        line = r"\copy person (person_id, year_of_birth) FROM 'person.csv' CSV;"
        [r] = translate(line, read="postgres", dialect="databricks", params={"data_dir": DATA_DIR})
        assert r["sql"].startswith("COPY INTO person (person_id, year_of_birth) FROM")
        assert "skipRows" not in r["sql"]

    def test_happy_order_kept_with_other_sql(self):
        """Happy path: statements around \\COPY stay in file order."""
        sql = "CREATE TABLE a (x INT);\n" + COPY_LINE + "\nCREATE TABLE b (y INT);\n"
        out = translate(sql, read="postgres", dialect="databricks", params={"data_dir": DATA_DIR})
        assert [o["sql"].split()[0:3] for o in out] == [
            ["CREATE", "TABLE", "a"], ["COPY", "INTO", "care_site"], ["CREATE", "TABLE", "b"]]

    def test_happy_crlf_line_endings(self):
        """Happy path: Windows line endings still match."""
        out = translate(COPY_LINE + "\r\n" + COPY_LINE + "\r\n", read="postgres",
                        dialect="databricks", params={"data_dir": DATA_DIR})
        assert len(out) == 2 and all(o["unsupported_reason"] is None for o in out)

    def test_pattern_does_not_catch_longer_table(self):
        """Happy path: 'observation' must not pick up observation_period_2.csv."""
        line = r"\COPY OBSERVATION FROM 'observation.csv' CSV HEADER;"
        [r] = translate(line, read="postgres", dialect="databricks", params={"data_dir": DATA_DIR})
        assert "PATTERN = 'observation{.csv,_[0-9]*.csv}'" in r["sql"]

    def test_forgetful_no_data_dir_flagged(self):
        """Forgetful: without data_dir the statement is flagged, not guessed."""
        [r] = translate(COPY_LINE, read="postgres", dialect="databricks")
        assert "data_dir" in r["unsupported_reason"]

    def test_databricks_rejects_nothing_but_needs_a_path(self):
        """Forgetful: an empty data_dir is treated as missing."""
        [r] = translate(COPY_LINE, read="postgres", dialect="databricks", params={"data_dir": ""})
        assert "data_dir" in r["unsupported_reason"]


STAGE = "@orion_stage/silver_output"


class TestPsqlCopySnowflake:
    def test_happy_becomes_copy_into_from_stage(self):
        """Happy path: \\COPY turns into Snowflake COPY INTO from the stage, header skipped."""
        [r] = translate(COPY_LINE, read="postgres", dialect="snowflake", params={"data_dir": STAGE})
        assert r["unsupported_reason"] is None
        sql = r["sql"]
        assert sql.startswith("COPY INTO care_site FROM @orion_stage/silver_output/ ")
        assert "PATTERN = '(.*/)?care_site(_[0-9]+)?[.]csv'" in sql
        assert "SKIP_HEADER = 1" in sql and "FIELD_DELIMITER = ','" in sql
        assert "ENCLOSED_BY" not in sql          # QUOTE E'\\b' means no quoting

    def test_pattern_matches_the_same_files_as_databricks(self):
        """Happy path: person.csv and person_2.csv match; observation_period_2.csv doesn't match observation."""
        import re
        line = r"\COPY OBSERVATION FROM 'observation.csv' CSV HEADER;"
        [r] = translate(line, read="postgres", dialect="snowflake", params={"data_dir": STAGE})
        pattern = re.search(r"PATTERN = '([^']*)'", r["sql"]).group(1)
        assert re.fullmatch(pattern, "silver_output/observation_2.csv")
        assert re.fullmatch(pattern, "observation.csv")
        assert not re.fullmatch(pattern, "silver_output/observation_period_2.csv")

    def test_happy_column_list_uses_select(self):
        """Happy path: a column list loads through SELECT $1, $2 ..."""
        line = r"\copy person (person_id, year_of_birth) FROM 'person.csv' CSV;"
        [r] = translate(line, read="postgres", dialect="snowflake", params={"data_dir": STAGE})
        assert r["sql"].startswith(
            "COPY INTO person (person_id, year_of_birth) FROM (SELECT $1, $2 FROM @orion_stage/silver_output/)")

    def test_angry_volume_path_rejected(self):
        """Angry path: a /Volumes path isn't a Snowflake stage, so it's flagged."""
        [r] = translate(COPY_LINE, read="postgres", dialect="snowflake",
                        params={"data_dir": "/Volumes/cat/sch/vol/silver_output"})
        assert "stage" in r["unsupported_reason"]