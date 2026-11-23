"""仕事の種類ごとの出力の検査（スクリプトの仕様の6章）。

検査の関数は、不合格の項目（state.json の reasons の形）のリストを返す。項目は、ファイルの順、行の順に並べる。
"""
import os
import re

from . import files, markdown, values
from . import pdf as pdfmod
from .common import TEMPLATES_DIR

ITEM = re.compile(r"- \[(.+?):([0-9]+)-([0-9]+)\] (.+)$")
_NUM = r"([0-9]+(?:\.[0-9]+)?)"
_FIGURE = re.compile(r"!\[(.*)\]\(figure:%s,\s*%s,\s*%s,\s*%s\)" % (_NUM, _NUM, _NUM, _NUM))
_SEPARATOR_CELL = re.compile(r":?-+:?")
_TAG = re.compile(r"<[A-Za-z/!?]")
_LETTER = re.compile(r"[A-Za-z]")
_CAMEL = re.compile(r"[a-z][A-Z]")
_FIGURE_VALUE = re.compile(r"\(figure:[^)]*\)")
_RECORD = re.compile(r"## ([0-9]+)(?:-([0-9]+))? (一致|食い違い|既存設計書のみ|対象外)")
_VERDICT = re.compile(r"\[([0-9]+)\]")
_REQUIREMENT = re.compile(r"\s*- (?:%s)\S*?: " % "|".join(values.REQUIREMENT_HEADS))

OVERALL = "全体"
RECORD_KEYS = {"一致": ("場所",), "食い違い": ("場所", "名前", "既存の設計書", "ソースコード"),
               "既存設計書のみ": ("モジュール", "内容"), "対象外": ()}
CONTENT_KEY = "内容"
TEXT_SUFFIX = {"text_missing": "が出力にない。", "text_extra": "が埋め込みテキストにない。"}


def item(rule, rel, line, detail):
    return {"rule": rule, "file": rel, "line": line, "detail": detail}


def missing(rel):
    return item("missing_file", rel, None, "出力のファイルがない。決まった場所に書く。")


def sort_items(items):
    return sorted(items, key=lambda x: (x["file"], x["line"] or 0))


def read_lines(path):
    return files.split_lines(files.read_text(path))


def check(ctx, job):
    """仕事の出力を検査する。verify の仕事は check_verify で調べる（8.5 の決まりで扱うため）。"""
    found = {"analyze": check_analyze, "convert": check_convert, "match": check_match,
             "write_module": check_write, "write_overall": check_write}[job["kind"]](ctx, job)
    return sort_items(found)


# ---------------------------------------------------------------------------
# 6.1 解析メモ
# ---------------------------------------------------------------------------

def check_analyze(ctx, job):
    rel = job["outputs"][0]
    path = ctx.abs(rel)
    if not os.path.isfile(path):
        return [missing(rel)]
    lines = read_lines(path)
    src = ctx.sources
    found, sections, locations = [], [], []
    for k, line in enumerate(lines, 1):
        if not line.strip() or (k == 1 and line.startswith("# ")):
            continue
        if line.startswith("## ") and line[3:] in values.MEMO_HEADINGS:
            sections.append({"name": line[3:], "line": k, "items": 0, "none": 0})
            continue
        if line == "- なし" and sections:
            sections[-1]["none"] += 1
            continue
        m = ITEM.match(line)
        if not m or not sections:
            found.append(item("bad_item", rel, k, "解析メモの形でない行がある。項目か `- なし` にする。"))
            continue
        sections[-1]["items"] += 1
        loc = (m.group(1), int(m.group(2)), int(m.group(3)))
        locations.append(loc)
        problem = src.location_problem(*loc, limit=sections[-1]["name"] != values.MEMO_HEADINGS[0])
        if problem:
            found.append(item("bad_location", rel, k, problem))
            continue
        found += [item(rule, rel, k, detail) for rule, detail in src.word_problems([loc], m.group(4), memo=True)]
    if [s["name"] for s in sections] != list(values.MEMO_HEADINGS):
        found.append(item("missing_heading", rel, None, "%dつの見出しが、決まった順にそろっていない。" % len(values.MEMO_HEADINGS)))
    for s in sections:
        if (s["items"] > 0) == (s["none"] > 0):
            found.append(item("bad_item", rel, s["line"], "見出しの下に、項目か `- なし` のどちらか一方を書く。"))
    found += _uncovered(ctx, rel, job["target"], locations)
    if len(lines) > values.MEMO_MAX_LINES:
        found.append(item("too_long", rel, None, "%d 行を超える。項目をまとめて短くする。" % values.MEMO_MAX_LINES))
    return found


def _uncovered(ctx, rel, unit_id, locations):
    """ユニットの行の、200 行ごとの区間のうち、どの項目の根拠の場所とも重ならない区間を探す。"""
    unit = next(u for u in ctx.plan["units"] if u["id"] == unit_id)
    rows = []  # ユニットの通し番号の順に、(相対パス, 行番号)
    for r in unit["files"]:
        rows += [(r["path"], n) for n in range(r["start"], r["end"] + 1)]
    found = []
    for b in range(0, len(rows), values.COVER_BLOCK):
        block = rows[b:b + values.COVER_BLOCK]
        if all(not ctx.sources.lines(p)[n - 1].strip() for p, n in block):
            continue
        if not any(p == lp and s <= n <= e for p, n in block for lp, s, e in locations):
            found.append(item("uncovered_lines", rel, None, "%d〜%d 行の区間に項目がない。"
                              % (b + 1, b + len(block))))
    return found


# ---------------------------------------------------------------------------
# 6.2 変換
# ---------------------------------------------------------------------------

def figures(lines, elems):
    """図の行を調べる。(添え字, 図の題, 範囲か None, 不合格の説明か None) のリストを返す。"""
    found = []
    for k, line in markdown.outside_code(lines, elems):
        if "](figure:" not in line:
            continue
        m = _FIGURE.fullmatch(line.strip())
        box = tuple(float(v) for v in m.groups()[1:]) if m else None
        nxt = next((x for x in lines[k + 1:] if x.strip()), "")
        if not m:
            detail = "図の行が `![<図の題>](figure:<x0>,<y0>,<x1>,<y1>)` の形でない。"
        elif not m.group(1).strip():
            detail = "図の題が空である。"
        elif not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
            detail = "図の範囲の値が、0 ≤ x0 < x1 ≤ 1、0 ≤ y0 < y1 ≤ 1 を満たさない。"
        elif not nxt.strip().startswith(values.FIGURE_NOTE):
            detail = "図の行の次の段落が `図の説明：` で始まらない。"
        else:
            detail = None
        found.append((k, m.group(1) if m else "", None if detail else box, detail))
    return found


def padded(box):
    """図の範囲の各辺を広げ、0〜1 に収める。"""
    x0, y0, x1, y1 = box
    p = values.FIGURE_PAD
    return (max(0.0, x0 - p), max(0.0, y0 - p), min(1.0, x1 + p), min(1.0, y1 + p))


def split_cells(row):
    """表の行を、コードスパンの外で、前に \\ がない | で区切る。(セルのリスト, | で終わるか) を返す。"""
    s = row.strip()
    inside = markdown.span_positions(s)
    cells, cur, closed = [], "", False
    for i, c in enumerate(s):
        if c == "|" and i not in inside and (i == 0 or s[i - 1] != "\\"):
            cells.append(cur)
            cur, closed = "", i == len(s) - 1
        else:
            cur += c
    cells.append(cur)
    return (cells[1:-1] if closed else cells[1:]), closed


def _table_problems(lines, elems):
    found, tables = [], []
    for e in elems:
        if e.kind == "table_head":
            tables.append([e.start])
        elif e.kind in ("table_sep", "table_row"):
            tables[-1].append(e.start)
    for rows in tables:
        head, _ = split_cells(lines[rows[0]])
        bad = None
        if len(rows) < 2:
            bad = (rows[0], "表が2行未満である。")
        elif not all(_SEPARATOR_CELL.fullmatch(c.strip()) for c in split_cells(lines[rows[1]])[0]):
            bad = (rows[1], "2行目が区切りの行（`| --- |`）でない。")
        else:
            for k in rows:
                cells, closed = split_cells(lines[k])
                if not closed:
                    bad = (k, "行が `|` で終わらない。")
                elif len(cells) != len(head):
                    bad = (k, "列の数が1行目と違う。")
                if bad:
                    break
        if bad:
            found.append((bad[0] + 1, "bad_table", bad[1]))
    return found


def _bare_name(word):
    """識別子の形の語（6.2 の bare_name）か。"""
    return ("_" in word and _LETTER.search(word)) or (len(word) >= values.CAMEL_MIN_CHARS and _CAMEL.search(word))


def line_span_names(line):
    """1行で、コードスパンの全体になっている、4 文字以上の語（6.2 の bare_name）。"""
    return {x for x in markdown.code_spans(line) if len(x) >= values.SPAN_MIN_CHARS and markdown.WORD.fullmatch(x)}


def span_names(lines, elems):
    """コードブロックの外で、コードスパンの全体になっている、4 文字以上の語（6.2 の bare_name）。"""
    return {x for _, line in markdown.outside_code(lines, elems) for x in line_span_names(line)}


def format_problems(lines, elems, spanned):
    """形式の検査（6.2）。(行番号, 検査の名前, 説明) のリストを返す。
    spanned は、行の添え字を受けて、その行のページと前後のページでコードスパンの全体になっている語を返す関数。"""
    found = _table_problems(lines, elems)
    found += [(e.start + 1, "unclosed_code", "コードブロックに閉じる行がない。ページの終わりで閉じ、次のページで開き直す。")
              for e in elems if e.kind == "code" and not e.closed]
    for k, line in markdown.outside_code(lines, elems):
        text = markdown.outside_spans(line)
        if _TAG.search(text.replace("<br>", " ")):
            found.append((k + 1, "bad_tag", "バッククォートの外に、`<br>` のほかのタグがある。"))
        if "__" in text:
            found.append((k + 1, "double_underscore", "バッククォートの外に `__` がある。"))
        names = [w for w in markdown.WORD.findall(text) if _bare_name(w) or w in spanned(k)] if "](" not in line else []
        if names:
            found.append((k + 1, "bare_name", "バッククォートの外に、識別子の形の語（`_` を含む語、途中に大文字がある "
                                               "5 文字以上の語、このページか前後のページでバッククォートで囲んだ語）"
                                               "がある：%s。バッククォートで囲む。"
                                               % "、".join("「%s」" % w for w in _dedupe(names))))
    found += [(k + 1, "bad_figure", d) for k, _, _, d in figures(lines, elems) if d]
    found += [(n, "bad_mermaid", d) for n, _, d in markdown.mermaid_problems(lines, elems)]
    return found


def _dedupe(strings):
    return list(dict.fromkeys(strings))


def _extra_text(lines, elems):
    """余分の検査で調べる文（6.2 の表の決まった部分を、空白1つに置き換えたもの）。"""
    lines = list(lines)
    for e in elems:
        if markdown.is_mermaid(lines, e):
            lines[e.start:e.end + 1] = [" "] * (e.end - e.start + 1)
    first_head = next((e.start for e in elems if e.kind == "table_head"), None)
    if first_head is not None:
        lines[first_head] = " "
    k = 0
    while k < len(lines):
        if lines[k].strip().startswith(values.FIGURE_NOTE):
            while k < len(lines) and lines[k].strip():
                lines[k] = " "
                k += 1
        k += 1
    text = "\n".join(_FIGURE_VALUE.sub(" ", x) if "](figure:" in x else x for x in lines)
    for s in values.MARKS + ("<br>",):
        text = text.replace(s, " ")
    return text


def string_diffs(ctx, pdf, page, lines, elems):
    """文字列の検査（6.2）。(欠けの文字列, 余分の文字列) を返す。"""
    folder = ctx.abs(".work/pdf/" + pdf["id"])
    near = [n for n in (page - 1, page, page + 1) if 1 <= n <= pdf["pages"]]
    outputs = [os.path.join(folder, "%04d.md" % n) for n in near]
    targets = [pdfmod.joined_chars(files.read_text(p)) for p in outputs if os.path.isfile(p)]
    info = files.read_json(os.path.join(folder, "%04d.json" % page))
    boxes = [padded(b) for _, _, b, _ in figures(lines, elems) if b]
    lacking = []
    for u in info["units"]:
        x0, y0, x1, y1 = u["box"]
        cx, cy = (x0 + x1) / 2 / values.POSITION_SCALE, (y0 + y1) / 2 / values.POSITION_SCALE
        if u["margin"] or any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in boxes):
            continue
        lacking += [s for s in pdfmod.check_strings(u["text"]) if not any(s in t for t in targets)]
    units = [u for n in near for u in files.read_json(os.path.join(folder, "%04d.json" % n))["units"]]
    every = pdfmod.joined_chars("".join(u["text"] for u in units))
    body = pdfmod.joined_chars("".join(u["text"] for u in units if not u["margin"]))
    extra = [s for s in pdfmod.check_strings(_extra_text(lines, elems)) if s not in every and s not in body]
    return _dedupe(lacking), _dedupe(extra)


def check_convert(ctx, job):
    """ページごとに合否を決める（6.2 のページの合否）。合格したページは、job の pages から外し、log に記録する。"""
    pdf_id = job["target"].split(":")[0]
    pdf = next(p for p in ctx.plan["pdfs"] if p["id"] == pdf_id)
    n = job["tries"] + 1
    found = []
    for rel in job["outputs"]:
        page = files.page_of(rel)
        info = job["pages"][str(page)]
        path = ctx.abs(rel)
        if not os.path.isfile(path):
            found.append(missing(rel))
            continue
        lines = read_lines(path)
        elems = markdown.parse(lines)
        spanned = span_names(lines, elems)
        for near in (page - 1, page + 1):
            other = os.path.join(os.path.dirname(path), "%04d.md" % near)
            if os.path.isfile(other):
                other_lines = read_lines(other)
                spanned |= span_names(other_lines, markdown.parse(other_lines))
        form = [item(rule, rel, k, d) for k, rule, d in format_problems(lines, elems, lambda k: spanned)]
        diffs = []
        if files.read_json(path[:-3] + ".json")["check"]:
            lacking, extra = string_diffs(ctx, pdf, page, lines, elems)
            diffs = [("text_missing", s) for s in lacking] + [("text_extra", s) for s in extra]
        names = ["%s:%s" % (r[5:], s) for r, s in diffs]
        if not form and (set(names) <= set(info["prev"]) or n == values.MAX_TRIES):
            ctx.state["log"] += [{"type": "convert_diff", "pdf": pdf_id, "page": page, "kind": r[5:], "text": s}
                                 for r, s in diffs]
            if n == values.MAX_TRIES and info["mermaid"]:
                ctx.state["log"].append({"type": "figure_switched", "pdf": pdf_id, "page": page})
            del job["pages"][str(page)]
            continue
        found += form + [item(r, rel, None, "「%s」%s" % (s, TEXT_SUFFIX[r]))
                         for (r, s), name in zip(diffs, names) if name not in info["prev"]]
        job["pages"][str(page)] = {"prev": names, "mermaid": any(x["rule"] == "bad_mermaid" for x in form)}
    return found


# ---------------------------------------------------------------------------
# 6.3 照合
# ---------------------------------------------------------------------------

def read_records(ctx, rel, info):
    """照合の記録を読む。(ファイル全体の不合格の項目, 記録のリスト) を返す。

    記録は、範囲（start、end。形が悪いときは start が None）、分類（cat）、キーの値（values）、内容の行（content）、
    根拠の場所（location）と、その記録だけの不合格の項目（problems）を持つ。振り分け（8.3）も、これを使う。
    """
    lines = read_lines(ctx.abs(rel))
    heads = [k for k, x in enumerate(lines) if x.startswith("## ")]
    before = [k for k in range(heads[0] if heads else len(lines)) if lines[k].strip()]
    found = [item("bad_record", rel, before[0] + 1, "最初の `## ` の行より前に、行がある。消す。")] if before else []
    ends = heads[1:] + [len(lines)]
    return found, [_record(ctx, rel, info, lines, k, end) for k, end in zip(heads, ends)]


def _record(ctx, rel, info, lines, k, end):
    rec = {"start": None, "problems": []}

    def bad(rule, detail):
        rec["problems"].append(item(rule, rel, k + 1, detail))

    m = _RECORD.fullmatch(lines[k].rstrip())
    if not m or int(m.group(2) or m.group(1)) < int(m.group(1)):
        bad("bad_record", "記録の行が `## <範囲> <分類>` の形でない。分類は、一致、食い違い、既存設計書のみ、対象外のどれかにする。")
        return rec
    rec.update(start=int(m.group(1)), end=int(m.group(2) or m.group(1)), cat=m.group(3), values={})
    rows = [j for j in range(k + 1, end) if lines[j].strip()]
    keys = RECORD_KEYS[rec["cat"]]
    for key, j in zip(keys, rows + [None] * len(keys)):
        line = lines[j].rstrip() if j is not None else ""
        head = "- %s:" % key
        value = line[len(head) + 1:] if line.startswith(head + " ") else ""
        if (line != head) if key == CONTENT_KEY else (not value or value[0].isspace()):
            bad("bad_record", "キー `%s` の行がない、順番が違う、または値が空である。キーは決まった順に書く。" % key)
            return rec
        rec["values"][key] = value
    if rec["cat"] in ("一致", "対象外") and rows[len(keys):]:
        bad("bad_record", "「%s」の記録に、決まったもののほかの行がある。消す。" % rec["cat"])
    if rec["cat"] == "一致" and any(markdown.IMAGE_LINE.fullmatch(e["text"].strip()) for e in info["lines"]
                                     if rec["start"] <= e["n"] <= rec["end"]):
        bad("bad_record", "「一致」の範囲に、画像の行がある。画像の行は「既存設計書のみ」にする。")
    if "場所" in keys:
        _record_location(ctx, rec, bad)
    if rec["cat"] == "既存設計書のみ":
        _record_content(ctx, rel, rec, lines[rows[1] + 1:end], rows[1] + 1, bad)
    return rec


def _record_location(ctx, rec, bad):
    v = rec["values"]
    m = markdown.LOCATION.match(v["場所"])
    if not m or m.end() != len(v["場所"]):
        bad("bad_location", "場所は、根拠の場所（`[<相対パス>:<開始行>-<終了行>]`）1個にする。")
        loc = None
    else:
        loc = (m.group(1), int(m.group(2)), int(m.group(3)))
        problem = ctx.sources.location_problem(*loc, limit=False)
        if problem:
            bad("bad_location", problem)
            loc = None
    rec["location"] = loc
    if rec["cat"] == "食い違い":
        words = markdown.WORD.findall(v["名前"])
        if not words or (loc and not all(ctx.sources.words(loc[0]).has(w) for w in words)):
            bad("unknown_word", "名前が、場所のファイルにない。場所のファイルにある関数か定義の名前を書く。")


def _record_content(ctx, rel, rec, content, offset, bad):
    rec["content"] = content
    elems = markdown.parse(content)
    if any(e.kind == "heading" for e in elems) or not any(e.kind in markdown.BODY for e in elems):
        bad("bad_record", "内容には、見出しを書かずに、文、表、図を1つ以上書く。")
    module = rec["values"]["モジュール"]
    if module != OVERALL and module not in {m["name"] for m in ctx.plan["modules"]}:
        bad("unknown_module", "モジュール `%s` が、モジュールの一覧にない。一覧の名前か `全体` にする。" % module)
    for n, _, detail in markdown.mermaid_problems(content, elems):
        rec["problems"].append(item("bad_mermaid", rel, offset + n, detail))
    for k, line in markdown.outside_code(content, elems):
        for name in markdown.name_problems(line, ctx.names):
            rec["problems"].append(item("unknown_name", rel, offset + k + 1, "`%s` が、ソースコードにも既存の設計書にもない。"
                                        "名前を元の表記のまま書く。" % name))


def check_match(ctx, job):
    rel = job["outputs"][0]
    if not os.path.isfile(ctx.abs(rel)):
        return [missing(rel)]
    info = files.read_json(ctx.abs(".work/match/%s.json" % job["id"]))
    found, records = read_records(ctx, rel, info)
    covered = [n for r in records if r["start"] is not None for n in range(r["start"], r["end"] + 1)]
    if sorted(covered) != list(range(1, info["count"] + 1)):
        found.append(item("bad_cover", rel, None, "範囲が、1 から %d までの番号を、ちょうど1回ずつ覆っていない。" % info["count"]))
    return found + [x for r in records for x in r["problems"]]


# ---------------------------------------------------------------------------
# 6.4、6.5 執筆
# ---------------------------------------------------------------------------

def planned_files(plan):
    """計画と mode から決まる docs/ の出力（出力先からの相対パス。9章の missing_file の一覧）。"""
    found = ["docs/index.md", "mkdocs.yml", "docs/review/unknowns.md"]
    if plan["mode"] == "both":
        found.append("docs/review/discrepancies.md")
    for m in plan["modules"]:
        names = [p["name"] for p in m["parts"]] + ([m["name"]] if len(m["parts"]) > 1 else [])
        found += ["docs/%s/%s.md" % (d, n) for n in names for d in ("design/modules", "requirements/3-1-functions")]
    if plan["mode"] != "pdf":
        found += ["docs/" + path for path, _ in values.OVERALL_FILES]
    return found + ["docs/legacy/%s/001.md" % p["folder"] for p in plan["pdfs"]]


def doc_rules(plan, rel):
    """6.4 と 6.5 の設計書の (1行目, 必須の見出し, 要求の接頭辞か None)。"""
    for m in plan["modules"]:
        for p in m["parts"]:
            if rel == "docs/design/modules/%s.md" % p["name"]:
                return "# " + p["name"], ["## " + h for h in values.MODULE_HEADINGS], None
            if rel == "docs/requirements/3-1-functions/%s.md" % p["name"]:
                return "# 3.1 機能（%s）" % p["name"], [values.FUNCTIONS_HEADING], p["fr_prefix"]
    # 全体の文書の1行目と必須の見出しは、ひな形に書いてある。
    with open(os.path.join(TEMPLATES_DIR, "docs", rel.rpartition("/")[2]), "r", encoding="utf-8") as f:
        template = files.split_lines(f.read())
    return template[0], [x for x in template[1:] if markdown.heading_level(x)], dict(values.OVERALL_FILES)[rel[5:]]


def section_body(elems, i):
    """elems[i] の見出しから、次の同じか上のレベルの見出しの前までの、本文の行の要素。"""
    found = []
    for e in elems[i + 1:]:
        if e.kind == "heading" and e.level <= elems[i].level:
            break
        if e.kind in markdown.BODY:
            found.append(e)
    return found


def doc_problems(ctx, rel, lines, all_names=False):
    """設計書と要求の検査（6.4 の表の「設計書、要求」）。check（9章）も使う。"""
    first, required, prefix = doc_rules(ctx.plan, rel)
    elems = markdown.parse(lines)
    found = []
    if not lines or lines[0].rstrip() != first:
        found.append(item("missing_heading", rel, 1, "1行目を `%s` にする。" % first))
    sections, k = [], 0
    for i, e in enumerate(elems):
        if e.kind != "heading":
            continue
        if e.start == 0 and lines[0].rstrip() == first:
            sections.append(i)
        elif k < len(required) and lines[e.start].rstrip() == required[k]:
            sections.append(i)
            k += 1
    if k < len(required):
        found.append(item("missing_heading", rel, None, "必須の見出し `%s` がないか、順番が違う。" % required[k]))
    found += [item("empty_section", rel, elems[i].start + 1, "節に本文の行がない。内容がないときは、決まった1文を書く。")
              for i in sections if not section_body(elems, i)]
    found += new_doc_problems(ctx, rel, lines, elems, all_names)
    if prefix:
        found += _requirement_problems(rel, lines, elems, prefix)
    return found


def too_long(rel, lines):
    if len(lines) > values.MAX_DOC_LINES:
        return [item("too_long", rel, None, "%d 行を超える。" % values.MAX_DOC_LINES)]
    return []


def link_and_mermaid(ctx, rel, lines, elems):
    """リンクと Mermaid の検査（5.7、5.4）。docs/ の全部のファイルに当てる。"""
    planned = set(planned_files(ctx.plan))
    found = [item(r, rel, n, d) for n, r, d in markdown.link_problems(
        rel, lines, elems, lambda t: t in planned or os.path.isfile(ctx.abs(t)))]
    return found + [item("bad_mermaid", rel, n, d) for n, _, d in markdown.mermaid_problems(lines, elems)]


def new_doc_problems(ctx, rel, lines, elems, all_names=False):
    """新しい設計書（docs/design/、docs/requirements/）の共通の検査。

    名前の検査は、執筆の出力では見出しと表の見出しの行だけに当てる（本文の行は検証が確かめる）。check は全部の行に当てる。
    """
    found = too_long(rel, lines) + link_and_mermaid(ctx, rel, lines, elems)
    found += [item(r, rel, n, d) for n, r, d in markdown.line_problems(lines, elems)]
    for e in elems:
        if e.kind in ("heading", "table_head") or (all_names and e.kind != "code"):
            found += [item("unknown_name", rel, e.start + 1, "`%s` が、ソースコードにない。名前を元の表記のまま書く。" % name)
                      for name in markdown.name_problems(lines[e.start], ctx.names)]
    return found


def _requirement_problems(rel, lines, elems, prefix):
    found, seen = [], set()
    shape = re.compile(re.escape(prefix) + r"[0-9]{3,}: ")
    for e in elems:
        s = lines[e.start].lstrip()
        if e.kind != "text" or not s.startswith("- ") or not s[2:].startswith(values.REQUIREMENT_HEADS):
            continue
        if not shape.match(s[2:]):
            found.append(item("bad_requirement_id", rel, e.start + 1, "要求の ID を `%s` と3桁以上の番号にする。" % prefix))
        rid = s[2:].split(": ", 1)[0]
        if rid in seen:
            found.append(item("duplicate_id", rel, e.start + 1, "要求の ID `%s` が重なっている。" % rid))
        seen.add(rid)
    return found


def check_write(ctx, job):
    found = []
    for rel in job["outputs"]:
        path = ctx.abs(rel)
        if not os.path.isfile(path):
            found.append(missing(rel))
            continue
        lines = read_lines(path)
        if not rel.startswith(".work/unknowns/"):
            found += doc_problems(ctx, rel, lines)
        elif any(x.strip() and not x.startswith("- ") for x in lines) or not any(x.startswith("- ") for x in lines):
            found.append(item("bad_item", rel, None, "不明点は、1行に1つ `- <文>` で書く。ないときは `- なし` と書く。"))
    return found


# ---------------------------------------------------------------------------
# 6.6 検証
# ---------------------------------------------------------------------------

def check_verify(ctx, job):
    """判定の記録を、番号ごとに検査する。(番号を振った行の JSON, 合格した判定, 不合格の項目) を返す。

    合格した判定は、番号の順の (SHA-1, 判定, 直した文か None, 探した語, 根拠の場所のリスト)。
    """
    rel = job["outputs"][0]
    info = files.read_json(ctx.abs(rel[:-3] + ".json"))
    got = {}
    if os.path.isfile(ctx.abs(rel)):
        for k, line in enumerate(read_lines(ctx.abs(rel)), 1):
            m = _VERDICT.match(line)
            if m:
                got.setdefault(int(m.group(1)), []).append((k, line[m.end():]))
    verdicts, found = [], []
    for e in info["lines"]:
        rows = got.get(e["n"], [])
        if len(rows) != 1:
            problems = [("missing_verdict", "判定がない。")] if not rows else [("bad_verdict", "同じ番号の行が2つ以上ある。")]
            verdict = None
        else:
            problems, verdict = _judge(ctx, e["text"], rows[0][1])
        line = rows[-1][0] if rows else None
        found += [dict(item(r, rel, line, d), n=e["n"], sha1=e["sha1"]) for r, d in problems]
        if not problems:
            verdicts.append((e["sha1"],) + verdict)
    return info, verdicts, found


def _locations(rest, pos):
    """pos から、空白1つで区切った根拠の場所を3個まで読む。(場所のリスト, 読み終えた位置) を返す。"""
    locs = []
    while len(locs) < values.MAX_VERDICT_LOCATIONS:
        if locs and not rest.startswith(" ", pos):
            break
        m = markdown.LOCATION.match(rest, pos + (1 if locs else 0))
        if not m:
            break
        locs.append((m.group(1), int(m.group(2)), int(m.group(3))))
        pos = m.end()
    return locs, pos


def _judge(ctx, t, rest):
    """1つの判定の検査。t は番号の行の文、rest は判定の行の [n] より後ろ。(不合格の項目, 判定) を返す。"""
    block = bool(markdown.FENCE.match(t))
    if rest == " 対象外":
        if block or markdown.code_spans(t):
            return [("bad_verdict", "コードスパンのある行とコードブロックは、OK、NG、不明のどれかにする。")], None
        return [], ("対象外", None, "", [])
    if rest.startswith(" 不明"):
        words = rest[len(" 不明 "):].strip() if rest.startswith(" 不明 ") else ""
        if not words:
            return [("bad_verdict", "不明には、探した語を書く。")], None
        return [], ("不明", None, words, [])
    m = re.match(r" (OK|NG) ", rest)
    locs, pos = _locations(rest, m.end()) if m else ([], 0)
    tail = rest[pos:]
    fixed = tail[1:] if tail.startswith(" ") else None
    if not locs or (m.group(1) == "OK" and tail) or (tail and fixed is None):
        return [("bad_verdict", "判定の行が決まった形でない。`[n] OK <根拠>` のように書く。")], None
    kind = m.group(1)
    if kind == "NG" and not block and not fixed:
        return [("bad_verdict", "NG には、直した文を書く。")], None
    if fixed == t:
        return [("bad_verdict", "直した文が、元の行と同じである。")], None
    problems = [("bad_location", p) for p in (ctx.sources.location_problem(*loc) for loc in locs) if p]
    if problems:
        return problems, None
    if block:
        return [], (kind, None, "", locs)  # コードブロックは、語を調べず、NG では直した文を使わない（8.5）
    problems = ctx.sources.word_problems(locs, t if kind == "OK" else fixed)
    if kind == "NG":
        if not _same_shape(t, fixed):
            problems.append(("bad_shape", "直した文の形（表の行、要求の行、箇条書き、段落）を、元の行と同じにする。"))
        problems += markdown.sentence_problems(fixed)
    return problems, (kind, fixed, "", locs)


def _same_shape(t, c):
    if t.strip().startswith("|"):
        s = c.strip()
        return s.startswith("|") and s.endswith("|") and len(split_cells(s)[0]) == len(split_cells(t)[0])
    for pattern in (_REQUIREMENT, markdown.BULLET):
        m = pattern.match(t)
        if m:
            return c.startswith(m.group(0))
    return not (c.strip().startswith("|") or markdown.BULLET.match(c) or markdown.heading_level(c)
                or markdown.FENCE.match(c))
