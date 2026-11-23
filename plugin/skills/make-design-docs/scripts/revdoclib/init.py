"""init：入力を確かめ、計画と最初の状態を書く。状態があれば、再開する（スクリプトの仕様の3章）。"""
import os

from . import files, packages, values
from . import plan as planmod
from .common import TEMPLATES_DIR, Fail, cmd

INPUT_LABELS = (("mode", "ソースコードと PDF の組み合わせ（mode）"), ("src", "ソースコードのフォルダ（src）"),
                ("pdf", "PDF の場所（pdf）"))


def _check_inputs(out, src, pdf):
    """1.3 の表の init の行を、上から順に確かめる（計画を作りながら確かめるものは plan.build）。"""
    for p in (out, src, pdf):
        if p and "'" in p:
            raise Fail("bad_path", "パスに ' を含むフォルダは使えない：%s" % p)
    if not src and not pdf:
        raise Fail("no_input", "ソースコードのフォルダ（--src）か、PDF（--pdf）を指示する。")
    if src and not os.path.isdir(src):
        raise Fail("src_not_found", "ソースコードのフォルダがない：%s" % src)
    if pdf and not (os.path.isdir(pdf) or (os.path.isfile(pdf) and pdf.lower().endswith(".pdf"))):
        raise Fail("pdf_not_found", "PDF のフォルダか、PDF のファイルがない：%s" % pdf)
    names = packages.missing(bool(pdf))
    if names:
        raise Fail("missing_packages", "Python のパッケージが足りない：%s" % "、".join(names), packages=names)


def _outputs(job):
    """仕事の出力のファイル（出力先からの相対パス）。"""
    kind, target = job["kind"], job["target"]
    if kind == "analyze":
        return [".work/memo/%s.md" % target]
    if kind == "convert":
        pdf_id, pages = target.split(":")
        first, last = (int(n) for n in pages.split("-"))
        return [".work/pdf/%s/%04d.md" % (pdf_id, n) for n in range(first, last + 1)]
    if kind in ("match", "verify"):
        return [".work/%s/%s.md" % (kind, job["id"])]
    unknowns = unknowns_path(job)
    if kind == "write_module":
        return ["docs/design/modules/%s.md" % target, "docs/requirements/3-1-functions/%s.md" % target, unknowns]
    return ["docs/" + target, unknowns]


def unknowns_path(job):
    """執筆の仕事の不明点のファイル。"""
    return ".work/unknowns/%s.md" % job["id"]


def job_entry(job, stage):
    """状態のファイルの仕事の項目（4.7）。job は計画の仕事の形（id、kind、target）。"""
    entry = dict(job, stage=stage, agent=values.AGENTS[job["kind"]], status="pending", tries=0,
                 outputs=_outputs(job), reasons=[], substitute=[])
    if job["kind"] == "convert":
        entry["pages"] = {str(files.page_of(p)): {"prev": [], "mermaid": False} for p in entry["outputs"]}
    return entry


def first_state(plan):
    jobs = [job_entry(job, job["kind"]) for job in plan["jobs"]]
    return {"version": 1, "stage": jobs[0]["stage"], "round": 0, "no_output": 0, "next_job": len(jobs) + 1,
            "jobs": jobs, "confirmed": {}, "log": []}


def _write_new(work, plan, copies, words):
    if plan["mode"] != "pdf":
        files.write_text(os.path.join(work, "names.txt"), "".join(w + "\n" for w in sorted(words)))
        files.write_text(os.path.join(work, "modules.md"), "".join(
            "- %s（フォルダ：%s、%d ファイル、%d 行）\n" % (m["name"], m["folder"] or "直下", m["files"], m["lines"])
            for m in plan["modules"]))
        for rel, text in copies.items():
            path = os.path.join(work, "src-utf8", *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # 行番号を元のファイルと同じにするため、改行は元のまま書く。
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        for path, _ in values.OVERALL_FILES:
            name = path.rpartition("/")[2]
            with open(os.path.join(TEMPLATES_DIR, "docs", name), "r", encoding="utf-8") as f:
                text = f.read()
            files.write_text(os.path.join(work, "templates", name),
                             text.replace("{{none_sentence}}", plan["none_sentence"]))
    files.write_text(os.path.join(work, "plan.json"), files.dumps(plan))
    # 状態のファイルがあることが、init が終わった印になるので、最後に書く。
    files.write_atomic(os.path.join(work, "state.json"), files.dumps(first_state(plan)))


def _resume(work, plan):
    saved = files.read_json(os.path.join(work, "plan.json"))
    if {k: v for k, v in saved.items() if k != "excluded"} != {k: v for k, v in plan.items() if k != "excluded"}:
        notes = ["%sが、前と違う。" % label for k, label in INPUT_LABELS if saved[k] != plan[k]]
        diff = planmod.changed_paths(saved, plan)
        if diff:
            notes.append("違いのあるファイル（%d 件）：%s" % (len(diff), "、".join(diff[:5])))
        raise Fail("input_changed", "入力が、作業を始めたときと違う。" + "".join(notes))
    state_path = os.path.join(work, "state.json")
    state = files.read_json(state_path)
    for job in state["jobs"]:
        if job["status"] == "issued":
            job["status"] = "pending"
    state["no_output"] = 0
    files.write_atomic(state_path, files.dumps(state))


def run(out, src, pdf):
    _check_inputs(out, src, pdf)
    plan, copies, words = planmod.build(src, pdf, out)
    if planmod.path_too_long(out, plan, os.name == "nt"):
        raise Fail("path_too_long", "出力先のパスが長すぎる。出力先を短いパスにして、やり直す：%s" % out)
    work = os.path.join(out, ".work")
    if os.path.exists(os.path.join(work, "state.json")):
        _resume(work, plan)
    else:
        _write_new(work, plan, copies, words)
    return {"ok": True, "do": "Run: " + cmd("next", out)}
