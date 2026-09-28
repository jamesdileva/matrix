@echo off
rem Locator wrapper: forwards all arguments to the Godot engine executable.
rem Resolution order: GODOT_EXE env var, `godot` on PATH, newest winget
rem install under %LOCALAPPDATA%. Keeps scripts working as bare shell lines
rem from the repo root (same pattern as the surfhop project).

setlocal
if defined GODOT_EXE (
    "%GODOT_EXE%" %*
    endlocal & exit /b %errorlevel%
)
where godot >nul 2>nul
if %errorlevel%==0 (
    godot %*
    endlocal & exit /b %errorlevel%
)
set "GODOT_FOUND="
for /f "delims=" %%i in ('dir /s /b "%LOCALAPPDATA%\Microsoft\WinGet\Packages\Godot_v*.exe" 2^>nul ^| findstr /i "GodotEngine.GodotEngine_"') do (
    if not defined GODOT_FOUND set "GODOT_FOUND=%%i"
)
if not defined GODOT_FOUND (
    echo godot.cmd: no Godot executable found ^(set GODOT_EXE^) >&2
    exit /b 1
)
"%GODOT_FOUND%" %*
endlocal & exit /b %errorlevel%
