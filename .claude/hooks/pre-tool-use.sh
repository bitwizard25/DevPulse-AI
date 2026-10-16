#!/usr/bin/env bash
# DevPulse Compiler-as-a-Judge PreToolUse hook
# Enforces exit code 2 on syntax failure or secret leak
devpulse verify "$@"
EXIT_CODE=$?
if [ $EXIT_CODE -eq 2 ]; then
  exit 2
fi
exit 0
