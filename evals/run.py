"""材料のコピーに対して、Claude Code を対話なしで動かし、実行の記録を残す（要件の 5.4）。

使い方: python evals/run.py <回の種類> <回のフォルダ> [--compact-window <トークン数>]

回の種類:
  small、large  通しの実行（ソースコードと PDF）。C-1 〜 C-11 と C-15 を見る。
  c12           小さい材料。next が3回呼ばれたところで止め、同じコマンドで動かし直す。
  c13           小さい材料。CLAUDE_CODE_AUTO_COMPACT_WINDOW でコンパクションを起こす。
  c14-src       C++ の材料のソースコードだけ。日本語と空白を含むパスで動かす。
  c14-pdf       小さい材料の PDF だけ。

回のフォルダは、リポジトリの外に置く。数時間かかるので、端末から切り離して動かす
（例：setsid nohup python evals/run.py small /tmp/eval/small > /tmp/eval/small.out 2>&1 &）。
止まったときは、同じ引数で動かすと続きから進む。failed で終わった回のフォルダも、最後の回の終わり方を
記録から決め直し、呼び直しを認める終わり方（利用枠の上限、再起動、API のエラー）なら、続きから進む。

回のフォルダの中身:
  run.json         設定と、実行の1回ずつの始まり、終わり、終わり方
  before.json      実行の前の、入力とプラグインのファイルのハッシュ（C-15）
  logs/attempt-N.jsonl、.times、.stderr   N 回目の stream-json の全部の行、各行を受け取った時刻、標準エラー
  logs/state-at-stop.json   C-12 で止めたときの状態のファイル
  <作業フォルダ>/input、plugin、out   材料のコピー、プラグインのコピー、出力先（claude はここで動く）
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time

from common import (AGENT_MODEL, KINDS, REPO, RETRY_REASONS, clean_env, end_reason, load_json, paths, read_events,
                    revdoc_command, save_json, tool_uses, tree_hashes)

MAX_ATTEMPTS = 20
API_ERROR_WAIT = 60   # API のエラーで止まったときに、呼び直す前に待つ秒数
C12_STOP_AFTER = 3


def say(text):
    print(time.strftime("%H:%M ") + text, flush=True)


def git(*args):
    return subprocess.run(["git", "-C", str(REPO)] + list(args), capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def prompt(kind, p):
    case, use_src, use_pdf, _ = KINDS[kind]
    parts = []
    if use_src:
        parts.append(f"ソースコードは {p['input'] / 'src'}")
    if use_pdf:
        parts.append(f"PDF は {p['input'] / 'pdf'}")
    parts.append(f"出力先は {p['out']}")
    return "/reverse:make-design-docs " + "、".join(parts)


def setup(kind, run_dir, compact_window):
    """材料とプラグインをコピーし、実行の前のハッシュと設定を残す。途中で止まったときは、作り直す。"""
    p = paths(run_dir, kind)
    if p["work"].exists():
        shutil.rmtree(p["work"])
    p["work"].mkdir(parents=True)
    subprocess.run([sys.executable, str(REPO / "evals" / "prepare.py"), KINDS[kind][0], str(p["input"])], check=True)
    shutil.copytree(REPO / "plugin", p["plugin"])
    save_json(p["run"] / "before.json", {"input": tree_hashes(p["input"]), "plugin": tree_hashes(p["plugin"]),
                                         "work": sorted(os.listdir(p["work"]))})
    command = ["claude", "-p", prompt(kind, p), "--plugin-dir", str(p["plugin"]), "--model", AGENT_MODEL,
               "--output-format", "stream-json", "--verbose"]
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True, encoding="utf-8").stdout
    return {"kind": kind, "case": KINDS[kind][0], "command": command, "cwd": str(p["work"]),
            "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": str(compact_window)} if kind == "c13" else {},
            "model": AGENT_MODEL, "claude_version": version.strip(),
            "plugin_commit": git("log", "-1", "--format=%H", "--", "plugin"),
            "plugin_dirty": bool(git("status", "--porcelain", "--", "plugin")),
            "attempts": [], "status": "running"}


def stop_group(pid):
    """claude のプロセスのグループを止める。再起動の後に同じ番号の別のプロセスがあるときは、止めない。"""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            if b"claude" not in f.read():
                return
    except OSError:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
            for _ in range(20):
                time.sleep(0.5)
                os.killpg(pid, 0)
        except (ProcessLookupError, PermissionError):
            return


def run_attempt(info, p, n, stop_after_next):
    """claude を1回動かす。stop_after_next があれば、next がその回数返ったところで止める。"""
    log = p["logs"] / f"attempt-{n}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = clean_env()
    env.update(info["env"])
    with open(log, "wb") as out, open(log.with_suffix(".times"), "w", encoding="utf-8") as times, \
            open(log.with_suffix(".stderr"), "wb") as err:
        proc = subprocess.Popen(info["command"], cwd=info["cwd"], env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=err, start_new_session=True)
        info["attempts"][-1]["pid"] = proc.pid
        save_json(p["run"] / "run.json", info)
        next_ids, next_done, agents, stopped = set(), 0, 0, False
        for raw in proc.stdout:
            out.write(raw)
            out.flush()
            times.write(f"{time.time():.3f}\n")
            times.flush()
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if event.get("parent_tool_use_id"):
                continue
            for block in tool_uses(event):
                if block.get("type") == "tool_use" and block.get("name") == "Agent":
                    agents += 1
                elif block.get("type") == "tool_use" and block.get("name") == "Bash" and \
                        revdoc_command(block.get("input", {}).get("command", ""), "next"):
                    next_ids.add(block.get("id"))
                elif block.get("type") == "tool_result" and block.get("tool_use_id") in next_ids:
                    next_done += 1
                    say(f"回 {n}：next {next_done} 回目（担当エージェント {agents} 体）")
                    if stop_after_next and next_done == stop_after_next and not stopped:
                        shutil.copyfile(p["out"] / ".work" / "state.json", p["logs"] / "state-at-stop.json")
                        say("C-12：プロセスを止める")
                        stop_group(proc.pid)
                        stopped = True
        proc.wait()
    return proc.returncode, stopped


def wait_for_limit(log):
    """利用枠の上限で止まったときは、解除の時刻（分からなければ 15 分）まで待つ。"""
    reset = 0
    for _, event in read_events(log):
        if event.get("type") == "rate_limit_event":
            reset = event.get("rate_limit_info", {}).get("resetsAt") or reset
    seconds = min(max(reset - time.time() + 60, 60), 6 * 3600) if reset else 900
    say(f"利用枠の上限のため、{int(seconds // 60)} 分待つ")
    time.sleep(seconds)


def status_after(reason):
    """回の終わり方から、実行の状態を決める。呼び直しを認める終わり方と C-12 の止めた回では、running のまま続ける。"""
    if reason == "finished":
        return "finished"
    if reason in RETRY_REASONS or reason == "c12_stop":
        return "running"
    return "failed"


def reopen(info, p):
    """failed で終わった実行の最後の回の終わり方を、記録から決め直す。呼び直しを認める終わり方なら、running に戻す。"""
    last = info["attempts"][-1] if info["attempts"] else None
    if info["status"] != "failed" or not last or last.get("reason") != "error" or len(info["attempts"]) >= MAX_ATTEMPTS:
        return
    last["reason"] = end_reason(read_events(p["logs"] / f"attempt-{last['n']}.jsonl"))
    info["status"] = status_after(last["reason"])
    save_json(p["run"] / "run.json", info)


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("run_dir")
    parser.add_argument("--compact-window", type=int, default=100000)
    args = parser.parse_args(argv)
    run_dir = os.path.abspath(args.run_dir)
    if os.path.commonpath([run_dir, str(REPO)]) == str(REPO):
        sys.exit(f"回のフォルダは、リポジトリの外にする: {run_dir}")
    p = paths(run_dir, args.kind)
    info = load_json(p["run"] / "run.json")
    if info is None or not info.get("attempts") and info["status"] == "setup":
        p["run"].mkdir(parents=True, exist_ok=True)
        save_json(p["run"] / "run.json", {"kind": args.kind, "status": "setup", "attempts": []})
        info = setup(args.kind, run_dir, args.compact_window)
        save_json(p["run"] / "run.json", info)
    if info["kind"] != args.kind:
        sys.exit(f"回のフォルダの種類が違う: {info['kind']}")
    reopen(info, p)

    while info["status"] == "running":
        last = info["attempts"][-1] if info["attempts"] else None
        if last and "end" not in last:
            stop_group(last.get("pid", 0))   # 前の run.py が止まった。残った claude を止めて、記録から終わり方を決める
            events = read_events(p["logs"] / f"attempt-{last['n']}.jsonl")
            last.update(end=max([t for t, _ in events] + [last["start"]]), reason=end_reason(events))
            save_json(p["run"] / "run.json", info)
            continue
        if last and last["reason"] == "rate_limit":
            wait_for_limit(p["logs"] / f"attempt-{last['n']}.jsonl")
        if last and last["reason"] == "api_error":
            say(f"API のエラーのため、{API_ERROR_WAIT} 秒待つ")
            time.sleep(API_ERROR_WAIT)
        if len(info["attempts"]) >= MAX_ATTEMPTS:
            info["status"] = "failed"
            break
        n = len(info["attempts"]) + 1
        info["attempts"].append({"n": n, "start": time.time()})
        save_json(p["run"] / "run.json", info)
        say(f"回 {n} を始める")
        c12 = info["kind"] == "c12" and not any(a.get("reason") == "c12_stop" for a in info["attempts"])
        code, stopped = run_attempt(info, p, n, C12_STOP_AFTER if c12 else 0)
        reason = "c12_stop" if stopped else end_reason(read_events(p["logs"] / f"attempt-{n}.jsonl"))
        info["attempts"][-1].update(end=time.time(), returncode=code, reason=reason)
        info["status"] = status_after(reason)
        say(f"回 {n} の終わり：{reason}（{int((info['attempts'][-1]['end'] - info['attempts'][-1]['start']) // 60)} 分）")
        save_json(p["run"] / "run.json", info)

    attempts = info["attempts"]
    if attempts:
        info["elapsed_sec"] = round(attempts[-1]["end"] - attempts[0]["start"])
        info["running_sec"] = round(sum(a["end"] - a["start"] for a in attempts))
        save_json(p["run"] / "run.json", info)
    say(f"状態：{info['status']}。採点：python evals/grade.py {run_dir}")
    return 0 if info["status"] == "finished" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
