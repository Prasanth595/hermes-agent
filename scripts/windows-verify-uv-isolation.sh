#!/usr/bin/env bash
# ============================================================================
# Windows host verification for PR #124313 (uv isolation)
# ============================================================================
# Run this INSIDE a Git Bash / MSYS shell on the Windows host, from the repo
# root. It runs the parts of the suite that only mean something on Windows, plus
# the cross-twin guard, and writes a single report you can paste into the PR.
#
#   bash scripts/windows-verify-uv-isolation.sh
#
# Every group goes through scripts/run_tests.sh, the repo's canonical runner, so
# the environment is the one CI uses: an inherited UV_CACHE_DIR / HERMES_HOME /
# locale would otherwise change what the installer tests assert, and the ambient
# %TEMP% would seed every tmp_path fixture.
#
# Nothing here touches the user's real HERMES_HOME: each test builds its own
# temporary home. The script only RUNS tests.
# ============================================================================
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

PY=""
for candidate in ".venv/Scripts/python.exe" "venv/Scripts/python.exe" ".venv/bin/python" "venv/bin/python"; do
    [ -f "$candidate" ] && { PY="$candidate"; break; }
done
if [ -z "$PY" ]; then
    printf 'no repo interpreter found (.venv/Scripts/python.exe); run setup-hermes.ps1 first\n' >&2
    exit 2
fi

REPORT="${REPORT:-./uv-isolation-windows-report.txt}"
: > "$REPORT"

say() { printf '%s\n' "$*" | tee -a "$REPORT"; }
hr() { say "------------------------------------------------------------------------"; }

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) HOST_IS_WINDOWS=1 ;;
    *) HOST_IS_WINDOWS=0 ;;
esac

# A scratch root this run owns, so a damaged ambient temp does not seed every
# tmp_path fixture. run_tests.sh forwards TEMP/TMP into the Windows child.
TEMP_DIR="${TEMP_DIR:-$PWD/.win-verify-tmp}"
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"
export TEMP="$TEMP_DIR" TMP="$TEMP_DIR" TMPDIR="$TEMP_DIR"

say "PR #124313 — Windows verification"
say "date    : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
say "host    : $(uname -srm)"
say "python  : $("$PY" -c 'import sys,platform;print(sys.version.split()[0], platform.machine(), platform.win32_ver()[0] or "n/a")')"
say "scratch : $TEMP_DIR"
hr

# Files that cannot be COLLECTED on native Windows: they import POSIX-only
# modules at module scope (``pty`` -> ``termios``). Unrelated to this branch;
# collecting them would redden a group for a reason that is not under test.
IGNORE=()
if [ "$HOST_IS_WINDOWS" = 1 ]; then
    IGNORE+=(--ignore=tests/scripts/install/test_install_sh_output.py)
fi

# Every group below is a surface the POSIX lane cannot cover, or covers with a
# forced platform rather than the real one. Each group lists the files THIS BRANCH
# touches, not whole directories: a directory sweep also drags in files that fail
# on Windows for reasons of their own, and a report where most red is unrelated
# hides the rows under test.
SURFACES=(
  "resolver ladder + cross-twin|tests/scripts/bootstrap/"
  "installer contracts          |tests/scripts/install/test_bootstrap_store_root_matches_pm.py tests/scripts/install/test_install_ps1_home_env_folds.py tests/scripts/install/test_install_ps1_uv_no_path_borrow.py tests/scripts/install/test_install_sh_uv_no_path_borrow.py tests/scripts/install/test_install_sh_uv_state.py tests/scripts/install/test_setup_hermes_ps1_uv_state.py tests/scripts/install/test_install_sh_repository_stage.py"
  "legacy uv cleanup            |tests/hermes_cli/test_legacy_uv_cleanup.py tests/hermes_cli/test_legacy_uv_lock.py"
  "doctor legacy uv             |tests/hermes_cli/test_doctor_legacy_uv.py"
  "update notice                |tests/hermes_cli/test_update_legacy_uv_notice.py"
  "uninstall launchers          |tests/hermes_cli/test_uninstall_windows_bin_launchers.py"
  "runtime self protection      |tests/agent/test_runtime_self_protection.py"
  "setup script                 |tests/hermes_cli/test_setup_hermes_script.py"
  "pm lock + activation         |tests/pm/test_store_lock_wait.py tests/pm/test_activate_scripts.py tests/pm/test_activation_setup.py tests/pm/test_setup_lock_format.py"
)

FAILED=0
for entry in "${SURFACES[@]}"; do
    name="${entry%%|*}"
    args="${entry#*|}"
    say ""
    say "### ${name% }"
    # shellcheck disable=SC2086  # args is intentionally word-split
    out=$(scripts/run_tests.sh $args ${IGNORE[@]+"${IGNORE[@]}"} 2>&1)
    rc=$?
    # The runner prints one line per file plus a Summary; keep both.
    printf '%s\n' "$out" | grep -E "^(=== Summary|\s+✗|✗ )|tests? (passed|failed)" | tee -a "$REPORT" | tail -n 6
    if [ $rc -ne 0 ]; then
        FAILED=$((FAILED + 1))
        say ">>> FAILED (exit $rc)"
        # Name the files, so the reader does not have to re-run to find them.
        printf '%s\n' "$out" | grep -E "✗ tests/" | tee -a "$REPORT"
    fi
done

hr
say ""
say "### Known pre-existing Windows failures inside these groups"
say ""
say "tests/agent/test_runtime_self_protection.py carries three failures on Windows"
say "that reproduce on the base commit and are not addressed by this branch —"
say "_split_words parses the command with shlex in POSIX mode, so an unquoted"
say "C:\\... path loses its backslashes and 'rm -rf <path>' never matches a"
say "protected path. Expected on every Windows host:"
say "  test_rm_rf_of_own_venv_is_detected"
say "  test_rm_of_whole_uv_install_dir_is_detected"
say "  test_windows_del_and_powershell_spellings"
say ""
say "### Expected platform skips"
say "Rows marked platforms(\"posix\") skip here by design; that is not a failure."
say "The rows this run exists for are platforms(\"windows\") and platforms(\"any\")."
say ""
say "### Manual probes the suite cannot assert"
say ""
say "1. No Hermes uv on PATH (new install):"
say "     where uv        # must NOT print <root>\\\\bin\\\\uv.exe"
say "     where hermes    # must print <root>\\\\bin\\\\hermes.exe"
say ""
say "2. Residue (only on a machine installed before 2026-08-31):"
say "     where uv              # prints <root>\\\\bin\\\\uv.exe  <- the shadow"
say "     hermes doctor         # must name it, and on Windows say 'by hand'"
say "     hermes update         # must still PRINT the notice (it cannot auto-fix here)"
say "     hermes doctor --fix   # must refuse and keep the file"
say ""
say "3. The notice/doctor text must name a home, and the files must be there:"
say "     dir <root>\\\\bin\\\\uv*"
say ""
hr
if [ "$FAILED" -eq 0 ]; then
    say "RESULT: all groups passed"
else
    say "RESULT: $FAILED group(s) FAILED"
fi
say "report written to: $REPORT"

[ "$FAILED" -eq 0 ]
