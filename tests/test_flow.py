"""進め方のテスト。

確かめる受入条件は A-3（通し）、A-4（next の出力）、A-5（指示のファイル）、A-6（不合格）、A-7（中断と再開）である。
根拠は、スクリプトの仕様（docs/script-spec.md）の4章（next）、7章（指示のファイル）、8.7（仕上げ）、12章（テストの入口）である。
"""
import json
import os
import re
import shutil
from pathlib import Path

import pytest

import helpers

LAST_LINE = "最後の返事は done の1語だけにする。"
NO_FILE_LINE = "前回は、出力のファイルがなかった。"
JOBS_DO = ("Start one foreground subagent per job in a single message: type = the job's agent,"
           " prompt = \"Read the file OUT/FILE and follow it.\" (OUT: the --out folder below,"
           " FILE: the job's file). When all of them have returned, run: ")
NO_OUTPUT_DO = ("Tell the user in Japanese that the subagents wrote no files and that they should check that"
                " subagents can write files in the output folder. Then stop. Running the same skill command"
                " again resumes the work.")
INPUT_CHANGED_DO = ("Tell the user in Japanese what the message says and that they can either restore the input"
                    " and run the same skill command again, or choose a new output folder to start over. Then stop.")
# 4.2 の段階の順と、担当エージェント
STAGES = ["analyze", "convert", "match", "write_module", "verify_module", "write_overall", "verify_overall"]
AGENTS = {"analyze": "reverse:code-analyst", "convert": "reverse:pdf-converter", "match": "reverse:doc-matcher",
          "write_module": "reverse:doc-writer", "verify_module": "reverse:doc-verifier",
          "write_overall": "reverse:doc-writer", "verify_overall": "reverse:doc-verifier"}


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


def _abs(out, rel):
    """出力先からの相対パス（/ 区切り）を、OS の書き方の絶対パスにする。"""
    return os.path.join(os.path.abspath(str(out)), *rel.split("/"))


def _job(out, job_id):
    return next(j for j in helpers.read_state(out)["jobs"] if j["id"] == job_id)


def _lines(out, rel):
    return helpers.read_text(Path(out) / rel).splitlines()


def _drive(out, **agent):
    """next と代わりの関数を、done かエラーまで繰り返す。最後の結果と、渡された仕事の ID の並びを返す。"""
    ids = []
    for _ in range(3000):
        r = helpers.revdoc("next", out)
        if not r.ok or r.data["state"] == "done":
            return r, ids
        ids += [j["id"] for j in helpers.jobs_with(out, status="issued")]
        helpers.fake_agent(out, **agent)
    raise AssertionError("next を 3,000 回呼んでも done にならない")


def _short_out(factory):
    """A-4 の前提：出力先と revdoc.py の絶対パスが、JSON に書いた長さでそれぞれ 100 バイト以下である。"""
    out = factory.mktemp("o") / "d"
    for p in (out, helpers.REVDOC_PY):
        assert len(json.dumps(os.path.abspath(str(p)))) - 2 <= 100, "テストの前提に合わない長いパス：%s" % p
    return out


def _check_passed(out, failed_jobs):
    r = helpers.revdoc("check", out)
    assert r.ok and r.data["passed"] is True and r.data["problem_count"] == 0, r.data
    assert r.data["failed_jobs"] == failed_jobs


def _check_job_file(out, plan, job):
    """渡した仕事の指示のファイルを確かめ、中身を返す（SR-08、SR-09。7.1、7.3）。"""
    path = Path(out) / ".work" / "jobs" / (job["id"] + ".md")
    assert path.stat().st_size <= 20480, "%s が 20KB を超える" % path.name
    text = helpers.read_text(path)
    assert text.splitlines()[-1] == LAST_LINE
    assert "{{" not in text
    for rel in job["outputs"]:
        assert _abs(out, rel) in text, "書く先 %s が指示のファイルにない" % rel
        assert os.path.isdir(os.path.dirname(_abs(out, rel))), "書く先の親フォルダがない：%s" % rel
        assert not os.path.exists(_abs(out, rel)), "書く先のファイルが残っている：%s" % rel
    if job["kind"] == "analyze":
        unit = next(u for u in plan["units"] if u["id"] == job["target"])
        listing = Path(out) / ".work" / "jobs" / (job["id"] + ".files.md")
        if listing.exists():
            n = len(helpers.read_text(listing).splitlines())
            assert "読むファイルの一覧は、%s（%d 行）にある。" % (_abs(out, ".work/jobs/%s.files.md" % job["id"]), n) in text
            assert "一覧の全部のファイルを読む。" in text
        else:
            for r in unit["files"]:
                row = "| %s | %d-%d | %s |" % (os.path.join(plan["src"], *r["path"].split("/")),
                                              r["start"], r["end"], r["path"])
                assert row in text, "ソースファイルの表の行がない：%s" % row
    return text


def _bad_memo(unit, count):
    """根拠の場所が全部ファイルの外を指す解析メモ（不合格の理由が count 個より多くなる）。"""
    rel = unit["files"][0]["path"]
    lines = ["# " + unit["id"], "", "## " + helpers.MEMO_HEADINGS[0]]
    lines += ["- [%s:%d-%d] 範囲がファイルの外を指す。" % (rel, 900 + k, 900 + k) for k in range(count)]
    for h in helpers.MEMO_HEADINGS[1:]:
        lines += ["", "## " + h, "- なし"]
    return "".join(line + "\n" for line in lines)


# ---------------------------------------------------------------------------
# A-3：通し
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["both", "source", "pdf"])
def test_full_run(tmp_path, mode):
    """A-3：3つの場合で done まで進み、check に合格し、出力先の形が決まりどおりで、mkdocs build が成功し、入力とほかのフォルダが変わらない（SR-07、SR-15、SR-69、SR-72、P-01、P-02）。"""
    src = pdf_dir = None
    if mode != "pdf":
        src = helpers.make_source_tree(tmp_path / "src", dict(helpers.DEFAULT_LAYOUT, **{"doc/readme.txt": "readme\n"}))
    if mode != "source":
        pdf_dir = tmp_path / "pdf"
        helpers.make_text_pdf(pdf_dir / "spec.pdf", pages=3)
        helpers.make_image_pdf(pdf_dir / "scan.pdf", pages=2)
    inputs = [p for p in (src, pdf_dir) if p is not None]
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    out = tmp_path / "out"
    before = [helpers.tree_hashes(p) for p in inputs]
    plugin_before = helpers.tree_hashes(helpers.REPO / "plugin")

    # ソースコードだけの場合は、コマンドとして動かす
    r = helpers.run_to_done(out, src=src, pdf=pdf_dir, cli=(mode == "source"), cwd=cwd)
    assert r.ok and r.data["state"] == "done", r.data
    _check_passed(out, 0)

    shape = {  # 8.7 の mode ごとの docs/ の形
        "docs/index.md": True, "docs/review/unknowns.md": True, "mkdocs.yml": True,
        "docs/requirements": mode != "pdf", "docs/design": mode != "pdf",
        "docs/legacy/spec": mode != "source", "docs/legacy/scan": mode != "source",
        "docs/review/discrepancies.md": mode == "both",
    }
    assert {rel: (out / rel).exists() for rel in shape} == shape
    if mode != "pdf":  # 代わりの関数が書いた Foo::bar の形の名前が、設計書に残る
        spans = [s for f in sorted((out / "docs" / "design").rglob("*.md"))
                 for line in helpers.read_text(f).splitlines() for s in helpers.code_spans(line)]
        assert any("::" in s for s in spans)

    b = helpers.mkdocs_build(out)
    assert b.returncode == 0, b.stderr.decode("utf-8", "replace")
    assert [helpers.tree_hashes(p) for p in inputs] == before
    assert helpers.tree_hashes(helpers.REPO / "plugin") == plugin_before
    assert list(cwd.iterdir()) == []


# ---------------------------------------------------------------------------
# A-4：next の出力
# ---------------------------------------------------------------------------

def test_next_output(tmp_path_factory):
    """A-4：短いパスの入力で、next の出力が毎回 1,000 バイト以下で、jobs が4件以下の決まった項目を持ち、段階の順、ID の順に渡される（SR-04、SR-05、SR-06）。"""
    base = tmp_path_factory.mktemp("a4")
    src = helpers.make_source_tree(base / "src")
    pdf = helpers.make_text_pdf(base / "pdf" / "spec.pdf", pages=3)
    out = _short_out(tmp_path_factory)
    assert helpers.revdoc("init", out, src=src, pdf=pdf).ok
    stages, ids = [], []
    for _ in range(3000):
        r = helpers.revdoc("next", out)
        assert r.ok, r.data
        assert len(r.stdout.rstrip("\n")) <= 1000, "next の出力が 1,000 バイトを超える：%d" % len(r.stdout)
        if r.data["state"] == "done":
            break
        state = helpers.read_state(out)
        issued = [j for j in state["jobs"] if j["status"] == "issued"]
        assert r.data["state"] == "running"
        assert 1 <= len(r.data["jobs"]) <= 4
        assert r.data["jobs"] == [{"agent": AGENTS[state["stage"]], "file": ".work/jobs/%s.md" % j["id"]}
                                  for j in issued]
        assert all(j["stage"] == state["stage"] for j in issued)
        assert r.data["do"] == JOBS_DO + _cmd("next", out)
        if not stages or stages[-1] != state["stage"]:
            stages.append(state["stage"])
        ids += [j["id"] for j in issued]
        helpers.fake_agent(out)
    assert stages == STAGES
    assert ids == sorted(set(ids))
    done = {"ok": True, "state": "done", "jobs": [], "do": "All jobs are finished. Run: " + _cmd("serve", out)}
    assert r.data == done
    assert helpers.revdoc("next", out).data == done


# ---------------------------------------------------------------------------
# A-5：指示のファイル
# ---------------------------------------------------------------------------

def _drive_instructions(out, src, pdf):
    """init から done まで進め、next ごとの .work/jobs/ の中身を返す。範囲が多い仕事には、1回目に悪い解析メモを書く。"""
    assert helpers.revdoc("init", out, src=src, pdf=pdf).ok
    plan = helpers.read_plan(out)
    many = next(u for u in plan["units"] if len(u["files"]) >= 400)
    many_job = next(j["id"] for j in plan["jobs"] if j["kind"] == "analyze" and j["target"] == many["id"])
    snaps = []
    rounds = 0
    for _ in range(3000):
        r = helpers.revdoc("next", out)
        assert r.ok, r.data
        if r.data["state"] == "done":
            break
        issued = helpers.jobs_with(out, status="issued")
        for job in issued:
            text = _check_job_file(out, plan, job)
            if job["id"] != many_job:
                continue
            rounds += 1
            assert (out / ".work" / "jobs" / (many_job + ".files.md")).is_file()  # 表が 20KB を超えるので、別のファイルになる
            if rounds == 2:  # 不合格の理由が 50 個を超える渡し直し
                total = len(job["reasons"])
                assert total > 50
                section = text.split("## 前回の不合格の理由", 1)[1]
                assert len(re.findall(r"^- \[[a-z_]+\] ", section, re.M)) == 50
                assert "- ほか %d 件" % (total - 50) in section
        snaps.append({p.name: helpers.read_text(p) for p in sorted((out / ".work" / "jobs").iterdir())})
        if rounds == 1 and any(j["id"] == many_job for j in issued):
            with open(_abs(out, ".work/memo/%s.md" % many["id"]), "w", encoding="utf-8", newline="\n") as f:
                f.write(_bad_memo(many, 60))
            helpers.fake_agent(out, skip=(many_job,))
        else:
            helpers.fake_agent(out)
    assert rounds == 2
    return snaps


def test_instruction_files(tmp_path_factory):
    """A-5：範囲が多い仕事と理由が 50 個を超える渡し直しを含めて、指示のファイルが 20KB 以下で、書く先の親フォルダがあり、書く先がなく、2回動かすと同じ内容になる（SR-08、SR-09、SR-19）。"""
    base = tmp_path_factory.mktemp("a5")
    layout = {"many/f%03d.c" % i: 5 for i in range(400)}  # 1つのユニットに 400 個の範囲
    layout.update({"lib/timer.cpp": 80, "lib/timer.hpp": 30})
    src = helpers.make_source_tree(base / "src", layout)
    pdf = helpers.make_text_pdf(base / "pdf" / "spec.pdf", pages=3)
    out = _short_out(tmp_path_factory)
    first = _drive_instructions(out, src, pdf)
    shutil.rmtree(str(out))
    assert _drive_instructions(out, src, pdf) == first


# ---------------------------------------------------------------------------
# A-6：不合格
# ---------------------------------------------------------------------------

def test_rejected_output_is_retried_then_failed(tmp_path):
    """A-6：悪い出力は、理由を指示のファイルに足して渡し直され、3回目で失敗になって先へ進み、不明点の一覧に載る（SR-10、SR-11、SR-66）。"""
    src = helpers.make_source_tree(tmp_path / "src")
    out = tmp_path / "out"
    assert helpers.revdoc("init", out, src=src).ok
    assert helpers.revdoc("next", out).ok
    memo = ".work/memo/U0001.md"
    for tries in (1, 2):
        helpers.fake_agent(out, bad=("J00001",))
        r = helpers.revdoc("next", out)
        assert r.ok and r.data["jobs"] == [{"agent": "reverse:code-analyst", "file": ".work/jobs/J00001.md"}], r.data
        job = _job(out, "J00001")
        assert job["status"] == "issued" and job["tries"] == tries and job["outputs"] == [memo]
        assert "bad_location" in [x["rule"] for x in job["reasons"]]
        rejected = out / ".work" / "rejected" / ("J00001-%d" % tries)
        assert (rejected / ".work" / "memo" / "U0001.md").is_file()
        text = helpers.read_text(out / ".work" / "jobs" / "J00001.md")
        assert "## 前回の不合格の理由" in text
        assert ("前回の出力は `%s` にある。不合格の項目だけを直し、ほかは前回のまま書く。"
                % os.path.abspath(str(rejected))) in text
        assert re.search(r"^- \[bad_location\] \.work/memo/U0001\.md [0-9]+ 行目：", text, re.M)
        assert text.splitlines()[-1] == LAST_LINE

    helpers.fake_agent(out, bad=("J00001",))
    r = helpers.revdoc("next", out)
    assert r.ok and r.data["state"] == "running"
    job = _job(out, "J00001")
    assert job["status"] == "failed" and job["tries"] == 3 and job["substitute"] == []
    assert (out / memo).is_file()  # 3回目に書かれたファイルは残す
    assert helpers.read_state(out)["stage"] == "write_module"

    module_job = helpers.jobs_with(out, kind="write_module")[0]["id"]
    r = helpers.run_to_done(out, src=src, bad=(module_job,))
    assert r.ok and r.data["state"] == "done", r.data
    assert _job(out, module_job)["status"] == "failed"
    _check_passed(out, 2)
    unknowns = _lines(out, "docs/review/unknowns.md")
    failed = unknowns[unknowns.index("### 失敗した仕事") + 1:]
    assert failed[0].startswith("- 解析：U0001：[bad_location] ")
    assert failed[1].startswith("- 執筆（モジュール）：_root：[")
    index = _lines(out, "docs/index.md")
    assert "| 失敗した仕事（解析） | 1 |" in index
    assert "| 失敗した仕事（執筆（モジュール）） | 1 |" in index


# ---------------------------------------------------------------------------
# A-7：中断と再開
# ---------------------------------------------------------------------------

def test_no_output_round(tmp_path):
    """A-7：全部の仕事に出力がない回は同じ仕事が回数を変えずに返り、2回続くと no_output で止まって回数が1増える（SR-12）。"""
    src = helpers.make_source_tree(tmp_path / "src")
    out = tmp_path / "out"
    assert helpers.revdoc("init", out, src=src).ok
    first = helpers.revdoc("next", out)
    files = [j["file"] for j in first.data["jobs"]]
    texts = [helpers.read_text(out / f) for f in files]

    assert helpers.revdoc("next", out).data == first.data
    assert [helpers.read_text(out / f) for f in files] == texts
    issued = helpers.jobs_with(out, status="issued")
    assert len(issued) == len(files) and all(j["tries"] == 0 for j in issued)

    stop = helpers.revdoc("next", out)
    assert stop.code == 1 and stop.data["error"] == "no_output" and stop.data["do"] == NO_OUTPUT_DO
    assert helpers.read_state(out)["no_output"] == 0
    for job in issued:
        after = _job(out, job["id"])
        assert after["status"] == "pending" and after["tries"] == 1
        assert [(x["rule"], x["file"], x["line"]) for x in after["reasons"]] == [
            ("missing_file", rel, None) for rel in job["outputs"]]

    assert helpers.revdoc("next", out).data == first.data
    assert all(NO_FILE_LINE in helpers.read_text(out / f) for f in files)
    helpers.fake_agent(out)
    assert helpers.revdoc("next", out).ok
    assert all(_job(out, j["id"])["status"] == "done" for j in issued)


def test_one_job_without_output_fails_alone(tmp_path):
    """A-7：1件だけ出力がない回が3回続くとその仕事だけが失敗になり、代わりのファイルが置かれる。検証の仕事は失敗にならない（SR-10、SR-11、SR-12）。"""
    src = helpers.make_source_tree(tmp_path / "src", {"m%02d/a.c" % i: 20 for i in range(10)})
    out = tmp_path / "out"
    assert helpers.revdoc("init", out, src=src).ok
    assert helpers.revdoc("next", out).ok
    for tries in (1, 2, 3):
        helpers.fake_agent(out, skip=("J00002",))
        assert helpers.revdoc("next", out).ok
        job = _job(out, "J00002")
        assert job["tries"] == tries and [x["rule"] for x in job["reasons"]] == ["missing_file"]
        if tries < 3:
            assert job["status"] == "issued"
            assert NO_FILE_LINE in helpers.read_text(out / ".work" / "jobs" / "J00002.md")
    assert job["status"] == "failed" and job["substitute"] == [".work/memo/U0002.md"]
    assert [j["id"] for j in helpers.jobs_with(out, kind="analyze") if j["status"] != "done"] == ["J00002"]
    assert _lines(out, ".work/memo/U0002.md") == [
        "# U0002", "", "解析できなかった。ソースコードを直接読む。", "", "- m01/a.c（1-20 行）"]

    r = helpers.run_to_done(out, src=src, stop_at="verify_module")
    assert r.ok, r.data
    verify = helpers.jobs_with(out, status="issued")
    assert len(verify) > 1 and all(j["kind"] == "verify" for j in verify)
    helpers.fake_agent(out, skip=(verify[0]["id"],))
    assert helpers.revdoc("next", out).ok
    v = _job(out, verify[0]["id"])
    assert v["status"] == "done" and v["tries"] == 0

    r = helpers.run_to_done(out, src=src)
    assert r.ok and r.data["state"] == "done", r.data
    assert [j["id"] for j in helpers.read_state(out)["jobs"] if j["status"] == "failed"] == ["J00002"]
    _check_passed(out, 1)
    assert any(line.startswith("- 解析：U0002：[missing_file] ") for line in _lines(out, "docs/review/unknowns.md"))


def test_single_job_round_stops_three_times(tmp_path):
    """A-7：仕事が1件だけの回で出力がないと、全部に出力がない回として扱われ、no_output で3回目に止まるときに失敗になり、呼び直すと先へ進む（SR-11、SR-12）。"""
    pdf = helpers.make_text_pdf(tmp_path / "pdf" / "spec.pdf", pages=3)
    out = tmp_path / "out"
    assert helpers.revdoc("init", out, pdf=pdf).ok
    for tries in (1, 2, 3):
        first = helpers.revdoc("next", out)
        assert first.ok and first.data["jobs"] == [{"agent": "reverse:pdf-converter", "file": ".work/jobs/J00001.md"}]
        assert helpers.revdoc("next", out).data == first.data
        stop = helpers.revdoc("next", out)
        assert stop.code == 1 and stop.data["error"] == "no_output" and stop.data["do"] == NO_OUTPUT_DO
        assert _job(out, "J00001")["tries"] == tries
    job = _job(out, "J00001")
    pages = [".work/pdf/D01/%04d.md" % n for n in (1, 2, 3)]
    assert job["status"] == "failed" and sorted(job["substitute"]) == pages
    for n, rel in enumerate(pages, 1):
        assert _lines(out, rel) == ["## 変換できなかったページ", "", "![ページ %d](figure:0,0,1,1)" % n, "",
                                    "図の説明：このページは変換できなかった。ページの全体を画像で載せる。"]

    r = helpers.revdoc("next", out)
    assert r.ok and r.data["state"] == "done", r.data
    _check_passed(out, 1)
    assert any(line.startswith("- 変換：spec.pdf p.1、2、3：[missing_file] ")
               for line in _lines(out, "docs/review/unknowns.md"))


def test_resume(tmp_path):
    """A-7：再開すると終わった仕事は渡されず、状態の一時ファイルが残っていても前の状態から続く。入力を変えると input_changed で止まり、外したファイルを足しても続く（SR-13、SR-14）。"""
    src = helpers.make_source_tree(tmp_path / "src")
    pdf_dir = tmp_path / "pdf"
    pdf = helpers.make_text_pdf(pdf_dir / "spec.pdf", pages=3)
    out = tmp_path / "out"
    r = helpers.run_to_done(out, src=src, pdf=pdf_dir, stop_at="write_module")
    assert r.ok, r.data
    state = helpers.read_state(out)
    finished = {j["id"]: j["tries"] for j in state["jobs"] if j["status"] in ("done", "failed")}
    issued = [j["id"] for j in state["jobs"] if j["status"] == "issued"]
    assert finished and issued

    # 書きかけの一時ファイル（全部の仕事が最初に戻った状態）を残す
    stale = dict(state, stage="analyze", jobs=[dict(j, status="pending", tries=0) for j in state["jobs"]])
    with open(_abs(out, ".work/state.json.tmp"), "w", encoding="utf-8") as f:
        json.dump(stale, f, ensure_ascii=False)
    (src / "kernel" / "notes.txt").write_text("memo\n", encoding="utf-8")  # 外したファイルを足す

    # ソースファイルと PDF を変えると止まる。戻すと続けられる
    for path, changed, name in ((src / "kernel" / "task.c", None, "kernel/task.c"), (pdf, 4, "spec.pdf")):
        original = path.read_bytes()
        if changed is None:
            path.write_bytes(original + b"int task_extra = 0;\n")
        else:
            helpers.make_text_pdf(path, pages=changed)
        r = helpers.revdoc("init", out, src=src, pdf=pdf_dir)
        assert r.code == 1 and r.data["error"] == "input_changed" and r.data["do"] == INPUT_CHANGED_DO
        assert name in r.data["message"]
        path.write_bytes(original)

    assert helpers.revdoc("init", out, src=src, pdf=pdf_dir).ok
    assert helpers.read_state(out)["stage"] == "write_module"
    r, ids = _drive(out)
    assert r.ok and r.data["state"] == "done", r.data
    assert ids[:len(issued)] == issued
    assert not set(ids) & set(finished)
    assert {j["id"]: j["tries"] for j in helpers.read_state(out)["jobs"] if j["id"] in finished} == finished


def test_input_changed_before_finish(tmp_path):
    """A-7：仕上げの前に入力を変えると、不明点の一覧の「作業中に変わった入力」と入口のページの件数に載る（SR-14、SR-66、SR-67）。"""
    src = helpers.make_source_tree(tmp_path / "src")
    out = tmp_path / "out"
    r = helpers.run_to_done(out, src=src, stop_at="verify_overall")
    assert r.ok, r.data
    with open(str(src / "kernel" / "task.c"), "ab") as f:
        f.write(b"int task_extra = 0;\n")
    helpers.fake_agent(out)
    r, _ = _drive(out)
    assert r.ok and r.data["state"] == "done", r.data
    unknowns = _lines(out, "docs/review/unknowns.md")
    assert unknowns[unknowns.index("### 作業中に変わった入力") + 1] == "- kernel/task.c"
    assert "| 作業中に変わった入力 | 1 |" in _lines(out, "docs/index.md")


def _verdict(e):
    """kernel の内部設計書の最初の番号の行を「不明」にする。ほかは既定の判定。"""
    return "不明" if e["file"] == "docs/design/modules/kernel.md" and e["n"] == 1 else None


@pytest.fixture(scope="module")
def uninterrupted(tmp_path_factory):
    """止めなかったときの docs/ を作る。入力は、止める側のテストと同じものを使う。"""
    base = tmp_path_factory.mktemp("a7")
    src = helpers.make_source_tree(base / "src")
    pdf = helpers.make_text_pdf(base / "pdf" / "spec.pdf", pages=3)
    out = base / "out"
    r = helpers.run_to_done(out, src=src, pdf=pdf, verdict=_verdict)
    assert r.ok and r.data["state"] == "done", r.data
    # 2つの場面（記録を入れる回、不明の判定がある回）が起きていることを確かめておく
    assert "## 既存の設計書にだけ書かれている内容" in _lines(out, "docs/design/modules/_root.md")
    assert any(x["type"] == "verify_unknown" and x["file"] == "docs/design/modules/kernel.md"
               for x in helpers.read_state(out)["log"])
    return src, pdf, helpers.tree_hashes(out / "docs")


@pytest.mark.parametrize("resume", ["next", "init"])
@pytest.mark.parametrize("stage", ["write_module", "verify_module"])
def test_interrupted_replace(tmp_path, monkeypatch, uninterrupted, stage, resume):
    """A-7：設計書の置き換えで例外を起こして next を止め、next か init から呼び直すと、止めなかったときと同じ設計書と不明点の一覧になる（SR-13。1.4、8.4、8.5）。"""
    src, pdf, expected = uninterrupted
    out = tmp_path / "out"
    r = helpers.run_to_done(out, src=src, pdf=pdf, stop_at=stage, verdict=_verdict)
    assert r.ok and helpers.read_state(out)["stage"] == stage, r.data
    helpers.fake_agent(out, verdict=_verdict)

    docs = os.path.abspath(str(out / "docs")) + os.sep
    real_replace = os.replace
    stopped = []

    def failing_replace(a, b, *args, **kwargs):
        if os.path.abspath(str(b)).startswith(docs):
            stopped.append(str(b))
            raise OSError("テストで起こした置き換えの失敗")
        return real_replace(a, b, *args, **kwargs)

    monkeypatch.setattr(os, "replace", failing_replace)
    r = helpers.revdoc("next", out)
    monkeypatch.undo()
    assert stopped, "設計書の書き換えが os.replace を通っていない（1.4）"
    assert r.code == 1 and r.data["error"] == "internal_error", r.data

    if resume == "init":
        assert helpers.revdoc("init", out, src=src, pdf=pdf).ok
    r, _ = _drive(out, verdict=_verdict)
    assert r.ok and r.data["state"] == "done", r.data
    assert helpers.tree_hashes(out / "docs") == expected
