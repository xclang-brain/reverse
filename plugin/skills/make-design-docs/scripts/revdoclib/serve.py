"""serve と stop と、内部用の _serve（スクリプトの仕様の 11章）。"""
import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

from . import files, finish, values
from .common import REVDOC_PY, Fail, cmd
from .state import Ctx

SERVING_DO = ("Tell the user in Japanese: the site URL (url), the folder of the documents (docs), the two review"
              " lists (discrepancies, unknowns), the counts (counts) and the number of failed jobs (failed_jobs)."
              " To stop the server, run: ")
BUILDING_DO = "The site is not ready yet. Run the same command again: "
HOST = "127.0.0.1"
# 利用者の環境のプロキシの設定があっても、自分のサーバーには直接つなぐ。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _record_path(out):
    return os.path.join(out, ".work", "serve.json")


def _read_record(out):
    try:
        return files.read_json(_record_path(out))
    except (OSError, ValueError):
        return None  # ないか、Windows で置き換えの途中


def _fresh(record):
    return record is not None and time.time() - record["time"] <= values.SERVE_FRESH


def _remove_record(out):
    if os.path.exists(_record_path(out)):
        files.fs_op(os.remove, _record_path(out))


def _responds(url):
    try:
        with _OPENER.open(url, timeout=values.HTTP_TIMEOUT) as res:
            return res.status == 200
    except (OSError, http.client.HTTPException):
        return False


def _port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(values.HTTP_TIMEOUT)
        return s.connect_ex((HOST, port)) == 0


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, port))
        except OSError:
            return False
    return True


def _log_tail(out):
    try:
        # mkdocs の出力の文字コードは環境で違うので、読めない文字は置き換える。
        with open(os.path.join(out, ".work", "serve.log"), "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-values.SERVE_LOG_LINES:]
    except OSError:
        return []


def _start(out):
    """切り離したプロセスで _serve を始める。serve の呼び出しが終わっても、サーバーが動き続けるようにする。"""
    if os.name == "nt":
        kw = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        kw = {"start_new_session": True}
    with open(os.path.join(out, ".work", "serve.log"), "wb") as log:
        subprocess.Popen([sys.executable, REVDOC_PY, "_serve", "--out", out], cwd=out, stdin=subprocess.DEVNULL,
                         stdout=log, stderr=subprocess.STDOUT, **kw)


def _serving(ctx, record):
    counts, failed = finish.summary(ctx, finish.unknown_groups(ctx))
    both = ctx.plan["mode"] == "both"
    return {"ok": True, "state": "serving", "url": record["url"], "site": ctx.abs("site"), "docs": ctx.abs("docs"),
            "discrepancies": ctx.abs("docs/review/discrepancies.md") if both else None,
            "unknowns": ctx.abs("docs/review/unknowns.md"), "counts": counts, "failed_jobs": sum(failed.values()),
            "do": SERVING_DO + cmd("stop", ctx.out)}


def run_serve(out):
    ctx = Ctx(out)
    if ctx.state["stage"] != "done":
        raise Fail("not_done", "作業が終わっていない。next を、state が done になるまで進めてから serve を動かす。")
    record = _read_record(out)
    if not (_fresh(record) and record["state"] != "failed"):
        _remove_record(out)
        _start(out)
    deadline = time.time() + values.SERVE_WAIT
    while True:
        record = _read_record(out)
        if record and record["state"] == "serving" and _responds(record["url"]):
            return _serving(ctx, record)
        if record and record["state"] == "failed":
            raise Fail("serve_failed", "サイトのビルドかサーバーが失敗した。または、使えるポート（%d〜%d）がない。"
                       "log はログの最後の部分である。" % (values.SERVE_PORTS[0], values.SERVE_PORTS[-1]),
                       log=_log_tail(out))
        if time.time() >= deadline:
            return {"ok": True, "state": "building", "do": BUILDING_DO + cmd("serve", out)}
        time.sleep(values.SERVE_POLL)


def run_internal(out):
    """_serve：ビルドしてからサーバーを動かし、状態を serve.json に書き続ける。"""
    record = {"state": "building", "pid": os.getpid(), "port": 0, "url": "", "time": 0}
    lock = threading.Lock()

    def write(**change):
        with lock:
            record.update(change, time=int(time.time()))
            files.write_atomic(_record_path(out), json.dumps(record) + "\n")

    def beat():
        # 動いていることを stop と serve に示すため、time を書き直し続ける。
        while True:
            time.sleep(values.SERVE_BEAT)
            write()

    write()
    threading.Thread(target=beat, daemon=True).start()
    mkdocs = [sys.executable, "-m", "mkdocs"]
    config = os.path.join(out, "mkdocs.yml")
    env = dict(os.environ, NO_MKDOCS_2_WARNING="1")
    if subprocess.call(mkdocs + ["build", "-f", config, "-q"], cwd=out, env=env) != 0:
        write(state="failed")
        raise Fail("serve_failed", "サイトのビルドが失敗した。")
    port = next((p for p in values.SERVE_PORTS if _port_free(p)), None)
    if port is None:
        write(state="failed")
        raise Fail("serve_failed", "使えるポートがない。")
    url = "http://%s:%d/" % (HOST, port)
    server = subprocess.Popen(mkdocs + ["serve", "-f", config, "-a", "%s:%d" % (HOST, port)], cwd=out, env=env)
    while server.poll() is None:
        if _responds(url):
            write(state="serving", port=port, url=url)
            break
        time.sleep(values.SERVE_POLL)
    server.wait()
    write(state="failed")
    raise Fail("serve_failed", "サーバーが終わった。")


def run_stop(out):
    record = _read_record(out)
    if not _fresh(record):
        _remove_record(out)
        return {"ok": True, "stopped": False}
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(record["pid"]), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(record["pid"], signal.SIGTERM)  # _serve は新しいセッションの先頭なので、グループの ID は pid と同じ
        except OSError:
            pass
    deadline = time.time() + values.STOP_WAIT
    while record["port"] and _port_open(record["port"]) and time.time() < deadline:
        time.sleep(values.STOP_POLL)
    _remove_record(out)
    return {"ok": True, "stopped": True}
