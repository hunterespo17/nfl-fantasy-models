@echo off
title Building your fantasy board
cd /d "%~dp0"

echo.
echo ================================================
echo   Building your board. This takes a few minutes.
echo   Leave this window alone until it finishes.
echo ================================================
echo.

where py >nul 2>nul
if errorlevel 1 goto nopython

echo [1 of 2]  Quarterbacks...
echo.
py scripts\06_build_qb_model.py
if errorlevel 1 goto oops

echo.
echo [2 of 2]  Running backs...
echo.
py scripts\11_build_rb_model.py
if errorlevel 1 goto oops

echo.
if not exist "outputs\index.html" goto nopage

echo ================================================
echo   Done. Opening your board now.
echo ================================================
start "" "outputs\index.html"
echo.
echo You can close this window.
pause >nul
exit /b 0


:nopython
echo.
echo Python isn't set up on this computer -- the "py" command isn't found.
echo Send Claude a screenshot of this window.
echo.
pause
exit /b 1


:nopage
echo.
echo Both models built, but outputs\index.html still isn't there.
echo Scroll up, copy everything you see, and send it to Claude.
echo.
pause
exit /b 1


:oops
echo.
echo ================================================
echo   Something went wrong above.
echo   Scroll up, copy the error, send it to Claude.
echo ================================================
echo.
pause
exit /b 1
