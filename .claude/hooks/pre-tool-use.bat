@echo off
rem DevPulse Compiler-as-a-Judge PreToolUse hook
rem Enforces exit code 2 on syntax failure or secret leak
devpulse verify %*
if errorlevel 2 exit /b 2
exit /b 0
