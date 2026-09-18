#!/usr/bin/env bash
#
# sync_poc_role.sh — align user_dbgap_permissions.poc_role with real Unity
# Catalog account-group membership.
#
# Rules:
#   * member of bdc-stewards                -> poc_role = 'steward'
#   * member of bdc-analysts (only)         -> poc_role = 'analyst'
#   * member of BOTH                        -> 'steward' (highest role wins)
#   * member of NEITHER (synthetic demo users) -> left unchanged
#
# is_account_group_member() only evaluates for the current caller, so this
# cannot be a pure-SQL view — membership is read via the account SCIM API and
# written back to the table. Re-run after changing group membership.
#
# Usage: ./scripts/sync_poc_role.sh [PROFILE] [WAREHOUSE_ID]

set -euo pipefail

PROFILE="${1:-artdscs}"
WAREHOUSE="${2:-69e7e6f0afe612c9}"
TABLE="governed.default.user_dbgap_permissions"

group_members() { # $1 = group display name -> newline-separated member emails
  local gid
  gid=$(databricks groups list --filter "displayName eq \"$1\"" --profile "$PROFILE" -o json |
    python3 -c "import json,sys; g=json.load(sys.stdin); print(g[0]['id'] if g else '')")
  if [[ -z "$gid" ]]; then
    echo "group not found: $1" >&2
    return 1
  fi
  databricks api get "/api/2.0/account/scim/v2/Groups/$gid?attributes=members" --profile "$PROFILE" |
    python3 -c "import json,sys; g=json.load(sys.stdin); print('\n'.join(m.get('display','') for m in g.get('members',[])))"
}

sql_in_list() { # stdin: newline-separated emails -> 'a','b','c'
  python3 -c "import sys; vals=[v.strip() for v in sys.stdin if v.strip()]; print(','.join(\"'\"+v.replace(\"'\",\"''\")+\"'\" for v in vals))"
}

STEWARDS=$(group_members bdc-stewards)
ANALYSTS=$(group_members bdc-analysts)

STEWARDS_IN=$(printf '%s\n' "$STEWARDS" | sql_in_list)
# Steward wins: exclude steward members from the analyst update.
ANALYSTS_ONLY_IN=$(printf '%s\n' "$ANALYSTS" | grep -Fxv -f <(printf '%s\n' "$STEWARDS") | sql_in_list || true)

run_sql() {
  databricks experimental aitools tools query --profile "$PROFILE" -w "$WAREHOUSE" "$1"
}

if [[ -n "$STEWARDS_IN" ]]; then
  echo "-> stewards: $STEWARDS_IN"
  run_sql "UPDATE $TABLE SET poc_role = 'steward' WHERE user_id IN ($STEWARDS_IN) AND poc_role <> 'steward'"
fi

if [[ -n "$ANALYSTS_ONLY_IN" ]]; then
  echo "-> analysts (not stewards): $ANALYSTS_ONLY_IN"
  run_sql "UPDATE $TABLE SET poc_role = 'analyst' WHERE user_id IN ($ANALYSTS_ONLY_IN) AND poc_role <> 'analyst'"
fi

echo "-> verify"
run_sql "SELECT user_id, poc_role FROM $TABLE GROUP BY user_id, poc_role ORDER BY user_id"
