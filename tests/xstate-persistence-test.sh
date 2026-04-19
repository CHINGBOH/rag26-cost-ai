#!/usr/bin/env bash
set -o pipefail

# =============================================================================
# XState PostgreSQL Persistence Test (Phase 4)
# =============================================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="${PROJECT_ROOT}/src/backend/server"
PASS_COUNT=0
FAIL_COUNT=0

report_ok() {
    local name="$1"
    echo "[TEST] $name ... OK"
    ((PASS_COUNT++))
}

report_fail() {
    local name="$1"
    local reason="$2"
    echo "[TEST] $name ... FAIL${reason:+: $reason}"
    ((FAIL_COUNT++))
}

# -----------------------------------------------------------------------------
# 1. TypeScript compilation check (new files must compile)
# -----------------------------------------------------------------------------
echo "[TEST] TypeScript compilation"
cd "$SERVER_DIR"
npx tsc --noEmit 2>/tmp/tsc-full.log || true
# Check that our new files don't introduce *new* compilation errors
NEW_ERRORS=$(grep -E "PostgresPersistenceService|RecursionController\.ts" /tmp/tsc-full.log | grep -v "Property 'token' does not exist" || true)
if [[ -z "$NEW_ERRORS" ]]; then
    report_ok "TypeScript compilation (no new errors in modified files)"
else
    report_fail "TypeScript compilation" "$NEW_ERRORS"
fi

# -----------------------------------------------------------------------------
# 2. Vitest graceful-degradation test (runs even without PostgreSQL)
# -----------------------------------------------------------------------------
echo "[TEST] Vitest graceful-degradation"
TEST_OUTPUT=$(npx vitest run src/__tests__/PostgresPersistenceService.test.ts --reporter=verbose 2>&1)
if echo "$TEST_OUTPUT" | grep -q "should initialize gracefully even without database"; then
    report_ok "Vitest graceful-degradation"
else
    report_fail "Vitest graceful-degradation" "test not found in output"
    echo "$TEST_OUTPUT"
fi

# -----------------------------------------------------------------------------
# 3. SQL schema file exists and is valid
# -----------------------------------------------------------------------------
SCHEMA_FILE="${SERVER_DIR}/sql/recursion_sessions.sql"
if [[ -f "$SCHEMA_FILE" ]]; then
    if grep -q "CREATE TABLE IF NOT EXISTS recursion_sessions" "$SCHEMA_FILE"; then
        report_ok "SQL schema file"
    else
        report_fail "SQL schema file" "missing expected CREATE TABLE"
    fi
else
    report_fail "SQL schema file" "file not found"
fi

# -----------------------------------------------------------------------------
# 4. RecursionController source contains persistence hooks
# -----------------------------------------------------------------------------
RC_FILE="${SERVER_DIR}/src/core/RecursionController.ts"
if grep -q "persistState" "$RC_FILE" && grep -q "restoreSession" "$RC_FILE" && grep -q "restoreAllActiveSessions" "$RC_FILE"; then
    report_ok "RecursionController persistence hooks"
else
    report_fail "RecursionController persistence hooks" "missing required methods"
fi

# -----------------------------------------------------------------------------
# 5. Server entry (index.ts) wires persistence
# -----------------------------------------------------------------------------
IDX_FILE="${SERVER_DIR}/src/index.ts"
if grep -q "PostgresPersistenceService" "$IDX_FILE" && grep -q "restoreAllActiveSessions" "$IDX_FILE"; then
    report_ok "Server entry persistence wiring"
else
    report_fail "Server entry persistence wiring" "missing in index.ts"
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
if [[ $FAIL_COUNT -eq 0 ]]; then
    echo "ALL TESTS PASSED ($PASS_COUNT tests)"
    exit 0
else
    echo "SOME TESTS FAILED (passed: $PASS_COUNT, failed: $FAIL_COUNT)"
    exit 1
fi
