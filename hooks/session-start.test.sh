#!/bin/sh
# Test for session-start.sh — verifies the hook's behavioral contract:
# it must emit the backlog reflex reminder (marker + storage path) and exit 0,
# otherwise the E2 always-on reflex silently breaks.
DIR=$(dirname "$0")
out=$(sh "$DIR/session-start.sh")
code=$?
fail=0

[ "$code" -eq 0 ] || { echo "FAIL: non-zero exit ($code)"; fail=1; }

case "$out" in
  *"[backlog]"*) ;;
  *) echo "FAIL: output missing [backlog] marker"; fail=1 ;;
esac

case "$out" in
  *"docs/backlogs"*) ;;
  *) echo "FAIL: output missing docs/backlogs reference"; fail=1 ;;
esac

if [ "$fail" -eq 0 ]; then
  echo "PASS: session-start.sh emits the reflex reminder and exits 0"
else
  exit 1
fi
