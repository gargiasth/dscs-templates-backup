"""Tests for validation/validation.py — no real Spark; FakeSpark simulates the workspace."""

import pytest

from validation.preflight_validator import preflight, ValidationError


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def collect(self):
        return self._rows


class FakeSpark:
    """Simulates which catalogs/schemas/volumes exist. CREATE adds them."""

    def __init__(self, catalogs=(), schemas=(), volumes=(), deny=()):
        self.catalogs, self.schemas, self.volumes = set(catalogs), set(schemas), set(volumes)
        self.deny = set(deny)          # statement prefixes that raise PERMISSION_DENIED
        self.calls = []

    def sql(self, q):
        self.calls.append(q)
        if any(q.startswith(d) for d in self.deny):
            raise RuntimeError("PERMISSION_DENIED: User does not have privilege")
        name = q.split("'")[1] if "'" in q else None
        if q.startswith("SHOW CATALOGS"):
            return _Result([1] if name in self.catalogs else [])
        if q.startswith("SHOW SCHEMAS"):
            return _Result([1] if name in self.schemas else [])
        if q.startswith("SHOW VOLUMES"):
            return _Result([1] if name in self.volumes else [])
        last = q.split(".")[-1].split()[-1].strip("`")
        if q.startswith("CREATE CATALOG"):
            self.catalogs.add(last)
        elif q.startswith("CREATE SCHEMA"):
            self.schemas.add(last)
        elif q.startswith("CREATE VOLUME"):
            self.volumes.add(last)
        return _Result([])


def test_everything_exists_creates_nothing():
    spark = FakeSpark(catalogs={"c"}, schemas={"s"}, volumes={"v"})
    preflight(spark, "c", "s", ["v"])
    assert not any(q.startswith("CREATE") for q in spark.calls)


def test_missing_objects_are_created_in_order():
    spark = FakeSpark()
    preflight(spark, "c", "s", ["v"])
    creates = [q.split()[1] for q in spark.calls if q.startswith("CREATE")]
    assert creates == ["CATALOG", "SCHEMA", "VOLUME"]


def test_creation_is_logged_as_warning(caplog):
    preflight(FakeSpark(), "c", "s", ["v"])
    assert "Created catalog c" in caplog.text
    assert "Created volume c.s.v" in caplog.text


def test_names_are_backtick_quoted():
    spark = FakeSpark()
    preflight(spark, "etl-cms", "s", ["v"])
    assert "CREATE CATALOG IF NOT EXISTS `etl-cms`" in spark.calls


def test_permission_denied_names_the_privilege():
    spark = FakeSpark(deny={"CREATE CATALOG"})
    with pytest.raises(ValidationError, match="CREATE CATALOG on the metastore"):
        preflight(spark, "c", "s", ["v"])


def test_use_schema_denied_names_the_privilege():
    spark = FakeSpark(catalogs={"c"}, schemas={"s"}, volumes={"v"}, deny={"USE SCHEMA"})
    with pytest.raises(ValidationError, match="USE SCHEMA on c.s"):
        preflight(spark, "c", "s", ["v"])


def test_other_errors_are_not_hidden():
    class Broken(FakeSpark):
        def sql(self, q):
            raise RuntimeError("network down")
    with pytest.raises(RuntimeError, match="network down"):
        preflight(Broken(), "c", "s", ["v"])


def test_every_volume_is_checked():
    spark = FakeSpark(catalogs={"c"}, schemas={"s"}, volumes={"v"})
    preflight(spark, "c", "s", ["v", "ref_data"])
    creates = [q for q in spark.calls if q.startswith("CREATE")]
    assert creates == ["CREATE VOLUME IF NOT EXISTS `c`.`s`.`ref_data`"]


def test_repeated_and_blank_volumes_are_checked_once():
    spark = FakeSpark(catalogs={"c"}, schemas={"s"})
    preflight(spark, "c", "s", ["v", "", "v"])
    assert sum(q.startswith("SHOW VOLUMES") for q in spark.calls) == 2   # before and after creating v


def test_unknown_platform_is_refused():
    with pytest.raises(ValidationError, match="not supported yet"):
        preflight(FakeSpark(), "c", "s", ["v"], platform="foundry")


def test_platform_sql_has_every_step():
    # guards the agnostic design: a new platform entry must fill in every step
    from validation.preflight_validator import _PLATFORMS
    steps = {"quote", "words", "show_catalog", "create_catalog", "use_catalog",
             "show_schema", "create_schema", "use_schema", "show_volume", "create_volume"}
    for name, sql in _PLATFORMS.items():
        assert steps <= set(sql), f"{name} is missing {steps - set(sql)}"