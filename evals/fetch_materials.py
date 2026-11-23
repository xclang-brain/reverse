"""評価に使う OSS の材料を取得する。

取得先は evals/materials/（Git の管理外）。すでにあるものは取得し直さない。

使い方: python evals/fetch_materials.py

できるもの:
  materials/small/src   ATK2-SC1 の kernel と include（約1.2万行）
  materials/small/pdf   ATK2 外部仕様書のうち、タスク、カウンタ、アラームのページ（25ページ）
  materials/large/src   ASP3 カーネル（約16.8万行）
  materials/large/pdf   TOPPERS 新世代カーネル統合仕様書 Release 1.7.1
  materials/cpp/src     QP/C++ 8.1.6 の src と include の .cpp と .hpp（約 6,700 行。GPL-3.0-or-later）
"""
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

DEST = Path(__file__).resolve().parent / "materials"
DOCS_URL = "https://www.toppers.jp/docs/tech/"

REPOS = {
    "atk2-sc1": ("https://github.com/toppers/atk2-sc1", "43f2fffecdca2b0fc08d3c581af23046056069bb"),
    "asp3_core": ("https://github.com/toppers/asp3_core", "bcf9a04ff9d1970b1f25967c8caf4e7388f18aad"),
    "qpcpp": ("https://github.com/QuantumLeaps/qpcpp", "458647c2f8717294a669cf498192f7257b5f0589"),
}
PDFS = ["ATK2-0010_ATK2_spec_122.pdf", "ngki_spec-171.pdf"]

SMALL_SOURCE_DIRS = ["kernel", "include"]
# 1始まりのページ番号（両端を含む）: 2.5 タスク、2.10 カウンタ〜2.12 アラーム
SMALL_PAGE_RANGES = [(44, 57), (78, 88)]

CPP_SOURCE_DIRS = ["src", "include"]
CPP_SUFFIXES = (".cpp", ".hpp")
# 商用のライセンスだけのファイル（ほかは GPL-3.0-or-later との二重ライセンス）
CPP_EXCLUDED = ["qf_stub.cpp"]


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def fetch_repo(name):
    url, commit = REPOS[name]
    target = DEST / "download" / name
    if not target.exists():
        target.mkdir(parents=True)
        run("git", "init", "-q", cwd=target)
        run("git", "remote", "add", "origin", url, cwd=target)
        run("git", "fetch", "-q", "--depth", "1", "origin", commit, cwd=target)
        run("git", "checkout", "-q", "FETCH_HEAD", cwd=target)
    return target


def fetch_pdf(name):
    target = DEST / "download" / name
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(DOCS_URL + name, target)
    return target


def copy_tree(source, target, ignore=shutil.ignore_patterns(".git")):
    if not target.exists():
        shutil.copytree(source, target, ignore=ignore)


def ignore_except_cpp(folder, names):
    """C++ の材料に入れないファイルの名前を返す（フォルダは残す）。"""
    return [n for n in names
            if (Path(folder) / n).is_file() and (not n.endswith(CPP_SUFFIXES) or n in CPP_EXCLUDED)]


def main():
    atk2 = fetch_repo("atk2-sc1")
    asp3 = fetch_repo("asp3_core")
    qpcpp = fetch_repo("qpcpp")
    atk2_pdf = fetch_pdf(PDFS[0])
    ngki_pdf = fetch_pdf(PDFS[1])

    for name in SMALL_SOURCE_DIRS:
        copy_tree(atk2 / name, DEST / "small" / "src" / name)
    small_pdf = DEST / "small" / "pdf" / "ATK2_spec_extract.pdf"
    if not small_pdf.exists():
        import pypdfium2 as pdfium
        small_pdf.parent.mkdir(parents=True, exist_ok=True)
        original = pdfium.PdfDocument(str(atk2_pdf))
        pages = [p - 1 for start, end in SMALL_PAGE_RANGES for p in range(start, end + 1)]
        extract = pdfium.PdfDocument.new()
        extract.import_pages(original, pages)
        extract.save(str(small_pdf))

    copy_tree(asp3, DEST / "large" / "src")
    large_pdf = DEST / "large" / "pdf" / PDFS[1]
    if not large_pdf.exists():
        large_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ngki_pdf, large_pdf)

    for name in CPP_SOURCE_DIRS:
        copy_tree(qpcpp / name, DEST / "cpp" / "src" / name, ignore=ignore_except_cpp)

    for case in ("small", "large", "cpp"):
        print("ok", DEST / case)
    return 0


if __name__ == "__main__":
    sys.exit(main())
