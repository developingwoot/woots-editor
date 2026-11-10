@echo off
rem Woot's review app. Double-click, or run this file from the repo's tools\review_app folder.
rem Opens http://localhost:8765 here. The app listens on this computer only.
rem The supervisor restarts the app by itself when its code changes (and the open page reloads itself): leave this window open.
rem Python: %WOOTS_PYTHON% if set, else the repo's own .venv, else a venv in %USERPROFILE%\.venvs\wootseditor, else whatever "python" is on PATH.
title Woot's review app
set PYTHONIOENCODING=utf-8
set "PYEXE=%WOOTS_PYTHON%"
if not defined PYEXE if exist "%~dp0..\..\.venv\Scripts\python.exe" set "PYEXE=%~dp0..\..\.venv\Scripts\python.exe"
if not defined PYEXE if exist "%USERPROFILE%\.venvs\wootseditor\Scripts\python.exe" set "PYEXE=%USERPROFILE%\.venvs\wootseditor\Scripts\python.exe"
if not defined PYEXE set "PYEXE=python"
"%PYEXE%" "%~dp0supervisor.py" --open %*
pause
