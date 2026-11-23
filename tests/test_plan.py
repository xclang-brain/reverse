"""計画と入口のテスト。

確かめる受入条件は A-1（計画）、A-2（規模と時間）、A-10（名前と文字コード）、A-12（Python のバージョン）、
A-14（Windows のファイルの制限）である。根拠は、スクリプトの仕様（docs/script-spec.md）の1章〜3章と12章である。
"""
import collections
import contextlib
import hashlib
import io
import os
import re
import runpy
import shutil
import sys
import time
from pathlib import Path

import pytest

import helpers

GENERIC_DO = "Tell the user in Japanese what the message says. Then stop."
INPUT_CHANGED_DO = ("Tell the user in Japanese what the message says and that they can either restore the input"
                    " and run the same skill command again, or choose a new output folder to start over. Then stop.")


# ---------------------------------------------------------------------------
# このファイルだけで使う道具
# ---------------------------------------------------------------------------

def _python():
    """1.5 の <python>。"""
    if os.name == "nt":
        return "py -3" if shutil.which("py") else "python"
    return "python3" if shutil.which("python3") else "python"


def _cmd(sub, out):
    """1.5 の CMD(sub)。"""
    return "%s '%s' %s --out '%s'" % (_python(), helpers.REVDOC_PY, sub, os.path.abspath(str(out)))


def _lines(data):
    """UTF-8 のバイト列を、1.4 の数え方で行に分ける。行末の改行は、その行に含める（2.3 の 2）。"""
    parts = data.split(b"\n")
    return [p + b"\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _sha1(data):
    return hashlib.sha1(data).hexdigest()


def _init(out, src=None, pdf=None):
    r = helpers.revdoc("init", out, src=src, pdf=pdf)
    assert r.ok, r.data
    return helpers.read_plan(out)


# ---------------------------------------------------------------------------
# A-1：計画
# ---------------------------------------------------------------------------

def test_plan_of_small_input(tmp_path):
    """A-1：小さい入力の計画（対象のファイル、外したファイル、ユニット、モジュール、PDF、仕事の順番）が正解と同じになる（SR-16、SR-18、SR-19）。"""
    src = tmp_path / "src"
    wide = "".join(("int w%03d = 0; /*" % i).ljust(997) + "*/\n" for i in range(300))  # 1行が 1,000 バイト
    helpers.make_source_tree(src, {
        "main.c": 40,
        ".github/workflows/ci.c": 10,
        ".git/hooks/pre.c": 5,                      # 計画に載せない
        "drivers/report/log.c": 13000,              # 7つの範囲、7つのユニット、2つの部分
        "kernel/big.c": 4500,                       # 2,000 行ずつの範囲に分ける
        "kernel/task.c": 1500,                      # big.c の残りと足して、ちょうど 2,000 行
        "kernel/task.h": 600,
        "kernel/README.MD": "# memo\n",
        "kernel/blob.c": b"\x7fELF\x00\x01",
        "kernel/empty.c": b"",
        "kernel/u16.c": b"\xff\xfe" + "int a;\n".encode("utf-16-le"),
        "doc/readme.txt": "readme\n",
        "lib/edge.c": "/*".ljust(102397) + "*/\n",  # 改行を含めて 102,400 バイトの1行
        "lib/long.c": "/*".ljust(102398) + "*/\n",  # 102,401 バイトの1行
        "lib/timer.cpp": 80,
        "lib/timer.hpp": 30,
        "lib/wide.c": wide,                         # 102 行ずつの範囲に分ける（バイト数の上限）
    })
    try:
        os.symlink(str(src / "main.c"), str(src / "lib" / "link.c"))
        linked = True
    except (OSError, NotImplementedError):  # シンボリックリンクを作れない Windows の環境
        linked = False
    pdf_dir = tmp_path / "pdf"
    pdf = helpers.make_text_pdf(pdf_dir / "spec.pdf", pages=25)
    out = tmp_path / "out"

    plan = _init(out, src=src, pdf=pdf_dir)

    report = [("drivers/m-report", [("drivers/report/log.c", s, min(s + 1999, 13000))]) for s in range(1, 13001, 2000)]
    units = [
        ("_root", [("main.c", 1, 40)]),
        ("_github/workflows", [(".github/workflows/ci.c", 1, 10)]),
    ] + report + [
        ("kernel", [("kernel/big.c", 1, 2000)]),
        ("kernel", [("kernel/big.c", 2001, 4000)]),
        ("kernel", [("kernel/big.c", 4001, 4500), ("kernel/task.c", 1, 1500)]),
        ("kernel", [("kernel/task.h", 1, 600)]),
        ("lib", [("lib/edge.c", 1, 1)]),
        ("lib", [("lib/timer.cpp", 1, 80), ("lib/timer.hpp", 1, 30)]),
        ("lib", [("lib/wide.c", 1, 102)]),
        ("lib", [("lib/wide.c", 103, 204)]),
        ("lib", [("lib/wide.c", 205, 300)]),
    ]
    data = {}
    for _, ranges in units:
        for rel, _, _ in ranges:
            data[rel] = (src / rel).read_bytes()
    lines = {rel: _lines(b) for rel, b in data.items()}

    assert plan["version"] == 1
    assert plan["mode"] == "both"
    assert plan["none_sentence"] == "ソースコードと既存の設計書から読み取れる内容はない。"
    assert os.path.isabs(plan["src"]) and os.path.samefile(plan["src"], str(src))
    assert os.path.isabs(plan["pdf"]) and os.path.samefile(plan["pdf"], str(pdf_dir))

    assert plan["files"] == [{"path": rel, "sha1": _sha1(b), "lines": len(lines[rel]), "bytes": len(b),
                              "encoding": "utf-8"} for rel, b in data.items()]

    excluded = [
        {"path": "doc/readme.txt", "reason": "extension"},
        {"path": "kernel/README.MD", "reason": "extension"},
        {"path": "kernel/blob.c", "reason": "binary"},
        {"path": "kernel/empty.c", "reason": "empty"},
        {"path": "kernel/u16.c", "reason": "utf16"},
        {"path": "lib/long.c", "reason": "long_line"},
    ]
    if linked:
        excluded.append({"path": "lib/link.c", "reason": "symlink"})
    assert plan["excluded"] == sorted(excluded, key=lambda e: e["path"])

    expected_units = []
    for k, (module, ranges) in enumerate(units, 1):
        expected_units.append({
            "id": "U%04d" % k, "module": module,
            "lines": sum(e - s + 1 for _, s, e in ranges),
            "bytes": sum(len(x) for rel, s, e in ranges for x in lines[rel][s - 1:e]),
            "files": [{"path": rel, "start": s, "end": e} for rel, s, e in ranges],
        })
    assert plan["units"] == expected_units

    def ids(a, b):
        return ["U%04d" % k for k in range(a, b + 1)]

    def module(name, folder, rels, parts):
        return {"name": name, "folder": folder, "files": len(rels), "lines": sum(len(lines[r]) for r in rels),
                "parts": [{"name": n, "units": u, "fr_prefix": p} for n, u, p in parts]}

    expected_modules = [
        module("_root", "", ["main.c"], [("_root", ids(1, 1), "FR-ROOT-")]),
        module("_github/workflows", ".github/workflows", [".github/workflows/ci.c"],
               [("_github/workflows", ids(2, 2), "FR-GITHUB-WORKFLOWS-")]),
        module("drivers/m-report", "drivers/report", ["drivers/report/log.c"],
               [("drivers/m-report/1", ids(3, 7), "FR-DRIVERS-M-REPORT-P1-"),
                ("drivers/m-report/2", ids(8, 9), "FR-DRIVERS-M-REPORT-P2-")]),
        module("kernel", "kernel", ["kernel/big.c", "kernel/task.c", "kernel/task.h"],
               [("kernel", ids(10, 13), "FR-KERNEL-")]),
        module("lib", "lib", ["lib/edge.c", "lib/timer.cpp", "lib/timer.hpp", "lib/wide.c"],
               [("lib", ids(14, 18), "FR-LIB-")]),
    ]
    assert plan["modules"] == expected_modules

    assert len(plan["pdfs"]) == 1
    p = plan["pdfs"][0]
    assert {k: v for k, v in p.items() if k != "margins"} == {
        "id": "D01", "path": "spec.pdf", "name": "spec.pdf", "folder": "spec",
        "sha1": _sha1(pdf.read_bytes()), "pages": 25, "text_check": True}
    assert [{k: m[k] for k in ("key", "side", "text")} for m in p["margins"]] == [
        {"key": "SPEC-DOC-", "side": "top", "text": "SPEC-DOC-0001"},
        {"key": "", "side": "bottom", "text": "1"},
    ]
    assert all(isinstance(m["y"], int) and 0 <= m["y"] <= 10000 for m in p["margins"])

    kinds = [("analyze", u["id"]) for u in expected_units]
    kinds += [("convert", "D01:1-10"), ("convert", "D01:11-20"), ("convert", "D01:21-25")]
    kinds += [("write_module", part["name"]) for m in expected_modules for part in m["parts"]]
    kinds += [("write_overall", path) for path, _, _, _ in helpers.OVERALL_FILES]
    assert plan["jobs"] == [{"id": "J%05d" % k, "kind": kind, "target": t} for k, (kind, t) in enumerate(kinds, 1)]
    _assert_first_state(out, plan)

    # 2.9 名前の集まりと、2.4 のモジュールの一覧
    words = set()
    for rel, b in data.items():
        words.update(re.findall(r"[A-Za-z0-9_]+", b.decode("utf-8") + "\n" + rel))
    assert helpers.read_text(out / ".work" / "names.txt").splitlines() == sorted(words)
    assert helpers.read_text(out / ".work" / "modules.md").splitlines() == [
        "- %s（フォルダ：%s、%d ファイル、%d 行）" % (m["name"], m["folder"] or "直下", m["files"], m["lines"])
        for m in expected_modules]


@pytest.mark.parametrize("mode", ["source", "pdf"])
def test_plan_modes(tmp_path, mode):
    """A-1：ソースコードだけ、PDF だけのときの計画の形と、作業フォルダのファイルが決まりどおりになる（SR-01、SR-16、SR-25）。"""
    out = tmp_path / "out"
    work = out / ".work"
    if mode == "source":
        src = helpers.make_source_tree(tmp_path / "src")
        plan = _init(out, src=src)
        assert plan["pdf"] is None and plan["pdfs"] == []
        assert plan["none_sentence"] == "ソースコードから読み取れる内容はない。"
        expected = [("analyze", u["id"]) for u in plan["units"]]
        expected += [("write_module", p["name"]) for m in plan["modules"] for p in m["parts"]]
        expected += [("write_overall", path) for path, _, _, _ in helpers.OVERALL_FILES]
        assert [m["name"] for m in plan["modules"]] == ["_root", "kernel", "lib"]
        for name in ("plan.json", "state.json", "names.txt", "modules.md"):
            assert (work / name).is_file(), name
        assert (work / "templates").is_dir()
    else:
        pdf = helpers.make_text_pdf(tmp_path / "in" / "Spec One.pdf", pages=12)
        plan = _init(out, pdf=pdf)
        assert plan["src"] is None
        assert plan["none_sentence"] is None
        for key in ("files", "excluded", "units", "modules"):
            assert plan[key] == [], key
        assert [(p["id"], p["path"], p["name"], p["folder"], p["pages"]) for p in plan["pdfs"]] == [
            ("D01", "Spec One.pdf", "Spec One.pdf", "Spec_One", 12)]
        expected = [("convert", "D01:1-10"), ("convert", "D01:11-12")]
        for name in ("plan.json", "state.json"):
            assert (work / name).is_file(), name
        for name in ("names.txt", "modules.md", "src-utf8", "templates"):
            assert not (work / name).exists(), name
    assert plan["mode"] == mode
    assert plan["jobs"] == [{"id": "J%05d" % k, "kind": kind, "target": t} for k, (kind, t) in enumerate(expected, 1)]
    _assert_first_state(out, plan)


def _assert_first_state(out, plan):
    """3章の 3：最初の状態の中身。"""
    agents = {"analyze": "reverse:code-analyst", "convert": "reverse:pdf-converter",
              "write_module": "reverse:doc-writer", "write_overall": "reverse:doc-writer"}
    state = helpers.read_state(out)
    assert {k: state[k] for k in ("version", "stage", "round", "no_output", "next_job", "confirmed", "log")} == {
        "version": 1, "stage": plan["jobs"][0]["kind"], "round": 0, "no_output": 0,
        "next_job": len(plan["jobs"]) + 1, "confirmed": {}, "log": []}
    assert [j["id"] for j in state["jobs"]] == [j["id"] for j in plan["jobs"]]
    for job, planned in zip(state["jobs"], plan["jobs"]):
        kind, target, jid = planned["kind"], planned["target"], planned["id"]
        pages = None
        if kind == "analyze":
            outputs = [".work/memo/%s.md" % target]
        elif kind == "convert":
            pdf_id, _, span = target.partition(":")
            first, _, last = span.partition("-")
            pages = list(range(int(first), int(last) + 1))
            outputs = [".work/pdf/%s/%04d.md" % (pdf_id, p) for p in pages]
        elif kind == "write_module":
            outputs = ["docs/design/modules/%s.md" % target, "docs/requirements/3-1-functions/%s.md" % target,
                       ".work/unknowns/%s.md" % jid]
        else:
            outputs = ["docs/" + target, ".work/unknowns/%s.md" % jid]
        expected = dict(planned, stage=kind, agent=agents[kind], status="pending", tries=0,
                        outputs=sorted(outputs), reasons=[], substitute=[])
        if pages is not None:
            expected["pages"] = {str(p): {"prev": [], "mermaid": False} for p in pages}
        assert dict(job, outputs=sorted(job["outputs"])) == expected, job


def test_init_command_default_out(tmp_path):
    """A-1：コマンドとして --out を省いて init を呼ぶと、カレントフォルダの design-docs が出力先になり、do が次のコマンドの全文になる（SR-01、SR-04、SR-78）。"""
    src = helpers.make_source_tree(tmp_path / "src")
    r = helpers.run_cli(["init", "--src", src], cwd=tmp_path)
    out = tmp_path / "design-docs"
    assert r.ok and r.code == 0, r.data
    assert r.data["do"] == "Run: " + _cmd("next", out)
    assert (out / ".work" / "plan.json").is_file()


# ---------------------------------------------------------------------------
# 1.3 エラーの一覧と順番
# ---------------------------------------------------------------------------

ERROR_CASES = [
    ("bad_path", "bad_path"), ("no_input", "no_input"), ("src_and_pdf_missing", "src_not_found"),
    ("pdf_not_found", "pdf_not_found"), ("no_pdf_files", "no_pdf_files"), ("pdf_unreadable", "pdf_unreadable"),
    ("no_source_files", "no_source_files"), ("src_inside_out", "no_source_files"),
    ("src_is_out", "no_source_files"), ("next", "not_initialized"), ("check", "not_initialized"),
    ("serve", "not_initialized"), ("unknown_command", "bad_arguments"), ("unknown_option", "bad_arguments"),
    ("option_without_value", "bad_arguments"),
]


def _error_argv(tmp_path, case):
    good = helpers.make_source_tree(tmp_path / "src")
    docs_only = tmp_path / "docs-only"
    docs_only.mkdir()
    (docs_only / "readme.txt").write_text("readme\n", encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    bad_pdf = tmp_path / "bad-pdf"
    bad_pdf.mkdir()
    (bad_pdf / "bad.pdf").write_bytes(b"this is not a pdf\n")
    note = tmp_path / "note.txt"
    note.write_text("note\n", encoding="utf-8")
    out = tmp_path / "out"
    init = ["init", "--out", out]
    inside = helpers.make_source_tree(out / "src", {"a.c": 3})  # 出力先の中のファイルは外す（2.1 の表の順1）
    return {
        "bad_path": ["init", "--out", tmp_path / "o'ut"],                          # no_input より先
        "no_input": init,
        "src_and_pdf_missing": init + ["--src", tmp_path / "none", "--pdf", tmp_path / "none.pdf"],
        "pdf_not_found": init + ["--src", good, "--pdf", note],
        "no_pdf_files": init + ["--src", docs_only, "--pdf", empty],                # no_source_files より先
        "pdf_unreadable": init + ["--src", docs_only, "--pdf", bad_pdf],            # no_source_files より先
        "no_source_files": init + ["--src", docs_only],
        "src_inside_out": init + ["--src", inside],
        "src_is_out": ["init", "--out", inside, "--src", inside],
        "next": ["next", "--out", out],
        "check": ["check", "--out", out],
        "serve": ["serve", "--out", out],
        "unknown_command": ["frobnicate", "--out", out],
        "unknown_option": init + ["--src", good, "--bogus", "x"],
        "option_without_value": ["init", "--out"],
    }[case]


@pytest.mark.parametrize("case,error", ERROR_CASES, ids=[c for c, _ in ERROR_CASES])
def test_errors_and_order(tmp_path, case, error):
    """A-1：入力の誤りが、1.3 の表の順に確かめた最初のエラーになり、決まった形と do で返る（SR-02、SR-04、SR-78）。"""
    r = helpers.run_main(_error_argv(tmp_path, case))
    assert r.code == 1 and r.data["ok"] is False
    assert r.data["error"] == error
    assert isinstance(r.data["message"], str) and r.data["message"]
    assert r.data["do"] == GENERIC_DO
    if error == "pdf_unreadable":
        assert "bad.pdf" in r.data["message"]


def test_missing_packages(tmp_path, monkeypatch, revdoclib):
    """A-1：足りないパッケージがあると、init が missing_packages と、インストールのコマンドを持つ do を返す（SR-02、SR-03、SR-77）。"""
    assert revdoclib.packages.missing(True) == []  # テストの環境には、全部のパッケージがある
    calls = []

    def missing(need_pdf):
        calls.append(need_pdf)
        return ["mkdocs-material", "pypdfium2>=5", "Pillow"] if need_pdf else ["mkdocs-material"]

    monkeypatch.setattr(revdoclib.packages, "missing", missing)
    src = helpers.make_source_tree(tmp_path / "src")
    empty = tmp_path / "empty"
    empty.mkdir()  # PDF がないフォルダ。no_pdf_files より missing_packages が先
    for pdf, names in ((empty, ["mkdocs-material", "pypdfium2>=5", "Pillow"]), (None, ["mkdocs-material"])):
        before = len(calls)
        r = helpers.revdoc("init", tmp_path / "out", src=src, pdf=pdf)
        # 呼ぶ回数は決まっていない。呼んだことと、need_pdf が --pdf の有無に合うことを確かめる。
        assert calls[before:] and all(bool(c) == (pdf is not None) for c in calls[before:]), calls
        assert r.code == 1 and r.data["error"] == "missing_packages"
        assert r.data["packages"] == names
        assert r.data["do"] == (
            "Tell the user in Japanese that these Python packages are missing and that they should run this"
            " themselves: %s -m pip install %s. Then stop. Running the same skill command again starts the work."
            % (_python(), " ".join('"%s"' % n for n in names)))


def test_init_resume(tmp_path):
    """A-1：再開の init が、渡したままの仕事を pending に戻し、回数を変えず、no_output を 0 にする。入力の場所か、ソースコードと PDF の組み合わせが変わると input_changed になる（SR-13、SR-14）。"""
    src = helpers.make_source_tree(tmp_path / "src")
    out = tmp_path / "out"
    _init(out, src=src)
    plan_text = helpers.read_text(out / ".work" / "plan.json")
    first = helpers.revdoc("next", out)
    assert first.ok and first.data["jobs"]
    issued = {j["id"]: j["tries"] for j in helpers.jobs_with(out, status="issued")}
    again = helpers.revdoc("next", out)  # 出力がない回（4.6 の 1）
    assert again.data["jobs"] == first.data["jobs"]
    assert helpers.read_state(out)["no_output"] == 1

    r = helpers.revdoc("init", out, src=src)
    assert r.ok and r.data["do"] == "Run: " + _cmd("next", out)
    state = helpers.read_state(out)
    assert state["no_output"] == 0
    for job in state["jobs"]:
        if job["id"] in issued:
            assert job["status"] == "pending" and job["tries"] == issued[job["id"]], job
    assert helpers.read_text(out / ".work" / "plan.json") == plan_text

    moved = shutil.copytree(str(src), str(tmp_path / "src2"))
    r = helpers.revdoc("init", out, src=moved)
    assert r.code == 1 and r.data["error"] == "input_changed"
    assert r.data["do"] == INPUT_CHANGED_DO

    # 同じソースコードに PDF を足すと、mode が変わる（3章の 4）
    pdf = helpers.make_text_pdf(tmp_path / "pdf" / "spec.pdf", pages=1)
    r = helpers.revdoc("init", out, src=src, pdf=pdf)
    assert r.code == 1 and r.data["error"] == "input_changed" and r.data["do"] == INPUT_CHANGED_DO

    # 出力先の中のファイルは、先頭の BOM を外して読む（1.4）
    (out / ".work" / "plan.json").write_bytes(b"\xef\xbb\xbf" + (out / ".work" / "plan.json").read_bytes())
    assert helpers.revdoc("init", out, src=src).ok


# ---------------------------------------------------------------------------
# A-2：規模と時間
# ---------------------------------------------------------------------------

def test_scale_one_million_lines(tmp_path):
    """A-2：100 万行と 2,000 ページで、全部の仕事が上限以下、2回の計画が同じ、init と仕事 2,000 件の next が 30 秒以内（SR-18、SR-19、SR-80）。"""
    # 1,119 行のファイルを1つずつ持つフォルダが 894 個。解析 894、変換 200、執筆 894 と 12 で、仕事は 2,000 件になる。
    src = helpers.make_source_tree(tmp_path / "src", helpers.scaled_layout(1000000, lines_per_file=1119,
                                                                          files_per_folder=1))
    pdf_dir = tmp_path / "pdf"
    helpers.make_text_pdf(pdf_dir / "big.pdf", pages=2000)

    plans = []
    for name in ("out1", "out2"):
        start = time.monotonic()
        r = helpers.revdoc("init", tmp_path / name, src=src, pdf=pdf_dir, cli=True)
        took = time.monotonic() - start
        assert r.ok, r.data
        assert took <= 30, "init に %.1f 秒かかった" % took
        plans.append(helpers.read_plan(tmp_path / name))
    assert plans[0] == plans[1]
    plan = plans[0]

    assert len(plan["jobs"]) == 2000
    assert sum(f["lines"] for f in plan["files"]) == 1000000
    assert sum(u["lines"] for u in plan["units"]) == 1000000
    for u in plan["units"]:
        assert u["lines"] <= 2000 and u["bytes"] <= 102400, u["id"]
        assert u["lines"] == sum(f["end"] - f["start"] + 1 for f in u["files"]), u["id"]
    pages = []
    for job in plan["jobs"]:
        if job["kind"] == "convert":
            first, last = job["target"].split(":")[1].split("-")
            assert int(last) - int(first) + 1 <= 10, job
            pages += list(range(int(first), int(last) + 1))
    assert pages == list(range(1, 2001))
    for m in plan["modules"]:
        for part in m["parts"]:
            assert len(part["units"]) <= 5, part["name"]

    start = time.monotonic()
    r = helpers.revdoc("next", tmp_path / "out1", cli=True)
    took = time.monotonic() - start
    assert r.ok and r.data["state"] == "running" and r.data["jobs"], r.data
    assert took <= 30, "next に %.1f 秒かかった" % took


# ---------------------------------------------------------------------------
# A-10：名前と文字コード
# ---------------------------------------------------------------------------

def _case_sensitive(tmp_path):
    probe = tmp_path / "case-probe"
    (probe / "X").mkdir(parents=True)
    return not (probe / "x").exists()


def test_module_and_pdf_names(tmp_path):
    """A-10：report、Summary、Kernel と kernel などから、決まりどおりのモジュールの名前、要求の接頭辞、PDF のフォルダ名ができる（SR-79）。"""
    layout = {"tools/report/a.c": 10, "Summary/b.c": 10, "my lib/c.c": 10, "my_lib/d.c": 10,
              "a-b/e.c": 10, "a_b/f.c": 10}
    expected = [("m-Summary", "FR-M-SUMMARY-"), ("a-b", "FR-A-B-"), ("a_b", "FR-A-B-2-"),
                ("my_lib", "FR-MY-LIB-"), ("my_lib-2", "FR-MY-LIB-2-"), ("tools/m-report", "FR-TOOLS-M-REPORT-")]
    if _case_sensitive(tmp_path):  # 大文字と小文字だけが違うフォルダは、区別するファイルシステムでだけ作れる
        layout.update({"Kernel/g.c": 10, "kernel/h.c": 10})
        expected.insert(0, ("Kernel", "FR-KERNEL-"))
        expected.insert(4, ("kernel-2", "FR-KERNEL-2-"))
    src = helpers.make_source_tree(tmp_path / "src", layout)
    pdf_dir = tmp_path / "pdf"
    for rel in ("a/Kernel.pdf", "b/kernel.PDF", "c/report.pdf"):
        helpers.make_text_pdf(pdf_dir / rel, pages=1)

    plan = _init(tmp_path / "out", src=src, pdf=pdf_dir)

    assert [(m["name"], m["parts"][0]["fr_prefix"]) for m in plan["modules"]] == expected
    assert all([p["name"] for p in m["parts"]] == [m["name"]] for m in plan["modules"])
    assert [(p["id"], p["path"], p["name"], p["folder"]) for p in plan["pdfs"]] == [
        ("D01", "a/Kernel.pdf", "Kernel.pdf", "Kernel"),
        ("D02", "b/kernel.PDF", "kernel.PDF", "kernel-2"),
        ("D03", "c/report.pdf", "report.pdf", "m-report"),
    ]


def test_encodings_and_unread_files(tmp_path):
    """A-10：Shift_JIS と EUC-JP のファイルから UTF-8 のコピーができて指示のファイルがコピーを指し、2MB を超えるテキストと文字コードが分からないファイルが不明点の一覧に載り、2MB を超えるバイナリーは載らない（SR-16、SR-17、SR-66）。"""
    sjis_text = "/* 日本語のコメント */\r\nint sjis_func(int x)\r\n{\r\n    return x;\r\n}\r\n"
    euc_text = "/* 日本語のコメント */\nint euc_func(int x)\n{\n    return x;\n}\n"
    odd = b"int odd_value = 1; /* \x81\x20 */\n"  # UTF-8、EUC-JP、CP932 のどれでも読めない
    src = helpers.make_source_tree(tmp_path / "src", {
        "main.c": 40,
        "jp/sjis.c": sjis_text.encode("cp932"),
        "jp/euc.c": euc_text.encode("euc_jp"),
        "jp/odd.c": odd,
        "big/huge.c": b"/* pad */\n" * 209716,        # 2,097,160 バイトのテキスト
        "big/blob.c": b"\x00" + b"a" * 2100000,       # 2MB を超えるバイナリー
    })
    out = tmp_path / "out"

    # 解析の指示のファイルの「ソースファイルの表」は、コピーがあるファイルではコピーの絶対パスを指す（2.2、7.3）
    plan = _init(out, src=src)
    assert helpers.revdoc("next", out).ok
    unit = next(u for u in plan["units"] if u["module"] == "jp")
    job = next(j for j in plan["jobs"] if j["kind"] == "analyze" and j["target"] == unit["id"])
    text = helpers.read_text(out / ".work" / "jobs" / (job["id"] + ".md"))
    for f in unit["files"]:
        copy = os.path.join(os.path.abspath(str(out)), ".work", "src-utf8", *f["path"].split("/"))
        assert "| %s | %d-%d | %s |" % (copy, f["start"], f["end"], f["path"]) in text.splitlines(), f

    r = helpers.run_to_done(out, src=src)
    assert r.ok and r.data["state"] == "done", r.data

    plan = helpers.read_plan(out)
    assert {f["path"]: f["encoding"] for f in plan["files"]} == {
        "main.c": "utf-8", "jp/euc.c": "euc_jp", "jp/odd.c": "latin-1", "jp/sjis.c": "cp932"}
    assert plan["excluded"] == [{"path": "big/blob.c", "reason": "binary"},
                                {"path": "big/huge.c", "reason": "too_large"}]
    sjis = next(f for f in plan["files"] if f["path"] == "jp/sjis.c")
    assert sjis["sha1"] == _sha1(sjis_text.encode("cp932"))
    assert sjis["bytes"] == len(sjis_text.encode("utf-8")) and sjis["lines"] == 5

    copies = out / ".work" / "src-utf8"
    assert (copies / "jp" / "sjis.c").read_bytes() == sjis_text.encode("utf-8")  # 改行は元のまま
    assert (copies / "jp" / "euc.c").read_bytes() == euc_text.encode("utf-8")
    assert (copies / "jp" / "odd.c").read_bytes() == odd.decode("latin-1").encode("utf-8")
    assert not (copies / "main.c").exists()

    unknowns = helpers.read_text(out / "docs" / "review" / "unknowns.md")
    rows = unknowns.splitlines()
    assert "### 読めなかったソースファイル" in rows
    assert "- big/huge.c：2MB を超えるため、読んでいない。" in rows
    assert "- jp/odd.c：文字コードが分からない。ASCII のほかの文字は読めていない。" in rows
    assert "big/blob.c" not in unknowns


def test_encoding_guard_catches_open_without_encoding(tmp_path):
    """A-10：文字コードを指定しないファイルの読み書きを、テストの見張りが見つける（SR-78）。"""
    mod = tmp_path / "guarded_mod.py"
    mod.write_text(
        "def bad(path):\n"
        "    with open(path, 'w') as f:\n"
        "        f.write('x')\n"
        "\n"
        "def good(path):\n"
        "    with open(path, 'w', encoding='utf-8') as f:\n"
        "        f.write('x')\n", encoding="utf-8")
    namespace = runpy.run_path(str(mod))
    with helpers.EncodingGuard(roots=[tmp_path]) as guard:
        namespace["good"](str(tmp_path / "good.txt"))
    assert guard.found == []
    with helpers.EncodingGuard(roots=[tmp_path]) as guard:
        namespace["bad"](str(tmp_path / "bad.txt"))
    assert len(guard.found) == 1 and "guarded_mod.py:2" in guard.found[0]


# ---------------------------------------------------------------------------
# A-12：Python のバージョン
# ---------------------------------------------------------------------------

def test_python_too_old(tmp_path, monkeypatch):
    """A-12：3.9 未満のバージョンでは、revdoc.py が revdoclib を読み込まずに python_too_old を返す（SR-77、SR-78）。"""
    version = collections.namedtuple("version_info", "major minor micro releaselevel serial")
    out = tmp_path / "out"
    for name in list(sys.modules):
        if name == "revdoclib" or name.startswith("revdoclib."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    monkeypatch.setattr(sys, "argv", [str(helpers.REVDOC_PY), "init", "--out", str(out)])
    buf = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n", write_through=True)
    code = None
    real_version = sys.version_info
    sys.version_info = version(3, 8, 18, "final", 0)
    try:
        with contextlib.redirect_stdout(buf):
            runpy.run_path(str(helpers.REVDOC_PY), run_name="__main__")
    except SystemExit as e:
        code = e.code
    finally:
        sys.version_info = real_version
    data = helpers.parse_stdout(buf.buffer.getvalue().decode("utf-8"), code)
    assert data["error"] == "python_too_old"
    assert data["do"] == GENERIC_DO
    assert "revdoclib" not in sys.modules
    assert not out.exists()


# ---------------------------------------------------------------------------
# A-14：Windows のファイルの制限
# ---------------------------------------------------------------------------

def test_path_too_long(tmp_path, revdoclib):
    """A-14：パスの長さの判定に、Windows と長い出力先を渡すと path_too_long に当たる（要件 R-15。スクリプトの仕様 1.3、12章）。"""
    out = tmp_path / "out"
    plan = _init(out, src=helpers.make_source_tree(tmp_path / "src"))
    long_out = os.path.abspath(str(tmp_path / ("d" * 250)))
    assert revdoclib.plan.path_too_long(long_out, plan, True) is True
    assert revdoclib.plan.path_too_long(long_out, plan, False) is False
    assert revdoclib.plan.path_too_long(os.path.abspath(str(out)), plan, True) is False


def test_next_survives_permission_errors(tmp_path, monkeypatch):
    """A-14：ファイルの置き換えが2回 PermissionError を出しても、next が成功する（要件 R-15。スクリプトの仕様 1.4）。"""
    out = tmp_path / "out"
    _init(out, src=helpers.make_source_tree(tmp_path / "src"))
    real_replace = os.replace
    calls = []

    def flaky_replace(src, dst, *args, **kwargs):
        calls.append(str(dst))
        if len(calls) <= 2:
            raise PermissionError("別のプロセスが開いている")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", flaky_replace)
    r = helpers.revdoc("next", out)
    monkeypatch.undo()
    assert r.ok and r.data["state"] == "running" and r.data["jobs"], r.data
    assert len(calls) >= 3
    assert len(helpers.jobs_with(out, status="issued")) == len(r.data["jobs"])
    assert not (out / ".work" / "state.json.tmp").exists()
