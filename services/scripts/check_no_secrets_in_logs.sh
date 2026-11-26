#!/usr/bin/env bash
# Release checklist: no secret appears in logs during the full test suite.
# Runs every test with all output shown, then looks for each test-only secret value
# (listed in tests/secret_values.txt).
set -uo pipefail
cd "$(dirname "$0")/.."
log="$(mktemp)"
trap 'rm -f "$log"' EXIT

uv run pytest -q -s -p no:cacheprovider >"$log" 2>&1
status=$?
tail -n 1 "$log"
if [ "$status" -ne 0 ]; then
  echo "The tests failed, so the log check means nothing. Fix them first." >&2
  exit "$status"
fi
if grep -n -F -f tests/secret_values.txt "$log"; then
  echo "A secret value was written to the test output (lines above)." >&2
  exit 1
fi
echo "No secret values in $(wc -l <"$log") lines of test output."
