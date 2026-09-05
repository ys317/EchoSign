@echo off
setlocal
pushd "%~dp0"

if not exist "_internal\playwright\driver\node.exe" goto missing
if not exist "_internal\playwright\driver\package\cli.js" goto missing
if not defined LOCALAPPDATA goto missingappdata

set "PLAYWRIGHT_BROWSERS_PATH=%LOCALAPPDATA%\ms-playwright"
echo Installing the Chromium version required by this EchoSign release.
echo Internet access is required. Python and administrator rights are not required.
echo Browser files: %PLAYWRIGHT_BROWSERS_PATH%
echo.
"_internal\playwright\driver\node.exe" "_internal\playwright\driver\package\cli.js" install chromium
if errorlevel 1 goto failed

echo.
echo Browser installation completed. You can now open EchoSign.exe.
popd
pause
exit /b 0

:missing
echo Required runtime files are missing. Extract the complete release ZIP first.
goto failed

:missingappdata
echo LOCALAPPDATA is not available. Run this script in your Windows user account.

:failed
echo.
echo Browser installation failed. Check the message above, then try again.
popd
pause
exit /b 1
