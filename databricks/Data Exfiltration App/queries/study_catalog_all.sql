SELECT
  dataset_id,
  study_name,
  access_tier,
  consent_group,
  dbgap_status,
  source_platform
FROM governed.default.study_catalog
ORDER BY study_name
