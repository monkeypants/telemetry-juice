#!/bin/sh
# Assert the hooks are installed and still contain the gates they claim to.
#
# Every other guard in this repository is tested; the hooks that enforce them
# were not. Two ways they fail quietly:
#
#   - core.hooksPath is unset in a fresh clone, so a new checkout has no
#     protection at all and nothing says so;
#   - a pre-push hook reads its refs from stdin, which can only be consumed
#     once. Add a second loop the obvious way and the *first* check passes
#     while the second reads an empty stdin and passes vacuously. That is a
#     guard that reports success because it did nothing.
#
# These are static assertions, which is the cheap half of the job. The
# expensive half — actually pushing to master and to a branch carrying a
# trailer, and watching both be refused — is done by hand when the hook
# changes, because a test that pushes for real needs a remote to push to.

root=$(git rev-parse --show-toplevel)
hook="$root/.githooks/pre-push"
status=0

fail() {
    printf '  FAIL  %s\n' "$1"
    status=1
}

[ "$(git config core.hooksPath)" = ".githooks" ] \
    || fail "core.hooksPath is not .githooks — run: make install-hooks"

[ -x "$hook" ] || fail "pre-push is not executable"

grep -q 'refs/heads/master' "$hook" \
    || fail "pre-push has no master gate — direct pushes would be allowed"

grep -q 'ALLOW_MASTER_PUSH' "$hook" \
    || fail "pre-push has no documented override for the master gate"

grep -q 'reject_attribution.sh' "$hook" \
    || fail "pre-push does not run the attribution guard"

# The stdin trap. If the hook reads stdin inside a loop rather than capturing
# it first, a second loop gets nothing and passes without checking anything.
grep -q 'refs=$(cat)' "$hook" \
    || fail "pre-push does not capture stdin up front; a second gate would pass vacuously"

grep -q 'reject_attribution.sh' "$root/.githooks/commit-msg" \
    || fail "commit-msg does not run the attribution guard"

if [ "$status" -eq 0 ]; then
    printf '    ok — pre-push refuses master and attribution; commit-msg is wired\n'
fi
exit "$status"
