@echo off
rem Wrapper so the demo can be started by double-click or from cmd.exe.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0reset-demo.ps1" %*
exit /b %ERRORLEVEL%
