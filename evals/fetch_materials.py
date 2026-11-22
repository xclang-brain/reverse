"""評価に使う OSS の材料を取得する。

取得先は evals/materials/（Git の管理外）。すでにあるものは取得し直さない。
使い方: python evals/fetch_materials.py
"""
import subprocess
import sys
import urllib.request
from pathlib import Path

DEST = Path(__file__).resolve().parent / "materials"

# (フォルダ名, リポジトリの URL, コミット)
REPOS = [
    ("atk2-sc1", "https://github.com/toppers/atk2-sc1", "43f2fffecdca2b0fc08d3c581af23046056069bb"),
]

# (ファイル名, URL)
PDFS = [
    ("ATK2-0010_ATK2_spec_122.pdf", "https://www.toppers.jp/docs/tech/ATK2-0010_ATK2_spec_122.pdf"),
]


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def main():
    DEST.mkdir(exist_ok=True)
    for name, url, commit in REPOS:
        target = DEST / name
        if not target.exists():
            run("git", "init", "-q", str(target))
            run("git", "remote", "add", "origin", url, cwd=target)
            run("git", "fetch", "-q", "--depth", "1", "origin", commit, cwd=target)
            run("git", "checkout", "-q", "FETCH_HEAD", cwd=target)
        print("ok", target)
    pdf_dir = DEST / "pdf"
    pdf_dir.mkdir(exist_ok=True)
    for name, url in PDFS:
        target = pdf_dir / name
        if not target.exists():
            urllib.request.urlretrieve(url, target)
        print("ok", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
