"""Schema response untuk Chime Discovery API.

Model di sini SENGAJA hanya mengekspos informasi yang aman untuk klien
publik (HTML Client) — TIDAK ada path absolut filesystem. Field-nya
diambil dari ``ChimeProfile`` (announcement/chime_catalog.py), tidak
pernah menyentuh filesystem secara langsung.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from announcement_server.announcement.chime_catalog import ChimeProfile


class ChimeInfo(BaseModel):
    """Informasi publik satu chime (aman ditampilkan ke klien)."""

    id: str = Field(description="Identifier chime, unik dalam lingkup direktori chime (nama file tanpa ekstensi).")
    name: str = Field(description="Nama tampilan chime.")
    file: str = Field(
        description="Path relatif terhadap announcement.sounds_dir (format SAMA dengan field "
        "'chime' pada request POST /speak) — siap dipakai langsung di request."
    )
    is_default: bool = Field(
        description="True jika ini chime default server (file bernama 'chime.*' atau 'default.*')."
    )

    @classmethod
    def from_profile(cls, profile: ChimeProfile) -> ChimeInfo:
        """Memetakan ChimeProfile (objek domain) ke ChimeInfo (publik)."""
        return cls(id=profile.id, name=profile.name, file=profile.file, is_default=profile.is_default)


class ChimeListResponse(BaseModel):
    """Response untuk GET /chimes."""

    chimes: list[ChimeInfo]
    count: int = Field(description="Jumlah chime pada `chimes` (setara len(chimes)).")
    default_chime: str | None = Field(
        default=None,
        description="`file` dari chime default (atau None jika tidak ada chime bertanda default). "
        "Kosongkan/null pada request = tanpa chime.",
    )
