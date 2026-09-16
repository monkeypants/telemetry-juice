#!/bin/sh
# Verify the attribution guard is installed AND that no commit already
# carries a trailer.
#
# The hooks in .githooks/ are only active when core.hooksPath points at
# them, and that is *local git config* — it is not cloned. So a fresh
# clone has no protection at all until someone runs `make install-hooks`.
# A check that runs in `make check` closes that gap: even where the hook
# was never installed, contamination cannot pass review unnoticed.
#
# Two things are checked, because either alone is insufficient:
#   1. the guard is wired up (prevention)
#   2. the history is clean (detection, which works without prevention)
#
# SCAN=all scans every commit rather than just this branch's.

set -u

root=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "not a git repository — nothing to check"; exit 0; }
guard="$root/scripts/reject_attribution.sh"
status=0

test -x "$guard" || { echo "FAIL: $guard missing or not executable"; exit 1; }

# --- 1. is the guard actually wired up? ------------------------------
hookspath=$(git config --get core.hooksPath || echo "")
if [ "$hookspath" != ".githooks" ]; then
    echo "FAIL: core.hooksPath is '${hookspath:-unset}', expected '.githooks'."
    echo "      The hooks are present but inert. Run: make install-hooks"
    status=1
else
    for h in commit-msg pre-push; do
        if [ ! -x "$root/.githooks/$h" ]; then
            echo "FAIL: .githooks/$h missing or not executable"
            status=1
        fi
    done
    [ "$status" -eq 0 ] && echo "    ok — commit-msg and pre-push hooks active"
fi

# --- 2. is the history clean? ----------------------------------------
# Detection works even where prevention was never installed, which is
# the case this check mainly exists for.
if [ "${SCAN:-}" = "all" ]; then
    range="--all"
    label="every commit"
elif git rev-parse --verify -q origin/master >/dev/null; then
    range="origin/master..HEAD"
    label="commits not yet on origin/master"
elif git rev-parse --verify -q master >/dev/null; then
    range="master..HEAD"
    label="commits not yet on master"
else
    range="HEAD"
    label="all commits (no master ref found)"
fi

n=0
bad=0
for sha in $(git rev-list $range 2>/dev/null); do
    n=$((n + 1))
    if ! git log -1 --format='%B' "$sha" | "$guard" >/dev/null 2>&1; then
        printf '\nCONTAMINATED  %s\n' "$(git log -1 --format='%h %s' "$sha")"
        git log -1 --format='%B' "$sha" | "$guard"
        bad=$((bad + 1))
        status=1
    fi
done

if [ "$bad" -eq 0 ]; then
    echo "    ok — $n $label carry no attribution"
else
    echo "$bad of $n commits carry AI attribution."
    echo "Rewrite them before pushing; a trailer that reaches a forge"
    echo "leaves a trace the forge will not delete on request."
fi

exit "$status"
