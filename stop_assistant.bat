@echo off
setlocal

echo Stopping Kira Assistant...

taskkill /FI "WINDOWTITLE eq Assistant" /T /F

echo.
echo Check the output above.
echo If it says "SUCCESS", the assistant was stopped.
echo If it says "INFO: No tasks running", the assistant was not running.

endlocal
pause