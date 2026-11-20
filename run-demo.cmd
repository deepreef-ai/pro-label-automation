@echo off
rem Wrapper so the demo can be started by double-click or from cmd.exe.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-demo.ps1" %*
exit /b %ERRORLEVEL%
