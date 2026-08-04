@echo off
title Building your fantasy board
cd /d "%~dp0"

echo.
echo ================================================
echo   Building your board. This takes a few minutes.
echo   Leave this window alone until it finishes.
echo.
echo   (This one builds it here only. To also put it
echo    on the website, use PUBLISH MY BOARD instead.)
echo ================================================
echo.

where py >nul 2>nul
if errorlevel 1 goto nopython

rem Draft prices first. If the sites are down or the internet is flaky this
rem step fails and we carry on with the prices already saved -- a bad network
rem day should never cost you the board.
echo [1 of 4]  Draft prices...
echo.
py scripts\15_pull_adp.py
if errorlevel 1 echo   (Couldn't refresh prices. Using the ones already saved.)

echo.
echo [2 of 4]  Quarterbacks...
echo.
py scripts\06_build_qb_model.py
if errorlevel 1 goto oops

echo.
echo [3 of 4]  Running backs...
echo.
py scripts\11_build_rb_model.py
if errorlevel 1 goto oops

rem This is the step that folds every position into ONE page with a tab each.
rem Without it there is no index.html at all.
echo.
echo [4 of 4]  Putting the positions on one page...
echo.
py scripts\12_build_site.py
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
echo Everything built, but outputs\index.html still isn't there.
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
