@echo off
setlocal
cd /d "%~dp0" || exit /b 1

set "NODE_EXE=node.exe"
where.exe node.exe >nul 2>&1
if errorlevel 1 (
  set "NODE_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
)

"%NODE_EXE%" --version >nul 2>&1
if errorlevel 1 (
  echo Node.js was not found. Install Node.js 22.12 or newer, then try again.
  pause
  exit /b 1
)

if not exist "node_modules\vite\bin\vite.js" (
  echo Project dependencies are missing. See README.md for first-time setup.
  pause
  exit /b 1
)

"%NODE_EXE%" "node_modules\vite\bin\vite.js" --host 127.0.0.1 --port 5173 --strictPort
if errorlevel 1 pause
