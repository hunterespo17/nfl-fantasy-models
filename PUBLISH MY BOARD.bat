@echo off
setlocal enabledelayedexpansion
title Building and publishing your fantasy board
cd /d "%~dp0"

echo.
echo ==================================================
echo   Building your board, then putting it on the web.
echo   Takes a few minutes. Leave this window alone.
echo ==================================================
echo.

where py >nul 2>nul
if errorlevel 1 goto nopython


rem ------------------------------------------------ website builder fix ----
rem One time only. The instructions GitHub follows to rebuild the website were
rem still the quarterback-only ones, so running backs were never going to show
rem up there no matter what you sent. If the replacement is sitting in this
rem folder, drop it into place and get rid of the spare copy.
if not exist "website-builder-update.txt" goto builderok
if not exist ".github\workflows\." mkdir ".github\workflows" 2>nul
copy /y "website-builder-update.txt" ".github\workflows\deploy.yml" >nul
if errorlevel 1 goto badcopy
del "website-builder-update.txt" >nul 2>nul
echo   Fixed the website's instructions -- it now publishes every position,
echo   not just quarterbacks. This part only happens once.
echo.
:builderok


rem ---------------------------------------------------------------- build ----
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
rem Without it there is no index.html and nothing to publish.
echo.
echo [4 of 4]  Putting the positions on one page...
echo.
py scripts\12_build_site.py
if errorlevel 1 goto oops

if not exist "outputs\index.html" goto nopage

echo.
echo   Board built. Opening it so you can look while I publish.
start "" "outputs\index.html"


rem -------------------------------------------------------------- publish ----
rem Git isn't on your PATH, but GitHub Desktop ships its own copy. Find it.
echo.
echo ==================================================
echo   Publishing to the website...
echo ==================================================
echo.

set "GIT="
for /f "delims=" %%G in ('where git 2^>nul') do if not defined GIT set "GIT=%%G"
if not defined GIT for /d %%D in ("%LOCALAPPDATA%\GitHubDesktop\app-*") do (
    if exist "%%D\resources\app\git\cmd\git.exe" set "GIT=%%D\resources\app\git\cmd\git.exe"
)
if not defined GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined GIT if exist "%ProgramFiles(x86)%\Git\cmd\git.exe" set "GIT=%ProgramFiles(x86)%\Git\cmd\git.exe"
if not defined GIT goto nogit

"%GIT%" rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 goto norepo

"%GIT%" add -A
rem Belt and braces: the price files live under data\, which used to be ignored
rem wholesale. Force them in so the website's builder has prices to work with.
for %%F in (adp.csv adp_history.csv playcallers.csv win_totals.csv) do (
    if exist "data\%%F" "%GIT%" add -f "data/%%F" >nul 2>nul
)

"%GIT%" diff --cached --quiet
if not errorlevel 1 goto nothingnew

"%GIT%" commit -m "Rebuild the board (%DATE%)"
if errorlevel 1 goto commitfailed

"%GIT%" push
if errorlevel 1 goto pushfailed

echo.
echo ==================================================
echo   Published.
echo.
echo   The website rebuilds itself now -- give it about
echo   three minutes, then hard-refresh the page with
echo   Ctrl and F5 together.
echo.
echo   https://hunterespo17.github.io/nfl-fantasy-models/
echo ==================================================
echo.
echo You can close this window.
pause >nul
exit /b 0


:nothingnew
echo.
echo Nothing changed since last time, so there's nothing to publish.
echo Your board is already up to date on the website.
echo.
pause
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


:nogit
echo.
echo Your board built fine and is open in your browser -- only the
echo publishing step couldn't run, because I can't find Git anywhere.
echo.
echo Open GitHub Desktop instead, type a short message in the bottom-left
echo box, click "Commit to main", then click "Push origin" at the top.
echo That does exactly the same thing.
echo.
pause
exit /b 1


:norepo
echo.
echo Your board built fine and is open in your browser -- but this folder
echo isn't connected to GitHub, so there's nothing to publish to.
echo Send Claude a screenshot of this window.
echo.
pause
exit /b 1


:commitfailed
echo.
echo Your board built fine, but saving the change failed. This is usually
echo Git not knowing your name yet.
echo Scroll up, copy the error, send it to Claude.
echo.
pause
exit /b 1


:pushfailed
echo.
echo Your board built fine and the change is saved, but sending it to
echo GitHub failed -- usually a sign-in thing.
echo.
echo Open GitHub Desktop and click "Push origin" at the top. Your commit
echo is already sitting there waiting.
echo.
pause
exit /b 1


:badcopy
echo.
echo Couldn't replace the website's instructions file. Usually that means
echo GitHub Desktop or an editor has it open. Close them and run this again.
echo.
pause
exit /b 1


:oops
echo.
echo ==================================================
echo   Something went wrong above, so I stopped before
echo   publishing -- a broken board never reaches the
echo   website.
echo   Scroll up, copy the error, send it to Claude.
echo ==================================================
echo.
pause
exit /b 1
