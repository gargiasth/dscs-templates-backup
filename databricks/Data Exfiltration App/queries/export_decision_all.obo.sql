SELECT
  dataset_id,
  access_tier,
  dbgap_status,
  user_id,
  role,
  expiration_ts,
  decision,
  decision_basis
FROM governed.default.export_decision_all
ORDER BY dataset_id, user_id
