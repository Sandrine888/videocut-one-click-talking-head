@echo off
rem VideoCut launcher: pick an LLM profile from llm_profiles.json, then run videocut.
set "VCROOT=%~dp0"
set "VCPY=%VCROOT%venv_build\Scripts\python.exe"
if not exist "%VCPY%" set "VCPY=%VCROOT%venv\Scripts\python.exe"
if not exist "%VCPY%" set "VCPY=python"
"%VCPY%" "%VCROOT%videocut_run.py" %*
exit /b %ERRORLEVEL%
