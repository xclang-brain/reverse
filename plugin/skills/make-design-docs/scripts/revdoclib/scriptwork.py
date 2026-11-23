"""スクリプトだけの処理（スクリプトの仕様の8章）。"""
import hashlib
import os
import posixpath
import re
import unicodedata

from . import files, init, jobchecks, markdown, values
from . import pdf as pdfmod

PAGE_MARK = re.compile(r"<!-- page: ([0-9]+) -->")
_NUMBERED = (re.compile(r"[0-9]+(\.[0-9]+)+\.?(\s|$)"), re.compile(r"[0-9]+\.(\s|$)"))
_FIG_PATH = re.compile(r"\]\((fig/[^)\s]*)\)")


# ---------------------------------------------------------------------------
# 8.1 既存の設計書の組み立て
# ---------------------------------------------------------------------------

def _strip_blank(lines):
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def _relevel(line):
    """番号の見出しの # の数を、数字のかたまりの個数にする。"""
    level = markdown.heading_level(line)
    text = line[level:].lstrip()
    for pattern in _NUMBERED:
        m = pattern.match(unicodedata.normalize("NFKC", text))
        if m:
            n = min(len(re.findall(r"[0-9]+", m.group(0))), values.MAX_HEADING_LEVEL)
            return "#" * n + " " + text
    return line


def _page_lines(ctx, pdf, n, crops):
    """1ページ分の行（目印、空行、ページの Markdown、空行）。図の行は、切り出した画像への参照にする。"""
    path = ctx.abs(".work/pdf/%s/%04d.md" % (pdf["id"], n))
    body = _strip_blank(jobchecks.read_lines(path) if os.path.isfile(path) else [])
    k = 0
    for i, title, box, _ in jobchecks.figures(body, markdown.parse(body)):
        if box:
            k += 1
            name = "p%04d-%d.png" % (n, k)
            body[i] = "![%s](fig/%s)" % (title, name)
            crops.append((n, jobchecks.padded(box), ctx.abs("docs/legacy/%s/fig/%s" % (pdf["folder"], name))))
    return ["<!-- page: %d -->" % n, ""] + body + [""]


def _cut_candidates(lines, elems):
    """切れ目の候補を {添え字: レベル} で返す。"""
    found = {}
    for i, e in enumerate(elems):
        if e.kind == "heading" and e.start not in found:
            found[e.start] = e.level
        elif e.kind == "comment" and PAGE_MARK.fullmatch(lines[e.start].strip()):
            nxt = next((x for x in elems[i + 1:] if x.kind != "blank"), None)
            if nxt is not None and nxt.kind == "heading":
                found[e.start] = nxt.level
                found[nxt.start] = None  # 目印を候補にしたので、見出しは候補にしない
            else:
                found[e.start] = values.MARKER_LEVEL
    return {k: v for k, v in found.items() if v is not None}


def split_legacy(lines, pages_of):
    """1ファイルが 1,000 行以下になるように分ける。pages_of は行ごとのページ。"""
    candidates = _cut_candidates(lines, markdown.parse(lines))
    parts, pos = [], 0
    while True:
        if len(lines) - pos <= values.LEGACY_PART_LINES:
            cut = len(lines)
        else:
            window = [k for k in candidates if pos < k <= pos + values.LEGACY_PART_LINES]
            cut = min(window, key=lambda k: (candidates[k], -k)) if window else pos + values.LEGACY_PART_LINES
        part = lines[pos:cut]
        if not PAGE_MARK.fullmatch(part[0].strip()):
            part = ["<!-- page: %d -->" % pages_of[pos], ""] + part
        parts.append(_strip_blank(part))
        if cut == len(lines):
            return parts
        pos = cut


def assemble(ctx):
    """PDF ごとに、ページの Markdown をつないで docs/legacy/ に書き、図を切り出す（SR-39、SR-40）。"""
    for pdf in ctx.plan["pdfs"]:
        lines, pages_of, crops = [], [], []
        for n in range(1, pdf["pages"] + 1):
            block = _page_lines(ctx, pdf, n, crops)
            lines += block
            pages_of += [n] * len(block)
        elems = markdown.parse(lines)
        for e in elems:
            if e.kind == "heading":
                lines[e.start] = _relevel(lines[e.start])
        while lines and not lines[-1].strip():
            lines.pop()
        for k, part in enumerate(split_legacy(lines, pages_of), 1):
            files.write_text(ctx.abs("docs/legacy/%s/%03d.md" % (pdf["folder"], k)), "".join(x + "\n" for x in part))
        if crops:
            pdfmod.crop_figures(ctx.pdf_path(pdf), crops)


# ---------------------------------------------------------------------------
# 8.2 照合の仕事を作る、8.5 の検証の仕事を作る
# ---------------------------------------------------------------------------

def _add_job(ctx, kind, rel, chunk):
    """仕事を状態の最後に足す。target は <docs/ からのパス>:<最初の番号の行の行番号>。"""
    st = ctx.state
    job = init.job_entry({"id": "J%05d" % st["next_job"], "kind": kind,
                          "target": "%s:%d" % (rel[len("docs/"):], chunk[0].start + 1)}, st["stage"])
    st["next_job"] += 1
    st["jobs"].append(job)
    return job["id"]


def make_match_jobs(ctx):
    for pdf in ctx.plan["pdfs"]:
        folder = "docs/legacy/" + pdf["folder"]
        for name in sorted(n for n in os.listdir(ctx.abs(folder)) if n.endswith(".md")):
            rel = "%s/%s" % (folder, name)
            lines = jobchecks.read_lines(ctx.abs(rel))
            elems = markdown.parse(lines)
            pages, page = {}, None
            for e in elems:
                m = PAGE_MARK.fullmatch(lines[e.start].strip()) if e.kind == "comment" else None
                page = int(m.group(1)) if m else page
                pages[e.start] = page
            body = {e for e in elems if e.kind in markdown.BODY}
            for chunk in markdown.split_numbered(elems, body, values.NUMBERED_LINES):
                job_id = _add_job(ctx, "match", rel, chunk)
                markdown.write_numbered(ctx.out, ".work/match", job_id, rel, lines, elems, chunk,
                                        lambda e: {"page": pages[e.start]})


# ---------------------------------------------------------------------------
# 8.3 照合の記録の振り分け
# ---------------------------------------------------------------------------

def _part_of(plan, path):
    """ソースファイルを持つユニットがある、最初の部分の (モジュールの名前, 部分の名前)。"""
    owner = {u["id"] for u in plan["units"] if any(r["path"] == path for r in u["files"])}
    return next((m["name"], p["name"]) for m in plan["modules"] for p in m["parts"] if owner & set(p["units"]))


def _design_path(part):
    return "docs/design/modules/%s.md" % part


def _relink(line, legacy_file, target):
    """内容の画像のパス（fig/…）を、差し込む先の設計書からの相対パスにする。"""
    def repl(m):
        path = posixpath.join(posixpath.dirname(legacy_file), m.group(1))
        return "](%s)" % posixpath.relpath(path, posixpath.dirname(target))
    return _FIG_PATH.sub(repl, line) if markdown.IMAGE_LINE.fullmatch(line.strip()) else line


def _section(title, blocks):
    """`## title` の節。項目がないときは `なし`。"""
    body = [x for b in blocks for x in [""] + b][1:] or ["なし"]
    return ["## " + title, ""] + body + [""]


def _legacy_file(title, recs):
    lines = ["# 照合の記録（%s。既存設計書のみ）" % title, ""]
    for r in recs:
        lines += ["### " + r["id"]] + r["content"].split("\n") + [""]
    return lines if recs else lines + ["なし"]


def distribute(ctx):
    plan, st = ctx.plan, ctx.state
    found = {"discrepancies": [], "legacy_only": [], "unmatched": []}
    parts = {}  # 部分の名前 → (食い違いの項目, 一致した図の項目)
    for job in (j for j in st["jobs"] if j["kind"] == "match"):
        info = files.read_json(ctx.abs(".work/match/%s.json" % job["id"]))
        pdf = next(p["id"] for p in plan["pdfs"] if info["file"].startswith("docs/legacy/%s/" % p["folder"]))
        rows = {e["n"]: e for e in info["lines"]}
        records = jobchecks.read_records(ctx, job["outputs"][0], info)[1] if os.path.isfile(
            ctx.abs(job["outputs"][0])) else []
        used = set()
        for rec in records:
            numbers = set(range(rec["start"], rec["end"] + 1)) if rec["start"] is not None else set()
            if not numbers or rec["problems"] or rec["start"] < 1 or rec["end"] > info["count"] or numbers & used:
                continue
            used |= numbers
            base = {"job": job["id"], "pdf": pdf, "page": rows[rec["start"]]["page"]}
            v = rec["values"]
            if rec["cat"] in ("一致", "食い違い"):
                path = rec["location"][0]
                module, part = _part_of(plan, path)
                entry = parts.setdefault(part, ([], []))
            if rec["cat"] == "食い違い":
                found["discrepancies"].append(dict(base, file=path, name=v["名前"], module=module,
                                                   legacy=v["既存の設計書"], source=v["ソースコード"]))
                entry[0].append(["### %s %s" % (path, v["名前"]), "- 既存の設計書: " + v["既存の設計書"],
                                 "- ソースコード: " + v["ソースコード"]])
            elif rec["cat"] == "一致":
                for n in sorted(numbers):
                    block = rows[n]["text"].split("\n")
                    if block[0].strip().startswith("```mermaid") and not markdown.mermaid_problems(
                            block, markdown.parse(block)):
                        entry[1].append(["### " + path] + block)
            elif rec["cat"] == "既存設計書のみ":
                module = v["モジュール"]
                target = ("docs/design/architecture.md" if module == jobchecks.OVERALL else
                          _design_path(next(m["parts"][0]["name"] for m in plan["modules"] if m["name"] == module)))
                content = _strip_blank([_relink(x, info["file"], target) for x in rec["content"]])
                found["legacy_only"].append(dict(base, id="E%04d" % (len(found["legacy_only"]) + 1), module=module,
                                                 target=target, content="\n".join(content)))
        rest = [n for n in sorted(rows) if n not in used]
        for k, n in enumerate(rest):
            if k == 0 or rest[k - 1] != n - 1:
                found["unmatched"].append({"job": job["id"], "pdf": pdf, "page": rows[n]["page"],
                                           "file": info["file"], "lines": 0})
            found["unmatched"][-1]["lines"] += 1
    for job in (j for j in st["jobs"] if j["kind"] == "write_module"):
        name = job["target"]
        disc, figs = parts.get(name, ([], []))
        lines = ["# 照合の記録（%s）" % name, ""] + _section("食い違い", disc) + _section("一致した図", figs)
        files.write_text(ctx.abs(".work/records/%s.md" % job["id"]), "".join(x + "\n" for x in lines[:-1]))
        recs = [r for r in found["legacy_only"] if r["target"] == _design_path(name)]
        files.write_text(ctx.abs(".work/records/%s.legacy.md" % job["id"]), _joined(_legacy_file(name, recs)))
    recs = [r for r in found["legacy_only"] if r["module"] == jobchecks.OVERALL]
    files.write_text(ctx.abs(".work/records/overall.md"), _joined(_legacy_file(jobchecks.OVERALL, recs)))
    files.write_text(ctx.abs(".work/records/records.json"), files.dumps(found))


def _joined(lines):
    return "".join(x + "\n" for x in _strip_blank(lines))


# ---------------------------------------------------------------------------
# 8.4「既存設計書のみ」の記録の差し込み
# ---------------------------------------------------------------------------

def _mark_line(line):
    """文の先頭（5.1）に印を足す。"""
    m = markdown.BULLET.match(line)
    head = m.group(0) if m else line[:len(line) - len(line.lstrip())]
    rest = line[len(head):]
    return line if rest.startswith(values.MARKS) else head + values.MARKS[0] + rest


def _marked(content):
    lines = content.split("\n")
    out = []
    for e in markdown.parse(lines):
        image = e.kind == "text" and markdown.IMAGE_LINE.fullmatch(lines[e.start].strip())
        kind = "table" if e.kind == "table_head" else "figure" if e.kind == "code" or image else None
        if kind:
            out += [values.MARK_BEFORE[kind], ""]
        if kind or e.kind in ("blank", "table_sep", "table_row"):
            out += lines[e.start:e.end + 1]
        else:
            out.append(_mark_line(lines[e.start]))
    return out


def legacy_cut(lines):
    """スクリプトが入れた見出しの行の添え字（なければ行の数）。"""
    elems = markdown.parse(lines)
    return next((e.start for e in elems if e.kind == "heading" and lines[e.start].strip() == values.LEGACY_HEADING),
                len(lines))


def _records(ctx):
    path = ctx.abs(".work/records/records.json")
    return files.read_json(path)["legacy_only"] if os.path.isfile(path) else []


def insert_legacy(ctx, job):
    if job["kind"] == "write_module":
        rel = _design_path(job["target"])
    elif job["target"] == "design/architecture.md":
        rel = "docs/" + job["target"]
    else:
        return
    lines = jobchecks.read_lines(ctx.abs(rel))
    title = lines[0][markdown.heading_level(lines[0]):].strip() if lines else ""
    recs = [r for r in _records(ctx) if r["target"] == rel]
    pages = [_strip_blank(lines[:legacy_cut(lines)]) + (["", values.LEGACY_HEADING, ""] if recs else [])]
    counts = [0]
    for r in recs:
        block = ([""] if counts[-1] else []) + _marked(r["content"])
        if len(pages[-1]) + len(block) > values.MAX_DOC_LINES and (len(pages) == 1 or counts[-1]):
            pages.append(["# %s（続き %d）" % (title, len(pages) + 1), "", values.LEGACY_HEADING, ""])
            counts.append(0)
            block = _marked(r["content"])
        pages[-1] += block
        counts[-1] += 1
    # 途中で止まっても、やり直せば同じ結果になるように、どのページも一時ファイルから置き換える。
    for k, page in enumerate(pages, 1):
        path = rel if k == 1 else "%s~p%d.md" % (rel[:-3], k)
        files.write_atomic(ctx.abs(path), "".join(x + "\n" for x in page))


# ---------------------------------------------------------------------------
# 8.5 検証の繰り返し
# ---------------------------------------------------------------------------

def line_hashes(lines, elems):
    """スクリプトが入れた見出しより前の本文の行ごとに、(要素, すぐ前の見出し, 行の SHA-1) を返す。"""
    stack, found = [], []
    for e in markdown.checked_body(lines, elems):
        if e.kind == "heading":
            stack = [h for h in stack if h[0] < e.level] + [(e.level, lines[e.start])]
        elif e.kind in markdown.BODY:
            heads = [h for _, h in stack]
            text = "\n".join(heads + [markdown.elem_text(lines, e)])
            found.append((e, heads[-1] if heads else "", hashlib.sha1(text.encode("utf-8")).hexdigest()))
    return found


def verify_files(ctx):
    """検証の段階の対象のファイル。代わりのファイルは除く。"""
    kind = "write_module" if ctx.state["stage"] == "verify_module" else "write_overall"
    found = []
    for job in (j for j in ctx.state["jobs"] if j["kind"] == kind):
        t = job["target"]
        docs = [_design_path(t), "docs/requirements/3-1-functions/%s.md" % t] if kind == "write_module" else ["docs/" + t]
        found += [rel for rel in docs if rel not in job["substitute"]]
    return found


def _matched_figures(ctx):
    """照合の記録の「一致した図」（8.3 の 6）の文。"""
    found = set()
    for job in (j for j in ctx.state["jobs"] if j["kind"] == "write_module"):
        path = ctx.abs(".work/records/%s.md" % job["id"])
        if os.path.isfile(path):
            lines = jobchecks.read_lines(path)
            found |= {markdown.elem_text(lines, e) for e in markdown.parse(lines) if e.kind == "code"}
    return found


def _targets(ctx, rel):
    """対象にする行。(ファイルの行, 要素, [(要素, 見出し, SHA-1)]) を返す。"""
    lines = jobchecks.read_lines(ctx.abs(rel))
    elems = markdown.parse(lines)
    skip = set(ctx.state["confirmed"].get(rel, []))
    figures = _matched_figures(ctx)
    found = []
    for e, heading, sha in line_hashes(lines, elems):
        text = markdown.elem_text(lines, e)
        if sha not in skip and text.strip() != ctx.plan["none_sentence"] and not (e.kind == "code" and text in figures):
            found.append((e, heading, sha))
        skip.add(sha)  # 同じ節の同じ文は、1つの番号で確かめる
    return lines, elems, found


def enter_verify(ctx):
    ctx.state["round"] = 1
    _make_verify_jobs(ctx)


def _make_verify_jobs(ctx):
    for rel in verify_files(ctx):
        lines, elems, rows = _targets(ctx, rel)
        sha = {e: h for e, _, h in rows}
        for chunk in markdown.split_numbered(elems, set(sha), values.NUMBERED_LINES):
            job_id = _add_job(ctx, "verify", rel, chunk)
            markdown.write_numbered(ctx.out, ".work/verify", job_id, rel, lines, elems, chunk,
                                    lambda e: {"sha1": sha[e]})


def next_round(ctx):
    """検証の回の仕事が全部済んだときに呼ぶ。次の回の仕事を作ったら True、段階を終えるなら False を返す。"""
    st = ctx.state
    left = {rel: _targets(ctx, rel)[2] for rel in verify_files(ctx)}
    if not any(left.values()):
        return False
    if st["round"] < values.MAX_ROUNDS:
        st["round"] += 1
        _make_verify_jobs(ctx)
        return True
    edits = {rel: [("delete", sha, None, "") for _, _, sha in rows] for rel, rows in left.items() if rows}
    _rewrite(ctx, edits, "verify_unjudged")
    return False


def _delete(lines, sha, none):
    """SHA-1 が同じ行を、上から順に1つずつ消す。(行, 消した (見出し, 文) のリスト) を返す。"""
    removed = []
    while True:
        elems = markdown.parse(lines)
        hit = next(((e, h) for e, h, s in line_hashes(lines, elems) if s == sha), None)
        if hit is None:
            return lines, removed
        e, heading = hit
        removed.append((heading, markdown.elem_text(lines, e)))
        start, end = e.start, e.end
        if e.kind == "table_row":
            i = elems.index(e)
            head = next(k for k in range(i, -1, -1) if elems[k].kind == "table_head")
            stop = next((k for k in range(i + 1, len(elems)) if elems[k].kind not in ("table_sep", "table_row")),
                        len(elems))
            if all(x is e or x.kind != "table_row" for x in elems[head:stop]):
                start, end = elems[head].start, elems[stop - 1].end  # 表にデータの行がなくなる
        lines = lines[:start] + lines[end + 1:]
        elems = markdown.parse(lines)
        heads = [i for i, x in enumerate(elems) if x.kind == "heading" and x.start < start]
        if heads and not jobchecks.section_body(elems, heads[-1]):
            lines.insert(start, none)


def _rewrite(ctx, edits, log_type):
    """設計書を直す。edits は {ファイル: [(操作, SHA-1, 直した文, 探した語)]}。

    途中で止まっても、やり直すと同じ結果になるように、消す行の記録を先に保存してから設計書を書き換える。
    """
    st = ctx.state
    docs = {}
    for rel, ops in edits.items():
        lines = jobchecks.read_lines(ctx.abs(rel))
        for op, sha, fixed, words in ops:
            if op == "replace":
                for e, _, s in line_hashes(lines, markdown.parse(lines)):
                    if s == sha:
                        lines[e.start] = fixed
                continue
            lines, removed = _delete(lines, sha, ctx.plan["none_sentence"])
            for heading, text in removed:
                entry = {"type": log_type, "file": rel, "heading": heading, "text": text}
                if log_type == "verify_unknown":
                    entry["words"] = words
                if not any(all(x.get(k) == entry[k] for k in ("type", "file", "heading", "text")) for x in st["log"]):
                    st["log"].append(entry)
        docs[rel] = lines
    ctx.save()
    for rel, lines in docs.items():
        files.write_atomic(ctx.abs(rel), "".join(x + "\n" for x in lines))


def apply_verdicts(ctx, jobs):
    """判定の記録を調べ、判定のとおりに設計書を直し、仕事を done にする（8.5 の判定の扱い）。"""
    st = ctx.state
    results = [(job,) + jobchecks.check_verify(ctx, job) for job in jobs]
    edits, confirm = {}, {}
    for job, info, verdicts, _ in results:
        for sha, kind, fixed, words in verdicts:
            if kind in ("OK", "対象外"):
                confirm.setdefault(info["file"], []).append(sha)
            else:
                op = "replace" if fixed is not None else "delete"
                edits.setdefault(info["file"], []).append((op, sha, fixed, words))
    _rewrite(ctx, edits, "verify_unknown")
    for rel, shas in confirm.items():
        known = st["confirmed"].setdefault(rel, [])
        known += [s for s in dict.fromkeys(shas) if s not in known]
    for job, _, _, reasons in results:
        job["status"], job["reasons"] = "done", reasons
    ctx.save()


# ---------------------------------------------------------------------------
# 8.6 要約
# ---------------------------------------------------------------------------

def _first_lines(lines, heading):
    """見出しの節の本文の行（要素の1行目）。"""
    elems = markdown.parse(lines)
    i = next((i for i, e in enumerate(elems) if e.kind == "heading" and lines[e.start].strip() == heading), None)
    return [] if i is None else [lines[e.start] for e in jobchecks.section_body(elems, i)]


def write_digest(ctx):
    jobs = [j for j in ctx.state["jobs"] if j["kind"] == "write_module"]
    k = max(0, min(values.DIGEST_DEPS, values.DIGEST_LINES // max(len(jobs), 1) - 1))
    out = []
    for job in jobs:
        rel = _design_path(job["target"])
        lines = jobchecks.read_lines(ctx.abs(rel))
        if rel in job["substitute"]:
            role = "（設計書を作れなかった）"
        else:
            role = next((x[m.end():] if (m := markdown.BULLET.match(x)) else x for x in _first_lines(lines, "## 役割")), "")
        out.append("- %s（%s、%d 行）：%s" % (job["target"], rel[len("docs/"):], len(lines), role))
        out += ["  " + x for x in _first_lines(lines, "## 依存関係")[:k]]
    files.write_text(ctx.abs(".work/digest.md"), "".join(x + "\n" for x in out))
