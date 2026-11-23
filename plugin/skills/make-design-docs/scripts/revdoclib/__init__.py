"""revdoc.py の本体。入口は main(argv) である（スクリプトの仕様の 12章）。

モジュールの役割（括弧はスクリプトの仕様の章）：

- values：仕様に書いた値。値は、ここだけに置く。
- common：エラー（Fail）と、結果の do の文（1.3、1.5）。
- files：ファイルの読み書き、置き換えのやり直し（1.4）。
- packages：使うパッケージがあるかを調べる（12章）。
- plan：計画を作る。対象のソースファイル、ユニット、モジュール、PDF、仕事（2章）。
- pdf：PDF を読む。ページの数、文字の対応づけ、ヘッダーとフッター（2.5、2.6）。
- init：init のサブコマンド（3章）。
- state：next の手順、段階、不合格と失敗、出力がない回、状態のファイル（4章）。
- markdown：Markdown の読み方と、共通の検査（5章）。
- jobchecks：仕事の種類ごとの出力の検査（6章）。
- instructions：指示のファイルとひな形（7章）。
- scriptwork：スクリプトだけの処理（8.1 〜 8.6）。state の ENTER と EXIT から呼ぶ。
- finish：仕上げ（8.7）と mkdocs.yml（10章）。最後の段階が終わったときに、state から呼ぶ。
- check：check のサブコマンド（9章）。
- serve：serve と stop と、内部用の _serve（11章）。
"""
import json
import os
import sys

from . import check, init, serve, state
from .common import Fail, error_do

# _serve は、serve が切り離したプロセスで動かす内部用のサブコマンドである（11.1）。
COMMANDS = ("init", "next", "check", "serve", "stop", "_serve")
OPTIONS = {"init": ("--out", "--src", "--pdf")}
DEFAULT_OPTIONS = ("--out",)
NEEDS_STATE = ("next", "check", "serve")


def _parse(argv):
    if not argv or argv[0] not in COMMANDS:
        raise Fail("bad_arguments", "知らないサブコマンドである：%s" % (argv[0] if argv else "（なし）"))
    sub, opts = argv[0], {}
    known = OPTIONS.get(sub, DEFAULT_OPTIONS)
    rest = argv[1:]
    while rest:
        key = rest.pop(0)
        if key not in known:
            raise Fail("bad_arguments", "知らないオプションである：%s" % key)
        if not rest:
            raise Fail("bad_arguments", "オプションに値がない：%s" % key)
        opts[key[2:]] = os.path.abspath(rest.pop(0))
    opts.setdefault("out", os.path.abspath("design-docs"))
    return sub, opts


def _run(argv):
    sub, opts = _parse(argv)
    if sub == "init":
        return init.run(opts["out"], opts.get("src"), opts.get("pdf"))
    if sub in NEEDS_STATE and not os.path.isfile(os.path.join(opts["out"], ".work", "state.json")):
        raise Fail("not_initialized", "作業を始めていない。先に init を動かす。")
    run = {"next": state.run, "check": check.run, "serve": serve.run_serve, "stop": serve.run_stop,
           "_serve": serve.run_internal}[sub]
    return run(opts["out"])


def main(argv):
    """結果の JSON を標準出力に1行で書き、終了コードを返す。"""
    try:
        result = _run(list(argv))
    except Fail as e:
        result = dict({"ok": False, "error": e.error, "message": e.message}, **e.extra)
        result["do"] = error_do(e)
    except Exception as e:
        fail = Fail("internal_error", "%s: %s" % (type(e).__name__, e))
        result = {"ok": False, "error": fail.error, "message": fail.message, "do": error_do(fail)}
    sys.stdout.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0 if result["ok"] else 1
