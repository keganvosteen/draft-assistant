@echo off
rem Launches the Draft Assistant desktop app (pywebview window).
rem pythonw = no console window. If the app fails to open, run
rem "python -m draft_assistant app" in a terminal to see the error.
cd /d "%~dp0"
start "" pythonw -m draft_assistant app
