# NSSM (Phase 12 — Windows Service)

Letakkan `nssm.exe` di folder ini agar `install_service.bat` /
`uninstall_service.bat` / `restart_service.bat` bisa menemukannya:

```
tools/nssm/nssm.exe
```

## Cara mendapatkan NSSM

1. Unduh dari https://nssm.cc/download
2. Ekstrak arsip zip.
3. Salin `win64\nssm.exe` (64-bit, umumnya yang dibutuhkan) ke folder ini.

NSSM (Non-Sucking Service Manager) dipakai untuk menjalankan
Announcement Server sebagai Windows Service — auto-start saat Windows
boot, auto-restart jika proses crash, tanpa perlu window terminal
terbuka terus-menerus.
