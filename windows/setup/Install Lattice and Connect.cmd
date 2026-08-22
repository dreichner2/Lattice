@echo off
setlocal
cd /d "%~dp0\..\.."
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-LatticeWindows.ps1" -LibraryRoot "%~dp0..\.."
set "lattice_setup_exit=%ERRORLEVEL%"
echo.
if not "%lattice_setup_exit%"=="0" (
  echo Lattice setup stopped with an error. Nothing on the Mac mini was changed.
) else (
  echo Keep this window open long enough to copy the Windows Device ID shown above.
)
pause
exit /b %lattice_setup_exit%
