"""1回の実行の出力と記録を、要件の 5.4 の条件（C-1 〜 C-15）で採点する。

使い方: python evals/grade.py <回のフォルダ> [--no-judge]

- 機械で決まる条件は、このスクリプトだけで判定する。
- 独立したエージェントの判定が要る条件は、乱数の種を固定して抜き取り、claude -p（読むだけのツール）に判定させる。
  判定は、判定に要るファイルだけを置いたフォルダの中で動かし、出力や記録や正解は読めないようにする。
  判定の入力と結果は <回のフォルダ>/judge/ に残し、採点し直すときは、ある結果を使い回す。
  --no-judge のときは、この条件を「判定なし」にする。
- 結果は <回のフォルダ>/result.json と report.md（評価の報告に貼る表）に書く。
"""
import argparse
import hashlib
import http.server
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
from bisect import bisect_left
from functools import partial
from pathlib import Path

from common import (AGENT_MODEL, FENCE, HEADING, JUDGE_MODEL, REPO, RETRY_REASONS, WORD, attempt_logs, body_lines,
                    clean_env, end_reason, legacy_index, load_json, outside_spans, page_files, paths, read_events,
                    read_text, result_text, revdoc_command, save_json, spans, split_lines, tool_uses, tree_hashes)

SEED = 20261123
CONDITIONS = {
    "small": ["C-1", "C-2", "C-3", "C-4", "C-5", "C-6", "C-7", "C-8", "C-9", "C-10", "C-11", "C-15"],
    "c12": ["C-12"], "c13": ["C-13"], "c14-src": ["C-14", "C-2"], "c14-pdf": ["C-14"],
}
CONDITIONS["large"] = CONDITIONS["small"]
STAGE_NAMES = {"analyze": "解析", "convert": "変換", "match": "照合", "write_module": "執筆（モジュール）",
               "write_overall": "執筆（全体）", "verify": "検証"}
AGENT_TOOLS = {"reverse:pdf-converter": {"Read", "Write"}}
for _name in ("code-analyst", "doc-matcher", "doc-writer", "doc-verifier"):
    AGENT_TOOLS["reverse:" + _name] = {"Read", "Grep", "Glob", "Write"}
FILE_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Grep", "Glob"}
ZYBO = "target/zybo_z7_gcc/xilinx_sdk/zybo_z7_hw"   # C-11 のコメントが英語だけのモジュール
JA = re.compile(r"[ぁ-ゖァ-ヺー々㐀-䶿一-鿿]")
SEARCH_WORD = re.compile(r"(?<=[ぁ-ゖ])[ァ-ヺー々㐀-䶿一-鿿]{3,}")
REQ_ID = re.compile(r"\b(?:FR|PR|UR|IR|DR|DC|SA)-[A-Za-z0-9-]*[0-9]{3,}\b")
VERDICTS = ["正しい", "誤り", "根拠がない", "事実を述べていない"]


def rng(name):
    return random.Random(f"{SEED}:{name}")


def pick(items, n, name):
    """抜き取り。決めた件数に満たないときは、全件を返す。"""
    return list(items) if len(items) <= n else rng(name).sample(list(items), n)


def ratio_ok(good, total, need, of):
    """total が of に満たないときも、同じ割合以上で合格とする。0 件は合格。"""
    return total == 0 or good * of >= need * total


def result(passed, **counts):
    return {"pass": passed, "counts": counts}


def heading_chains(lines):
    """行ごとに、その行より前の見出しの並び（上のレベルから。スクリプトの仕様の 8.5 の節）を返す。"""
    chains, stack, fence = [], [], False
    for line in lines:
        chains.append([h for _, h in stack])
        if fence:
            fence = line.strip() != "```"
        elif FENCE.match(line):
            fence = True
        elif HEADING.match(line):
            level = len(line) - len(line.lstrip("#"))
            stack = [(lv, h) for lv, h in stack if lv < level] + [(level, line.rstrip())]
    return chains


def place(src, dst):
    """判定のフォルダにファイルを置く。読むだけなので、できればハードリンクにする。"""
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


class Run:
    """1回の実行の出力と記録。"""

    def __init__(self, run_dir, use_judge):
        self.info = load_json(Path(run_dir) / "run.json")
        self.kind = self.info["kind"]
        self.p = paths(run_dir, self.kind)
        self.use_judge = use_judge
        self.docs = self.p["out"] / "docs"
        work = self.p["out"] / ".work"
        self.plan = load_json(work / "plan.json", {})
        self.state = load_json(work / "state.json", {})
        self.truth = load_json(REPO / "evals" / "truth" / f"{self.info['case']}.json")
        self.logs = [(int(log.stem.split("-")[1]), read_events(log)) for log in attempt_logs(run_dir)]
        self._names = None

    # ---- ソースコード ----
    def source_path(self, rel):
        copy = self.p["out"] / ".work" / "src-utf8" / rel
        return copy if copy.exists() else self.p["input"] / "src" / rel

    def names(self):
        """名前の集まり（対象のソースファイルの内容とパスの語）。"""
        if self._names is None:
            words = set()
            for f in self.plan.get("files", []):
                words.update(WORD.findall(f["path"]))
                words.update(WORD.findall(read_text(self.source_path(f["path"]))))
            self._names = sorted(words)
        return self._names

    def unknown_words(self, text):
        names = self.names()
        bad = []
        for span in spans(text):
            for m in re.finditer(r"([A-Za-z0-9_]+)(\*?)", span):
                word, star = m.groups()
                i = bisect_left(names, word)
                found = i < len(names) and (names[i].startswith(word) if star else names[i] == word)
                if not found:
                    bad.append(word)
        return bad

    def quote_found(self, item):
        path = self.source_path(item.get("file", ""))
        if not item.get("quote", "").strip() or not path.is_file():
            return False
        lines = split_lines(read_text(path))[max(item["start"], 1) - 1:item["end"]]
        norm = lambda s: re.sub(r"\s+", " ", s).strip()
        return all(norm(q) in norm("\n".join(lines)) for q in item["quote"].split("\n") if q.strip())

    # ---- 新しい設計書 ----
    def doc_lines(self, rel, after_legacy=False):
        """本文の行。after_legacy が偽なら見出し「既存の設計書にだけ…」より前、真なら後ろ。"""
        lines = split_lines(read_text(self.docs / rel))
        cut = legacy_index(lines)
        rows = body_lines(lines[cut:] if after_legacy else lines[:cut])
        return [(n + cut if after_legacy else n, t) for n, t in rows]

    def new_docs(self):
        """新しい設計書のファイル（docs/ からの相対パス）。"""
        return sorted(p.relative_to(self.docs).as_posix() for sub in ("design", "requirements")
                      for p in (self.docs / sub).rglob("*.md")) if self.docs.exists() else []

    def verify_targets(self):
        """検証の対象の行（SR-59、スクリプトの仕様の 8.5）。分類は、機能の要求、モジュール、全体。
        分けたモジュールの入口、続きのファイル、代わりのファイルは除く。同じ節の同じ文は、最初の行だけにする。"""
        none = self.plan.get("none_sentence")
        substitutes = {re.sub(r"^docs/", "", p) for j in self.state.get("jobs", []) for p in j.get("substitute") or []}
        rows = []
        for rel in self.new_docs():
            path = self.docs / rel
            if "~p" in path.stem or path.with_suffix("").is_dir() or rel in substitutes:
                continue
            cat = "fr" if rel.startswith("requirements/3-1-functions/") else \
                "module" if rel.startswith("design/modules/") else "overall"
            chains, seen = heading_chains(split_lines(read_text(path))), set()
            for n, text in self.doc_lines(rel):
                sha = hashlib.sha1("\n".join(chains[n - 1] + [text]).encode("utf-8")).hexdigest()
                if text.strip() != none and re.sub(r"^\s*([-*+]|[0-9]+\.) ", "", text).strip() != none \
                        and sha not in seen:
                    seen.add(sha)
                    rows.append({"cat": cat, "file": rel, "line": n, "text": text, "chain": chains[n - 1]})
        return rows

    def table_header(self, row):
        """表の行なら、その表の見出しの行を返す。"""
        lines = split_lines(read_text(self.docs / row["file"]))
        n = row["line"] - 1
        if not lines[n].strip().startswith("|"):
            return None
        while n > 0 and lines[n - 1].strip().startswith("|"):
            n -= 1
        return lines[n]

    def legacy_pages(self):
        """既存の設計書の Markdown を、ページごとにまとめる（最初の PDF）。"""
        pages, page = {}, 0
        folder = self.docs / "legacy" / self.plan["pdfs"][0]["folder"]
        for f in sorted(folder.glob("*.md")):
            for line in split_lines(read_text(f)):
                m = re.match(r"<!-- page: ([0-9]+) -->", line.strip())
                if m:
                    page = int(m.group(1))
                    continue
                pages.setdefault(page, []).append(line)
        return {k: "\n".join(v).strip() for k, v in pages.items()}, folder

    def render_page(self, page, folder):
        import pypdfium2 as pdfium
        png = self.p["judge"] / folder / f"p{page:04d}.png"
        if not png.exists():
            png.parent.mkdir(parents=True, exist_ok=True)
            pdf = pdfium.PdfDocument(str(self.p["input"] / "pdf" / self.plan["pdfs"][0]["path"]))
            pdf[page - 1].render(scale=150 / 72).to_pil().save(png)
            pdf.close()
        return png

    # ---- 独立したエージェント ----
    def judge(self, name, prompt, props, ids, files=None, src=True):
        """claude -p に判定させ、id ごとの答えを返す。結果があれば使い回す。
        判定は、空のフォルダ judge/ws-<name>/ に、src/（対象のソースファイルの写し）と files（そのフォルダからのパス →
        元のファイルかフォルダ）だけを置き、その中だけを読める設定で動かす。入力と答えは、そのフォルダの外に残す。"""
        saved = self.p["judge"] / f"{name}.json"
        answer = (load_json(saved) or {}).get("items")
        if answer is None:
            if not self.use_judge:
                return None
            ws = self.p["judge"] / f"ws-{name}"
            if ws.exists():
                shutil.rmtree(ws)
            ws.mkdir(parents=True)
            if src:
                for f in self.plan.get("files", []):
                    place(self.source_path(f["path"]), ws / "src" / f["path"])
            for rel, source in (files or {}).items():
                if Path(source).is_dir():
                    shutil.copytree(source, ws / rel, copy_function=place)
                else:
                    place(source, ws / rel)
            schema = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
                "type": "object", "required": list(props), "properties": props}}}}
            text = ("あなたは、作成に関わっていない、独立した採点者である。ファイルは読むだけにする。"
                    + ("ソースコードは src/ にある。根拠のファイルは、src/ からの相対パスで書く。" if src else "")
                    + f"\n\n{prompt}")
            with open(saved.with_suffix(".prompt.md"), "w", encoding="utf-8") as f:
                f.write(text)
            for _ in range(2):
                run = subprocess.run(["claude", "-p", "--model", JUDGE_MODEL, "--tools", "Read,Grep,Glob",
                                      "--allowedTools", "Read(./**),Grep(./**),Glob(./**)", "--output-format", "json",
                                      "--json-schema", json.dumps(schema, ensure_ascii=False)],
                                     input=text, capture_output=True, text=True, encoding="utf-8",
                                     cwd=ws, env=clean_env(), timeout=3600)
                try:
                    out = json.loads(run.stdout)
                    answer, models = out["structured_output"]["items"], sorted(out.get("modelUsage", {}))
                except (ValueError, KeyError, TypeError):
                    answer = None
                if answer is not None and set(ids) <= {a["id"] for a in answer}:
                    break
                answer = None
            if answer is None:
                sys.exit(f"独立したエージェントの答えを受け取れない: {name}\n{run.stdout[-2000:]}{run.stderr[-2000:]}")
            if any(m.split("[")[0] != JUDGE_MODEL for m in models):
                sys.exit(f"独立したエージェントが、{JUDGE_MODEL} のほかのモデルを使った: {name} {models}")
            save_json(saved, {"models": models, "items": answer})
            shutil.rmtree(ws)
        return {a["id"]: a for a in answer}

    # ---- 実行の記録 ----
    def scan(self):
        """記録を1回読み、機械で決まる条件に使う数を求める。"""
        s = {"questions": 0, "denials": 0, "early_next": 0, "next": 0, "next_max_sec": 0, "compactions": 0,
             "max_context": 0, "main_file_tools": 0, "agent_tool_misuse": [], "agents_without_log": 0,
             "models": set(), "serve": None, "final": "", "restarts": {}}
        agents = {}   # Agent の呼び出しの ID → [種類, 子のツールの (呼び出しの ID, 名前), セッションの ID, 担当の ID]
        no_tool = set()   # ツールがないと断られた呼び出しの ID（C-15 で数えない）
        hooked = set()   # SR-86 のフックが止めた呼び出しの ID（C-1 の denials に数えない）
        for n, events in self.logs:
            reason = end_reason(events)
            if reason in RETRY_REASONS and n != self.logs[-1][0]:
                s["restarts"][reason] = s["restarts"].get(reason, 0) + 1
            pending, calls = set(), {}
            for t, e in events:
                kind, parent = e.get("type"), e.get("parent_tool_use_id")
                if kind == "result":
                    s["denials"] += sum(d.get("tool_use_id") not in hooked for d in e.get("permission_denials") or [])
                    s["final"] = str(e.get("result", ""))
                if kind == "system" and e.get("subtype") == "compact_boundary" and not parent:
                    s["compactions"] += 1
                if kind == "system" and e.get("subtype") == "task_notification":
                    pending.discard(e.get("tool_use_id"))
                if kind == "assistant":
                    s["models"].add(e["message"].get("model"))
                if kind == "assistant" and not parent:
                    u = e["message"].get("usage") or {}
                    s["max_context"] = max(s["max_context"], sum(u.get(k, 0) for k in (
                        "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")))
                for b in tool_uses(e):
                    if b.get("type") == "tool_use":
                        name, args = b.get("name"), b.get("input") or {}
                        calls[b.get("id")] = (name, args, t)
                        if parent:
                            agents.setdefault(parent, ["?", [], None, None])[1].append((b.get("id"), name))
                            continue
                        if name == "AskUserQuestion":
                            s["questions"] += 1
                        elif name == "Agent":
                            agents.setdefault(b.get("id"), [None, [], None, None])[0] = args.get("subagent_type", "")
                            agents[b.get("id")][2] = e.get("session_id")
                            pending.add(b.get("id"))
                        elif name == "Bash" and revdoc_command(args.get("command", ""), "next"):
                            s["early_next"] += bool(pending)
                        elif name in FILE_TOOLS and self.touches_out(name, args):
                            s["main_file_tools"] += 1
                    elif b.get("type") == "tool_result":
                        text = result_text(b)
                        if b.get("is_error") and "No such tool available" in text:
                            no_tool.add(b.get("tool_use_id"))
                        if b.get("is_error") and re.search(r"PreToolUse:\w+ hook error", text):
                            hooked.add(b.get("tool_use_id"))
                        elif b.get("is_error") and re.search(r"requested permissions|haven't granted", text):
                            s["denials"] += 1
                        name, args, t0 = calls.get(b.get("tool_use_id"), ("", {}, t))
                        if name == "Agent" and not parent:
                            # バックグラウンドで始めたときだけ、終わりの通知（task_notification）まで待つ
                            info = e.get("tool_use_result") if isinstance(e.get("tool_use_result"), dict) else {}
                            if b.get("tool_use_id") in agents:
                                agents[b.get("tool_use_id")][3] = info.get("agentId")
                            background = info.get("status") == "async_launched" or \
                                not info and re.search(r"(?i)async agent launched", text)
                            if b.get("is_error") or not background:
                                pending.discard(b.get("tool_use_id"))
                        if name == "Bash" and revdoc_command(args.get("command", ""), "next"):
                            s["next"] += 1
                            s["next_max_sec"] = max(s["next_max_sec"], round(t - t0, 1))
                        if name == "Bash" and revdoc_command(args.get("command", ""), "serve"):
                            for line in text.splitlines():
                                if line.strip().startswith("{") and '"serving"' in line:
                                    s["serve"] = json.loads(line.strip())
        # 担当エージェントのツール。記録に Read も Write もない担当は、Claude Code が残した担当の記録から読む
        for kind, uses, session, agent_id in agents.values():
            if kind is None:
                continue
            if not {"Read", "Write"} & {x for _, x in uses} and session and agent_id:
                for log in Path.home().glob(f".claude/projects/*/{session}/subagents/agent-{agent_id}.jsonl"):
                    for _, e in read_events(log):
                        if e.get("type") == "assistant":
                            s["models"].add(e["message"].get("model"))
                        for b in tool_uses(e):
                            if b.get("type") == "tool_use":
                                uses.append((b.get("id"), b.get("name")))
                            elif b.get("is_error") and "No such tool available" in result_text(b):
                                no_tool.add(b.get("tool_use_id"))
            names = [x for i, x in uses if i not in no_tool]
            if not {"Read", "Write"} & set(names):
                s["agents_without_log"] += 1
            s["agent_tool_misuse"] += [f"{kind}:{x}" for x in names if x not in AGENT_TOOLS.get(kind, set())]
        s["models"] = sorted(m for m in s["models"] if m and m != "<synthetic>")
        s["hook_blocked"] = len(hooked)
        return s

    def touches_out(self, name, args):
        """統括のファイルのツールの呼び出しが、出力先の中を指すか。相対パスは、claude を動かしたフォルダから解決する。"""
        cwd, out = Path(self.info["cwd"]), Path(os.path.normpath(self.p["out"]))
        targets = [str(args[k]) for k in ("file_path", "path", "notebook_path") if args.get(k)]
        if name == "Glob" and args.get("pattern"):
            base = Path(cwd, args.get("path") or "")
            targets.append(str(base / re.split(r"[*?\[{]", str(args["pattern"]))[0]))
        for target in targets:
            p = Path(os.path.normpath(cwd / target))
            if p == out or out in p.parents:
                return True
        return False

    def check(self):
        revdoc = self.p["plugin"] / "skills" / "make-design-docs" / "scripts" / "revdoc.py"
        run = subprocess.run([sys.executable, str(revdoc), "check", "--out", str(self.p["out"])],
                             capture_output=True, text=True, encoding="utf-8")
        try:
            return json.loads(run.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {"ok": False, "passed": False, "error": (run.stdout + run.stderr)[-300:]}

    def failed_jobs(self):
        counts = {}
        for job in self.state.get("jobs", []):
            c = counts.setdefault(job["kind"], [0, 0])
            c[0] += 1
            c[1] += job["status"] == "failed"
        return counts


# ---- 条件ごとの判定 ----

def c1(run, s):
    done = run.state.get("stage") == "done"
    check = run.check()
    jobs = run.failed_jobs()
    if run.info["case"] == "large":
        jobs_ok = all(failed <= max(1, total * 0.05) for total, failed in jobs.values())
    else:
        jobs_ok = sum(f for _, f in jobs.values()) == 0
    serve = s["serve"] or {}
    final = s["final"]
    # 一覧の場所は、パス（serve が返した絶対パスか、出力先か docs/ からの相対パス）で書く。ファイル名だけでは足りない
    located = lambda key: f"review/{key}.md" in final
    reply_ok = bool(serve.get("url")) and serve["url"] in final and located("unknowns") and \
        (serve.get("discrepancies") is None or located("discrepancies"))
    models_ok = s["models"] == [AGENT_MODEL]   # 統括と担当エージェントが、5.7 のモデルだけで動いた
    return result(done and check.get("passed") is True and jobs_ok and s["questions"] == 0 and s["denials"] == 0
                  and s["early_next"] == 0 and reply_ok and models_ok,
                  done=done, check=check.get("passed"), problems=check.get("problem_count"),
                  failed={STAGE_NAMES[k]: f"{f}/{t}" for k, (t, f) in jobs.items()}, questions=s["questions"],
                  denials=s["denials"], hook_blocked=s["hook_blocked"], early_next=s["early_next"], reply=reply_ok,
                  restarts=s["restarts"],
                  models=s["models"])


C2_PROPS = {"id": {"type": "integer"}, "verdict": {"type": "string", "enum": VERDICTS}, "file": {"type": "string"},
            "start": {"type": "integer"}, "end": {"type": "integer"}, "quote": {"type": "string"},
            "names_unquoted": {"type": "boolean"}, "missing_condition": {"type": "boolean"}}
C2_PROMPT = """次の各項目は、ソースコードについて書いた設計書の行である。項目ごとに、判定を1つ選ぶ。
各項目には、行のある設計書のファイル名と、行の上にある見出しの並び（上のレベルから）を付けた。行は、その見出しの下で読む。

- 正しい：行の全部を、引用したソースコードの行で確かめられた。
- 誤り：一部でもソースコードと違う。
- 根拠がない：ソースコードで確かめられない。
- 事実を述べていない：ソースコードについての内容を持たない行（文書の説明、表の案内）。コードスパン（バッククォートで囲んだ所）のある行は、これにしない。

「正しい」と「誤り」のときは、根拠のファイル（file）、行の範囲（start、end）、その範囲の行の引用（quote。ソースコードのとおりに写す）を書く。ほかの判定では、空の文字列と 0 にする。
引用は、範囲の行をそのまま写す。途中を省く記号を書かない。長いときは、範囲を狭めて、確かめるのに要る行だけを引用する。
あわせて、次の2つに true か false で答える。
- names_unquoted：ソースコードの名前（関数、変数、型、マクロ）を、バッククォートで囲まずに書いているか。
- missing_condition：条件付きコンパイル（#if、#ifdef など）の中の内容を、条件の名前を書かずに述べているか。
"""


def cells(row):
    return [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]


def plain(text, header=None):
    """C-2 で渡す形にそろえる。表の行は「列の見出し：セル」を「。」でつなぎ（要件の 5.4）、
    箇条書きの記号と先頭の要求の ID を除く。"""
    s = text.strip()
    if s.startswith("|"):
        pairs = zip(cells(header), cells(s)) if header else (("", c) for c in cells(s))
        s = "。".join(f"{h}：{c}" if h else c for h, c in pairs if c and not REQ_ID.fullmatch(c))
    s = re.sub(r"^([-*+]|[0-9]+\.) ", "", s)
    return re.sub(r"^%s(:\s*|、)" % REQ_ID.pattern, "", s)


def item_list(items):
    return "\n".join(f"### 項目 {i}\n{text}\n" for i, text in items)


def placed(text, row):
    """C-2 と C-3 で渡す形。行に、設計書のファイル名と見出しの並びを付ける（要件の 5.4）。"""
    chain = " > ".join(h.lstrip("#").strip() for h in row["chain"]) or "なし"
    return f"- 設計書：{row['file']}\n- 見出し：{chain}\n- 行：{text}"


def false_place(rows, text, k):
    """誤りと分かっている文に付ける場所。文のコードスパンの名前を前から順に見て、最初に、同じ名前を含む行が
    見つかった名前で、その行の1つを選ぶ。同じ名前を含む行がないときは、検証の対象の行の1つを選ぶ。"""
    for name in spans(text):
        hits = [r for r in rows if re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(name), r["text"])]
        if hits:
            return rng(f"C-3-place-{k}").choice(hits)
    return rng(f"C-3-place-{k}").choice(rows) if rows else {"file": "", "chain": []}


def c2_c3(run):
    rows = run.verify_targets()   # 3つの種類から 10 件ずつ抜き取る
    picked = {cat: pick([r for r in rows if r["cat"] == cat], 10, f"C-2-{cat}") for cat in ("fr", "module", "overall")}
    real = [r for cat in ("fr", "module", "overall") for r in picked[cat]]
    false = run.truth["false_statements"] if run.truth and run.kind != "c14-src" else []
    tries, c3_ok, judged = 3 if false else 1, None, None
    for t in range(1, tries + 1):
        mixed = [(placed(plain(r["text"], run.table_header(r)), r), r) for r in real] + \
            [(placed(plain(f), false_place(rows, f, k)), None) for k, f in enumerate(false)]   # 区別を付けずに渡す
        rng(f"C-2-order-{t}").shuffle(mixed)
        items = list(enumerate(mixed, 1))
        answers = run.judge(f"c2-try{t}", C2_PROMPT + "\n" + item_list([(i, m[0]) for i, m in items]), C2_PROPS,
                            [i for i, _ in items])
        if answers is None:
            break
        judged = [(answers[i], text, row) for i, (text, row) in items]
        wrong = sum(a["verdict"] == "誤り" for a, _, row in judged if row is None)
        c3_ok = not false or wrong * 5 >= 4 * len(false)
        if c3_ok:
            break
    out = {}
    if judged is None:
        out["C-2"] = result(None, lines=len(real))
    else:
        rows = [(a, row["text"]) for a, _, row in judged if row is not None]
        facts = [(a, text) for a, text in rows if a["verdict"] != "事実を述べていない"]
        # コードブロックの行では、名前をバッククォートで囲めないので、names_unquoted と unknown_words を見ない
        correct = sum(a["verdict"] == "正しい" and not a["missing_condition"] and run.quote_found(a)
                      and (text.startswith("```") or not (a["names_unquoted"] or run.unknown_words(text)))
                      for a, text in facts)
        fr_ok, fr_n = c2_fr(run, picked["fr"])
        empty = [cat for cat in picked if not picked[cat]]
        # 抜き取った行が全部「事実を述べていない」のときは、合格の範囲（抜き取る先が 0 件）に入らない
        passed = None if not c3_ok else (not empty and len(facts) > 0 and correct * 10 >= 9 * len(facts)
                                         and fr_ok is not None and ratio_ok(fr_ok, fr_n, 8, 10))
        out["C-2"] = result(passed, lines=len(rows), facts=len(facts), correct=correct,
                            no_basis=sum(a["verdict"] == "根拠がない" for a, _ in rows),
                            not_fact=len(rows) - len(facts), empty_kinds=empty, fr_three_yes=f"{fr_ok}/{fr_n}",
                            tries=t)
    if false:
        wrong = None if judged is None else sum(a["verdict"] == "誤り" for a, _, row in judged if row is None)
        out["C-3"] = result(None if judged is None else bool(c3_ok), wrong=f"{wrong}/{len(false)}", tries=t)
    return out


def c2_fr(run, rows):
    props = {"id": {"type": "integer"}, "single": {"type": "boolean"}, "has_target": {"type": "boolean"},
             "has_condition_or_result": {"type": "boolean"}}
    prompt = ("次の各項目は、機能の要求の文である。項目ごとに、3つの問いに true（はい）か false（いいえ）で答える。\n"
              "- single：内容が1つだけか。\n- has_target：対象の名前があるか。\n- has_condition_or_result：条件か結果があるか。\n\n")
    items = list(enumerate((r["text"] for r in rows), 1))
    if not items:
        return 0, 0
    answers = run.judge("c2-fr", prompt + item_list(items), props, [i for i, _ in items])
    if answers is None:
        return None, len(items)
    return sum(all(answers[i][k] for k in ("single", "has_target", "has_condition_or_result")) for i, _ in items), \
        len(items)


def extern_names(run):
    names = set()
    for h in (run.p["input"] / "src" / "include").rglob("*.h"):
        for line in split_lines(read_text(h)):
            if re.match(r"\s*extern\s", line) and not re.match(r'\s*extern\s+"C"', line):
                m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\(", line)
                if m:
                    names.add(m.group(1))
    return names


def c4(run):
    names = extern_names(run)
    words = set()
    for rel in run.new_docs():
        lines = split_lines(read_text(run.docs / rel))
        for line in lines[:legacy_index(lines)]:
            words.update(WORD.findall(line))
    found = len(names & words)
    removed = sum(e["type"] in ("verify_unknown", "verify_unjudged") for e in run.state.get("log", []))
    targets = removed + len(run.verify_targets())
    return result(ratio_ok(found, len(names), 9, 10) and removed * 5 <= targets,
                  extern=f"{found}/{len(names)}", removed=f"{removed}/{targets}",
                  missing=sorted(names - words)[:20])


def discrepancies(run):
    items, item = [], None
    for f in page_files(run.docs / "review", "discrepancies"):
        for line in split_lines(read_text(f)):
            if line.startswith("## "):
                item = {} if re.match(r"## [0-9]+\. ", line) else None
                if item is not None:
                    items.append(item)
            elif item is not None and line.startswith("- ") and ": " in line:
                key, value = line[2:].split(": ", 1)
                item[key] = value.strip()
    for it in items:
        m = re.match(r"(.+) p\.([0-9]+)$", it.get("既存の設計書での場所", ""))
        it["pdf"], it["page"] = (m.group(1), int(m.group(2))) if m else ("", 0)
        loc = it.get("ソースコードでの場所", "").rsplit(" ", 1)
        it["file"], it["name"] = (loc[0], loc[1]) if len(loc) == 2 else ("", "")
    return items


BASIS = ("答えの根拠のファイル（file）、行の範囲（start、end）、その行の引用（quote）を書く。"
         "根拠がないときは、空の文字列と 0 にする。")
BASIS_PROPS = {"file": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"},
               "quote": {"type": "string"}}


def c5(run):
    items = discrepancies(run)
    changes = run.truth["changes"]
    listed = sum(any((it["file"] == ch["file"] or Path(it["file"]).name == Path(ch["file"]).name)
                     and it["name"] in ch["names"] and any(abs(it["page"] - p) <= 1 for p in ch["pages"])
                     for it in items) for ch in changes)
    # 変えた場所の関数名か、変える前の値を含む、検証の対象の行（行の全体。コードブロックはブロックの全体）
    rows = []
    for r in run.verify_targets():
        hit = [k for k, ch in enumerate(changes, 1)
               if any(re.search(r"\b%s\b" % re.escape(n), r["text"]) for n in ch["names"])
               or re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(ch["before_value"]), r["text"])]
        if hit:
            rows.append((r, hit))
    listing = "\n".join(f"変更 {k}: {ch['file']} {', '.join(ch['names'])} {ch['line']} 行\n"
                        f"  変える前の行: {ch['before_line']}\n  変えた後の行: {ch['after_line']}\n"
                        f"  変える前の値: {ch['before_value']}　変えた後の値: {ch['after_value']}"
                        for k, ch in enumerate(changes, 1))
    prompt = ("ソースコードのコピーには、既知の変更を入れてある。いまのソースコードは、変えた後の内容である。\n\n"
              f"{listing}\n\n次の各項目は、新しい設計書の行である。項目ごとに、示した関係する変更について、"
              "変える前の内容を書いているか（writes_before）を答え、理由（reason）を短く書く。"
              f"{BASIS}\n\n")
    items_text = [(i, f"関係する変更: {', '.join(map(str, hit))}\n{r['text']}") for i, (r, hit) in enumerate(rows, 1)]
    before = 0
    if rows:
        answers = run.judge("c5", prompt + item_list(items_text),
                            {"id": {"type": "integer"}, "writes_before": {"type": "boolean"},
                             "reason": {"type": "string"}, **BASIS_PROPS}, [i for i, _ in items_text])
        before = None if answers is None else sum(answers[i]["writes_before"] for i, _ in items_text)
    return result(None if before is None else ratio_ok(listed, len(changes), 8, 10) and before == 0,
                  listed=f"{listed}/{len(changes)}", candidates=len(rows), writes_before=before)


def c6(run):
    items = discrepancies(run)
    complete = sum(bool(it["pdf"] and it["page"] and it["file"] and it["name"]) for it in items)
    picked = pick(list(enumerate(items, 1)), 10, "C-6")
    texts, images = [], {}
    for i, it in picked:
        png = f"pages/p{it['page']:04d}.png" if it["page"] else ""
        if png:
            images[png] = run.render_page(it["page"], "c6")
        texts.append((i, f"- 既存の設計書：{it['pdf']} {it['page']} ページ（画像：{png}）\n"
                         f"- 既存の設計書の内容：{it.get('既存の設計書の内容', '')}\n"
                         f"- ソースコードの場所：{it['file']} の {it['name']}\n"
                         f"- ソースコードの内容：{it.get('ソースコードの内容', '')}"))
    prompt = ("次の各項目は、食い違いの一覧の項目である。項目ごとに答える。\n"
              "- legacy_ok：「既存の設計書の内容」が、そのページに書かれたとおりにあるか（画像を Read で開いて確かめる）。\n"
              "- source_ok：「ソースコードの内容」が、そのソースファイルのその関数（または定義）に、書かれたとおりにあるか。\n"
              "- conflict：2つの内容が両立しないか。\n"
              "- file、start、end、quote：ソースコードの根拠（相対パス、行の範囲、その行の引用）。\n\n")
    good = 0
    if texts:
        answers = run.judge("c6", prompt + item_list(texts), {
            "id": {"type": "integer"}, "legacy_ok": {"type": "boolean"}, "source_ok": {"type": "boolean"},
            "conflict": {"type": "boolean"}, "file": {"type": "string"}, "start": {"type": "integer"},
            "end": {"type": "integer"}, "quote": {"type": "string"}}, [i for i, _ in texts], files=images)
        good = None if answers is None else sum(
            answers[i]["legacy_ok"] and answers[i]["source_ok"] and answers[i]["conflict"] for i, _ in texts)
    return result(None if good is None else complete == len(items) and ratio_ok(good, len(texts), 8, 10),
                  items=len(items), complete=complete, sampled=f"{good}/{len(texts)}")


def legacy_rows(run):
    """見出し「既存の設計書にだけ…」から後ろの本文の行。"""
    rows = []
    for rel in run.new_docs():
        lines = split_lines(read_text(run.docs / rel))
        if "~p" in Path(rel).stem or legacy_index(lines) < len(lines):
            rows += [(rel, t) for _, t in run.doc_lines(rel, after_legacy=True)]
    return rows


def c7(run):
    rows = legacy_rows(run)
    found = sum(any(all(w in t for w in lo["words"]) for _, t in rows) for lo in run.truth["legacy_only"])
    lead = re.compile(r"^【既存設計書のみ】次の(表|図)は、既存の設計書の内容である。$")
    picked = pick([t for _, t in rows if not lead.match(t.strip())], 10, "C-7")
    items = list(enumerate((t.replace("【既存設計書のみ】", "") for t in picked), 1))   # 印は、答えを示すので除く
    unverifiable = 0
    if items:
        answers = run.judge("c7", "次の各項目は、設計書の行である。"
                            "項目ごとに、その内容をソースコードで確かめられるか（verifiable）を答える。確かめられるときは、"
                            "根拠のファイル、行の範囲、その行の引用を書く。確かめられないときは、空の文字列と 0 にする。\n\n"
                            + item_list(items), {"id": {"type": "integer"}, "verifiable": {"type": "boolean"},
                                                 "file": {"type": "string"}, "start": {"type": "integer"},
                                                 "end": {"type": "integer"}, "quote": {"type": "string"}},
                            [i for i, _ in items])
        unverifiable = None if answers is None else sum(not answers[i]["verifiable"] for i, _ in items)
    lo = len(run.truth["legacy_only"])
    return result(None if unverifiable is None else ratio_ok(found, lo, 8, 10) and ratio_ok(unverifiable, len(items), 8, 10),
                  marked=f"{found}/{lo}", rows=len(rows), unverifiable=f"{unverifiable}/{len(items)}")


def c8(run):
    rows, section = [], ""
    for f in page_files(run.docs / "review", "unknowns"):
        for line in split_lines(read_text(f)):
            if line.startswith("### "):
                section = line[4:].strip()
            elif line.startswith("## "):
                section = ""
            elif line.startswith("- ") and section in ("執筆担当が書いた不明点", "検証で確かめられなかった行"):
                rows.append(line[2:])
    items = list(enumerate(pick(rows, 10, "C-8"), 1))
    unknown = 0
    if items:
        answers = run.judge("c8", "次の各項目は、不明点の一覧の項目である。項目ごとに、ソースコードの全体と、既存の設計書"
                            "（Markdown にしたもの。legacy/ にある）を探して、答えが分かるか（answer_found）を答える。"
                            f"{BASIS}\n\n" + item_list(items),
                            {"id": {"type": "integer"}, "answer_found": {"type": "boolean"}, **BASIS_PROPS},
                            [i for i, _ in items], files={"legacy": run.docs / "legacy"})
        unknown = None if answers is None else sum(not answers[i]["answer_found"] for i, _ in items)
    return result(None if unknown is None else ratio_ok(unknown, len(items), 8, 10),
                  rows=len(rows), not_found=f"{unknown}/{len(items)}")


def convert_rules():
    """変換の決まり（SR-26 〜 SR-31）と、図の行を画像の参照に置き換える決まり（SR-40）の文を、要件の文書から取る。"""
    text = read_text(REPO / "docs" / "requirements" / "specification.md")
    return "\n".join("- " + re.split(r"(?<!\\)\|", line)[2].strip().replace("\\|", "|") for line in text.splitlines()
                     if re.match(r"\| SR-(2[6-9]|3[01]|40) \|", line))


def c9(run):
    pages, folder = run.legacy_pages()
    props = {"id": {"type": "integer"}, "ok": {"type": "boolean"}, "problems": {"type": "array", "items": {
        "type": "object", "required": ["kind", "where", "detail"], "properties": {
            "kind": {"type": "string", "enum": ["欠け", "誤り"]}, "where": {"type": "string"},
            "detail": {"type": "string"}}}}}
    good, judged = 0, 0
    for page in run.truth["check_pages"]:
        png = run.render_page(page, "c9")
        md = "\n\n".join(f"#### {p} ページの Markdown\n````markdown\n{pages.get(p, '')}\n````" for p in (page - 1, page, page + 1)
                         if p in pages or p == page)
        prompt = (f"既存の設計書（PDF）の {page} ページの画像は page.png にある。Read で開いて見る。"
                  "このページを Markdown に変換した結果を、前後1ページと一緒に下に示す。図の画像（fig/…）は legacy/ の下にある。\n"
                  "ページの画像と Markdown を見比べて、このページの内容に、欠けか誤りがあるかを判定する。見るものは、見出し、本文の行、"
                  "表の行数と列数とセル、図の表し方と内容である。画像で載せた図は、図の全体が入っていることと、説明文があることを見る。"
                  "ページをまたぐ段落と表の行は、始まったページに書く決まりなので、前後のページの Markdown にあれば欠けにしない。"
                  "次の決まりのとおりに書かれた内容は、正しいとする。ヘッダー、フッター、ページ番号、行番号は見ない。"
                  "【判読できない】の箇所は、欠けに数える。\n"
                  f"{convert_rules()}\n\n答えは items に1件だけ書く（id は 1）。ok は、欠けも誤りもないとき true。\n\n{md}")
        answers = run.judge(f"c9-p{page:04d}", prompt, props, [1], files={"page.png": png, "legacy": folder},
                            src=False)
        if answers is not None:
            judged += 1
            good += bool(answers[1]["ok"])
    n = len(run.truth["check_pages"])
    return result(None if judged < n else good * 10 >= 9 * n, ok_pages=f"{good}/{n}")


SITE_JS = r"""
const {chromium} = require('playwright');
(async () => {
  const cfg = JSON.parse(process.argv[1]);
  const base = new URL(cfg.base);
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const blocked = [];
  await context.route('**/*', r => {
    const u = new URL(r.request().url());
    if (u.host === base.host || u.protocol === 'data:' || u.protocol === 'blob:') return r.continue();
    blocked.push(u.href); return r.abort();
  });
  const page = await context.newPage();
  const pages = [];
  for (const p of cfg.pages) {
    const row = {url: p.url, status: 0, heading: '', rendered: 0, failed: 0};
    try {
      const res = await page.goto(base.href + p.url, {waitUntil: 'load'});
      row.status = res ? res.status() : 0;
      row.heading = ((await page.locator('.md-content h1').first().textContent({timeout: 3000}).catch(() => '')) || '').trim();
      if (p.mermaid) {
        let last = '', same = 0;
        for (let i = 0; i < 40 && same < 6; i++) {
          await page.waitForTimeout(500);
          const now = [await page.locator('div.mermaid').count(), await page.locator('pre.mermaid').count()].join();
          same = now === last ? same + 1 : 0; last = now;
        }
        row.rendered = await page.locator('div.mermaid').count();
        row.failed = await page.locator('pre.mermaid').count();
      }
    } catch (e) { row.error = String(e); }
    pages.push(row);
  }
  const search = [];
  for (const w of cfg.words) {
    let n = 0;
    try {
      await page.goto(base.href, {waitUntil: 'load'});
      await page.evaluate(() => { const t = document.querySelector('#__search'); if (t) t.checked = true; });
      const input = page.locator('input.md-search__input');
      await input.fill(w);
      await input.press('End');
      for (let i = 0; i < 40 && n === 0; i++) {
        await page.waitForTimeout(500);
        n = await page.locator('.md-search-result__item').count();
      }
    } catch (e) {}
    search.push({word: w, results: n});
  }
  console.log(JSON.stringify({pages, blocked, search}));
  await browser.close();
})();
"""


def page_url(rel):
    from urllib.parse import quote
    rel = rel[:-3]
    if rel == "index" or rel.endswith("/index"):
        rel = rel[:-5]
    else:
        rel += "/"
    return quote(rel)


def site_check(run):
    """サイトを Playwright で開き、ページ、図、外へのリクエスト、検索を調べる（C-10、C-14）。"""
    site = run.p["out"] / "site"
    yml = run.p["out"] / "mkdocs.yml"
    if not (site / "index.html").exists() or not yml.exists():
        return None
    nav = re.findall(r':\s*"?([^"\s]+\.md)"?\s*$', read_text(yml), re.M)
    mermaid = {p.relative_to(run.docs).as_posix() for p in run.docs.rglob("*.md") if "```mermaid" in read_text(p)}
    words = set()
    for p in run.docs.rglob("*.md"):
        for _, t in body_lines(split_lines(read_text(p))):
            if not t.startswith("```"):
                words.update(SEARCH_WORD.findall(outside_spans(t)))
    words = pick(sorted(words), 3, "C-10")
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cfg = {"base": f"http://127.0.0.1:{server.server_address[1]}/", "words": words,
           "pages": [{"url": page_url(rel), "mermaid": rel in mermaid, "nav": rel in nav}
                     for rel in sorted(set(nav) | mermaid)]}
    env = clean_env()
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    env["NODE_PATH"] = root + (":" + env["NODE_PATH"] if env.get("NODE_PATH") else "")
    try:
        run_js = subprocess.run(["node", "-e", SITE_JS, json.dumps(cfg)], capture_output=True, text=True,
                                encoding="utf-8", env=env, timeout=3600)
    finally:
        server.shutdown()
    try:
        out = json.loads(run_js.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        sys.exit("Playwright の結果を読めない:\n" + run_js.stderr[-2000:])
    navs = {p["url"] for p in cfg["pages"] if p["nav"]}
    out["nav_ok"] = sum(r["status"] == 200 and bool(r["heading"]) for r in out["pages"] if r["url"] in navs)
    out["nav"] = len(navs)
    out["blocks"] = sum(r["rendered"] + r["failed"] for r in out["pages"])
    out["failed_blocks"] = sum(r["failed"] for r in out["pages"])
    save_json(run.p["run"] / "site-check.json", out)
    return out


def c10(run):
    site = site_check(run)
    if site is None:
        return result(False, site="なし")
    limit = 0 if run.info["case"] == "small" else site["blocks"] * 0.05
    found = sum(s["results"] > 0 for s in site["search"])
    return result(site["nav_ok"] == site["nav"] and site["failed_blocks"] <= limit and not site["blocked"]
                  and found == len(site["search"]), pages=f"{site['nav_ok']}/{site['nav']}",
                  mermaid_failed=f"{site['failed_blocks']}/{site['blocks']}", blocked=len(site["blocked"]),
                  words=len(site["search"]), search={s["word"]: s["results"] for s in site["search"]})


def ja_ratio(run, rels):
    ja = ascii_letters = 0
    for rel in rels:
        for _, t in body_lines(split_lines(read_text(run.docs / rel))):
            if t.startswith("```"):
                continue
            t = REQ_ID.sub(" ", re.sub(r"\]\([^)]*\)", "]", outside_spans(t)))
            ja += len(JA.findall(t))
            ascii_letters += len(re.findall(r"[A-Za-z]", t))
    return ja, ja + ascii_letters


def c11(run):
    ja, total = ja_ratio(run, run.new_docs())
    counts = {"all": f"{ja}/{total}"}
    passed = total > 0 and ja * 2 >= total
    if run.info["case"] == "large":
        rels = [r for r in run.new_docs() for base in ("design/modules/", "requirements/3-1-functions/")
                if r == base + ZYBO + ".md" or r.startswith(base + ZYBO + "/")]
        zja, ztotal = ja_ratio(run, rels)
        counts["zybo"] = f"{zja}/{ztotal}"
        passed = passed and ztotal > 0 and zja * 10 >= 4 * ztotal
    return result(passed, **counts)


def c12(run):
    before = load_json(run.p["logs"] / "state-at-stop.json")
    stopped = any(a.get("reason") == "c12_stop" for a in run.info["attempts"])
    if before is None:
        return result(False, stopped=stopped)
    after = {j["id"]: j for j in run.state.get("jobs", [])}
    finished = [j for j in before["jobs"] if j["status"] in ("done", "failed")]
    same = sum(after.get(j["id"], {}).get("tries") == j["tries"] and after[j["id"]]["status"] == j["status"]
               for j in finished)
    done = run.state.get("stage") == "done"
    return result(stopped and done and same == len(finished), stopped=stopped, done=done,
                  unchanged=f"{same}/{len(finished)}")


def c13(run, s):
    done = run.state.get("stage") == "done"
    check = run.check()
    return result(s["compactions"] >= 1 and done and check.get("passed") is True,
                  compactions=s["compactions"], done=done, check=check.get("passed"))


def c14(run, s):
    done = run.state.get("stage") == "done"
    check = run.check()
    failed = sum(f for _, f in run.failed_jobs().values())
    site = site_check(run)
    shown = bool(s["serve"]) and site is not None and site["nav_ok"] == site["nav"] > 0
    return result(s["questions"] == 0 and done and check.get("passed") is True and failed == 0 and shown,
                  questions=s["questions"], done=done, check=check.get("passed"), failed=failed, site=shown)


def c15(run, s):
    before = load_json(run.p["run"] / "before.json")
    changed = {}
    for key in ("input", "plugin"):
        now = tree_hashes(run.p[key])
        old = before[key]
        changed[key] = sorted(k for k in set(now) | set(old) if now.get(k) != old.get(k))
    new = sorted(set(p.name for p in run.p["work"].iterdir()) - set(before["work"]) - {"out"})
    leaked = []
    if run.info["case"] == "small":
        names = extern_names(run)
        for f in run.p["plugin"].rglob("*"):
            if f.is_file():
                leaked += sorted(names & set(WORD.findall(read_text(f))))
    # 記録のない担当がいるときは、ツールを数えきれないので「判定なし」にする
    passed = not changed["input"] and not changed["plugin"] and not new and s["main_file_tools"] == 0 \
        and not leaked and not s["agent_tool_misuse"]
    return result(None if passed and s["agents_without_log"] else passed,
                  input_changed=len(changed["input"]), plugin_changed=len(changed["plugin"]), new_files=new,
                  main_file_tools=s["main_file_tools"], names_in_plugin=sorted(set(leaked))[:10],
                  agent_tools=sorted(set(s["agent_tool_misuse"])), agents_without_log=s["agents_without_log"])


def metrics(run, s):
    """報告に載せる数（合否には使わない。要件の 5.4 の表の下の補足）。"""
    jobs = run.state.get("jobs", [])
    by_stage = {}
    for j in jobs:
        by_stage[j["stage"]] = by_stage.get(j["stage"], 0) + 1
    # 検証の回ごとの仕事の数。状態のファイルに回の番号はないので、ファイルと行の順が前に戻る所を、回の初めとみる。
    rounds, docs = {}, {"docs/" + r: i for i, r in enumerate(run.new_docs())}
    for stage in ("verify_module", "verify_overall"):
        r, last = 0, None
        for x in (x for x in jobs if x["stage"] == stage):
            f, line = x["target"].rsplit(":", 1)
            key = (docs.get(f, docs.get("docs/" + f, len(docs))), int(line))
            r += last is None or key <= last
            rounds.setdefault(stage, {})[r] = rounds.get(stage, {}).get(r, 0) + 1
            last = key
    lines = sum(f["lines"] for f in run.plan.get("files", []))
    match = [len(split_lines(read_text(p))) for p in (run.p["out"] / ".work" / "match").glob("J*.md")
             if not p.name.endswith(".lines.md")]
    log = run.state.get("log", [])
    return {"next": s["next"], "jobs_by_stage": by_stage, "verify_rounds": rounds, "max_context": s["max_context"],
            "compactions": s["compactions"], "elapsed_sec": run.info.get("elapsed_sec"),
            "next_max_sec": s["next_max_sec"], "largest_match_record": max(match, default=0),
            "next_per_million_lines": round(s["next"] * 1_000_000 / lines) if lines else None,
            "none_sentence_sections": sum(t.strip() == run.plan.get("none_sentence") for rel in run.new_docs()
                                          if rel.startswith("requirements/") for _, t in run.doc_lines(rel)),
            "figure_switched": sum(e["type"] == "figure_switched" for e in log),
            "verify_removed": sum(e["type"] in ("verify_unknown", "verify_unjudged") for e in log)}


def report(run, conditions, extra, models):
    info = run.info
    lines = [f"### 回：{info['kind']}（材料：{info['case']}）", "",
             f"- `plugin/` のコミット：{info.get('plugin_commit')}" + ("（変更あり）" if info.get("plugin_dirty") else ""),
             f"- モデル：{info.get('model')}（記録にあったモデル：{'、'.join(models) or 'なし'}。"
             f"独立したエージェント：{JUDGE_MODEL}）",
             f"- Claude Code：{info.get('claude_version')}",
             f"- 実行：{len(info['attempts'])} 回（" + "、".join(f"{a['n']}：{a.get('reason')}" for a in info["attempts"])
             + f"）。かかった時間 {info.get('elapsed_sec')} 秒"]
    # 材料に入れた既知の変更に頼る条件（C-3、C-5）は、ほかの条件と分ける（要件の 5.7）
    for title, ids in (("", [c for c in conditions if c not in ("C-3", "C-5")]),
                       ("既知の変更に頼る条件", [c for c in conditions if c in ("C-3", "C-5")])):
        if not ids:
            continue
        lines += [""] + ([f"#### {title}", ""] if title else []) + ["| 条件 | 件数 | 合否 |", "| --- | --- | --- |"]
        for cid in ids:
            r = conditions[cid]
            counts = "、".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in r["counts"].items())
            mark = {True: "合格", False: "不合格", None: "判定なし"}[r["pass"]]
            lines.append(f"| {cid} | {counts.replace('|', '/')} | {mark} |")
    if run.truth and info["kind"] in ("small", "large"):
        ch = run.truth["changes"]
        lines += ["", f"正解：変えた場所 {len(ch)} か所（" + "、".join(f"`{c['before_value']}`→`{c['after_value']}`"
                                                        for c in ch).replace("|", "\\|") + "）、誤りの文 "
                  f"{len(run.truth['false_statements'])} 件、既存の設計書にしかない記述 {len(run.truth['legacy_only'])} 件"]
    if extra:
        lines += ["", "記録した数：" + "、".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in extra.items())]
    return "\n".join(lines) + "\n"


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--no-judge", action="store_true")
    args = parser.parse_args(argv)
    run = Run(Path(args.run_dir).resolve(), not args.no_judge)
    s = run.scan()
    conditions = {}
    for cid in CONDITIONS[run.kind]:
        if cid in conditions:
            continue
        if cid in ("C-2", "C-3"):
            conditions.update(c2_c3(run))
            continue
        func = {"C-1": c1, "C-4": c4, "C-5": c5, "C-6": c6, "C-7": c7, "C-8": c8, "C-9": c9, "C-10": c10,
                "C-11": c11, "C-12": c12, "C-13": c13, "C-14": c14, "C-15": c15}[cid]
        conditions[cid] = func(run, s) if cid in ("C-1", "C-13", "C-14", "C-15") else func(run)
    conditions = {c: conditions[c] for c in sorted(conditions, key=lambda c: int(c[2:]))}
    extra = metrics(run, s) if run.kind in ("small", "large") else {}
    save_json(run.p["run"] / "result.json", {"kind": run.kind, "info": run.info, "conditions": conditions,
                                             "metrics": extra})
    text = report(run, conditions, extra, s["models"])
    with open(run.p["run"] / "report.md", "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
