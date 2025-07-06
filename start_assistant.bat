@echo off
setlocal

set "GOOGLE_API_KEY=AIzaSyBICmVNeGDo_mcscvsDkDb3nLB2GLQnwsM"
set "GOOGLE_APPLICATION_CREDENTIALS=C:\Programming\AI Assistant\Kira\tts_key\built-in-solution-c1edb66ee40d.json"

set "PROJECT_DIR=C:\Programming\AI Assistant\Kira"

set "PYTHONW_EXE=%PROJECT_DIR%\.venv\Scripts\pythonw.exe"
set "SCRIPT_PATH=%PROJECT_DIR%\kira.pyw"

if not exist "%PYTHONW_EXE%" (
    echo [ERROR] Python executable not found!
    echo The script was looking for it at this exact path:
    echo %PYTHONW_EXE%
    echo.
    echo Please verify that this path is correct and the file exists.
    pause
    exit /b 1
)
if not exist "%SCRIPT_PATH%" (
    echo [ERROR] Main script 'kira.pyw' not found.
    echo Path checked: %SCRIPT_PATH%
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"
start "Assistant" "%PYTHONW_EXE%" "%SCRIPT_PATH%"

endlocal