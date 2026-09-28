"""Sisipkan komentar dokumentasi di atas fungsi JS yang belum punya komentar.

AMAN: hanya menyisipkan baris komentar sebelum `function NAMA(...)` /
`async function NAMA(...)`. Tidak mengubah baris lain. Fungsi yang sudah
punya komentar (baris non-kosong terdekat di atasnya adalah komentar) di-skip.
"""
import pathlib
import re

HTML = pathlib.Path("TTSClientV2.html")
text = HTML.read_text(encoding="utf-8")
js_start = text.index("<script>")
js_end = text.index("</script>") + len("</script>")

DESC = {
    "saveServerConfigs": "Simpan daftar server (label/host/port) ke localStorage.",
    "loadServerConfigs": "Baca daftar server tersimpan dari localStorage; kembalikan null bila tidak ada/rusak.",
    "makeServerState": "Buat objek state runtime per-server (status HTTP/WS, zone, queue, discovery, scheduler).",
    "baseUrl": "URL HTTP dasar server (http://host:port).",
    "wsUrl": "URL WebSocket status server (ws://host:port/ws/status).",
    "getServerById": "Cari objek server berdasarkan id; null bila tidak ditemukan.",
    "renderServerList": "Render daftar server (kartu) dengan status HTTP/WS + aksi Pilih/Hapus.",
    "httpStatusLabel": "Label teks status HTTP server (Online/Offline/…).",
    "wsStatusLabel": "Label teks status WebSocket server (Connected/Reconnecting/…).",
    "renderActiveBanner": "Render banner server aktif (dot status HTTP, WS, tombol disconnect).",
    "populateEngineSelect": "Isi dropdown engine dari hasil discovery; engine tak tersedia di-disable.",
    "populateVoiceSelect": "Isi dropdown voice sesuai engine terpilih; voice custom tetap bisa round-trip.",
    "renderChimeSelectors": "Isi ulang dropdown chime pada form TTS & Scheduler dari data discovery.",
    "renderEngineVoiceSelectors": "Render info discovery + isi dropdown engine/voice/chime + visibilitas field voice.",
    "formatUptime": "Format detik menjadi 'Xj Ym Zd'.",
    "formatBytes": "Format ukuran byte menjadi B/KB/MB.",
    "badgeMap": "Render objek kunci:nilai menjadi kumpulan badge (untuk metrics).",
    "renderStatusMetrics": "Render panel Status (GET /status) & Metrics (GET /metrics).",
    "renderScheduler": "Render tabel jadwal scheduler dengan aksi Edit/Trigger/Toggle/Hapus.",
    "renderAll": "Render ulang seluruh panel yang terikat server aktif.",
    "escapeHtml": "Escape teks agar aman dirender sebagai HTML (anti-XSS).",
    "startHealthPolling": "Mulai polling GET /health berkala untuk server aktif.",
    "stopHealthPolling": "Hentikan polling kesehatan.",
    "refreshVoices": "Muat daftar voice (GET /tts/voices) ke state server; gagal = daftar kosong.",
    "clearPendingQueue": "Hapus seluruh item pending antrean (POST /clear) — hanya untuk zone 'main'.",
    "startMetricsAutoRefresh": "Mulai refresh otomatis /status + /metrics (jika checkbox aktif).",
    "stopMetricsAutoRefresh": "Hentikan refresh otomatis metrics.",
    "updateZone": "Kirim PUT /zones/{name} dengan patch (volume/enabled/device_id).",
    "deleteZone": "Hapus zone (DELETE /zones/{name}) lalu muat ulang daftar zone.",
    "buildScheduleAnnouncement": "Baca form Scheduler jadi payload announcement (tts/audio + engine/voice/chime/dll).",
    "collectSchedulePayload": "Kumpulkan & validasi seluruh field form jadwal jadi payload create/update; null bila tidak valid.",
    "createSchedule": "Kirim POST /scheduler untuk membuat jadwal baru.",
    "updateSchedule": "Kirim PUT /scheduler/{id} (parsial) untuk memperbarui jadwal.",
    "startScheduleEdit": "Isi form Scheduler dengan data jadwal yang akan diedit (mode edit).",
    "cancelScheduleEditUi": "Kembalikan form Scheduler ke mode buat (kosongkan & sembunyikan tombol Batal).",
    "toggleScheduleEnabled": "Balik status enabled jadwal (PUT parsial {enabled}).",
    "deleteSchedule": "Hapus jadwal (DELETE /scheduler/{id}).",
    "triggerSchedule": "Jalankan jadwal secara manual (POST /scheduler/{id}/trigger).",
    "clearTtsForm": "Kosongkan form TTS (type/text/file/engine/voice/chime/pengaturan).",
    "updateTtsTypeFields": "Tampilkan/sembunyikan field text vs file sesuai tipe TTS (tts/audio).",
    "setGlobalDevice": "Set device output global (POST /device {device_id}).",
    "setZoneDevice": "Set device output per zone (POST /zones/{name}/device).",
    "categoryForEvent": "Petakan tipe event WebSocket/UI ke kategori log.",
    "addEventLogEntry": "Tambahkan entri ke event log server (dibatasi EVENT_LOG_MAX) lalu render.",
    "truncateBody": "Potong body panjang ke API_BODY_MAX_CHARS karakter + penanda terpotong.",
    "pushApiLogEntry": "Tambahkan entri ke log API Terminal (buang yang melebihi API_LOG_MAX) lalu render.",
    "apiStatusClass": "Kelas CSS badge status: ok (2xx), warn (4xx), err (5xx/network error).",
    "renderApiLog": "Render tab API Terminal sesuai filter 'Termasuk GET' + auto-scroll.",
    "copyApiEntry": "Salin satu entri API (JSON lengkap) ke clipboard.",
    "detailForEvent": "Ringkas detail event WebSocket untuk baris log.",
    "applyEventToZone": "Terapkan event realtime (queue_changed/speaking/idle/pause/resume/finished) ke data zone.",
    "scheduleReconnect": "Jadwalkan reconnect WebSocket dengan backoff eksponensial.",
    "closeWebSocket": "Tutup WebSocket secara manual (tanpa auto-reconnect).",
    "resetServerRuntimeState": "Reset seluruh data runtime server (zone/queue/history/discovery/dll).",
    "disconnect": "Putuskan server aktif: hentikan polling, tutup WS, reset state.",
    "removeServer": "Hapus server dari daftar (termasuk disconnect bila sedang aktif) lalu simpan.",
}

pat = re.compile(
    r"(?m)^(\s*)(async\s+)?function\s+(\w+)\s*\(",
)
result = []
last_match_end = 0
count = 0
skipped = 0
for m in pat.finditer(text):
    # PENTING: slice antar-match SELALU dipertahankan (termasuk teks sebelum
    # <script>), apa pun status match-nya — jangan pernah buang konten.
    result.append(text[last_match_end:m.start()])
    last_match_end = m.end()
    if not (js_start <= m.start() < js_end):
        continue
    name = m.group(3)
    desc = DESC.get(name)
    if desc is None:
        skipped += 1
        continue
    # cek baris non-kosong terdekat di atas: sudah komentar?
    line_start = text.rfind("\n", 0, m.start()) + 1
    prefix = text[last_match_end:line_start]
    non_empty = [ln.strip() for ln in prefix.splitlines() if ln.strip()]
    if non_empty and (non_empty[-1].startswith("//") or non_empty[-1].startswith("/*") or non_empty[-1].startswith("*")):
        skipped += 1
        continue
    indent = m.group(1) or "    "
    result.append(f"{indent}// {desc}\n{text[m.start():m.end()]}")
    count += 1

result.append(text[last_match_end:])
new_text = "".join(result)

assert new_text.count("<script>") == text.count("<script>"), "struktur script rusak"
HTML.write_text(new_text, encoding="utf-8", newline="\n")
print(f"Dokumentasi ditambahkan ke {count} fungsi; {skipped} fungsi dilewati (komentar sudah ada / tak dikenal).")
