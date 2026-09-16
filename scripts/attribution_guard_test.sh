#!/bin/sh
# Prove the guard rejects what it claims to reject.
#
# An untested guard is a comment. These cases are the real trailers that
# have actually been injected into sessions, not invented examples.

set -u
guard="$(git rev-parse --show-toplevel)/scripts/reject_attribution.sh"
pass=0
fail=0

reject() { # description, message
    if printf '%s\n' "$2" | "$guard" >/dev/null 2>&1; then
        echo "  FAIL  should have been REJECTED: $1"; fail=$((fail + 1))
    else
        echo "    ok  rejected: $1"; pass=$((pass + 1))
    fi
}
accept() {
    if printf '%s\n' "$2" | "$guard" >/dev/null 2>&1; then
        echo "    ok  accepted: $1"; pass=$((pass + 1))
    else
        echo "  FAIL  should have been ACCEPTED: $1"; fail=$((fail + 1))
    fi
}

reject "Co-Authored-By Claude"        "Add a thing

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
reject "Claude-Session trailer"       "Add a thing

Claude-Session: https://claude.ai/code/session_01ABC"
reject "Generated with Claude Code"   "Add a thing

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
reject "bare robot emoji"             "Add a thing 🤖"
reject "claude.ai/code link"          "Add a thing

https://claude.ai/code/session_xyz"
reject "lowercase co-authored-by"     "Add a thing

co-authored-by: claude <x@anthropic.com>"
reject "Assisted-By AI"               "Add a thing

Assisted-By: AI"
reject "Copilot co-author"            "Add a thing

Co-authored-by: Copilot <copilot@github.com>"

# Case variants. Not decoration: matching used to be case-encoded per
# pattern, so a line that forgot its [Cc] left exactly these spellings
# open. The check is case-insensitive now and these hold it there - an
# agent told to attribute itself will not politely use the capitalised
# form the pattern was written against.
reject "SHOUTED trailer"              "Add a thing

CO-AUTHORED-BY: CLAUDE <NOREPLY@ANTHROPIC.COM>"
reject "mIxEd case trailer"           "Add a thing

cO-aUtHoReD-bY: Claude"
reject "shouted generated-with"       "Add a thing

GENERATED WITH CLAUDE CODE"
reject "mixed case session trailer"   "Add a thing

CLAUDE-session: https://CLAUDE.ai/code/x"
reject "uppercase assisted-by"        "Add a thing

ASSISTED-BY: AI"

accept "a clean kernel-style message" "Add worker extra with LLM dependency

Adds 'worker' optional dependency group to pyproject.toml
and updates Dockerfile.worker to install it."
reject "a human co-author"            "Fix the thing

Co-Authored-By: A Person <person@example.com>"
reject "Assisted-By a human"          "Fix the thing

Assisted-By: A Person <person@example.com>"
accept "the rule named in a comment"  "Add a thing

# reminder: never add Co-Authored-By: Claude here"
accept "credit as prose in the body"  "Fix the thing

Found and diagnosed by a colleague; the fix and this commit are mine."

echo
if [ "$fail" -ne 0 ]; then
    echo "$fail case(s) FAILED, $pass passed"
    exit 1
fi
echo "all $pass attribution guard cases passed"
