@echo off
REM =============================================================================
REM Announcement Server - Run Script (Windows)
REM =============================================================================
setlocal

REM Pindah ke direktori tempat script ini berada
cd /d "%~dp0"

REM Buat virtual environment jika belum ada
if not exist "venv\" (
    echo [INFO] Membuat virtual environment...
    python -m venv venv
)

REM Aktifkan virtual environment
call venv\Scripts\activate.bat

REM Install/update dependencies
echo [INFO] Menginstall dependencies...
pip install --disable-pip-version-check -q -r requirements.txt

REM Set PYTHONPATH agar package "announcement_server" di folder src/ dikenali
set PYTHONPATH=%cd%\src

REM Jalankan server
echo [INFO] Menjalankan Announcement Server...
python -m uvicorn announcement_server.main:app --host 0.0.0.0 --port 8000

endlocal
