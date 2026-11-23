"""仕上げ（スクリプトの仕様の 8.7）と、mkdocs.yml（10章）。最後の段階が終わったときに、state から呼ぶ。"""
import json
import os
import posixpath
import re

from . import files, jobchecks, markdown, values
from . import plan as planmod
from .common import Fail
from .scriptwork import PAGE_MARK

MARK_NOTES = ("- 【既存設計書のみ】：既存の設計書から取った内容である。ソースコードでは確かめていない。"
              "ソースコードに見つからなかった機能の記述を含む。",
              "- 【判読できない】：既存の設計書の文字のうち、読み取れなかった部分である。")
REVIEW_DIR = "docs/review"
DIFF_KINDS = {"missing": "欠け", "extra": "余分"}
_PLAIN_PATH = re.compile(r"[A-Za-z0-9._\-/~]+")

MKDOCS_FIXED = r"""docs_dir: docs
site_dir: site
theme:
  name: material
  language: ja
  font: false
  features:
    - navigation.prune
plugins:
  - search:
      lang: en
      separator: '[\s\-,:!=\[\]()"/\u3000-\u303f\u3041-\u309f\uff00-\uffef]+'
      pipeline: []
  - privacy:
      cache_dir: .work/privacy
markdown_extensions:
  - tables
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
nav:
"""


def _text(lines):
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return "".join(x + "\n" for x in lines)


def _pdf_names(plan):
    return {p["id"]: p["name"] for p in plan["pdfs"]}


# ---------------------------------------------------------------------------
# 1 入力を確かめる、2 分けたモジュールの入口のページ
# ---------------------------------------------------------------------------

def _check_inputs(ctx):
    try:
        changed = planmod.changed_paths(ctx.plan, planmod.build(ctx.plan["src"], ctx.plan["pdf"], ctx.out)[0])
    except Fail:
        # フォルダや PDF が消えて計画を作り直せないときも、仕上げは続ける。
        changed = sorted(f["path"] for key in ("files", "pdfs") for f in ctx.plan[key])
    log = ctx.state["log"]
    known = {x["path"] for x in log if x["type"] == "input_diff"}
    log += [{"type": "input_diff", "path": p} for p in changed if p not in known]


def _entry_pages(ctx):
    units = {u["id"]: u for u in ctx.plan["units"]}
    for m in ctx.plan["modules"]:
        if len(m["parts"]) < 2:
            continue
        for folder in ("docs/design/modules", "docs/requirements/3-1-functions"):
            rel = "%s/%s.md" % (folder, m["name"])
            lines = ["# " + m["name"], ""]
            for p in m["parts"]:
                names = dict.fromkeys(r["path"].rpartition("/")[2] for uid in p["units"] for r in units[uid]["files"])
                link = posixpath.relpath("%s/%s.md" % (folder, p["name"]), posixpath.dirname(rel))
                lines.append("- [%s](%s)：%s" % (p["name"], link, "、".join(names)))
            files.write_text(ctx.abs(rel), _text(lines))


# ---------------------------------------------------------------------------
# 3、4 2つの一覧
# ---------------------------------------------------------------------------

def _write_paged(ctx, rel, title, first, blocks):
    """一覧を書く。1,000 行を超えるときは、blocks の切れ目で切り、続きのファイルに書く。

    blocks は [(行, 続きのファイルの先頭にもう一度書く行)]。first は、1つ目のファイルの見出しの後ろに書く行。
    """
    pages = [["# " + title, ""] + first]
    base = len(pages[0])
    for lines, heads in blocks:
        if len(_text(pages[-1] + lines).splitlines()) > values.MAX_DOC_LINES and len(pages[-1]) > base:
            pages.append(["# %s（続き %d）" % (title, len(pages) + 1), ""] + heads)
            base = len(pages[-1])
        pages[-1] += lines
    for k, page in enumerate(pages, 1):
        files.write_text(ctx.abs(rel if k == 1 else "%s~p%d.md" % (rel[:-3], k)), _text(page))


def _discrepancies(ctx, records):
    pdf_names = _pdf_names(ctx.plan)
    blocks = [(["## %d. %s %s" % (k, d["file"], d["name"]), "",
                "- 既存の設計書での場所: %s p.%d" % (pdf_names[d["pdf"]], d["page"]),
                "- ソースコードでの場所: %s %s" % (d["file"], d["name"]),
                "- モジュール: " + d["module"],
                "- 既存の設計書の内容: " + d["legacy"],
                "- ソースコードの内容: " + d["source"], ""], [])
              for k, d in enumerate(records["discrepancies"], 1)]
    first = ["ソースコードと既存の設計書で、内容が食い違う点である。新しい設計書には、ソースコードの内容を書いた。", ""]
    if not blocks:
        first += ["食い違いは見つからなかった。", ""]
    if records["unmatched"]:
        rest = ["## 照合していない範囲", ""] + ["- %s p.%d（%s の %d 行）" % (pdf_names[u["pdf"]], u["page"], u["file"], u["lines"])
                                        for u in records["unmatched"]]
        # 切れ目は「## <番号>.」の見出しの前だけなので、最後の食い違いにつなげる。
        if blocks:
            blocks[-1] = (blocks[-1][0] + rest, [])
        else:
            first += rest
    _write_paged(ctx, "docs/review/discrepancies.md", "食い違いの一覧", first, blocks)


def _written_unknowns(ctx):
    found = []
    for job in ctx.state["jobs"]:
        path = ctx.abs(".work/unknowns/%s.md" % job["id"])
        if job["kind"] not in ("write_module", "write_overall") or not os.path.isfile(path):
            continue
        who = job["target"] if job["kind"] == "write_module" else jobchecks.doc_rules(ctx.plan, "docs/" + job["target"])[0][2:]
        found += ["- %s：%s" % (who, x[2:] if x.startswith("- ") else x.strip())
                  for x in jobchecks.read_lines(path) if x.strip() and x != "- なし"]
    return found


def _empty_sections(ctx):
    none = ctx.plan["none_sentence"]
    found = []
    for rel in files.md_files(ctx.out, "docs/design") + files.md_files(ctx.out, "docs/requirements"):
        lines = jobchecks.read_lines(ctx.abs(rel))
        heading = ""
        for e in markdown.parse(lines):
            if e.kind == "heading":
                heading = lines[e.start].rstrip()
            elif e.kind == "text" and lines[e.start].strip() == none:
                found.append("- %s「%s」" % (rel, heading))
    return found


def _comment_mismatches(ctx):
    found = []
    for u in ctx.plan["units"]:
        path = ctx.abs(".work/memo/%s.md" % u["id"])
        if not os.path.isfile(path):
            continue
        section = None
        for x in jobchecks.read_lines(path):
            if x.startswith("## "):
                section = x[3:]
            m = jobchecks.ITEM.match(x)
            if section == values.MEMO_HEADINGS[-1] and m and m.group(4).startswith(values.COMMENT_MISMATCH):
                found.append("- [%s:%s-%s] %s" % (m.group(1), m.group(2), m.group(3),
                                                   m.group(4)[len(values.COMMENT_MISMATCH):]))
    return found


def _unreadable_pages(ctx):
    found = []
    for p in ctx.plan["pdfs"]:
        pages = set()
        for rel in files.md_files(ctx.out, "docs/legacy/" + p["folder"]):
            page = None
            for x in jobchecks.read_lines(ctx.abs(rel)):
                m = PAGE_MARK.fullmatch(x.strip())
                page = int(m.group(1)) if m else page
                if values.MARKS[1] in x:
                    pages.add(page)
        found += ["- %s p.%d" % (p["name"], n) for n in sorted(pages)]
    return found


def _failed_target(ctx, job):
    kind, target = job["kind"], job["target"]
    if kind == "convert":
        name = _pdf_names(ctx.plan)[target.split(":")[0]]
        return "%s p.%s" % (name, "、".join(str(files.page_of(rel)) for rel in job["outputs"]))
    if kind == "match":
        info = files.read_json(ctx.abs(".work/match/%s.json" % job["id"]))
        return "%s の %d 行" % (info["file"], info["count"])
    if kind == "verify":
        return files.read_json(ctx.abs(".work/verify/%s.json" % job["id"]))["file"]
    return "docs/" + target if kind == "write_overall" else target


def _failed_jobs(ctx):
    found = []
    for job in ctx.state["jobs"]:
        if job["status"] == "failed":
            r = job["reasons"][0]
            found.append("- %s：%s：[%s] %s" % (values.STAGE_LABELS[job["kind"]], _failed_target(ctx, job), r["rule"],
                                               r["detail"]))
    return found


def _unreadable_sources(plan):
    rows = [(e["path"], e["reason"]) for e in plan["excluded"] if e["reason"] in values.UNREADABLE_REASONS]
    rows += [(f["path"], f["encoding"]) for f in plan["files"] if f["encoding"] in values.UNREADABLE_REASONS]
    return ["- %s：%s" % (path, values.UNREADABLE_REASONS[r]) for path, r in sorted(rows)]


def unknown_groups(ctx):
    """不明点の一覧の [(## の見出し, [(### の見出し, [項目の行])])]。1つ目の ## が「不明点」である。"""
    log = ctx.state["log"]
    pdf_names = _pdf_names(ctx.plan)

    def of(kind):
        return [x for x in log if x["type"] == kind]

    def line(x):
        # 一覧は docs/review/ にあるので、設計書のフォルダからのリンクのままでは、リンク先が見つからない（9章）。
        text = x["text"]
        text = text.split("\n")[0] if markdown.FENCE.match(text) else markdown.rebase_links(text, x["file"], REVIEW_DIR)
        return "- %s「%s」：%s" % (x["file"], x["heading"], text)

    return [
        ("不明点", [
            ("執筆担当が書いた不明点", _written_unknowns(ctx)),
            ("検証で確かめられなかった行", [line(x) + ("（探した語：%s）" % x["words"] if x["words"] else "")
                                for x in of("verify_unknown")]),
            ("読み取れる内容がなかった節", _empty_sections(ctx) if ctx.plan["none_sentence"] else []),
            ("コメントと実装の食い違い", _comment_mismatches(ctx)),
            ("判読できない文字のあるページ", _unreadable_pages(ctx)),
        ]),
        ("処理の失敗", [
            ("失敗した仕事", _failed_jobs(ctx)),
            ("変換で残った違い", ["- %s p.%d：%s「%s」" % (pdf_names[x["pdf"]], x["page"], DIFF_KINDS[x["kind"]], x["text"])
                          for x in of("convert_diff")]),
            ("画像に切り替えた図", ["- %s p.%d" % (pdf_names[x["pdf"]], x["page"]) for x in of("figure_switched")]),
            ("判定が付かなかった行", [line(x) for x in of("verify_unjudged")]),
            ("読めなかったソースファイル", _unreadable_sources(ctx.plan)),
            ("作業中に変わった入力", ["- " + p for p in sorted(x["path"] for x in of("input_diff"))]),
        ]),
    ]


def _unknowns(ctx, groups):
    blocks = []
    for title, subs in groups:
        head = ["## " + title, ""]
        subs = [(h, items) for h, items in subs if items]
        group = [] if subs else [(["- なし", ""], [])]
        for h, items in subs:
            # 切った所の ## と ### の見出しを、続きのファイルの先頭にもう一度書く。
            group += [(([] if k else ["### " + h]) + [x] + ([""] if k == len(items) - 1 else []),
                       head + (["### " + h] if k else []))
                      for k, x in enumerate(items)]
        # ## の見出しだけがファイルの最後に残らないように、最初のブロックにつなげる。
        blocks += [(head + group[0][0], [])] + group[1:]
    _write_paged(ctx, "docs/review/unknowns.md", "不明点の一覧", [], blocks)


def summary(ctx, groups):
    """入口のページと serve の件数。(counts, 種類ごとの失敗した仕事の数) を返す。"""
    discrepancies = 0
    if ctx.plan["mode"] == "both":
        discrepancies = len(files.read_json(ctx.abs(".work/records/records.json"))["discrepancies"])
    counts = {"modules": len(ctx.plan["modules"]), "discrepancies": discrepancies,
              "unknowns": sum(len(items) for _, items in groups[0][1]),
              "changed_inputs": len([x for x in ctx.state["log"] if x["type"] == "input_diff"])}
    failed = {kind: 0 for kind in values.STAGE_LABELS}
    for job in ctx.state["jobs"]:
        if job["status"] == "failed":
            failed[job["kind"]] += 1
    return counts, failed


# ---------------------------------------------------------------------------
# 5 入口のページ
# ---------------------------------------------------------------------------

def _site_name(plan):
    if plan["mode"] == "pdf":
        return plan["pdfs"][0]["name"][:-len(".pdf")] + " 設計書"
    return os.path.basename(os.path.normpath(plan["src"])) + " 設計書"


def _checked_pages(ctx, pdf):
    found = 0
    for n in range(1, pdf["pages"] + 1):
        path = ctx.abs(".work/pdf/%s/%04d.json" % (pdf["id"], n))
        if os.path.isfile(path) and files.read_json(path)["check"]:
            found += 1
    return found


def _index(ctx, counts, failed):
    plan, mode = ctx.plan, ctx.plan["mode"]
    links = []
    if mode != "pdf":
        links += ["- [要求仕様書](requirements/1-introduction.md)", "- [内部設計書](design/architecture.md)"]
    links += ["- [既存の設計書（%s）](legacy/%s/001.md)" % (p["name"], p["folder"]) for p in plan["pdfs"]]
    if mode == "both":
        links.append("- [食い違いの一覧](review/discrepancies.md)")
    links.append("- [不明点の一覧](review/unknowns.md)")
    lines = ["# " + _site_name(plan), "", "## 設計書の構成", ""] + links + [""]
    marks = MARK_NOTES[:1] * (mode == "both") + MARK_NOTES[1:] * (mode != "source")
    if marks:
        lines += ["## 印の意味", ""] + list(marks) + [""]
    lines += ["## 使った入力", ""]
    if mode != "pdf":
        lines.append("- ソースコード：%s（%d ファイル、%d 行）" % (os.path.basename(os.path.normpath(plan["src"])),
                                                     len(plan["files"]), sum(f["lines"] for f in plan["files"])))
        reasons = [(label, len([e for e in plan["excluded"] if e["reason"] == r]))
                   for r, label in values.EXCLUDED_LABELS.items()]
        if plan["excluded"]:
            lines.append("- 対象から外したファイル：%d（%s）" % (len(plan["excluded"]),
                                                     "、".join("%s：%d" % x for x in reasons if x[1])))
    lines += ["- 既存の設計書：%s（%d ページ。埋め込みテキストで文字を確かめたページ：%d）"
              % (p["name"], p["pages"], _checked_pages(ctx, p)) for p in plan["pdfs"]]
    lines.append("")
    if mode != "pdf":
        lines += ["## モジュールの一覧", ""]
        lines += ["- [%s](design/modules/%s.md)：%s" % (m["name"], m["name"], m["folder"] or "直下") for m in plan["modules"]]
        lines.append("")
    rows = [("モジュール", counts["modules"])] * (mode != "pdf") + [("食い違い", counts["discrepancies"])] * (mode == "both")
    rows.append(("不明点", counts["unknowns"]))
    for kind, label in values.STAGE_LABELS.items():
        stage = "verify_module" if kind == "verify" else kind
        if mode in values.STAGE_MODES[stage]:
            rows.append(("失敗した仕事（%s）" % label, failed[kind]))
    rows.append(("作業中に変わった入力", counts["changed_inputs"]))
    lines += ["## 件数", "", "| 項目 | 件数 |", "| --- | --- |"] + ["| %s | %d |" % r for r in rows]
    if sum(failed.values()) or counts["changed_inputs"]:
        lines += ["", "失敗した仕事と、作業中に変わった入力は、[不明点の一覧](review/unknowns.md) に載せた。"]
    files.write_text(ctx.abs("docs/index.md"), _text(lines))


# ---------------------------------------------------------------------------
# 10章 mkdocs.yml
# ---------------------------------------------------------------------------

def _with_continuations(ctx, label, path):
    """nav の項目と、その後ろの続きのファイル（8.4、8.7）の項目。path は docs/ からのパス。"""
    found, k = [(label, path)], 2
    while os.path.isfile(ctx.abs("docs/%s~p%d.md" % (path[:-3], k))):
        found.append(("%s（続き %d）" % (label, k), "%s~p%d.md" % (path[:-3], k)))
        k += 1
    return found


def _module_nav(ctx, folder):
    found = []
    for m in ctx.plan["modules"]:
        if len(m["parts"]) == 1:
            found += _with_continuations(ctx, m["name"], "%s/%s.md" % (folder, m["name"]))
            continue
        sub = [("入口", "%s/%s.md" % (folder, m["name"]))]
        for k, p in enumerate(m["parts"], 1):
            sub += _with_continuations(ctx, str(k), "%s/%s.md" % (folder, p["name"]))
        found.append((m["name"], sub))
    return found


def _legacy_label(lines):
    elems = markdown.parse(lines)
    head = next((lines[e.start][e.level:].strip() for e in elems if e.kind == "heading"), "")
    pages = [int(m.group(1)) for m in (PAGE_MARK.fullmatch(lines[e.start].strip()) for e in elems if e.kind == "comment")
             if m]
    span = "(p.%d)" % pages[0] if pages[0] == pages[-1] else "(p.%d-%d)" % (pages[0], pages[-1])
    return "%s %s" % (head[:values.NAV_LABEL_CHARS], span) if head else span


def _nav(ctx):
    plan = ctx.plan
    nav = [("ホーム", "index.md")]
    if plan["mode"] != "pdf":
        reqs = []
        for path, _ in values.OVERALL_FILES:
            if path.startswith("requirements/"):
                reqs += _with_continuations(ctx, jobchecks.doc_rules(plan, "docs/" + path)[0][2:], path)
            if path == "requirements/2-references.md":
                reqs.append(("3.1 機能", _module_nav(ctx, "requirements/3-1-functions")))
        nav.append(("要求仕様書", reqs))
        nav.append(("内部設計書", _with_continuations(ctx, "全体", "design/architecture.md")
                    + [("モジュール", _module_nav(ctx, "design/modules"))]))
    if plan["pdfs"]:
        nav.append(("既存の設計書", [
            (p["name"], [(_legacy_label(jobchecks.read_lines(ctx.abs(rel))), rel[len("docs/"):])
                         for rel in files.md_files(ctx.out, "docs/legacy/" + p["folder"])])
            for p in plan["pdfs"]]))
    review = _with_continuations(ctx, "食い違いの一覧", "review/discrepancies.md") if plan["mode"] == "both" else []
    nav.append(("確認の一覧", review + _with_continuations(ctx, "不明点の一覧", "review/unknowns.md")))
    return nav


def _quote(s):
    return json.dumps(s, ensure_ascii=False)


def _yaml(items, indent):
    lines = []
    for label, value in items:
        if isinstance(value, list):
            lines.append("%s- %s:" % (indent, _quote(label)))
            lines += _yaml(value, indent + "  ")
        else:
            lines.append("%s- %s: %s" % (indent, _quote(label), value if _PLAIN_PATH.fullmatch(value) else _quote(value)))
    return lines


def _mkdocs(ctx):
    text = "site_name: %s\n%s" % (_quote(_site_name(ctx.plan)), MKDOCS_FIXED)
    files.write_text(ctx.abs("mkdocs.yml"), text + _text(_yaml(_nav(ctx), "  ")))


def run(ctx):
    _check_inputs(ctx)
    if ctx.plan["mode"] != "pdf":
        _entry_pages(ctx)
    if ctx.plan["mode"] == "both":
        _discrepancies(ctx, files.read_json(ctx.abs(".work/records/records.json")))
    groups = unknown_groups(ctx)
    _unknowns(ctx, groups)
    _index(ctx, *summary(ctx, groups))
    _mkdocs(ctx)
