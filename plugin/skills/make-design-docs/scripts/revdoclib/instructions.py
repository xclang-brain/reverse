"""指示のファイル（スクリプトの仕様の7章）。同じ状態からは、同じ内容になる。"""
import os
import re

from . import files, init, jobchecks, values
from .common import TEMPLATES_DIR
from .jobchecks import TEXT_SUFFIX

LAST_LINE = "最後の返事は done の1語だけにする。"
_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")
LIST_SENTENCES = {
    "analyze": "一覧の全部のファイルを読む。",
    "write_module": "解析メモから書く。ソースコードは、不明点の答えを探すときに、必要な範囲だけ読む。",
    "verify": "判定の根拠にする範囲だけ読む。",
}
EXTRA_NOTE = "ページの画像で確かめ、画像のとおりなら残す。"
USE_IMAGE = "Mermaid の検査に不合格だった図は、画像で載せる。"
SIDE_NAMES = {"top": "上端", "bottom": "下端", "left": "左端", "right": "右端"}
NOT_WRITTEN = "書かない"
PREVIOUS_VERDICTS = "前回の判定のうち、次の番号は使えなかった。"


def _with_lines(ctx, rel):
    """`<絶対パス>（<行数> 行）`。"""
    path = ctx.abs(rel)
    return "%s（%d 行）" % (path, len(files.split_lines(files.read_text(path))))


def _source_table(ctx, units):
    rows = ["| 読むファイル | 行 | 記録に書く名前 |", "| --- | --- | --- |"]
    for u in units:
        rows += ["| %s | %d-%d | %s |" % (ctx.sources.read_path(r["path"]), r["start"], r["end"], r["path"])
                 for r in u["files"]]
    return "\n".join(rows)


def _part(ctx, name):
    """(モジュール, 部分, 部分の番号) を返す。"""
    return next((m, p, k) for m in ctx.plan["modules"] for k, p in enumerate(m["parts"], 1) if p["name"] == name)


def _part_units(ctx, part):
    return [u for u in ctx.plan["units"] if u["id"] in part["units"]]


def _output(ctx, job, rel):
    return ctx.abs(rel) if rel in job["outputs"] else NOT_WRITTEN


def _records_line(ctx, job_id):
    if ctx.plan["mode"] != "both":
        return ""
    return ("- 照合の記録（食い違いと、一致した図。全部読む）：%s\n- 照合の記録（既存設計書のみ。語で探す）：%s"
            % (_with_lines(ctx, ".work/records/%s.md" % job_id), _with_lines(ctx, ".work/records/%s.legacy.md" % job_id)))


def _values(ctx, job):
    """7.3 の値。"""
    plan, kind, target = ctx.plan, job["kind"], job["target"]
    v = {"job_id": job["id"], "src_dir": plan["src"] or "なし", "none_sentence": plan["none_sentence"] or "",
         "src_note": ""}
    if any(f["encoding"] != "utf-8" for f in plan["files"]):
        v["src_note"] = ("UTF-8 でないファイルは、%s に、同じ相対パスで UTF-8 のコピーがある。コピーがあるファイルは、"
                         "コピーを読む。" % ctx.abs(".work/src-utf8"))
    if kind == "analyze":
        unit = next(u for u in plan["units"] if u["id"] == target)
        v.update(unit=target, module=unit["module"], source_table=_source_table(ctx, [unit]),
                 output=ctx.abs(job["outputs"][0]))
    elif kind == "convert":
        v.update(_convert_values(ctx, job))
    elif kind == "write_module":
        module, part, k = _part(ctx, target)
        units = _part_units(ctx, part)
        v.update(name=target, folder=module["folder"] or "（直下）", fr_prefix=part["fr_prefix"],
                 part_note=("このモジュールは %d 個に分けて書く。これは %d 個目である。" % (len(module["parts"]), k)
                            if len(module["parts"]) > 1 else ""),
                 memo_list="\n".join("- " + _with_lines(ctx, ".work/memo/%s.md" % u["id"]) for u in units),
                 records_line=_records_line(ctx, job["id"]), source_table=_source_table(ctx, units),
                 design_output=_output(ctx, job, "docs/design/modules/%s.md" % target),
                 functions_output=_output(ctx, job, "docs/requirements/3-1-functions/%s.md" % target),
                 unknowns_output=_output(ctx, job, init.unknowns_path(job)))
    elif kind == "write_overall":
        name = target.rpartition("/")[2]
        v.update(doc_title=jobchecks.doc_rules(plan, "docs/" + target)[0][2:],
                 template_file=_with_lines(ctx, ".work/templates/" + name),
                 digest_file=_with_lines(ctx, ".work/digest.md"), modules_dir=ctx.abs("docs/design/modules"),
                 functions_dir=ctx.abs("docs/requirements/3-1-functions"),
                 records_line=("- 照合の記録（既存設計書のみ。語で探す）：" + _with_lines(ctx, ".work/records/overall.md")
                               if plan["mode"] == "both" else ""),
                 output=_output(ctx, job, "docs/" + target),
                 unknowns_output=_output(ctx, job, init.unknowns_path(job)),
                 id_prefix=dict(values.OVERALL_FILES)[target] or "なし")
    else:
        folder = ".work/match/" if kind == "match" else ".work/verify/"
        info = files.read_json(ctx.abs(folder + job["id"] + ".json"))
        v.update(lines_file=_with_lines(ctx, folder + job["id"] + ".lines.md"), line_count=str(info["count"]),
                 modules_file=_with_lines(ctx, ".work/modules.md"), output=ctx.abs(job["outputs"][0]))
        doc = info["file"]
        if kind == "match":
            pdf = next(p for p in plan["pdfs"] if doc.startswith("docs/legacy/%s/" % p["folder"]))
            v.update(pdf_name=pdf["name"], memo_dir=ctx.abs(".work/memo"))
        else:
            # 部分の設計書と機能の要求、write_module の仕事の不明点のファイルでは、その部分の表（7.3）。
            writer = next((j["target"] for j in ctx.state["jobs"]
                           if j["kind"] == "write_module" and doc == init.unknowns_path(j)), None)
            part = next((p for m in plan["modules"] for p in m["parts"]
                         if p["name"] == writer or doc in ("docs/design/modules/%s.md" % p["name"],
                                                           "docs/requirements/3-1-functions/%s.md" % p["name"])), None)
            v.update(doc_file=doc, source_table=_source_table(ctx, _part_units(ctx, part)) if part else "なし")
    return v


def _convert_values(ctx, job):
    pdf_id = job["target"].split(":")[0]
    pdf = next(p for p in ctx.plan["pdfs"] if p["id"] == pdf_id)
    folder = ".work/pdf/%s/" % pdf_id
    pages = [files.page_of(rel) for rel in job["outputs"]]
    rows = ["| ページ | 画像 | 埋め込みテキスト | 書く先 |", "| --- | --- | --- | --- |"]
    for n in pages:
        base = folder + "%04d" % n
        text = ctx.abs(base + ".txt") if files.read_json(ctx.abs(base + ".json"))["check"] else "なし"
        rows.append("| %d | %s | %s | %s |" % (n, ctx.abs(base + ".png"), text, ctx.abs(base + ".md")))
    near = sorted({k for n in pages for k in (n - 1, n + 1) if 1 <= k <= pdf["pages"]} - set(pages))
    context = "\n".join(["| ページ | 画像 |", "| --- | --- |"]
                        + ["| %d | %s |" % (n, ctx.abs(folder + "%04d.png" % n)) for n in near]) if near else "なし"
    sides = {}
    for m in pdf["margins"]:
        sides.setdefault(m["side"], []).append(m["text"] if m["key"] else "（数字）")
    margins = ["- %s：%s" % (SIDE_NAMES[s], " ".join(t)) for s, t in sides.items()]
    if pdf["line_numbers"]:
        margins.append("- 行の先頭：行番号（数字）")
    return {"pdf_name": pdf["name"], "page_table": "\n".join(rows), "context_table": context,
            "margin_list": "\n".join(margins) or "- なし"}


def _fill(name, v):
    with open(os.path.join(TEMPLATES_DIR, name), "r", encoding="utf-8") as f:
        text = f.read()

    def repl(m):
        if m.group(1) not in v:
            raise ValueError("ひな形 %s に、知らない値 {{%s}} がある" % (name, m.group(1)))
        return v[m.group(1)]

    # 差し込む値（パスなど）には {{ があってよいので、置き換える前のひな形で調べる。
    if "{{" in _PLACEHOLDER.sub("", text):
        raise ValueError("ひな形 %s に、置き換えられない {{ が残る" % name)
    return _PLACEHOLDER.sub(repl, text).rstrip("\n")


def _entries(job):
    """不合格の理由の項目を、(並べる鍵, 行, 含む reasons の数) で返す（7.2）。"""
    entries, groups = [], {}
    convert = job["kind"] == "convert"
    for r in job["reasons"]:
        key = (r["file"], r["line"] or 0)
        if convert and r["rule"] in TEXT_SUFFIX:
            groups.setdefault((r["file"], r["rule"]), []).append(r["detail"][1:-len("」" + TEXT_SUFFIX[r["rule"]])])
            if len(groups[(r["file"], r["rule"])]) == 1:
                entries.append([key, (r["file"], r["rule"]), 0])
            continue
        if convert and r["rule"] == "missing_file":
            place = "p.%d" % files.page_of(r["file"])
        elif r["line"] is None:
            place = r["file"]
        else:
            place = "%s %d 行目" % (r["file"], r["line"])
        entries.append([key, "- [%s] %s：%s" % (r["rule"], place, r["detail"]), 1])
    for e in entries:
        if isinstance(e[1], tuple):
            rel, rule = e[1]
            shown = groups[e[1]][:values.REASON_STRINGS]
            text = "".join("「%s」" % s[:values.REASON_STRING_CHARS] for s in shown) + TEXT_SUFFIX[rule]
            e[1:] = ["- [%s] p.%d：%s%s" % (rule, files.page_of(rel), text, EXTRA_NOTE if rule == "text_extra" else ""),
                     len(shown)]
    if convert and job["tries"] == values.MAX_TRIES - 1:
        entries += [[(rel, 0), "- [use_image] p.%d：%s" % (files.page_of(rel), USE_IMAGE), 0]
                    for rel in job["outputs"] if job["pages"][str(files.page_of(rel))]["mermaid"]]
    entries.sort(key=lambda e: e[0])
    return entries


def _previous_verdicts(ctx, job):
    """検証の2回目からの仕事で、番号の行と SHA-1 が同じ、前の回の理由の項目（8.5、7.2）。"""
    numbers = {e["sha1"]: e["n"] for e in files.read_json(ctx.abs(".work/verify/%s.json" % job["id"]))["lines"]}
    doc = job["target"].rpartition(":")[0]
    latest = {}  # SHA-1 → その行を持っていた、いちばん新しい前の仕事。1つのファイルの中で、同じ回の仕事は同じ行を持たない。
    for j in ctx.state["jobs"]:
        if (j["kind"] == "verify" and j["stage"] == job["stage"] and int(j["id"][1:]) < int(job["id"][1:])
                and j["target"].rpartition(":")[0] == doc):
            for e in files.read_json(ctx.abs(".work/verify/%s.json" % j["id"]))["lines"]:
                if e["sha1"] in numbers:
                    latest[e["sha1"]] = j
    found = [(numbers[r["sha1"]], "- [%s] [%d]：%s" % (r["rule"], numbers[r["sha1"]], r["detail"]))
             for sha, j in latest.items() for r in j["reasons"] if r.get("sha1") == sha]
    return [(line, 1) for _, line in sorted(found)]


def _section(ctx, job):
    """不合格の理由の節の (2行目, [(項目の行, 含む reasons の数)], reasons の数)。渡し直しでないときは None。"""
    if job["tries"] and job["reasons"]:
        if all(r["rule"] == "missing_file" for r in job["reasons"]):
            second = "前回は、出力のファイルがなかった。"
        else:
            second = ("前回の出力は `%s` にある。不合格の項目だけを直し、ほかは前回のまま書く。"
                      % ctx.abs(".work/rejected/%s-%d" % (job["id"], job["tries"])))
        return second, [(e[1], e[2]) for e in _entries(job)], len(job["reasons"])
    found = _previous_verdicts(ctx, job) if job["kind"] == "verify" else []
    return (PREVIOUS_VERDICTS, found, len(found)) if found else None


def _reasons(section, count):
    """不合格の理由の節。count は書く項目の数。"""
    second, entries, total = section
    lines = [e[0] for e in entries[:count]]
    rest = total - sum(e[1] for e in entries[:count])
    if rest:
        lines.append("- ほか %d 件" % rest)
    return "## 前回の不合格の理由\n\n%s\n\n%s" % (second, "\n".join(lines))


def write(ctx, job):
    """.work/jobs/<仕事の ID>.md を書く。"""
    kind = job["kind"]
    v = _values(ctx, job)
    name = values.JOB_TEMPLATES[kind]
    listing = ".work/jobs/%s.files.md" % job["id"]
    section = _section(ctx, job)
    count = values.MAX_REASONS

    def render():
        parts = [_fill(name, v)] + ([_reasons(section, count)] if section else []) + [LAST_LINE]
        return "\n\n".join(parts) + "\n"

    text = render()
    if len(text.encode("utf-8")) > values.MAX_JOB_BYTES and "source_table" in v and v["source_table"] != "なし":
        files.write_text(ctx.abs(listing), v["source_table"] + "\n")
        v["source_table"] = "読むファイルの一覧は、%sにある。%s" % (_with_lines(ctx, listing), LIST_SENTENCES[kind])
        text = render()
    elif os.path.isfile(ctx.abs(listing)):
        files.fs_op(os.remove, ctx.abs(listing))
    while section and len(text.encode("utf-8")) > values.MAX_JOB_BYTES and count > 0:
        count -= 1
        text = render()
    files.write_text(ctx.abs(".work/jobs/%s.md" % job["id"]), text)
