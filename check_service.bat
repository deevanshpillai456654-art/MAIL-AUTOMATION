@echo off
curl.exe --silent --show-error --fail --max-time 3 "http://127.0.0.1:4597/api/v1/health" >nul 2>nul
exit /b %ERRORLEVEL%
