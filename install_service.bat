@echo off
REM =============================================================================
REM Announcement Server - Install Windows Service (Phase 12, via NSSM)
REM =============================================================================
setlocal enabledelayedexpansion

cd /d "%~dp0"

set SERVICE_NAME=AnnouncementServer
set NSSM_PATH=%~dp0tools\nssm\nssm.exe

REM --- Harus dijalankan sebagai Administrator ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Script ini harus dijalankan sebagai Administrator.
    echo         Klik kanan install_service.bat -^> "Run as administrator".
    exit /b 1
)

REM --- Pastikan NSSM tersedia ---
if not exist "%NSSM_PATH%" (
    echo [ERROR] nssm.exe tidak ditemukan di "%NSSM_PATH%".
    echo         Unduh NSSM dari https://nssm.cc/download, lalu salin nssm.exe
    echo         ^(pilih folder win64^) ke: %~dp0tools\nssm\nssm.exe
    exit /b 1
)

REM --- Pastikan virtual environment + dependencies siap ---
if not exist "venv\" (
    echo [INFO] Membuat virtual environment...
    python -m venv venv
)
call venv\Scripts\activate.bat
echo [INFO] Menginstall dependencies...
pip install --disable-pip-version-check -q -r requirements.txt

set PYTHON_EXE=%~dp0venv\Scripts\python.exe
set APP_DIR=%~dp0
if "%APP_DIR:~-1%"=="\" set APP_DIR=%APP_DIR:~0,-1%

if not exist "logs\" mkdir logs

REM --- Hapus service lama jika sudah pernah terinstall (supaya install_service.bat aman dijalankan ulang) ---
"%NSSM_PATH%" status %SERVICE_NAME% >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Service %SERVICE_NAME% sudah ada, menghentikan ^& menghapusnya dulu...
    "%NSSM_PATH%" stop %SERVICE_NAME% >nul 2>&1
    "%NSSM_PATH%" remove %SERVICE_NAME% confirm >nul 2>&1
)

echo [INFO] Menginstall service %SERVICE_NAME%...
"%NSSM_PATH%" install %SERVICE_NAME% "%PYTHON_EXE%" "-m uvicorn announcement_server.main:app --host 0.0.0.0 --port 8000"

"%NSSM_PATH%" set %SERVICE_NAME% AppDirectory "%APP_DIR%"
"%NSSM_PATH%" set %SERVICE_NAME% AppEnvironmentExtra "PYTHONPATH=%APP_DIR%\src"
"%NSSM_PATH%" set %SERVICE_NAME% DisplayName "Announcement Server"
"%NSSM_PATH%" set %SERVICE_NAME% Description "Text-to-Speech Announcement Server (Public Address System) - lihat README.md"

REM --- Log stdout/stderr proses (terpisah dari logs aplikasi sendiri, lihat core/logging.py Phase 11) ---
"%NSSM_PATH%" set %SERVICE_NAME% AppStdout "%APP_DIR%\logs\service_stdout.log"
"%NSSM_PATH%" set %SERVICE_NAME% AppStderr "%APP_DIR%\logs\service_stderr.log"
"%NSSM_PATH%" set %SERVICE_NAME% AppRotateFiles 1
"%NSSM_PATH%" set %SERVICE_NAME% AppRotateBytes 10485760

REM --- Auto restart jika proses crash (production hardening) ---
"%NSSM_PATH%" set %SERVICE_NAME% AppExit Default Restart
"%NSSM_PATH%" set %SERVICE_NAME% AppRestartDelay 3000

REM --- Auto Start Windows (deliverable utama Phase 12) ---
"%NSSM_PATH%" set %SERVICE_NAME% Start SERVICE_AUTO_START

echo [INFO] Menjalankan service %SERVICE_NAME%...
"%NSSM_PATH%" start %SERVICE_NAME%

echo.
echo [OK] Service "%SERVICE_NAME%" terinstall dan berjalan (auto-start saat Windows boot).
echo      Cek status : sc query %SERVICE_NAME%
echo      Cek API    : http://localhost:8000/health
echo      Log service: logs\service_stdout.log / logs\service_stderr.log
echo      Log aplikasi: logs\announcement_server.log (lihat Phase 11)

endlocal
