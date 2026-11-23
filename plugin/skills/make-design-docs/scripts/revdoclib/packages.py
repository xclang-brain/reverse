"""使うパッケージがあるかを調べる（スクリプトの仕様の 12章）。テストは missing を差し替える。"""
import importlib
import importlib.metadata


def _importable(*names):
    try:
        for name in names:
            importlib.import_module(name)
    except Exception:
        return False
    return True


def _pypdfium2_ok():
    if not _importable("pypdfium2"):
        return False
    try:
        return int(importlib.metadata.version("pypdfium2").split(".")[0]) >= 5
    except Exception:
        return False


def missing(need_pdf):
    """足りないパッケージの、pip に渡す名前のリストを返す。"""
    found = []
    if not _importable("mkdocs", "material"):
        found.append("mkdocs-material")
    if need_pdf:
        if not _pypdfium2_ok():
            found.append("pypdfium2>=5")
        if not _importable("PIL"):
            found.append("Pillow")
    return found
