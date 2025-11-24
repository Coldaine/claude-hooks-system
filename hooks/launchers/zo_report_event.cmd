@echo off
REM Windows launcher for zo_report_event.py hook
REM Usage: Invoked automatically by Claude Code hooks system

python "%~dp0..\zo_report_event.py" %*
