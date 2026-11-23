"""run.py と grade.py が共に使う、回の決まり、実行の記録の読み方、Markdown の読み方。"""
import hashlib
import json
import os
import re
from pathlib import Path

EVALS = Path(__file__).resolve().parent
REPO = EVALS.parent
AGENT_MODEL = "claude-sonnet-5-5"   # 統括と担当エージェント（要件の 5.7）
JUDGE_MODEL = "claude-opus-5-5"     # 独立したエージェント（要件の 5.7）

# 回の種類：材料、ソースコードを渡すか、PDF を渡すか、作業フォルダの名前
KINDS = {
    "small": ("small", True, True, "work"),
    "large": ("large", True, True, "work"),
    "c12": ("small", True, True, "work"),
    "c13": ("small", True, True, "work"),
    "c14-src": ("cpp", True, False, "評価 の作業"),   # 日本語と空白を含むパス（C-14）
    "c14-pdf": ("small", False, True, "work"),
}

# 評価する側のセッションから引き継ぐと、振る舞いか使うモデルが変わる環境変数
DROP_ENV = ["CLAUDECODE", "CLAUDE_AUTO_BACKGROUND_TASKS", "CLAUDE_EFFORT", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE",
            "CLAUDE_AFTER_LAST_COMPACT", "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "CLAUDE_ADDITIONAL_DIRECTORIES",
            "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH",
            "ANTHROPIC_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"]
MODEL_ENV = re.compile(r"ANTHROPIC_DEFAULT_\w+_MODEL")

LIMIT_TEXT = re.compile(r"hit your .*limit|usage limit|rate limit|session limit|weekly limit|limit reached", re.I)
LEGACY_HEADING = "## 既存の設計書にだけ書かれている内容"
FENCE = re.compile(r"^ {0,3}```")
HEADING = re.compile(r"^#{1,6}\s")
WORD = re.compile(r"[A-Za-z0-9_]+")
SPAN = re.compile(r"`([^`]*)`")


def clean_env():
    env = dict(os.environ)
    for name in list(env):
        if name in DROP_ENV or MODEL_ENV.fullmatch(name):
            del env[name]
    return env


def paths(run_dir, kind):
    """回のフォルダの中の場所を返す。作業フォルダ（claude を動かすフォルダ）に、入力、プラグイン、出力先を置く。"""
    work = Path(run_dir) / KINDS[kind][3]
    return {"run": Path(run_dir), "work": work, "input": work / "input", "plugin": work / "plugin",
            "out": work / "out", "logs": Path(run_dir) / "logs", "judge": Path(run_dir) / "judge"}


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().lstrip("﻿").replace("\r", "")


def load_json(path, default=None):
    if not Path(path).exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def tree_hashes(root, skip=()):
    """フォルダの全部のファイルの SHA-1 を、相対パスごとに返す。シンボリックリンクは、リンク先の文字列で数える。"""
    result = {}
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = [d for d in dirnames if (rel_dir / d).as_posix() not in skip]
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            p = Path(dirpath) / name
            rel = (rel_dir / name).as_posix()
            if p.is_symlink():
                result[rel] = "link:" + os.readlink(p)
            else:
                with open(p, "rb") as f:
                    result[rel] = hashlib.sha1(f.read()).hexdigest()
    return result


# ---- 実行の記録（stream-json） ----

def attempt_logs(run_dir):
    return sorted(Path(run_dir, "logs").glob("attempt-*.jsonl"), key=lambda p: int(p.stem.split("-")[1]))


def read_events(log):
    """記録の1行ずつを (時刻, イベント) で返す。時刻は、run.py が書いた .times の値。"""
    times_path = log.with_suffix(".times")
    times = read_text(times_path).split() if times_path.exists() else []
    events = []
    with open(log, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            events.append((float(times[i]) if i < len(times) else 0.0, event))
    return events


# 呼び直しを認める終わり方（要件の 5.4 の C-1）
RETRY_REASONS = ("rate_limit", "restart", "api_error")


def end_reason(events):
    """1回の実行の終わり方：finished（終わった）、rate_limit（利用枠の上限）、restart（記録が途中で切れた）、
    api_error（API のエラー。認証、ネットワーク、サーバーの障害）、error（プラグインの動きで止まった）。"""
    rejected = any(e.get("type") == "rate_limit_event" and e.get("rate_limit_info", {}).get("status") == "rejected"
                   for _, e in events)
    results = [e for _, e in events if e.get("type") == "result"]
    if not results:
        return "rate_limit" if rejected else "restart"
    last = results[-1]
    if not last.get("is_error"):
        return "finished"
    if last.get("api_error_status") == 429 or LIMIT_TEXT.search(str(last.get("result", ""))) or rejected:
        return "rate_limit"
    if last.get("terminal_reason") == "api_error":
        return "api_error"
    return "error"


def tool_uses(event):
    """イベントの中のツールの呼び出しと結果を返す。"""
    message = event.get("message") or {}
    content = message.get("content")
    return content if isinstance(content, list) else []


def result_text(block):
    content = block.get("content")
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return str(content or "")


def revdoc_command(command, sub):
    """Bash のコマンドが、revdoc.py の sub（next など）の呼び出しかを返す。"""
    return "revdoc.py" in command and re.search(r"\s%s(\s|$)" % sub, command) is not None


# ---- Markdown（スクリプトの仕様 5.1、5.2） ----

def split_lines(text):
    lines = text.split("\n")
    return lines[:-1] if text.endswith("\n") else lines


def body_lines(lines, start=0):
    """本文の行を (行番号, 文) で返す。コードブロックは、全部の行をつないで1行とする。"""
    out, i, n = [], start, len(lines)
    while i < n:
        line, s = lines[i], lines[i].strip()
        if FENCE.match(line):
            j = i + 1
            while j < n and lines[j].strip() != "```":
                j += 1
            out.append((i + 1, "\n".join(lines[i:j + 1])))
            i = j + 1
        elif s.startswith("|"):
            j = i
            while j < n and lines[j].strip().startswith("|"):
                j += 1
            out.extend((k + 1, lines[k]) for k in range(i + 2, j))
            i = j
        else:
            if s and not HEADING.match(line) and not (s.startswith("<!--") and s.endswith("-->")):
                out.append((i + 1, line))
            i += 1
    return out


def legacy_index(lines):
    """「既存の設計書にだけ書かれている内容」の見出しの位置（ないときは行の数）。"""
    for i, line in enumerate(lines):
        if line.rstrip() == LEGACY_HEADING:
            return i
    return len(lines)


def spans(line):
    return SPAN.findall(line)


def outside_spans(line):
    return SPAN.sub(" ", line)


def page_files(folder, stem):
    """一覧の本体と続きのファイル（stem~p2.md など）を、順に返す。"""
    files = [Path(folder) / (stem + ".md")] + sorted(Path(folder).glob(stem + "~p*.md"),
                                                       key=lambda p: int(p.stem.split("~p")[1]))
    return [p for p in files if p.exists()]
