"""check：docs/ の全部の .md に、仕事の出来の検査と同じ決まりを当てる（スクリプトの仕様の9章）。"""
import os

from . import files, jobchecks, markdown, values
from .scriptwork import PAGE_MARK
from .state import Ctx

NEW_DOCS = ("docs/design/", "docs/requirements/")
LEGACY_RULES = ("bad_table", "bad_tag", "double_underscore", "bare_name")


def _skipped(ctx):
    """失敗として記録したファイル。不合格に数えない。"""
    found = set()
    for job in (j for j in ctx.state["jobs"] if j["status"] == "failed"):
        found.update(job["outputs"] + job["substitute"])
        if job["kind"] != "convert":
            continue
        pages = {files.page_of(rel) for rel in job["outputs"]}
        pdf = next(p for p in ctx.plan["pdfs"] if p["id"] == job["target"].split(":")[0])
        for rel in files.md_files(ctx.out, "docs/legacy/" + pdf["folder"]):
            marks = (PAGE_MARK.fullmatch(x.strip()) for x in jobchecks.read_lines(ctx.abs(rel)))
            if any(m and int(m.group(1)) in pages for m in marks):
                found.add(rel)
    return found


def _writer_outputs(plan):
    """6.4 と 6.5 の docs/ の出力。"""
    found = {"docs/" + path for path, _ in values.OVERALL_FILES} if plan["mode"] != "pdf" else set()
    for m in plan["modules"]:
        for p in m["parts"]:
            found |= {"docs/design/modules/%s.md" % p["name"], "docs/requirements/3-1-functions/%s.md" % p["name"]}
    return found


def _pages(lines):
    """行ごとのページ。ページの目印（`<!-- page: N -->`）から決める。"""
    found, page = [], None
    for x in lines:
        m = PAGE_MARK.fullmatch(x.strip())
        page = int(m.group(1)) if m else page
        found.append(page)
    return found


def _legacy_spans(ctx, folder):
    """PDF の docs/legacy/ のフォルダの全部のファイルから、ページごとの span_names を {ページ: 語} で返す。
    1,000 行で分けたファイルの境目でも、前後のページを使えるように、フォルダの全部を見る。"""
    found = {}
    for rel in files.md_files(ctx.out, folder):
        lines = jobchecks.read_lines(ctx.abs(rel))
        pages = _pages(lines)
        for k, line in markdown.outside_code(lines, markdown.parse(lines)):
            found.setdefault(pages[k], set()).update(jobchecks.line_span_names(line))
    return found


def _legacy_format(ctx, rel, lines, elems, spans):
    folder = "/".join(rel.split("/")[:3])
    if folder not in spans:
        spans[folder] = _legacy_spans(ctx, folder)
    by_page, pages = spans[folder], _pages(lines)

    def spanned(k):
        p = pages[k]
        near = (p,) if p is None else (p - 1, p, p + 1)
        return set().union(*(by_page.get(n, ()) for n in near))
    return [jobchecks.item(r, rel, n, d) for n, r, d in jobchecks.format_problems(lines, elems, spanned)
            if r in LEGACY_RULES and not (r == "bad_tag" and PAGE_MARK.fullmatch(lines[n - 1].strip()))]


def _problems(ctx, rel, writers, spans):
    lines = jobchecks.read_lines(ctx.abs(rel))
    if rel in writers:
        return jobchecks.doc_problems(ctx, rel, lines, all_names=True)
    elems = markdown.parse(lines)
    if rel.startswith(NEW_DOCS):
        return jobchecks.new_doc_problems(ctx, rel, lines, elems, all_names=True)
    found = jobchecks.too_long(rel, lines) if rel.startswith(("docs/legacy/", "docs/review/")) else []
    found += jobchecks.link_and_mermaid(ctx, rel, lines, elems)
    if rel.startswith("docs/legacy/"):
        found += _legacy_format(ctx, rel, lines, elems, spans)
    return found


def run(out):
    ctx = Ctx(out)
    writers = _writer_outputs(ctx.plan)
    found = [jobchecks.missing(rel) for rel in jobchecks.planned_files(ctx.plan) if not os.path.isfile(ctx.abs(rel))]
    spans = {}
    for rel in files.md_files(out, "docs"):
        found += _problems(ctx, rel, writers, spans)
    skipped = _skipped(ctx)
    found = [x for x in jobchecks.sort_items(found) if x["file"] not in skipped]
    return {"ok": True, "passed": not found, "problem_count": len(found),
            "failed_jobs": len([j for j in ctx.state["jobs"] if j["status"] == "failed"]),
            "problems": found[:values.MAX_PROBLEMS]}
