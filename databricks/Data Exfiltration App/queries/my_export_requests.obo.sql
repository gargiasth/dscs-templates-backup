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
  expires_at
FROM governed.default.export_requests
WHERE submitter = current_user()
ORDER BY created_at DESC
