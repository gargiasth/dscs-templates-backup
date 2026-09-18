SELECT
  current_user() AS user_email,
  is_account_group_member('bdc-stewards') AS is_steward,
  is_account_group_member('bdc-analysts') AS is_analyst
