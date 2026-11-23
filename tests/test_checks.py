"""出力の検査（A-8 のうち、スクリプトの仕様の5章と6章）と、PDF の読み取り（A-9）のテスト。

根拠は docs/script-spec.md の 2.5、2.6、5章、6章である。
検査のテストは、どれも次の順に進める。

1. 入力を作り、確かめる段階の仕事が渡されたところまで進める（helpers.run_to_done の stop_at）。
2. 渡された仕事に、代わりの関数（helpers.fake_agent）で合格する出力を書き、確かめる仕事の出力だけを、表の出力に書き換える。
3. next を呼び、state.json のその仕事の status と、reasons の rule を見る。
   合格なら done になる。不合格なら、回数が1増え、reasons に検査の名前が入る（4.5）。
"""
import hashlib
import os
import re
from pathlib import Path

import pytest

import helpers

# ---------------------------------------------------------------------------
# 入力
# ---------------------------------------------------------------------------

# kernel/task.c は 300 行。1〜7 行目と 300 行目に名前があり、間は注釈の行である。
TASK_C = "".join(line + "\n" for line in (
    ["/* kernel/task.c */",
     "#define TASK_MAX 16",
     "int task_count = 0;",
     "int ActivateTask(int id)",
     "{",
     "    return id + task_count;",
     "}"]
    + ["/* filler */"] * 292
    + ["int TerminateTask(void) { return TASK_MAX; }"]))
LAYOUT = {"kernel/task.c": TASK_C, "lib/timer.cpp": 20}

# mode が source のときの決まった1文（2.8）
NONE = "ソースコードから読み取れる内容はない。"


def _start(tmp_path, stage, src=True, pdf=None):
    """入力を作り、段階 stage の仕事を渡したところまで進め、渡した仕事に合格する出力を書いて、出力先を返す。"""
    out = tmp_path / "out"
    s = helpers.make_source_tree(tmp_path / "src", LAYOUT) if src else None
    r = helpers.run_to_done(out, src=s, pdf=pdf, stop_at=stage)
    assert r.ok and helpers.read_state(out)["stage"] == stage, r.data
    helpers.fake_agent(out)
    return out


def _issued(out, kind):
    """渡したままの、種類が kind の仕事を ID の順に返す。"""
    return helpers.jobs_with(out, status="issued", kind=kind)


def _job(out, job_id):
    return next(j for j in helpers.read_state(out)["jobs"] if j["id"] == job_id)


def _write(out, rel, text):
    with open(Path(out) / rel, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _edit(text, edits):
    """(元の文字列, 新しい文字列) の組を、順に1回ずつ置き換える。"""
    for old, new in edits:
        assert old in text, "置き換える文字列がない：%r" % old
        text = text.replace(old, new, 1)
    return text


def _next_and_assert(out, job_id, rule):
    """next を呼び、仕事が合格（rule が None）か、rule の検査で不合格かを確かめる。"""
    r = helpers.revdoc("next", out)
    assert r.ok, r.data
    job = _job(out, job_id)
    rules = {x["rule"] for x in job["reasons"]}
    if rule is None:
        assert job["status"] == "done", job
    else:
        assert job["status"] != "done" and job["tries"] == 1 and rule in rules, job
    return job


# ---------------------------------------------------------------------------
# 6.1 解析メモ
# ---------------------------------------------------------------------------

ROLE = "- [kernel/task.c:1-7] `ActivateTask` は、`task_count` を足した値を返す。"
IFACE = "- [kernel/task.c:300-300] `TerminateTask` は、`TASK_MAX` を返す。"
MEMO = ("# U0001\n\n## 役割\n" + ROLE + "\n\n## 公開インターフェース\n" + IFACE + "\n\n"
        + "".join("## %s\n- なし\n\n" % h for h in helpers.MEMO_HEADINGS[2:])).rstrip("\n") + "\n"

ANALYZE_CASES = [
    pytest.param([], None, id="ok"),
    pytest.param([(ROLE, "- [kernel/task.c:1-7] `TASK_*` を使う。")], None, id="prefix_star"),
    pytest.param([(ROLE, ROLE + "\n- [kernel/task.c:8-20] `task` の範囲の注釈である。")], None, id="path_word_in_range"),
    pytest.param([(ROLE, "- [kernel/task.c:1-7] `ActivateTask` は `timer` と別である。")], None, id="other_path_word"),
    pytest.param([(ROLE, "- [kernel/task.c:1-150] `ActivateTask` を定義する。")], None, id="range_150"),
    pytest.param([("## 分からなかったこと\n- なし\n", "")], "missing_heading", id="missing_heading"),
    pytest.param([("## データ構造\n- なし\n\n## 処理の流れ\n- なし",
                   "## 処理の流れ\n- なし\n\n## データ構造\n- なし")], "missing_heading", id="heading_order"),
    pytest.param([(ROLE, ROLE + "\n説明の文である。")], "bad_item", id="stray_line"),
    pytest.param([("## データ構造\n- なし\n", "## データ構造\n")], "bad_item", id="no_item"),
    pytest.param([("## データ構造\n- なし\n", "## データ構造\n- なし\n" + ROLE + "\n")], "bad_item", id="item_and_none"),
    pytest.param([(ROLE, ROLE + "\n- [kernel/task.c:301-301] `ActivateTask` を定義する。")], "bad_location",
                 id="beyond_file"),
    pytest.param([(ROLE, ROLE + "\n- [kernel/task.c:7-4] `ActivateTask` を定義する。")], "bad_location",
                 id="start_after_end"),
    pytest.param([(ROLE, "- [kernel/task.c:1-151] `ActivateTask` を定義する。")], "bad_location", id="range_151"),
    pytest.param([(ROLE, ROLE + "\n- [kernel/none.c:1-1] `ActivateTask` を定義する。")], "bad_location",
                 id="not_source_file"),
    pytest.param([(ROLE, "- [kernel/task.c:1-7] `ActivateTask` は `NoSuchName` を呼ぶ。")], "unknown_word",
                 id="unknown_word"),
    pytest.param([(ROLE, "- [kernel/task.c:1-7] `activatetask` を定義する。")], "unknown_word", id="case_sensitive"),
    pytest.param([(ROLE, ROLE + "\n- [kernel/task.c:8-20] `ActivateTask` を呼ぶ。")], "no_word_in_range",
                 id="no_word_in_range"),
    pytest.param([(IFACE, "- なし")], "uncovered_lines", id="uncovered_lines"),
    pytest.param([(ROLE, "\n".join([ROLE] * 200))], "too_long", id="too_long"),
]


@pytest.mark.parametrize("edits,rule", ANALYZE_CASES)
def test_analyze_checks(tmp_path, edits, rule):
    """A-8：解析メモの検査（6.1、5.3）が、合格する出力を通し、反する出力を不合格にする（SR-20、SR-21、SR-23、SR-52）。"""
    out = _start(tmp_path, "analyze")
    job = next(j for j in _issued(out, "analyze") if j["target"] == "U0001")
    _write(out, job["outputs"][0], _edit(MEMO, edits))
    _next_and_assert(out, job["id"], rule)


def test_too_long_memo_is_used_on_third_try(tmp_path):
    """A-6：行数だけが上限を超えた解析メモは、3回目にそのまま使われ、失敗にならない（SR-11。4.5 の例外）。"""
    out = _start(tmp_path, "analyze")
    job = next(j for j in _issued(out, "analyze") if j["target"] == "U0001")
    memo = _edit(MEMO, [(ROLE, "\n".join([ROLE] * 200))])  # 200 行を超えるが、ほかの検査には合格する
    for tries in (1, 2, 3):
        _write(out, job["outputs"][0], memo)
        assert helpers.revdoc("next", out).ok
        now = _job(out, job["id"])
        if tries < 3:
            assert now["status"] == "issued" and {x["rule"] for x in now["reasons"]} == {"too_long"}, now
    assert now["status"] == "done", now
    assert helpers.read_text(Path(out) / job["outputs"][0]) == memo


# ---------------------------------------------------------------------------
# 6.2 変換：形式の検査と Mermaid の検査（画像だけの PDF なので、文字列の検査はない）
# ---------------------------------------------------------------------------

PAGE = """## 2.5 タスク

タスクの状態を示す。

| 状態 | 説明 |
| --- | :---: |
| 実行<br>`RUNNING` | `a|b` と a\\|b |

![図 1](figure:0.1, 0.2, 0.9, 0.5)

図の説明：箱と線の図である。

`a__b` と `<div>` と a < b を書く。

```mermaid
stateDiagram-v2
    [*] --> s1
```
"""
FIG = "![図 1](figure:0.1, 0.2, 0.9, 0.5)"
ROW = "| 実行<br>`RUNNING` | `a|b` と a\\|b |"

CONVERT_CASES = [
    pytest.param([], None, id="ok"),
    pytest.param([(FIG, "![図 1](figure:0,0,1,1)")], None, id="figure_whole_page"),
    pytest.param([(ROW, ROW + "\n| a | b | c |")], "bad_table", id="table_cells"),
    pytest.param([("| --- | :---: |", "| --- | x |")], "bad_table", id="table_separator"),
    pytest.param([(ROW, ROW + "\n| a | b")], "bad_table", id="table_row_end"),
    pytest.param([("タスクの状態を示す。", "| a | b |")], "bad_table", id="table_one_line"),
    pytest.param([("タスクの状態を示す。", "<b>タスク</b>の状態を示す。")], "bad_tag", id="tag"),
    pytest.param([("タスクの状態を示す。", "タスク__状態を示す。")], "double_underscore", id="double_underscore"),
    pytest.param([(FIG, "![図 1](figure:0.9,0.2,0.1,0.5)")], "bad_figure", id="figure_x_order"),
    pytest.param([(FIG, "![図 1](figure:0.1,0.2,0.9,1.5)")], "bad_figure", id="figure_over_1"),
    pytest.param([(FIG, "![図 1](figure:0.1,0.2,0.9)")], "bad_figure", id="figure_three_values"),
    pytest.param([(FIG, "![図 1](figure:.1,0.2,0.9,0.5)")], "bad_figure", id="figure_value_form"),
    pytest.param([(FIG, "![](figure:0.1,0.2,0.9,0.5)")], "bad_figure", id="figure_empty_title"),
    pytest.param([("図の説明：箱と線の図である。", "箱と線の図である。")], "bad_figure", id="figure_no_description"),
    pytest.param([(FIG, FIG + "\n\n```mermaid\nflowchart LR\n    a --> b\n```")], "bad_figure",
                 id="figure_code_block_next"),
]


def _convert_start(tmp_path, pdf_maker, **kw):
    pdf = pdf_maker(tmp_path / "pdf" / "spec.pdf", **kw)
    out = _start(tmp_path, "convert", src=False, pdf=pdf)
    return out, _issued(out, "convert")[0]


@pytest.mark.parametrize("edits,rule", CONVERT_CASES)
def test_convert_format_checks(tmp_path, edits, rule):
    """A-8：変換の形式の検査（6.2）が、合格するページを通し、反するページを不合格にする（SR-27、SR-28、SR-31、SR-32）。"""
    out, job = _convert_start(tmp_path, helpers.make_image_pdf)
    _write(out, job["outputs"][0], _edit(PAGE, edits))
    _next_and_assert(out, job["id"], rule)


def _mermaid(*lines, **kw):
    close = kw.get("close", True)
    return "```mermaid\n" + "".join(line + "\n" for line in lines) + ("```\n" if close else "")


MERMAID_CASES = [
    # 合格する例（5.4 の例と、当たらないと書かれた行）
    pytest.param(_mermaid("stateDiagram-v2", '    state "休止状態 (SUSPENDED)" as s1', "    [*] --> s1",
                          "    s1 --> s2: 起動 (ActivateTask)", "    s2 --> [*]"), None, id="state_example"),
    pytest.param(_mermaid("flowchart LR", '    a["起動 (x)"] -->|"はい"| b{"条件"}', '    subgraph g1["カーネル"]',
                          '        b --> c(["終了"])', "    end"), None, id="flowchart_example"),
    pytest.param(_mermaid("%% 図", "flowchart LR", "    endpoint --> b"), None, id="comment_first_and_endpoint"),
    pytest.param(_mermaid("stateDiagram-v2", "    [*] --> s1", "    note right of s1: 文"), None, id="note_one_line"),
    pytest.param(_mermaid("stateDiagram-v2", "    s1 --> s2: a#59; b"), None, id="state_entity"),
    pytest.param(_mermaid("sequenceDiagram", "    participant A as 利用者", "    loop 毎周期",
                          "        A->>B: 起動する", "    end"), None, id="sequence"),
    # 不合格の例（番号ごと）
    pytest.param(_mermaid("flowchart LR", "    a --> b", close=False), "M1", id="M1"),
    pytest.param(_mermaid("graph LR", "    a --> b"), "M2", id="M2"),
    pytest.param(_mermaid("flowchart LR"), "M3", id="M3"),
    pytest.param(_mermaid("stateDiagram-v2", '    s1 --> s2: say "hi'), "M4", id="M4"),
    pytest.param(_mermaid("flowchart LR", "    a[起動] --> b"), "F1", id="F1"),
    pytest.param(_mermaid("flowchart LR", "    a[start] --> b"), "F2", id="F2"),
    pytest.param(_mermaid("flowchart LR", "    a -->|yes| b"), "F3", id="F3"),
    pytest.param(_mermaid("flowchart LR", "    a --> end"), "F4", id="F4_word"),
    pytest.param(_mermaid("flowchart LR", "    a --> b", "    end x"), "F4", id="F4_end_line"),
    pytest.param(_mermaid("stateDiagram-v2", "    休止 --> 実行"), "S1", id="S1"),
    pytest.param(_mermaid("stateDiagram-v2", "    [*] --> s1", "    note right of s1", "        日本語の注釈",
                          "    end note"), "S1", id="S1_note_block"),
    pytest.param(_mermaid("stateDiagram-v2", "    s1 --> s2: a; b"), "S2", id="S2"),
    pytest.param(_mermaid("sequenceDiagram", "    A->>B: a; b"), "Q1", id="Q1"),
    pytest.param(_mermaid("sequenceDiagram", "    利用者->>B: hello"), "Q2", id="Q2"),
]


@pytest.mark.parametrize("text,code", MERMAID_CASES)
def test_mermaid_checks(tmp_path, text, code):
    """A-8：Mermaid の検査（5.4）が、正しい図（`[*]` を含む状態遷移図など）を通し、番号ごとの決まりに反する図を不合格にする（SR-30、SR-32）。"""
    out, job = _convert_start(tmp_path, helpers.make_image_pdf)
    _write(out, job["outputs"][0], text)
    job = _next_and_assert(out, job["id"], None if code is None else "bad_mermaid")
    if code is not None:
        details = [x["detail"] for x in job["reasons"] if x["rule"] == "bad_mermaid"]
        assert any(d.startswith(code) for d in details), details


# ---------------------------------------------------------------------------
# 6.2 変換：文字列の検査
# ---------------------------------------------------------------------------

TEXTS = {1: "Alpha scheduler starts", 2: "Bravo timer stops", 3: "Charlie alarm rings"}

STRING_CASES = [
    pytest.param({}, None, id="ok"),
    pytest.param({1: "Alpha scheduler"}, "text_missing", id="missing"),
    pytest.param({1: "Alpha scheduler starts Zulu"}, "text_extra", id="extra"),
    pytest.param({1: "Alpha scheduler starts Bravo"}, None, id="extra_found_in_next_page"),
    pytest.param({1: "Alpha scheduler", 2: "starts\n\nBravo timer stops"}, None, id="missing_found_in_next_output"),
    pytest.param({1: "Ａｌｐｈａ scheduler starts"}, None, id="nfkc"),
    pytest.param({1: "Alpha scheduler starts\n\n" + _mermaid("flowchart LR", "    zulu --> yankee")
                  + "\n| Zulu | Yankee |\n| --- | --- |\n| Alpha | starts |\n\n図の説明：ズールーの説明。\n\n【判読できない】"},
                 None, id="excluded_parts"),
    pytest.param({1: "![Alpha](figure:0,0,1,0.5)\n\n図の説明：ズールーの図。"}, None, id="figure_range_not_missing"),
    pytest.param({1: "| Alpha | starts |\n| --- | --- |\n| Alpha | scheduler |\n\n"
                  "| Zulu | starts |\n| --- | --- |\n| Alpha | scheduler |"}, "text_extra", id="second_table_header"),
]


@pytest.mark.parametrize("pages,rule", STRING_CASES)
def test_convert_string_checks(tmp_path, pages, rule):
    """A-8：文字列の検査（6.2）が、前後1ページを含めて欠けと余分を見つけ、決まった部分を対象から外す（SR-33、SR-34）。"""
    out, job = _convert_start(tmp_path, helpers.make_text_pdf,
                              pages=[[(56, 120, TEXTS[n])] for n in (1, 2, 3)])
    assert helpers.read_plan(out)["pdfs"][0]["text_check"] is True
    for rel in job["outputs"]:
        n = int(Path(rel).stem)
        _write(out, rel, pages.get(n, TEXTS[n]) + "\n")
    _next_and_assert(out, job["id"], rule)


def test_convert_retry(tmp_path):
    """A-8：変換は不合格のページだけを渡し直し、余分の指摘に画像で確かめる文を書き、同じ指摘だけが残ったページは合格して一覧に載り、3回目には Mermaid に不合格だった図を画像にする指示を書く（SR-35、SR-36、SR-38）。"""
    out, job = _convert_start(tmp_path, helpers.make_text_pdf, pages=[[(56, 120, TEXTS[n])] for n in (1, 2, 3)])
    jid = job["id"]
    p1, p2, p3 = job["outputs"]
    extra = TEXTS[1] + " Zulu\n"                                            # p.1：余分「Zulu」
    bad_fig = TEXTS[2] + "\n\n" + _mermaid("flowchart LR", "    a -->|yes| b")  # p.2：F3 に当たる図
    instruction = Path(out) / ".work" / "jobs" / (jid + ".md")

    # 1回目：p.1 と p.2 だけが不合格になり、渡し直される
    _write(out, p1, extra)
    _write(out, p2, bad_fig)
    _write(out, p3, TEXTS[3] + "\n")
    job = _next_and_assert(out, jid, "text_extra")
    assert "bad_mermaid" in {x["rule"] for x in job["reasons"]} and job["outputs"] == [p1, p2], job
    text = helpers.read_text(instruction)
    line = next(x for x in text.splitlines() if x.startswith("- [text_extra] p.1："))
    assert "Zulu" in line and "ページの画像で確かめ、画像のとおりなら残す。" in line, line
    assert "[use_image]" not in text

    # 2回目：p.1 は前の回と同じ指摘だけなので合格する。p.2 は不合格のままで、3回目の指示に [use_image] が入る
    _write(out, p1, extra)
    _write(out, p2, bad_fig)
    assert helpers.revdoc("next", out).ok
    job = _job(out, jid)
    assert job["status"] == "issued" and job["tries"] == 2 and job["outputs"] == [p2], job
    assert re.search(r"^- \[use_image\] p\.2：", helpers.read_text(instruction), re.M)

    # 3回目：図を画像で載せると合格する
    _write(out, p2, TEXTS[2] + "\n\n![Bravo](figure:0.1,0.5,0.9,0.9)\n\n図の説明：箱と線の図である。\n")
    r = helpers.revdoc("next", out)
    assert r.ok and r.data["state"] == "done" and _job(out, jid)["status"] == "done", r.data
    log = helpers.read_state(out)["log"]
    assert {"type": "convert_diff", "pdf": "D01", "page": 1, "kind": "extra", "text": "Zulu"} in log, log
    assert {"type": "figure_switched", "pdf": "D01", "page": 2} in log, log
    assert "Alpha scheduler starts Zulu" in helpers.read_text(Path(out) / "docs" / "legacy" / "spec" / "001.md")
    unknowns = helpers.read_text(Path(out) / "docs" / "review" / "unknowns.md").split("\n")
    for heading, item in (("### 変換で残った違い", "- spec.pdf p.1：余分「Zulu」"), ("### 画像に切り替えた図", "- spec.pdf p.2")):
        rest = unknowns[unknowns.index(heading) + 1:]
        end = next((i for i, x in enumerate(rest) if x.startswith("#")), len(rest))
        assert [x for x in rest[:end] if x.strip()] == [item], unknowns


@pytest.mark.parametrize("maker,text_check,checks,rule", [
    pytest.param(helpers.make_text_pdf, True, [True, True, True], "text_extra", id="text"),
    pytest.param(lambda p: helpers.make_text_pdf(p, pages=[[(56, 120, TEXTS[1])], [], [(56, 120, TEXTS[3])]]),
                 True, [True, False, True], "text_extra", id="page_without_text"),
    pytest.param(helpers.make_image_pdf, False, [False, False], None, id="image_only"),
    pytest.param(helpers.make_unmapped_pdf, False, [False], None, id="unmapped"),
    # 対応づけられない文字の割合：3 / 45 前後は 5% を超え、1 / 102 前後は超えない
    pytest.param(lambda p: helpers.make_unmapped_pdf(p, text="ABC", mapped="B" * 40), False, [False], None,
                 id="unmapped_over_5_percent"),
    pytest.param(lambda p: helpers.make_unmapped_pdf(p, text="A", mapped="B" * 99), True, [True], "text_extra",
                 id="unmapped_under_5_percent"),
])
def test_text_check_decision(tmp_path, maker, text_check, checks, rule):
    """A-9：対応づけられない文字が 5% を超える PDF、画像だけの PDF、埋め込みテキストのないページは、文字列の検査を行わない（SR-37）。"""
    out, job = _convert_start(tmp_path, maker)
    assert helpers.read_plan(out)["pdfs"][0]["text_check"] is text_check
    outputs = sorted(job["outputs"])
    assert [helpers.read_json(Path(out) / (rel[:-3] + ".json"))["check"] for rel in outputs] == checks
    for rel in outputs:
        _write(out, rel, "Zulu yankee\n")
    _next_and_assert(out, job["id"], rule)


# ---------------------------------------------------------------------------
# A-9：ページの画像と埋め込みテキスト、ヘッダーとフッター
# ---------------------------------------------------------------------------

BODY = ["Body one", "Body two", "Body three"]


def _margin_pages(count):
    """上端の文書番号、本文と同じ行の左端の行番号、右寄せのページ番号を持つページのリスト。"""
    pages = []
    for p in range(1, count + 1):
        items = [(56, 40, "SPEC-DOC-0001")]
        for k, body in enumerate(BODY):
            items += [(20, 200 + 20 * k, str(k + 1)), (100, 200 + 20 * k, body)]
        num = str(p)
        items.append((helpers.A4[0] - 56 - len(num) * 6.2, helpers.A4[1] - 30, num))
        pages.append(items)
    return pages


def test_page_image_and_text(tmp_path):
    """A-9：変換の仕事を渡すと、ページの画像（150 dpi）、埋め込みテキスト、単位の JSON ができる（SR-24）。"""
    from PIL import Image

    out, job = _convert_start(tmp_path, helpers.make_text_pdf, pages=_margin_pages(4))
    folder = Path(out) / ".work" / "pdf" / "D01"
    for p in range(1, 5):
        with Image.open(str(folder / ("%04d.png" % p))) as img:
            w, h = img.size
        assert abs(w - 1241) <= 1 and abs(h - 1754) <= 1, (w, h)
        assert "Body one" in helpers.read_text(folder / ("%04d.txt" % p))
        info = helpers.read_json(folder / ("%04d.json" % p))
        assert info["page"] == p and info["check"] is True
        assert info["size"] == [pytest.approx(helpers.A4[0], abs=0.01), pytest.approx(helpers.A4[1], abs=0.01)]
        margin = {u["text"].strip(): u["margin"] for u in info["units"]}
        assert margin["SPEC-DOC-0001"] is True and margin["Body one"] is False and margin["1"] is True


def test_context_pages(tmp_path):
    """A-9：変換の仕事を渡すと、書くページの前後1ページの画像などもでき、指示のファイルに読むだけのページとして載る（SR-24、SR-25。6.2、7.3）。"""
    out, _ = _convert_start(tmp_path, helpers.make_text_pdf, pages=41)
    jobs = helpers.jobs_with(out, kind="convert")
    # 1回に渡すのは4件（1〜40 ページ）。41 ページは、4件目の後ろの、読むだけのページである。
    assert [(j["target"], j["status"]) for j in jobs] == [
        ("D01:1-10", "issued"), ("D01:11-20", "issued"), ("D01:21-30", "issued"), ("D01:31-40", "issued"),
        ("D01:41-41", "pending")]
    folder = os.path.join(os.path.abspath(str(out)), ".work", "pdf", "D01")
    for ext in ("png", "txt", "json"):
        assert os.path.isfile(os.path.join(folder, "0041." + ext)), ext

    def instruction(job):
        return helpers.read_text(Path(out) / ".work" / "jobs" / (job["id"] + ".md"))

    first, fourth = instruction(jobs[0]), instruction(jobs[3])
    assert "| ページ | 画像 |" in first.splitlines() and os.path.join(folder, "0011.png") in first
    assert os.path.join(folder, "0030.png") in fourth and os.path.join(folder, "0041.png") in fourth


@pytest.mark.parametrize("count,expected", [
    pytest.param(4, [("SPEC-DOC-", "top", "SPEC-DOC-0001"), ("", "bottom", "1"),
                     ("", "left", "1"), ("", "left", "2"), ("", "left", "3")], id="four_pages"),
    pytest.param(3, [], id="three_pages"),
])
def test_header_footer(tmp_path, count, expected):
    """A-9：ヘッダーとフッターの判定（2.6）が、右寄せのページ番号と本文と同じ行の行番号を見つけ、欠けの検査から外す（SR-34）。"""
    out, job = _convert_start(tmp_path, helpers.make_text_pdf, pages=_margin_pages(count))
    margins = helpers.read_plan(out)["pdfs"][0]["margins"]
    assert [(m["key"], m["side"], m["text"].strip()) for m in margins] == expected
    if expected:
        for rel in job["outputs"]:  # 本文だけを書いたページは、欠けの検査に合格する
            _write(out, rel, "\n\n".join(BODY) + "\n")
        _next_and_assert(out, job["id"], None)


# ---------------------------------------------------------------------------
# 6.3 照合
# ---------------------------------------------------------------------------

LEGACY_SENTENCE = "`ActivateTask` と `TASK_*` と `s1` を使う。"
RECORD = """## 1 食い違い
- 場所: [kernel/task.c:4-7]
- 名前: ActivateTask
- 既存の設計書: 上限は 1 である。
- ソースコード: 上限は 2 である。

## 2-3 既存設計書のみ
- モジュール: kernel
- 内容:

{fig}

{desc}

""" + LEGACY_SENTENCE + """

## 4 一致
- 場所: [kernel/task.c:1-300]

## 5-8 対象外
"""

MATCH_CASES = [
    pytest.param([], None, id="ok"),
    pytest.param([("- モジュール: kernel", "- モジュール: 全体")], None, id="module_overall"),
    pytest.param([("## 5-8 対象外", "## 5-8 不一致")], "bad_record", id="unknown_category"),
    pytest.param([("## 5-8 対象外", "## 5-8 照合していない")], "bad_record", id="script_only_category"),
    pytest.param([("## 1 食い違い", "前書き\n\n## 1 食い違い")], "bad_record", id="text_before_record"),
    pytest.param([("- 名前: ActivateTask\n", "")], "bad_record", id="missing_key"),
    pytest.param([("- 既存の設計書: 上限は 1 である。\n- ソースコード: 上限は 2 である。",
                   "- ソースコード: 上限は 2 である。\n- 既存の設計書: 上限は 1 である。")], "bad_record", id="key_order"),
    pytest.param([("- ソースコード: 上限は 2 である。", "- ソースコード:")], "bad_record", id="empty_value"),
    pytest.param([("- 場所: [kernel/task.c:4-7]", "- 場所:[kernel/task.c:4-7]")], "bad_record", id="key_without_space"),
    pytest.param([(LEGACY_SENTENCE, "### 見出し\n\n" + LEGACY_SENTENCE)], "bad_record", id="heading_in_content"),
    pytest.param([("- 内容:\n\n{fig}\n\n{desc}\n\n" + LEGACY_SENTENCE + "\n", "- 内容:\n")], "bad_record",
                 id="empty_content"),
    pytest.param([("- 場所: [kernel/task.c:1-300]\n", "- 場所: [kernel/task.c:1-300]\n余分な行\n")], "bad_record",
                 id="extra_line_in_match"),
    pytest.param([("## 4 一致", "## 4-6 一致"), ("## 5-8 対象外", "## 7-8 対象外")], "bad_record",
                 id="image_in_match"),
    pytest.param([("## 5-8 対象外", "## 5-7 対象外")], "bad_cover", id="gap"),
    pytest.param([("## 5-8 対象外", "## 4-8 対象外")], "bad_cover", id="overlap"),
    pytest.param([("[kernel/task.c:4-7]", "[kernel/none.c:4-7]")], "bad_location", id="location_file"),
    pytest.param([("[kernel/task.c:1-300]", "[kernel/task.c:1-301]")], "bad_location", id="location_beyond"),
    pytest.param([("[kernel/task.c:1-300]", "[kernel/task.c:1-7] [kernel/task.c:8-9]")], "bad_location",
                 id="two_locations"),
    pytest.param([("- 名前: ActivateTask", "- 名前: NoSuchFunc")], "unknown_word", id="name_not_in_file"),
    pytest.param([("- 名前: ActivateTask", "- 名前: （なし）")], "unknown_word", id="name_without_word"),
    pytest.param([("- モジュール: kernel", "- モジュール: nosuch")], "unknown_module", id="unknown_module"),
    pytest.param([(LEGACY_SENTENCE, LEGACY_SENTENCE + "\n\n" + _mermaid("flowchart LR", "    a -->|yes| b"))],
                 "bad_mermaid", id="legacy_mermaid"),
    pytest.param([("`TASK_*`", "`NoSuchName`")], "unknown_name", id="legacy_unknown_name"),
]


def _match_start(tmp_path):
    """ソースコードと画像だけの PDF（2ページ）で、照合の仕事を渡したところまで進める。"""
    pdf = helpers.make_image_pdf(tmp_path / "pdf" / "spec.pdf", pages=2)
    out = _start(tmp_path, "match", pdf=pdf)
    job = _issued(out, "match")[0]
    info = helpers.read_json(Path(out) / ".work" / "match" / (job["id"] + ".json"))
    text = {e["n"]: e["text"] for e in info["lines"]}
    # 代わりの関数の変換の出力は、ページごとに、表の行、図の行、図の説明、Mermaid の順になる。
    assert info["count"] == 8 and text[2].startswith("![") and text[4].startswith("```mermaid"), info
    return out, job, info, text


@pytest.mark.parametrize("edits,rule", MATCH_CASES)
def test_match_checks(tmp_path, edits, rule):
    """A-8：照合の記録の検査（6.3）が、合格する記録を通し、反する記録を不合格にする（SR-42、SR-44、SR-45、SR-65）。"""
    out, job, _, text = _match_start(tmp_path)
    record = _edit(RECORD, edits).replace("{fig}", text[2]).replace("{desc}", text[3])
    _write(out, job["outputs"][0], record)
    _next_and_assert(out, job["id"], rule)


def test_match_numbered_lines(tmp_path):
    """A-8：照合の番号を振った行（5.6）が、表の見出しの行とページの目印を含む形で書かれ、行ごとのページを持つ（SR-41）。"""
    out, job, info, text = _match_start(tmp_path)
    assert info["file"] == "docs/legacy/spec/001.md"
    assert [e["page"] for e in info["lines"]] == [1, 1, 1, 1, 2, 2, 2, 2]
    expected = ["# docs/legacy/spec/001.md"]
    for p in (1, 2):
        b = 4 * (p - 1)
        if p == 2:
            expected.append("<!-- page: 2 -->")
        expected += ["| 項目 | 値 |", "| --- | --- |", "[%d] | ページ | %d |" % (b + 1, p),
                     "[%d] %s" % (b + 2, text[b + 2]),
                     "[%d] 図の説明：ページ %d の箱と線の図である。" % (b + 3, p),
                     "[%d] ```mermaid" % (b + 4), "stateDiagram-v2", "    [*] --> s1", "    s1 --> [*]", "```"]
    lines_md = helpers.read_text(Path(out) / ".work" / "match" / (job["id"] + ".lines.md"))
    assert lines_md.rstrip("\n").split("\n") == expected


# ---------------------------------------------------------------------------
# 6.4 モジュールの執筆、5.5 行の検査、5.7 リンクの検査、5.8 名前の検査
# ---------------------------------------------------------------------------

D_ROLE = "- `ActivateTask` は、`task_count` を足した値を返す。"
D_IFACE = "- `TerminateTask` は、`TASK_MAX` を返す。"
D_PARA = "これは説明の段落である。"
D_ROW = "| `TASK_MAX` | `16` |"
D_BLOCK = "```mermaid\nstateDiagram-v2\n    [*] --> s1\n```"
D_DEP = "- `TerminateTask` を呼ぶ。"
DESIGN = ("# kernel\n\n## 役割\n\n" + D_ROLE + "\n\n## 公開インターフェース\n\n" + D_IFACE
          + "\n\n## データ構造\n\n" + D_PARA + "\n\n| 名前 | 値 |\n| --- | --- |\n" + D_ROW
          + "\n\n## 処理の流れ\n\n" + NONE + "\n\n## 状態\n\n" + D_BLOCK + "\n\n## 依存関係\n\n" + D_DEP + "\n"
          + "".join("\n## %s\n\n%s\n" % (h, NONE) for h in helpers.MODULE_HEADINGS[6:]))
REQ = ("# 3.1 機能（kernel）\n\n## 機能の要求\n\n"
       "- FR-KERNEL-001: `ActivateTask` は、`id` に `task_count` を足した値を返す。\n"
       "- FR-KERNEL-002: `TerminateTask` は、`TASK_MAX` を返す。\n")
DEP = "## 依存関係\n\n" + D_DEP + "\n"


def _add(line):
    """依存関係の節の最後に、行を1つ足す置き換え。"""
    return [(DEP, DEP + line + "\n")]


MODULE_CASES = [
    pytest.param("design", [], None, id="ok"),
    pytest.param("design", [("## 状態\n", "### 補足\n\n- `ActivateTask` を呼ぶ。\n\n## 状態\n")], None, id="extra_heading"),
    pytest.param("design", [(DEP, "## 依存関係\n\n### 呼び出し\n\n" + D_DEP + "\n")], None, id="body_under_sub_heading"),
    pytest.param("design", [("# kernel\n", "# カーネル\n")], "missing_heading", id="first_line"),
    pytest.param("design", [("## エラー処理\n\n%s\n\n" % NONE, "")], "missing_heading", id="missing_heading"),
    pytest.param("design", [("## エラー処理", "## X"), ("## 並行性とタイミング", "## エラー処理"),
                            ("## X", "## 並行性とタイミング")], "missing_heading", id="heading_order"),
    pytest.param("design", [(DEP, "## 依存関係\n")], "empty_section", id="empty_section"),
    pytest.param("design", _add("\n".join("- `ActivateTask` の項目 %d。" % k for k in range(1001))), "too_long",
                 id="too_long"),
    pytest.param("design", _add("- [要求](../../requirements/3-1-functions/kernel.md) と [一覧](../../review/unknowns.md)"
                                " と [全体](../architecture.md#依存関係) を見る。"), None, id="link_planned"),
    pytest.param("design", _add("- [外](https://example.com/x)、[節](#役割)、`[x](nosuch.md)` を見る。"), None,
                 id="link_not_checked"),
    pytest.param("design", _add("- [説明](nosuch.md) を見る。"), "broken_link", id="broken_link"),
    pytest.param("design", _add("- [説明]() を見る。"), "broken_link", id="broken_link_empty_path"),
    pytest.param("design", _add(_mermaid("flowchart LR", "    a -->|yes| b").rstrip("\n")), "bad_mermaid",
                 id="bad_mermaid"),
    pytest.param("design", [(DEP, "## 依存関係\n\n### `TASK_*`\n\n" + D_DEP + "\n")], None, id="prefix_star_heading"),
    pytest.param("design", _add("- `ActivateTask` は、おそらく `id` を返す。"), "speculation", id="speculation"),
    pytest.param("design", _add("```c\nint x; /* おそらく */\n```"), None, id="speculation_in_code_block"),
    pytest.param("design", _add("- `ActivateTask` は task.c:4 にある。"), "file_line", id="file_line"),
    pytest.param("design", _add("- E0001 の内容である。"), "file_line", id="record_number"),
    pytest.param("design", _add("- `E0001` の内容である。"), None, id="record_number_in_code_span"),
    pytest.param("design", _add("- 【既存設計書のみ】`ActivateTask` を呼ぶ。"), "bad_mark", id="legacy_mark"),
    pytest.param("design", _add("- 【既存の内容】を書く。"), "bad_mark", id="wrong_mark"),
    pytest.param("design", _add("- 【判読できない】の文字がある。"), None, id="unreadable_mark"),
    pytest.param("design", [(DEP, "## 依存関係\n\n### `ActivateTask`\n\n" + D_DEP + "\n")], None, id="name_in_heading"),
    pytest.param("design", [(DEP, "## 依存関係\n\n### `NoSuchName`\n\n" + D_DEP + "\n")], "unknown_name",
                 id="unknown_name_heading"),
    pytest.param("design", [("| 名前 | 値 |", "| `NoSuchName` | 値 |")], "unknown_name", id="unknown_name_table_header"),
    pytest.param("design", _add("- `NoSuchName` を呼ぶ。"), None, id="name_in_body_not_checked"),
    pytest.param("req", [("# 3.1 機能（kernel）", "# 3.1 機能")], "missing_heading", id="req_first_line"),
    pytest.param("req", [("## 機能の要求\n\n", "")], "missing_heading", id="req_missing_heading"),
    pytest.param("req", [(REQ[REQ.index("- FR"):], "")], "empty_section", id="req_empty_section"),
    pytest.param("req", [("FR-KERNEL-002", "FR-KERNEL-0002")], None, id="req_id_four_digits"),
    pytest.param("req", [("FR-KERNEL-002", "FR-LIB-002")], "bad_requirement_id", id="req_other_prefix"),
    pytest.param("req", [("FR-KERNEL-002", "FR-KERNEL-02")], "bad_requirement_id", id="req_two_digits"),
    pytest.param("req", [("FR-KERNEL-002", "FR-KERNEL-001")], "duplicate_id", id="req_duplicate_id"),
    pytest.param("unknowns", [("- なし\n", "説明の文である。\n")], "bad_item", id="unknowns_text"),
    pytest.param("unknowns", [("- なし\n", "")], "bad_item", id="unknowns_empty"),
]


def _module_files(job):
    """write_module の仕事の outputs を、design、req、unknowns の名前で返す。"""
    files = {}
    for rel in job["outputs"]:
        key = "design" if rel.startswith("docs/design/") else "req" if rel.startswith("docs/requirements/") else "unknowns"
        files[key] = rel
    assert files["design"] == "docs/design/modules/kernel.md", job
    return files


def _module_start(tmp_path, design=DESIGN):
    """モジュールの執筆の仕事を渡したところまで進め、kernel の仕事の3つの出力に design、REQ、`- なし` を書く。"""
    out = _start(tmp_path, "write_module")
    job = next(j for j in _issued(out, "write_module") if j["target"] == "kernel")
    files = _module_files(job)
    texts = {"design": design, "req": REQ, "unknowns": "- なし\n"}
    for key, rel in files.items():
        _write(out, rel, texts[key])
    return out, job, files, texts


@pytest.mark.parametrize("target,edits,rule", MODULE_CASES)
def test_write_module_checks(tmp_path, target, edits, rule):
    """A-8：執筆の出力の検査（6.4、5.4、5.5、5.7、5.8）が、合格する出力を通し、反する出力を不合格にする（SR-47、SR-48、SR-51、SR-52、SR-56、SR-57、SR-58、SR-65）。"""
    out, job, files, texts = _module_start(tmp_path)
    _write(out, files[target], _edit(texts[target], edits))
    _next_and_assert(out, job["id"], rule)


# ---------------------------------------------------------------------------
# 6.5 全体の執筆
# ---------------------------------------------------------------------------

ARCH_FIRST = "- `ActivateTask` を持つ。"
ARCH = "# 全体の内部設計書\n" + "".join(
    "\n%s\n\n%s\n" % (h, ARCH_FIRST if k == 0 else NONE) for k, h in enumerate(helpers.OVERALL_FILES[0][2]))
PERF_LINE = "- PR-001: `ActivateTask` は、`TASK_MAX` 回まで呼べる。"
PERF = "# 3.2 性能の要求\n\n" + PERF_LINE + "\n"

OVERALL_CASES = [
    pytest.param("design/architecture.md", [], None, id="arch_ok"),
    pytest.param("design/architecture.md", [("## 実行の構造\n\n%s\n" % NONE, "")], "missing_heading", id="arch_missing_heading"),
    pytest.param("design/architecture.md", [(ARCH_FIRST, "- PR-1: `ActivateTask` を持つ。")], None, id="arch_no_prefix"),
    pytest.param("requirements/3-2-performance.md", [], None, id="perf_ok"),
    pytest.param("requirements/3-2-performance.md", [("- PR-001:", "- FR-KERNEL-001:")], "bad_requirement_id",
                 id="perf_other_prefix"),
    pytest.param("requirements/3-2-performance.md", [(PERF_LINE, PERF_LINE + "\n" + PERF_LINE.replace("呼べる", "使える"))],
                 "duplicate_id", id="perf_duplicate_id"),
]


@pytest.mark.parametrize("target,edits,rule", OVERALL_CASES)
def test_write_overall_checks(tmp_path, target, edits, rule):
    """A-8：全体の執筆の検査（6.5）が、ファイルごとの必須の見出しと要求の接頭辞で合否を決める（SR-49、SR-50、SR-57）。"""
    out = _start(tmp_path, "write_overall")
    job = next(j for j in _issued(out, "write_overall") if j["target"] == target)
    base = ARCH if target == "design/architecture.md" else PERF
    for rel in job["outputs"]:
        _write(out, rel, _edit(base, edits) if rel == "docs/" + target else "- なし\n")
    _next_and_assert(out, job["id"], rule)


# ---------------------------------------------------------------------------
# 6.6 検証、5.6 番号を振った行
# ---------------------------------------------------------------------------

def _verify_start(tmp_path, design):
    """kernel の内部設計書に design を書いて、モジュールの検証の仕事を渡したところまで進める。
    kernel の内部設計書の検証の仕事を、ID の順に返す。"""
    out, _, files, _ = _module_start(tmp_path, design)
    r = helpers.revdoc("next", out)
    assert r.ok and helpers.read_state(out)["stage"] == "verify_module", r.data
    jobs = []
    for j in helpers.jobs_with(out, kind="verify"):
        info = helpers.read_json(Path(out) / ".work" / "verify" / (j["id"] + ".json"))
        if info["file"] == files["design"]:
            jobs.append((j, info))
    assert jobs, "kernel の内部設計書の検証の仕事がない"
    return out, jobs


VERIFY_CASES = [
    pytest.param("role", "[{n}] OK [kernel/task.c:1-7]", None, id="ok"),
    pytest.param("role", "[{n}] OK [kernel/task.c:4-4] [kernel/task.c:300-300]", None, id="ok_two_locations"),
    pytest.param("role", "[{n}] NG [kernel/task.c:1-7] - `ActivateTask` は、`id` を返す。", None, id="ng"),
    pytest.param("table", "[{n}] NG [kernel/task.c:2-2] | `TASK_MAX` | `16` 個 |", None, id="ng_table"),
    pytest.param("block", "[{n}] NG [kernel/task.c:1-7]", None, id="ng_code_block"),
    pytest.param("role", "[{n}] 不明 ActivateTask", None, id="unknown"),
    pytest.param("para", "[{n}] 対象外", None, id="not_fact"),
    pytest.param("role", None, "missing_verdict", id="missing_verdict"),
    pytest.param("role", "[{n}] たぶん正しい", "bad_verdict", id="bad_form"),
    pytest.param("role", "[{n}] OK [kernel/task.c:1-7] 余分な文", "bad_verdict", id="ok_with_text"),
    pytest.param("role", "[{n}] OK [kernel/task.c:1-7] ", "bad_verdict", id="ok_with_space"),
    pytest.param("role", "[{n}] OK [kernel/task.c:1-7]\n[{n}] OK [kernel/task.c:1-7]", "bad_verdict", id="duplicate"),
    pytest.param("role", "[{n}] 対象外", "bad_verdict", id="not_fact_with_code_span"),
    pytest.param("block", "[{n}] 対象外", "bad_verdict", id="not_fact_code_block"),
    pytest.param("role", "[{n}] 不明", "bad_verdict", id="unknown_without_words"),
    pytest.param("role", "[{n}] NG [kernel/task.c:1-7]", "bad_verdict", id="ng_without_text"),
    pytest.param("role", "[{n}] NG [kernel/task.c:1-7] " + D_ROLE, "bad_verdict", id="ng_same_text"),
    pytest.param("role", "[{n}] OK [kernel/task.c:1-151]", "bad_location", id="range_151"),
    pytest.param("role", "[{n}] OK [kernel/none.c:1-1]", "bad_location", id="not_source_file"),
    pytest.param("role", "[{n}] OK [lib/timer.cpp:1-5]", "unknown_word", id="unknown_word"),
    pytest.param("role", "[{n}] OK [kernel/task.c:8-20]", "no_word_in_range", id="no_word_in_range"),
    pytest.param("role", "[{n}] NG [kernel/task.c:1-7] - `NoSuchName` を返す。", "unknown_word", id="ng_unknown_word"),
    pytest.param("role", "[{n}] NG [kernel/task.c:1-7] `ActivateTask` は、`id` を返す。", "bad_shape", id="shape_item"),
    pytest.param("table", "[{n}] NG [kernel/task.c:2-2] | `TASK_MAX` |", "bad_shape", id="shape_table"),
    pytest.param("para", "[{n}] NG [kernel/task.c:1-7] - これは箇条書きである。", "bad_shape", id="shape_paragraph"),
    pytest.param("role", "[{n}] NG [kernel/task.c:1-7] - `ActivateTask` は、おそらく `id` を返す。", "speculation",
                 id="ng_speculation"),
    pytest.param("role", "[{n}] NG [kernel/task.c:1-7] - `ActivateTask` は task.c:4 にある。", "file_line",
                 id="ng_file_line"),
    pytest.param("role", "[{n}] NG [kernel/task.c:1-7] - 【既存設計書のみ】`ActivateTask` を返す。", "bad_mark",
                 id="ng_mark"),
]

V_TEXT = {"role": D_ROLE, "para": D_PARA, "table": D_ROW, "block": D_BLOCK}


@pytest.mark.parametrize("target,verdict,rule", VERIFY_CASES)
def test_verify_checks(tmp_path, target, verdict, rule):
    """A-8：判定の記録の検査（6.6）が、番号ごとに、合格する判定を通し、反する判定を不合格にする（SR-60、SR-61）。"""
    out, jobs = _verify_start(tmp_path, DESIGN)
    job, info = jobs[0]
    helpers.fake_agent(out)
    n = next(e["n"] for e in info["lines"] if e["text"] == V_TEXT[target])
    rel = job["outputs"][0]
    lines = [line for line in helpers.read_text(Path(out) / rel).split("\n")
             if line and not line.startswith("[%d] " % n)]
    if verdict is not None:
        lines.append(verdict.replace("{n}", str(n)))
    _write(out, rel, "\n".join(lines) + "\n")
    r = helpers.revdoc("next", out)
    assert r.ok, r.data
    done = _job(out, job["id"])
    assert done["status"] == "done", done
    rules = {x["rule"] for x in done["reasons"] if x.get("n") == n}
    assert (not rules) if rule is None else (rule in rules), done["reasons"]


def _sha1(headings, text):
    return hashlib.sha1("\n".join(headings + [text]).encode("utf-8")).hexdigest()


def test_verify_numbered_lines(tmp_path):
    """A-8：検証の番号を振った行（5.6）が、節の見出し、表の見出しの行、コードブロックを決まった形で持ち、行の SHA-1 を持つ（SR-59）。"""
    out, jobs = _verify_start(tmp_path, DESIGN)
    assert len(jobs) == 1
    job, info = jobs[0]
    file_lines = DESIGN.split("\n")
    rows = [("## 役割", D_ROLE), ("## 公開インターフェース", D_IFACE), ("## データ構造", D_PARA),
            ("## データ構造", D_ROW), ("## 状態", D_BLOCK), ("## 依存関係", D_DEP)]
    expected = [{"n": n, "line": file_lines.index(text.split("\n")[0]) + 1, "text": text,
                 "sha1": _sha1(["# kernel", h], text)} for n, (h, text) in enumerate(rows, 1)]
    assert info == {"file": "docs/design/modules/kernel.md", "count": 6, "lines": expected}
    lines_md = helpers.read_text(Path(out) / ".work" / "verify" / (job["id"] + ".lines.md"))
    assert lines_md.rstrip("\n").split("\n") == [
        "# docs/design/modules/kernel.md",
        "## 役割", "[1] " + D_ROLE,
        "## 公開インターフェース", "[2] " + D_IFACE,
        "## データ構造", "[3] " + D_PARA, "| 名前 | 値 |", "| --- | --- |", "[4] " + D_ROW,
        "## 処理の流れ", NONE, "## 状態", "[5] " + D_BLOCK.split("\n")[0]] + D_BLOCK.split("\n")[1:] + [
        "## 依存関係", "[6] " + D_DEP]


def test_verify_split(tmp_path):
    """A-8：対象の行が 30、25、115、15 行の節は、5.6 の分け方で 30、25、50、50、30 行の5つの仕事になり、全部の行に番号が振られる（SR-59）。"""
    sizes = [30, 25, 115, 15]
    lines = ["# kernel"]
    targets = []
    k = 0
    for i, h in enumerate(helpers.MODULE_HEADINGS):
        lines += ["", "## " + h, ""]
        if i < len(sizes):
            for _ in range(sizes[i]):
                k += 1
                lines.append("- `ActivateTask` の項目 %d。" % k)
                targets.append(len(lines))
        else:
            lines.append(NONE)
    out, jobs = _verify_start(tmp_path, "\n".join(lines) + "\n")
    assert [info["count"] for _, info in jobs] == [30, 25, 50, 50, 30]
    assert [e["line"] for _, info in jobs for e in info["lines"]] == targets
