@echo off
REM =============================================================================
REM Announcement Server - Restart Windows Service (Phase 12, via NSSM)
REM =============================================================================
setlocal

cd /d "%~dp0"

set SERVICE_NAME=AnnouncementServer
set NSSM_PATH=%~dp0tools\nssm\nssm.exe

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Script ini harus dijalankan sebagai Administrator.
    echo         Klik kanan restart_service.bat -^> "Run as administrator".
    exit /b 1
)

if not exist "%NSSM_PATH%" (
    echo [ERROR] nssm.exe tidak ditemukan di "%NSSM_PATH%".
    exit /b 1
)

"%NSSM_PATH%" status %SERVICE_NAME% >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Service %SERVICE_NAME% belum terinstall. Jalankan install_service.bat dulu.
    exit /b 1
)

echo [INFO] Merestart service %SERVICE_NAME%...
"%NSSM_PATH%" restart %SERVICE_NAME%

echo.
echo [OK] Service "%SERVICE_NAME%" berhasil direstart.
echo      Cek status: sc query %SERVICE_NAME%
echo      Cek API   : http://localhost:8000/health

endlocal
