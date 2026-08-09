@echo off
REM Wrapper around dev.ps1, so the project starts the same way from anywhere.
REM
REM dev.ps1 alone only works when it is invoked from a PowerShell prompt that is
REM already sitting in this folder. That leaves three ways to "run the script" that
REM all fail: cmd.exe does not understand .\dev.ps1, double-clicking a .ps1 opens it
REM in an editor rather than running it, and any shell in another directory cannot
REM find it. This file fixes all three -- %~dp0 is where this file lives, so the
REM working directory of the caller does not matter.

setlocal
pushd "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %*
set "exitcode=%ERRORLEVEL%"
popd

REM No "pause" on the way out. Detecting a double-click means inspecting
REM %cmdcmdline%, which also matches an ordinary scripted call -- and a launcher
REM that blocks forever waiting for a keypress nobody is there to press is a worse
REM failure than a console window closing too fast. Run this from a terminal.

exit /b %exitcode%
