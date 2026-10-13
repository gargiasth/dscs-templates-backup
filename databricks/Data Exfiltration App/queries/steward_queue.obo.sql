SELECT
  request_id,
  submitter,
  dataset,
  justification,
  format,
  status,
  created_at,
  steward,
  steward_comment,
  approved_at,
  rejected_at,
  output_url,
  study_name,
  access_tier,
  dbgap_status,
  consent_group,
  submitter_role,
  submitter_expiration_ts,
  submitter_decision,
  submitter_decision_basis
FROM governed.default.steward_queue
ORDER BY created_at DESC
