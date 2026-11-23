"""評価に使う材料のコピーを、リポジトリの外に作る。

small と large では、正解のファイル（evals/truth/<材料>.json）の「変えた場所」をコピーに当てる。
cpp は、コピーするだけである。

使い方: python evals/prepare.py <small|large|cpp> <コピー先のフォルダ>

コピー先は、まだないフォルダか、空のフォルダにする。日本語と空白を含むパスも使える。
"""
import json
import shutil
import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent
REPO = EVALS.parent
MATERIALS = EVALS / "materials"
TRUTH = EVALS / "truth"
CASES = ("small", "large", "cpp")


def changed_files(src, changes):
    """変えた後のファイルの中身を、相対パスごとに返す。変える前の行が合わないときは、エラーで止まる。"""
    files = {}
    for change in changes:
        name = change["file"]
        if name not in files:
            with open(src / name, encoding="utf-8", newline="") as f:
                files[name] = f.read().split("\n")
        lines, index = files[name], change["line"] - 1
        line = lines[index] if 0 <= index < len(lines) else ""
        ending = "\r" if line.endswith("\r") else ""
        if line[:len(line) - len(ending)] != change["before_line"]:
            sys.exit(f"変える前の行が合わない: {name} {change['line']} 行\n"
                     f"  正解: {change['before_line']!r}\n  実際: {line!r}")
        lines[index] = change["after_line"] + ending
    return {name: "\n".join(lines) for name, lines in files.items()}


def main(argv):
    if len(argv) != 2 or argv[0] not in CASES:
        sys.exit("使い方: python evals/prepare.py <small|large|cpp> <コピー先のフォルダ>")
    case, dest = argv[0], Path(argv[1]).resolve()
    if dest == REPO or REPO in dest.parents:
        sys.exit(f"コピー先は、リポジトリの外にする: {dest}")
    if dest.exists() and any(dest.iterdir()):
        sys.exit(f"コピー先が空でない: {dest}")
    source = MATERIALS / case
    if not source.exists():
        sys.exit(f"材料がない。先に python evals/fetch_materials.py を動かす: {source}")
    changes = []
    if case != "cpp":
        with open(TRUTH / f"{case}.json", encoding="utf-8") as f:
            changes = json.load(f)["changes"]
    files = changed_files(source / "src", changes)

    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(".git"), dirs_exist_ok=True)
    for name, text in files.items():
        with open(dest / "src" / name, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    print(f"ok {dest}（変えた場所 {len(changes)} か所）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
