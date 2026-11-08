@echo off
setlocal
cd /d "%~dp0"
set "URL=http://127.0.0.1:8777"
if exist "data\server_url.txt" set /p URL=<"data\server_url.txt"
start "" "%URL%"
endlocal
