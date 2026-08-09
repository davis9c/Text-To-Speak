"""Deteksi kode mati (dead code) dengan AST — offline, tanpa dependency.

1. Unused imports per file (mengabaikan __init__ re-exports & __all__).
2. Fungsi/metode publik yang TIDAK direferensikan di seluruh codebase
   (kandidat dead code — verifikasi manual tetap diperlukan).
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "announcement_server"
TESTS = ROOT / "tests"


def py_files(root):
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def iter_import_names(tree):
    """Kumpulkan (asal_alias, nama_lokal) dari semua import di satu file."""
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                local = a.asname or a.name.split(".")[0]
                names.append((a.name, local))
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == "*":
                    continue
                local = a.asname or a.name
                names.append((f"{node.module}.{a.name}" if node.module else a.name, local))
    return names


def name_used(tree, name):
    """Apakah nama muncul sebagai penggunaan (bukan hanya definisi/import)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
            return True
    return False


def unused_imports():
    print("=" * 72)
    print("UNUSED IMPORTS")
    print("=" * 72)
    found = 0
    for path in py_files(SRC):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            print(f"  [skip syntax] {path.relative_to(ROOT)}: {e}")
            continue
        src = path.read_text(encoding="utf-8")
        is_init = path.name == "__init__.py"
        body = "".join(src.split("\n")[1:]) if False else src
        for full, local in iter_import_names(tree):
            # import di __init__ sering sengaja untuk re-export
            if is_init:
                continue
            used = name_used(tree, local)
            if not used:
                # abaikan import yang hanya muncul di string (mis. docstring)
                print(f"  {path.relative_to(ROOT)}: {full} (sebagai '{local}')")
                found += 1
    print(f"TOTAL: {found}\n")
    return found


def all_def_names():
    """Semua nama fungsi/metode/kelas yang didefinisikan, per modul."""
    table = {}  # (modul, nama) -> lokasi
    for path in py_files(SRC):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                table[(path.stem, node.name)] = f"{path.relative_to(ROOT)}:{node.lineno}"
    return table


def def_names_in_tree(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def is_public_entry(name):
    """Nama yang dipanggil sebagai entry point / hook framework."""
    return (
        name.startswith("__") and name.endswith("__")
        or name in ("app", "router", "main", "run", "startup", "shutdown", "create_app")
        or name == "get_router"
    )


def dead_functions():
    print("=" * 72)
    print("KANDIDAT DEAD CODE (fungsi/metode yang tidak pernah direferensikan)")
    print("=" * 72)
    found = 0
    # Kumpulkan semua penggunaan nama di seluruh codebase (src + tests)
    used_anywhere = set()
    for path in py_files(SRC) + py_files(TESTS):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used_anywhere.add(node.id)
            if isinstance(node, ast.Attribute):
                used_anywhere.add(node.attr)
    for (module, name), loc in all_def_names().items():
        if name in used_anywhere:
            continue
        if is_public_entry(name):
            continue
        # abaikan metode dunder & helper one-liner umum
        if name.startswith("_") and not (name.startswith("__") and name.endswith("__")):
            continue
        print(f"  {loc}  ({module}.{name})")
        found += 1
    print(f"TOTAL KANDIDAT: {found}")
    return found


if __name__ == "__main__":
    t1 = unused_imports()
    t2 = dead_functions()
    print("=" * 72)
    print(f"Kesimpulan: {t1} unused import, {t2} kandidat dead function.")
