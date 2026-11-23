# -*- coding: utf-8 -*-
"""スクリプトの入口。バージョンを確かめてから、本体（revdoclib）を読み込む。

古い Python でも構文エラーにならないように、f 文字列と型の注釈を使わない（スクリプトの仕様の 1.1）。
"""
import json
import os
import sys

sys.dont_write_bytecode = True


def main():
    # 本体は 3.9 以上の書き方なので、読み込む前に確かめる。
    if sys.version_info < (3, 9):
        # revdoclib を読み込めないので、エラーの形と do の文をここにも書く。
        data = {"ok": False, "error": "python_too_old",
                "message": u"Python 3.9 以上が必要である。",
                "do": "Tell the user in Japanese what the message says. Then stop."}
        sys.stdout.write(json.dumps(data, ensure_ascii=True, separators=(",", ":")) + "\n")
        return 1
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import revdoclib
    return revdoclib.main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
