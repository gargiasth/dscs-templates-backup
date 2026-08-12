-- Role-scoped app audit log. Runs OBO (as the logged-in user), so the row
-- filter in governed.default.audit_events_scoped decides visibility:
--   * stewards (bdc-stewards) -> every event
--   * everyone else           -> only rows where user = current_user()
SELECT
  event_id,
  `timestamp`,
  `user`,
  action_type,
  resource,
  outcome,
  details
FROM governed.default.audit_events_scoped
ORDER BY `timestamp` DESC
