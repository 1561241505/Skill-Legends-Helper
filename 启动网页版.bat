@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title 选技大乱斗 - 网页版

set "PYTHON_EXE=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
set "PYTHON_ARGS="
if not exist "%PYTHON_EXE%" goto try_py
"%PYTHON_EXE%" -c "import numpy, PIL" >nul 2>nul
if not errorlevel 1 goto run

:try_py
set "PYTHON_EXE=py"
set "PYTHON_ARGS=-3"
%PYTHON_EXE% %PYTHON_ARGS% -c "import numpy, PIL" >nul 2>nul
if not errorlevel 1 goto run

set "PYTHON_EXE=python"
set "PYTHON_ARGS="
%PYTHON_EXE% -c "import numpy, PIL" >nul 2>nul
if not errorlevel 1 goto run

echo.
echo 未找到带 numpy / Pillow 的 Python。
pause
exit /b 1

:run
"%PYTHON_EXE%" %PYTHON_ARGS% run.py --port 8777
if not defined XUANJI_NO_PAUSE pause
endlocal
