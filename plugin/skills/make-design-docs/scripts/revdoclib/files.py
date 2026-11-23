"""ファイルの読み書き（スクリプトの仕様の 1.4）。"""
import json
import os
import time

from . import values


def split_lines(text):
    """行に分ける。最後が改行で終わるときは、その後ろの空の行を数えない。"""
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return lines


def read_text(path):
    """出力先の中のファイルを読む。担当エージェントが書いたファイルもあるので、BOM と行末の \\r を外す。"""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        text = f.read().replace("\r\n", "\n")
    return text[:-1] if text.endswith("\r") else text


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fs_op(func, *args):
    """置き換え、移動、削除を行う。Windows では、ほかのプロセスが開いている間は PermissionError になるので、やり直す。"""
    for k in range(values.FS_RETRIES + 1):
        try:
            return func(*args)
        except PermissionError:
            if k == values.FS_RETRIES:
                raise
            time.sleep(values.FS_RETRY_WAIT)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_atomic(path, text):
    """途中で止まっても前の中身が残るように、一時ファイルに書いてから置き換える。"""
    tmp = path + ".tmp"
    write_text(tmp, text)
    fs_op(os.replace, tmp, path)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=1) + "\n"


def md_files(out, folder):
    """出力先の folder（出力先からの相対パス）の下の全部の .md を、出力先からの相対パスで、文字の順に返す。"""
    found = []
    for d, _, names in os.walk(os.path.join(out, *folder.split("/"))):
        found += [os.path.relpath(os.path.join(d, n), out).replace(os.sep, "/") for n in names if n.endswith(".md")]
    return sorted(found)
