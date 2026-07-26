@echo off
REM =============================================================================
REM Announcement Server - Uninstall Windows Service (Phase 12, via NSSM)
REM =============================================================================
setlocal

cd /d "%~dp0"

set SERVICE_NAME=AnnouncementServer
set NSSM_PATH=%~dp0tools\nssm\nssm.exe

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Script ini harus dijalankan sebagai Administrator.
    echo         Klik kanan uninstall_service.bat -^> "Run as administrator".
    exit /b 1
)

if not exist "%NSSM_PATH%" (
    echo [ERROR] nssm.exe tidak ditemukan di "%NSSM_PATH%".
    exit /b 1
)

"%NSSM_PATH%" status %SERVICE_NAME% >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Service %SERVICE_NAME% tidak ditemukan/sudah tidak terinstall.
    exit /b 0
)

echo [INFO] Menghentikan service %SERVICE_NAME%...
"%NSSM_PATH%" stop %SERVICE_NAME%

echo [INFO] Menghapus service %SERVICE_NAME%...
"%NSSM_PATH%" remove %SERVICE_NAME% confirm

echo.
echo [OK] Service "%SERVICE_NAME%" berhasil di-uninstall.
echo      Aplikasi/venv/config TIDAK dihapus, hanya registrasi service Windows-nya.

endlocal
