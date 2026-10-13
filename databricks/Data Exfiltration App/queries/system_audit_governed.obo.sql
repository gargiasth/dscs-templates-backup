SELECT
  CAST(event_time AS STRING) AS event_time,
  COALESCE(user_identity.email, '') AS user_email,
  service_name,
  action_name,
  COALESCE(request_params['full_name_arg'], request_params['name_arg'], '') AS target,
  CAST(response.status_code AS STRING) AS status_code
FROM system.access.audit
WHERE event_date >= current_date() - INTERVAL 30 DAYS
  AND (
    request_params['full_name_arg'] LIKE 'governed.default.%'
    OR request_params['name_arg'] LIKE 'governed%'
  )
ORDER BY event_time DESC
LIMIT 200
