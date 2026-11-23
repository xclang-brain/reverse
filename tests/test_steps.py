"""スクリプトだけの処理（A-8 のうち、スクリプトの仕様の8章〜10章）のテスト。

根拠は docs/script-spec.md の 8章（組み立て、振り分け、差し込み、検証の繰り返し、要約、仕上げ）、9章（check）、
10章（mkdocs.yml）である。
テストは、どれも次の順に進める。

1. 入力を作り、確かめる処理の前の段階まで、代わりの関数（helpers.fake_agent）で進める。
2. 確かめる処理に渡る出力だけを、テストの中で書く。
3. next を呼んで処理を進め、出力先のファイルと state.json を見る。
"""
import hashlib
import posixpath
import re
from pathlib import Path

import pytest

import helpers

# ---------------------------------------------------------------------------
# 入力と、共通の値
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

# 決まった1文（2.8）
NONE_SOURCE = "ソースコードから読み取れる内容はない。"
NONE_BOTH = "ソースコードと既存の設計書から読み取れる内容はない。"

KERNEL = "docs/design/modules/kernel.md"
LEGACY_HEADING = "## 既存の設計書にだけ書かれている内容"
MARK = "【既存設計書のみ】"
MARK_FIG = MARK + "次の図は、既存の設計書の内容である。"
MARK_TABLE = MARK + "次の表は、既存の設計書の内容である。"

# 内部設計書の行（kernel/task.c の名前を使う）
D_ROLE = "- `ActivateTask` は、`task_count` を足した値を返す。"
D_IFACE = "- `TerminateTask` は、`TASK_MAX` を返す。"
D_PARA = "これは説明の段落である。"
D_ROW = "| `TASK_MAX` | `16` |"
D_BLOCK = "```mermaid\nstateDiagram-v2\n    [*] --> s1\n```"
SAME = "- `ActivateTask` を呼ぶ。"
REQ = "# 3.1 機能（kernel）\n\n## 機能の要求\n\n- FR-KERNEL-001: `ActivateTask` は、`task_count` を足した値を返す。\n"

# mkdocs.yml の nav のほかの部分（10章）
MKDOCS_COMMON = {
    "docs_dir": "docs",
    "site_dir": "site",
    "theme": {"name": "material", "language": "ja", "font": False, "features": ["navigation.prune"]},
    "plugins": [{"search": {"lang": "ja"}}, {"privacy": {"cache_dir": ".work/privacy"}}],
    "markdown_extensions": ["tables", {"pymdownx.superfences": {"custom_fences": [
        {"name": "mermaid", "class": "mermaid",
         "format": "!!python/name:pymdownx.superfences.fence_code_format"}]}}],
}


# ---------------------------------------------------------------------------
# このファイルの道具
# ---------------------------------------------------------------------------

def _write(out, rel, text):
    with open(Path(out) / rel, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _file_lines(path):
    """ファイルを 1.4 の数え方で行に分ける（最後の \\n の後ろの空の行は数えない）。"""
    lines = helpers.read_text(path).split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _nonempty(lines):
    return [line for line in lines if line.strip()]


def _items(lines, heading):
    """heading の行の次から、次の見出し（# で始まる行）の前までの、空でない行を返す。"""
    i = lines.index(heading)
    found = []
    for line in lines[i + 1:]:
        if line.startswith("#"):
            break
        if line.strip():
            found.append(line)
    return found


def _between(lines, start, end=None):
    """start の行と end の行（省くとファイルの最後）の間の、空でない行を返す。"""
    i = lines.index(start) + 1
    j = lines.index(end) if end is not None else len(lines)
    return _nonempty(lines[i:j])


def _after_legacy(lines):
    """「既存の設計書にだけ書かれている内容」の見出しから後ろの、空でない行を返す。"""
    return _between(lines, LEGACY_HEADING)


def _sha1(headings, text):
    """8.5 の行の SHA-1（見出しの並びと行の文を \\n でつないだもの）。"""
    return hashlib.sha1("\n".join(headings + [text]).encode("utf-8")).hexdigest()


def _job(out, job_id):
    return next(j for j in helpers.read_state(out)["jobs"] if j["id"] == job_id)


def _start(tmp_path, stage, layout=None, src=True, pdf=None):
    """入力を作り、段階 stage の仕事を渡したところまで代わりの関数で進めて、出力先を返す。"""
    out = tmp_path / "out"
    s = helpers.make_source_tree(tmp_path / "src", layout or LAYOUT) if src else None
    r = helpers.run_to_done(out, src=s, pdf=pdf, stop_at=stage)
    assert r.ok and helpers.read_state(out)["stage"] == stage, r.data
    return out


def _drive(out, until=None, skip=None, bad=None, verdict=None):
    """init を呼ばずに、next と代わりの関数を繰り返す。done か、段階 until に入ったところで返す。

    skip と bad は、仕事（state.json の項目）を受け取り、当たるかを返す関数。no_output のエラーは、続けて呼ぶ。
    """
    for _ in range(500):
        r = helpers.revdoc("next", out)
        if not r.ok:
            assert r.data["error"] == "no_output", r.data
            continue
        if r.data["state"] == "done" or helpers.read_state(out)["stage"] == until:
            return r
        issued = helpers.jobs_with(out, status="issued")
        helpers.fake_agent(out, skip=[j["id"] for j in issued if skip and skip(j)],
                           bad=[j["id"] for j in issued if bad and bad(j)], verdict=verdict)
    raise AssertionError("next を 500 回呼んでも終わらない")


def _design(sections, none=NONE_SOURCE):
    """kernel の内部設計書を作る。sections は {見出し: [行, …]}。ない見出しには決まった1文を書く。"""
    lines = ["# kernel"]
    for h in helpers.MODULE_HEADINGS:
        lines += ["", "## " + h, ""] + (sections.get(h) or [none])
    return "\n".join(lines) + "\n"


def _module_start(tmp_path, design):
    """ソースコードだけの入力で、モジュールの執筆の仕事を渡したところまで進め、kernel の出力に design を書く。"""
    out = _start(tmp_path, "write_module")
    helpers.fake_agent(out)
    job = next(j for j in helpers.jobs_with(out, status="issued", kind="write_module") if j["target"] == "kernel")
    for rel in job["outputs"]:
        _write(out, rel, design if rel == KERNEL else REQ if rel.startswith("docs/requirements/") else "- なし\n")
    return out


def _verify_jobs(out, rel):
    """設計書 rel の検証の仕事と、その番号を振った行の JSON の組を、ID の順に返す。"""
    found = []
    for j in helpers.jobs_with(out, kind="verify"):
        info = helpers.read_json(Path(out) / ".work" / "verify" / (j["id"] + ".json"))
        if info["file"] == rel:
            found.append((j, info))
    return found


def _check(out):
    r = helpers.revdoc("check", out)
    assert r.ok, r.data
    return r.data


def _load_mkdocs(out):
    """mkdocs.yml を読む。!!python/name: のタグは、そのままの文字列にする。"""
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("tag:yaml.org,2002:python/name:",
                                 lambda loader, suffix, node: "!!python/name:" + suffix)
    with open(Path(out) / "mkdocs.yml", "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=Loader)


def _nav(data, label):
    """nav の、ラベルが label の項目の中身を返す。"""
    return next(item[label] for item in data["nav"] if label in item)


def _link_targets(lines):
    """docs/index.md の行のリンク先（5.7 のパス）を、# から後ろを除き、docs/ からの相対パスにして返す。"""
    found = []
    for line in lines:
        for m in re.finditer(r"\]\(([^)\s]+)", line):
            path = m.group(1).split("#", 1)[0]
            if path and not re.match(r"(https?|mailto):", path):
                found.append(posixpath.normpath(path))
    return found


def _links_under(targets, folder):
    """リンク先のどれかが、docs/ の folder の中（folder そのものを含む）にあるか。"""
    return any(t == folder or t.startswith(folder + "/") for t in targets)


# ---------------------------------------------------------------------------
# 8.1 既存の設計書の組み立て
# ---------------------------------------------------------------------------

PAGE1 = """# ２．５ タスク

## 2.5.9 起動

#### 3. 手順

### 2 概要

## 1.2.3.4.5.6.7 深い

## 2.5x 番号でない

本文の行である。

![図 A](figure:0.1,0.2,0.5,0.6)

図の説明：箱の図である。

![図 B](figure:0, 0.9, 0.3, 1)

図の説明：線の図である。
"""
PAGE2 = """

#### 2.6. 終了

![図 C](figure:0.2,0.2,0.8,0.4)

図の説明：ページ 2 の図である。

読めない文字は【判読できない】と書く。

"""
ASSEMBLED = [
    "<!-- page: 1 -->", "",
    "## ２．５ タスク", "",            # NFKC で 2.5 → 数字のかたまり2つ
    "### 2.5.9 起動", "",
    "# 3. 手順", "",                   # 1. の形 → 1つ
    "### 2 概要", "",                  # 番号の形でない見出しは変えない
    "###### 1.2.3.4.5.6.7 深い", "",   # 6 が上限
    "## 2.5x 番号でない", "",
    "本文の行である。", "",
    "![図 A](fig/p0001-1.png)", "",
    "図の説明：箱の図である。", "",
    "![図 B](fig/p0001-2.png)", "",
    "図の説明：線の図である。", "",
    "<!-- page: 2 -->", "",
    "## 2.6. 終了", "",
    "![図 C](fig/p0002-1.png)", "",
    "図の説明：ページ 2 の図である。", "",
    "読めない文字は【判読できない】と書く。",
]
# 図の範囲（各辺を 0.04 広げ、0 〜 1 に収めたもの）
FIGURES = [("p0001-1.png", 1, (0.06, 0.16, 0.54, 0.64)),
           ("p0001-2.png", 1, (0.0, 0.86, 0.34, 1.0)),
           ("p0002-1.png", 2, (0.16, 0.16, 0.84, 0.44))]


def _dark_box(img):
    """グレーの画像の、黒い部分（128 未満）を囲む外枠（左、上、右、下）。黒い部分がなければ None。"""
    return img.point(lambda v: 255 if v < 128 else 0).getbbox()


def test_assemble_pages_headings_figures(tmp_path):
    """A-8、A-9：組み立てで、ページの目印が入り、番号の見出しのレベルがそろい、図が決まった範囲と大きさで切り出される（SR-39、SR-40）。"""
    import pypdfium2 as pdfium
    from PIL import Image

    pdf = helpers.make_image_pdf(tmp_path / "pdf" / "spec.pdf", pages=2)
    out = _start(tmp_path, "convert", src=False, pdf=pdf)
    job = helpers.jobs_with(out, status="issued", kind="convert")[0]
    assert job["outputs"] == [".work/pdf/D01/0001.md", ".work/pdf/D01/0002.md"], job
    _write(out, job["outputs"][0], PAGE1)
    _write(out, job["outputs"][1], PAGE2)
    r = helpers.revdoc("next", out)
    assert r.ok and r.data["state"] == "done", r.data

    legacy = Path(out) / "docs" / "legacy" / "spec"
    assert _file_lines(legacy / "001.md") == ASSEMBLED
    assert sorted(p.name for p in (legacy / "fig").iterdir()) == [f[0] for f in FIGURES]
    doc = pdfium.PdfDocument(str(pdf))
    try:
        for name, page, (x0, y0, x1, y1) in FIGURES:
            w, h = helpers.read_json(Path(out) / ".work" / "pdf" / "D01" / ("%04d.json" % page))["size"]
            with Image.open(str(legacy / "fig" / name)) as img:
                got = img.convert("L")
            assert abs(got.size[0] - (x1 - x0) * w * 200 / 72) <= 2 and abs(got.size[1] - (y1 - y0) * h * 200 / 72) <= 2, \
                (name, got.size)
            # 範囲：テストの中でページを 200 dpi で描いて同じ範囲を切り出し、黒い部分の外枠の位置を比べる
            whole = doc[page - 1].render(scale=200 / 72).to_pil().convert("L")
            ref = whole.crop((round(x0 * whole.size[0]), round(y0 * whole.size[1]),
                              round(x1 * whole.size[0]), round(y1 * whole.size[1])))
            ref_box = _dark_box(ref)
            if ref_box is not None:  # 何も描いていない範囲は、位置を比べられない
                got_box = _dark_box(got.resize(ref.size))
                assert got_box is not None and max(abs(a - b) for a, b in zip(got_box, ref_box)) <= 6, \
                    (name, got_box, ref_box)
    finally:
        doc.close()
    unknowns = _file_lines(Path(out) / "docs" / "review" / "unknowns.md")
    assert _items(unknowns, "### 判読できない文字のあるページ") == ["- spec.pdf p.2"]


def _body(tag, n):
    return ["%s の本文 %d である。" % (tag, k) for k in range(1, n + 1)]


def test_assemble_split(tmp_path):
    """A-8：組み立てで、1,000 行を超える既存の設計書が、決まった切れ目で 1,000 行以下に分かれ、nav のラベルが決まりどおりになる（SR-39、SR-68）。"""
    pages = [["# A 章", ""] + _body("A", 300),
             ["# B 章", ""] + _body("B", 300),
             ["# C 章", ""] + _body("C", 300),
             _body("D", 200) + ["", "## D 節", ""] + _body("E", 1300)]
    pdf = helpers.make_image_pdf(tmp_path / "pdf" / "spec.pdf", pages=4)
    out = _start(tmp_path, "convert", src=False, pdf=pdf)
    job = helpers.jobs_with(out, status="issued", kind="convert")[0]
    for rel, lines in zip(job["outputs"], pages):
        _write(out, rel, "\n".join(lines) + "\n")
    r = helpers.revdoc("next", out)
    assert r.ok and r.data["state"] == "done", r.data

    # 8.1 の 1 でつないだ全体（2,420 行）
    full = []
    for n, lines in enumerate(pages, 1):
        full += ["<!-- page: %d -->" % n, ""] + lines + [""]
    full.pop()
    m3, m4, d = full.index("<!-- page: 3 -->"), full.index("<!-- page: 4 -->"), full.index("## D 節")
    # 1つ目：候補は p.2、p.3 の目印（レベル 1）と p.4 の目印（レベル 7）。いちばん後ろのレベル 1（p.3 の目印）の前で切る。
    # 2つ目：候補は p.4 の目印（レベル 7）と「## D 節」（レベル 2）。「## D 節」の前で切る。
    # 3つ目：998 行の中に候補がないので、998 行で切る。1行目が目印でないので、p.4 の目印と空行を足す。
    # 4つ目：残りは 998 行以下。1行目が目印でないので、p.4 の目印と空行を足す。
    expected = [full[:m3 - 1], full[m3:d - 1], [full[m4], ""] + full[d:d + 998], [full[m4], ""] + full[d + 998:]]
    legacy = Path(out) / "docs" / "legacy" / "spec"
    assert sorted(p.name for p in legacy.glob("*.md")) == ["001.md", "002.md", "003.md", "004.md"]
    for k, lines in enumerate(expected, 1):
        got = _file_lines(legacy / ("%03d.md" % k))
        assert len(got) <= 1000 and got == lines, (k, len(got), len(lines))
    assert _nav(_load_mkdocs(out), "既存の設計書") == [{"spec.pdf": [
        {"A 章 (p.1-2)": "legacy/spec/001.md"}, {"C 章 (p.3-4)": "legacy/spec/002.md"},
        {"D 節 (p.4)": "legacy/spec/003.md"}, {"(p.4)": "legacy/spec/004.md"}]}]


# ---------------------------------------------------------------------------
# 8.2 照合の仕事を作る
# ---------------------------------------------------------------------------

def test_match_split(tmp_path):
    """A-8：照合の仕事は、docs/legacy/ の本文の行を、見出しの切れ目で 100 行までに分けたものになる（SR-41。5.6、8.2）。"""
    pdf = helpers.make_image_pdf(tmp_path / "pdf" / "spec.pdf", pages=2)
    out = _start(tmp_path, "convert", pdf=pdf)
    job = helpers.jobs_with(out, status="issued", kind="convert")[0]
    pages = [["## A", ""] + _body("A", 60) + ["", "## B", ""] + _body("B", 50) + ["", "## C", ""] + _body("C", 230),
             ["## D", ""] + _body("D", 30)]
    for rel, lines in zip(job["outputs"], pages):
        _write(out, rel, "\n".join(lines) + "\n")
    assert helpers.revdoc("next", out).ok and helpers.read_state(out)["stage"] == "match"

    legacy = _file_lines(Path(out) / "docs" / "legacy" / "spec" / "001.md")
    jobs = helpers.jobs_with(out, kind="match")
    infos = [helpers.read_json(Path(out) / ".work" / "match" / (j["id"] + ".json")) for j in jobs]
    # 5.6 の例と同じ：60、50、230、30 行の節は、60、50、100、100、30 + 30 行の5つの仕事になる
    assert [i["count"] for i in infos] == [60, 50, 100, 100, 60]
    assert all(i["file"] == "docs/legacy/spec/001.md" for i in infos)
    assert [legacy[i["lines"][0]["line"] - 1] for i in infos] == [
        "A の本文 1 である。", "B の本文 1 である。", "C の本文 1 である。", "C の本文 101 である。", "C の本文 201 である。"]
    assert [j["target"] for j in jobs] == ["legacy/spec/001.md:%d" % i["lines"][0]["line"] for i in infos]


# ---------------------------------------------------------------------------
# 8.3 照合の記録の振り分け、8.4「既存設計書のみ」の記録の差し込み
# ---------------------------------------------------------------------------

def _match_start(tmp_path):
    """ソースコードと画像だけの PDF（2ページ）で、照合の仕事を渡したところまで進める。
    代わりの関数の変換の出力は、ページごとに、表の行、図の行、図の説明、Mermaid の順になる。"""
    pdf = helpers.make_image_pdf(tmp_path / "pdf" / "spec.pdf", pages=2)
    out = _start(tmp_path, "match", pdf=pdf)
    job = helpers.jobs_with(out, status="issued", kind="match")[0]
    info = helpers.read_json(Path(out) / ".work" / "match" / (job["id"] + ".json"))
    text = {e["n"]: e["text"] for e in info["lines"]}
    assert info["count"] == 8 and text[1].startswith("|") and text[2] == "![ページ 1 の図](fig/p0001-1.png)" \
        and text[4].startswith("```mermaid") and text[6] == "![ページ 2 の図](fig/p0002-1.png)", info
    return out, job, text


DISCREPANCY = """## 1 食い違い
- 場所: [kernel/task.c:4-7]
- 名前: ActivateTask
- 既存の設計書: 上限は 1 である。
- ソースコード: 上限は 2 である。

"""


def _part_job(out, target):
    return next(j for j in helpers.read_state(out)["jobs"] if j["kind"] == "write_module" and j["target"] == target)


def test_distribute_records(tmp_path):
    """A-8：照合の記録が、部分ごと、全体、records.json に振り分けられ、「一致」の範囲の Mermaid の図がモジュールの照合の記録に載り、照合していない範囲が一覧に載る（SR-44、SR-46、SR-81）。"""
    out, job, t = _match_start(tmp_path)
    # 8 番を覆わない記録。3回とも bad_cover で失敗になり、合格する記録だけが使われる（8.3 の 1）。
    record = (DISCREPANCY
              + "## 2-3 既存設計書のみ\n- モジュール: kernel\n- 内容:\n\n%s\n\n%s\n\n" % (t[2], t[3])
              + "## 4 一致\n- 場所: [kernel/task.c:1-7]\n\n"
              + "## 5 既存設計書のみ\n- モジュール: 全体\n- 内容:\n\n| 優先度 | 用途 |\n| --- | --- |\n| 0 | 割込み処理 |\n\n"
              + "## 6-7 既存設計書のみ\n- モジュール: lib\n- 内容:\n\n%s\n\n%s\n" % (t[6], t[7]))
    for _ in range(3):
        _write(out, job["outputs"][0], record)
        r = helpers.revdoc("next", out)
        assert r.ok, r.data
    mj = job["id"]
    assert _job(out, mj)["status"] == "failed" and helpers.read_state(out)["stage"] == "write_module"

    work = Path(out) / ".work" / "records"
    data = helpers.read_json(work / "records.json")
    assert data["discrepancies"] == [{"job": mj, "pdf": "D01", "page": 1, "file": "kernel/task.c",
                                      "name": "ActivateTask", "module": "kernel",
                                      "legacy": "上限は 1 である。", "source": "上限は 2 である。"}]
    assert [(e["id"], e["job"], e["pdf"], e["page"], e["target"]) for e in data["legacy_only"]] == [
        ("E0001", mj, "D01", 1, "docs/design/modules/kernel.md"),
        ("E0002", mj, "D01", 2, "docs/design/architecture.md"),
        ("E0003", mj, "D01", 2, "docs/design/modules/lib.md")]
    assert data["legacy_only"][0]["module"] == "kernel" and data["legacy_only"][2]["module"] == "lib"
    assert data["unmatched"] == [{"job": mj, "pdf": "D01", "page": 2, "file": "docs/legacy/spec/001.md", "lines": 1}]

    kj, lj = _part_job(out, "kernel")["id"], _part_job(out, "lib")["id"]
    kernel = _file_lines(work / (kj + ".md"))
    assert kernel[0] == "# 照合の記録（kernel）"
    assert _between(kernel, "## 食い違い", "## 一致した図") == [
        "### kernel/task.c ActivateTask", "- 既存の設計書: 上限は 1 である。", "- ソースコード: 上限は 2 である。"]
    assert _between(kernel, "## 一致した図") == ["### kernel/task.c"] + t[4].split("\n")
    lib = _file_lines(work / (lj + ".md"))
    assert lib[0] == "# 照合の記録（lib）"
    assert _between(lib, "## 食い違い", "## 一致した図") == ["なし"] and _between(lib, "## 一致した図") == ["なし"]
    # 画像の行のパスは、差し込む先の設計書からの相対パスになる（8.3 の 5）。
    k_legacy = _file_lines(work / (kj + ".legacy.md"))
    assert k_legacy[0] == "# 照合の記録（kernel。既存設計書のみ）"
    assert _nonempty(k_legacy[1:]) == ["### E0001", "![ページ 1 の図](../../legacy/spec/fig/p0001-1.png)", t[3]]
    l_legacy = _file_lines(work / (lj + ".legacy.md"))
    assert _nonempty(l_legacy[1:]) == ["### E0003", "![ページ 2 の図](../../legacy/spec/fig/p0002-1.png)", t[7]]
    overall = _file_lines(work / "overall.md")
    assert _nonempty(overall[1:]) == ["### E0002", "| 優先度 | 用途 |", "| --- | --- |", "| 0 | 割込み処理 |"]

    r = _drive(out)
    assert r.data["state"] == "done", r.data
    disc = _file_lines(Path(out) / "docs" / "review" / "discrepancies.md")
    assert disc[0] == "# 食い違いの一覧"
    assert [x for x in disc if x.startswith("## ")] == ["## 1. kernel/task.c ActivateTask", "## 照合していない範囲"]
    assert _items(disc, "## 1. kernel/task.c ActivateTask") == [
        "- 既存の設計書での場所: spec.pdf p.1", "- ソースコードでの場所: kernel/task.c ActivateTask",
        "- モジュール: kernel", "- 既存の設計書の内容: 上限は 1 である。", "- ソースコードの内容: 上限は 2 である。"]
    assert _items(disc, "## 照合していない範囲") == ["- spec.pdf p.2（docs/legacy/spec/001.md の 1 行）"]
    failed = _items(_file_lines(Path(out) / "docs" / "review" / "unknowns.md"), "### 失敗した仕事")
    assert len(failed) == 1 and failed[0].startswith("- 照合：docs/legacy/spec/001.md の ") \
        and "[bad_cover]" in failed[0], failed
    c = _check(out)
    assert c["passed"] is True and c["failed_jobs"] == 1, c


def _big(k):
    return ["大きい記録 %d の行 %d。" % (k, i) for i in range(1, 601)]


SPECULATION = "スケジューラは、優先度の高いタスクを先に実行すると思われる。"
SPEC_ROW = "| 0 | おそらく割込み処理に使う |"


def test_legacy_only_inserted(tmp_path):
    """A-8：「既存設計書のみ」の記録が、印つきで設計書の見出しの下に入り、1,000 行を超える分は続きのファイルに入り、推測の言い回しのある表を含んでも done の後の check に合格する（SR-54、SR-56、SR-58、SR-59、SR-68、SR-69）。"""
    out, job, t = _match_start(tmp_path)
    record = (DISCREPANCY
              + "## 2-3 既存設計書のみ\n- モジュール: kernel\n- 内容:\n\n%s\n\n%s\n\n%s\n\n" % (t[2], t[3], SPECULATION)
              + "## 4 一致\n- 場所: [kernel/task.c:1-7]\n\n"
              + "## 5 既存設計書のみ\n- モジュール: 全体\n- 内容:\n\n| 優先度 | 用途 |\n| --- | --- |\n%s\n\n" % SPEC_ROW
              + "## 6-7 既存設計書のみ\n- モジュール: kernel\n- 内容:\n\n%s\n\n%s\n\n%s\n\n" % (t[6], t[7], "\n".join(_big(1)))
              + "## 8 既存設計書のみ\n- モジュール: kernel\n- 内容:\n\n%s\n\n%s\n" % (t[8], "\n".join(_big(2))))
    _write(out, job["outputs"][0], record)
    r = _drive(out)
    assert r.data["state"] == "done", r.data
    docs = Path(out) / "docs"

    # kernel.md には E0001 と E0003 が入る。E0004 は 1,000 行を超えるので、続きのファイルに入る（8.4 の 4）。
    kernel = _file_lines(docs / "design" / "modules" / "kernel.md")
    assert MARK not in "\n".join(kernel[:kernel.index(LEGACY_HEADING)])
    assert _after_legacy(kernel) == (
        [MARK_FIG, "![ページ 1 の図](../../legacy/spec/fig/p0001-1.png)", MARK + t[3], MARK + SPECULATION,
         MARK_FIG, "![ページ 2 の図](../../legacy/spec/fig/p0002-1.png)", MARK + t[7]]
        + [MARK + x for x in _big(1)])
    i = kernel.index(MARK_FIG)
    assert kernel[i + 1:i + 3] == ["", "![ページ 1 の図](../../legacy/spec/fig/p0001-1.png)"]
    cont = _file_lines(docs / "design" / "modules" / "kernel~p2.md")
    assert cont[:3] == ["# kernel（続き 2）", "", LEGACY_HEADING]
    assert _after_legacy(cont) == [MARK_FIG] + t[8].split("\n") + [MARK + x for x in _big(2)]
    assert not (docs / "design" / "modules" / "kernel~p3.md").exists()
    arch = _file_lines(docs / "design" / "architecture.md")
    assert _after_legacy(arch) == [MARK_TABLE, "| 優先度 | 用途 |", "| --- | --- |", SPEC_ROW]
    assert LEGACY_HEADING not in _file_lines(docs / "design" / "modules" / "lib.md")
    for lines in (kernel, cont, arch):
        assert len(lines) <= 1000 and "E000" not in "\n".join(lines)

    # 差し込んだ記録と決まった1文は、検証の対象にならない（SR-59）。
    for j in helpers.jobs_with(out, kind="verify"):
        info = helpers.read_json(Path(out) / ".work" / "verify" / (j["id"] + ".json"))
        assert all(MARK not in e["text"] and e["text"] != NONE_BOTH for e in info["lines"]), info
    c = _check(out)
    assert c["passed"] is True and c["problem_count"] == 0, c
    assert _nav(_load_mkdocs(out), "内部設計書")[1]["モジュール"] == [
        {"kernel": "design/modules/kernel.md"}, {"kernel（続き 2）": "design/modules/kernel~p2.md"},
        {"lib": "design/modules/lib.md"}]


# ---------------------------------------------------------------------------
# 8.5 検証の繰り返し
# ---------------------------------------------------------------------------

def test_verdicts_applied(tmp_path):
    """A-8：判定のとおりに設計書が直り、別の節の同じ文は1つ目が OK、2つ目が不明のとき2つ目だけが消え、置き換えた文が次の回に検証される（SR-63、SR-64、SR-66）。"""
    design = _design({"役割": [D_ROLE, D_ROLE, SAME], "公開インターフェース": [D_IFACE],
                      "データ構造": [D_PARA, "", "| 名前 | 値 |", "| --- | --- |", D_ROW],
                      "状態": [D_BLOCK], "依存関係": [SAME]})
    dep_line = len(design.split("\n")) - design.split("\n")[::-1].index(SAME)  # 依存関係の SAME の行番号

    def verdict(e):
        if e["file"] != KERNEL:
            return None
        if e["text"] == D_IFACE or e["text"].startswith("```"):
            return "NG"
        if e["text"] == D_ROW or (e["text"] == SAME and e["line"] == dep_line):
            return "不明"
        return None  # ほかは既定（コードスパンがあれば OK、なければ対象外）

    out = _module_start(tmp_path, design)
    _drive(out, until="write_overall", verdict=verdict)
    fixed = D_IFACE + "（直した）"
    jobs = _verify_jobs(out, KERNEL)
    # 同じ節の同じ文（D_ROLE の2行）は1つの番号になる。NG で置き換えた文だけが、2回目の仕事になる。
    assert [[e["text"] for e in info["lines"]] for _, info in jobs] == [
        [D_ROLE, SAME, D_IFACE, D_PARA, D_ROW, D_BLOCK, SAME], [fixed]]
    expected = ["# kernel", "## 役割", D_ROLE, D_ROLE, SAME, "## 公開インターフェース", fixed,
                "## データ構造", D_PARA, "## 状態", NONE_SOURCE, "## 依存関係", NONE_SOURCE]
    for h in helpers.MODULE_HEADINGS[6:]:
        expected += ["## " + h, NONE_SOURCE]
    assert _nonempty(_file_lines(Path(out) / KERNEL)) == expected
    logs = [x for x in helpers.read_state(out)["log"] if x["type"] == "verify_unknown" and x["file"] == KERNEL]
    assert sorted((x["heading"], x["words"]) for x in logs) == [
        ("## 依存関係", "ActivateTask"), ("## データ構造", "TASK_MAX、16"), ("## 状態", "")]

    r = _drive(out)
    assert r.data["state"] == "done", r.data
    unknowns = _file_lines(Path(out) / "docs" / "review" / "unknowns.md")
    items = _items(unknowns, "### 検証で確かめられなかった行")
    for item in ["- docs/design/modules/kernel.md「## 依存関係」：" + SAME + "（探した語：ActivateTask）",
                 "- docs/design/modules/kernel.md「## データ構造」：" + D_ROW + "（探した語：TASK_MAX、16）",
                 "- docs/design/modules/kernel.md「## 状態」：```mermaid"]:
        assert item in items, items
    assert "- docs/design/modules/kernel.md「## 状態」" in _items(unknowns, "### 読み取れる内容がなかった節")
    assert _check(out)["passed"] is True


def test_rewritten_line_is_verified_again(tmp_path):
    """A-8：代わりの関数が設計書の行を書き換えると、その行が次の回の検証の仕事になる（SR-64、P-10）。"""
    out = _module_start(tmp_path, _design({"役割": [D_ROLE], "公開インターフェース": [D_IFACE]}))
    _drive(out, until="verify_module")
    assert [j["status"] for j, _ in _verify_jobs(out, KERNEL)] == ["issued"]
    helpers.fake_agent(out)
    new = "- `TerminateTask` は、いつも `TASK_MAX` を返す。"
    path = Path(out) / KERNEL
    _write(out, KERNEL, helpers.read_text(path).replace(D_IFACE, new))
    _drive(out, until="write_overall")
    jobs = _verify_jobs(out, KERNEL)
    assert [[e["text"] for e in info["lines"]] for _, info in jobs] == [[D_ROLE, D_IFACE], [new]]
    assert new in _file_lines(path)
    assert jobs[1][1]["lines"][0]["sha1"] in helpers.read_state(out)["confirmed"][KERNEL]


def test_unjudged_lines_removed_after_round_3(tmp_path):
    """A-8：3回の検証で判定が付かなかった行は、2回目からの指示に使えなかった番号が書かれ、設計書から消え、決まった1文が入り、不明点の一覧に載る（SR-63、SR-64、SR-66。7.2）。"""
    out = _module_start(tmp_path, _design({"役割": [D_ROLE], "公開インターフェース": [D_IFACE]}))
    files = {}
    texts = {}

    def bad(j):  # kernel の内部設計書の検証の仕事にだけ、形の悪い判定を書く。渡したときの指示のファイルを残しておく。
        if j["kind"] != "verify":
            return False
        if j["id"] not in files:
            files[j["id"]] = helpers.read_json(Path(out) / ".work" / "verify" / (j["id"] + ".json"))["file"]
            texts[j["id"]] = helpers.read_text(Path(out) / ".work" / "jobs" / (j["id"] + ".md"))
        return files[j["id"]] == KERNEL

    _drive(out, until="write_overall", bad=bad)
    jobs = _verify_jobs(out, KERNEL)
    assert [[e["text"] for e in info["lines"]] for _, info in jobs] == [[D_ROLE, D_IFACE]] * 3
    assert all(j["status"] == "done" and j["tries"] == 0 for j, _ in jobs), jobs
    assert "## 前回の不合格の理由" not in texts[jobs[0][0]["id"]]
    for j, _ in jobs[1:]:  # 2回目と3回目：前の回の理由を、今回の番号で書く
        section = texts[j["id"]].split("## 前回の不合格の理由", 1)[1]
        assert "前回の判定のうち、次の番号は使えなかった。" in section
        for n in (1, 2):
            assert re.search(r"^- \[[a-z_]+\] \[%d\]：" % n, section, re.M), section
    expected = ["# kernel"]
    for h in helpers.MODULE_HEADINGS:
        expected += ["## " + h, NONE_SOURCE]
    assert _nonempty(_file_lines(Path(out) / KERNEL)) == expected
    logs = [x for x in helpers.read_state(out)["log"] if x["type"] == "verify_unjudged" and x["file"] == KERNEL]
    assert sorted((x["heading"], x["text"]) for x in logs) == [("## 公開インターフェース", D_IFACE), ("## 役割", D_ROLE)]

    r = _drive(out)
    assert r.data["state"] == "done", r.data
    items = _items(_file_lines(Path(out) / "docs" / "review" / "unknowns.md"), "### 判定が付かなかった行")
    assert "- docs/design/modules/kernel.md「## 役割」：" + D_ROLE in items, items
    assert "- docs/design/modules/kernel.md「## 公開インターフェース」：" + D_IFACE in items, items


def test_many_verify_jobs_in_one_file(tmp_path):
    """A-8：1つのファイルの検証の仕事が5件以上で、2回に分けて渡したとき、全部の仕事の判定が設計書に使われる（SR-63）。"""
    sections = {h: ["- `ActivateTask` の項目 %d-%d。" % (i, k) for k in range(1, 51)]
                for i, h in enumerate(helpers.MODULE_HEADINGS[:5])}
    last = set(sections[helpers.MODULE_HEADINGS[4]])
    design = _design(sections)
    out = _module_start(tmp_path, design)
    _drive(out, until="write_overall",
           verdict=lambda e: "不明" if e["file"] == KERNEL and e["text"] in last else None)
    assert len(_verify_jobs(out, KERNEL)) >= 5
    expected = ["# kernel"]
    for i, h in enumerate(helpers.MODULE_HEADINGS):
        expected += ["## " + h] + (sections[h] if i < 4 else [NONE_SOURCE])
    assert _nonempty(_file_lines(Path(out) / KERNEL)) == expected
    confirmed = set(helpers.read_state(out)["confirmed"][KERNEL])
    for h in helpers.MODULE_HEADINGS[:4]:
        assert all(_sha1(["# kernel", "## " + h], x) in confirmed for x in sections[h]), h


# ---------------------------------------------------------------------------
# 8.6 要約、9章 check（失敗として記録したファイル）
# ---------------------------------------------------------------------------

def test_digest_and_failed_module(tmp_path):
    """A-8：要約が、部分ごとの行数、役割の最初の行、依存関係の先頭の K 行を持ち、失敗した部分の代わりのファイルは check で不合格に数えない（SR-11、SR-66、SR-67、SR-69）。"""
    deps = ["- `TerminateTask` を呼ぶ（%d）。" % k for k in range(1, 13)]
    out = _start(tmp_path, "write_module")
    lib = _part_job(out, "lib")["id"]
    helpers.fake_agent(out, skip=[lib])
    kernel_job = _part_job(out, "kernel")
    for rel in kernel_job["outputs"]:
        _write(out, rel, _design({"役割": [D_ROLE], "依存関係": deps}) if rel == KERNEL
               else REQ if rel.startswith("docs/requirements/") else "- なし\n")

    def skip_lib(j):
        return j["id"] == lib

    _drive(out, until="write_overall", skip=skip_lib)
    assert _job(out, lib)["status"] == "failed"

    # M = 2 なので、K = min(10, 2000 // 2 - 1) = 10。
    docs = Path(out) / "docs"
    k_lines = len(_file_lines(docs / "design" / "modules" / "kernel.md"))
    l_lines = len(_file_lines(docs / "design" / "modules" / "lib.md"))
    assert _nonempty(_file_lines(Path(out) / ".work" / "digest.md")) == (
        ["- kernel（design/modules/kernel.md、%d 行）：%s" % (k_lines, D_ROLE[2:])]
        + ["  " + x for x in deps[:10]]
        + ["- lib（design/modules/lib.md、%d 行）：（設計書を作れなかった）" % l_lines])

    r = _drive(out, skip=skip_lib)
    assert r.data["state"] == "done", r.data
    c = _check(out)
    assert c["passed"] is True and c["failed_jobs"] == 1, c
    failed = _items(_file_lines(docs / "review" / "unknowns.md"), "### 失敗した仕事")
    assert len(failed) == 1 and failed[0].startswith("- 執筆（モジュール）：lib：[missing_file]"), failed
    index = _file_lines(docs / "index.md")
    after = index[index.index("## 件数") + 1:]
    assert "| 失敗した仕事（執筆（モジュール）） | 1 |" in after
    assert "review/unknowns.md" in _link_targets([x for x in after if not x.startswith("|")]), after


# ---------------------------------------------------------------------------
# 8.7 仕上げ（2つの一覧、入口のページ、mode ごとの docs/ の形）、10章 mkdocs.yml
# ---------------------------------------------------------------------------

EXCLUDED = {"doc/readme.txt": "説明\n", "empty.c": b"", "lib/blob.bin": b"\x00\x01\x02binary"}
MARK_LINES = ["- 【既存設計書のみ】：既存の設計書から取った内容である。ソースコードでは確かめていない。"
              "ソースコードに見つからなかった機能の記述を含む。",
              "- 【判読できない】：既存の設計書の文字のうち、読み取れなかった部分である。"]


def _unknown_count(lines):
    """不明点の一覧（続きのファイルの行をつないだものでもよい）の「## 不明点」の下の項目の数（`- なし` は数えない）。"""
    count, section = 0, None
    for x in lines:
        if x.startswith("## "):
            section = x
        elif section == "## 不明点" and x.startswith("- ") and x != "- なし":
            count += 1
    return count


@pytest.mark.parametrize("mode", ["both", "source", "pdf"])
def test_finish_by_mode(tmp_path, mode):
    """A-8：仕上げで、入口のページ、不明点の一覧、mkdocs.yml が mode ごとに決まりどおりにでき、check に合格する（SR-66、SR-67、SR-68、SR-69、SR-72）。"""
    src = helpers.make_source_tree(tmp_path / "src", dict(LAYOUT, **EXCLUDED)) if mode != "pdf" else None
    pdf = helpers.make_text_pdf(tmp_path / "pdf" / "spec.pdf", pages=3) if mode != "source" else None
    out = tmp_path / "out"
    r = helpers.run_to_done(out, src=src, pdf=pdf)
    assert r.ok and r.data["state"] == "done", r.data
    docs = Path(out) / "docs"
    # mode ごとの docs/ の形（8.7 の表）は、test_flow.py の test_full_run が確かめる
    c = _check(out)
    assert c["passed"] is True and c["problem_count"] == 0 and c["failed_jobs"] == 0, c

    # 不明点の一覧
    unknowns = _file_lines(docs / "review" / "unknowns.md")
    assert unknowns[0] == "# 不明点の一覧" and _items(unknowns, "## 処理の失敗") == ["- なし"]
    if mode == "pdf":
        assert _items(unknowns, "## 不明点") == ["- なし"]
    else:
        assert "- docs/design/modules/kernel.md「## エラー処理」" in _items(unknowns, "### 読み取れる内容がなかった節")

    # 入口のページ
    index = _file_lines(docs / "index.md")
    site = "spec 設計書" if mode == "pdf" else "src 設計書"
    headings = ["# " + site, "## 設計書の構成", "## 印の意味", "## 使った入力", "## モジュールの一覧", "## 件数"]
    if mode == "pdf":
        headings.remove("## モジュールの一覧")
    got = [x for x in index if x.startswith("#")]
    if mode == "source":  # 印が1つもないので、印の意味の行を書かない
        got = [x for x in got if x != "## 印の意味"]
        headings.remove("## 印の意味")
        assert not any(x in index for x in MARK_LINES)
    else:
        assert _items(index, "## 印の意味") == (MARK_LINES if mode == "both" else MARK_LINES[1:])
    assert got == headings
    links = _items(index, "## 設計書の構成")
    assert links and all("](" in x for x in links), links
    targets = _link_targets(links)  # リンク先の書き方は決まっていないので、行き先で比べる
    assert _links_under(targets, "requirements") == (mode != "pdf"), targets
    assert _links_under(targets, "design") == (mode != "pdf"), targets
    assert _links_under(targets, "legacy") == (mode != "source"), targets
    assert ("review/discrepancies.md" in targets) == (mode == "both"), targets
    assert "review/unknowns.md" in targets, targets
    inputs = []
    if mode != "pdf":
        inputs += ["- ソースコード：src（2 ファイル、320 行）",
                   "- 対象から外したファイル：3（文書、データ、ビルドの出力の拡張子：1、空のファイル：1、バイナリー：1）"]
    if mode != "source":
        inputs.append("- 既存の設計書：spec.pdf（3 ページ。埋め込みテキストで文字を確かめたページ：3）")
    assert _items(index, "## 使った入力") == inputs
    if mode != "pdf":
        assert _items(index, "## モジュールの一覧") == ["- [kernel](design/modules/kernel.md)：kernel",
                                                     "- [lib](design/modules/lib.md)：lib"]
    disc = len(helpers.read_json(Path(out) / ".work" / "records" / "records.json")["discrepancies"]) \
        if mode == "both" else 0
    rows = [("モジュール", 2), ("食い違い", disc), ("不明点", _unknown_count(unknowns))]
    rows += [("失敗した仕事（%s）" % s, 0) for s in ["解析", "変換", "照合", "執筆（モジュール）", "執筆（全体）", "検証"]]
    rows.append(("作業中に変わった入力", 0))
    drop = {"source": {"食い違い", "失敗した仕事（変換）", "失敗した仕事（照合）"},
            "pdf": {"モジュール", "食い違い", "失敗した仕事（解析）", "失敗した仕事（照合）", "失敗した仕事（執筆（モジュール））",
                    "失敗した仕事（執筆（全体））", "失敗した仕事（検証）"}}.get(mode, set())
    assert [x for x in _items(index, "## 件数") if x.startswith("|")] == (
        ["| 項目 | 件数 |", "| --- | --- |"] + ["| %s | %d |" % (k, v) for k, v in rows if k not in drop])

    # mkdocs.yml（nav のほかは決まった内容。nav の項目は mode に合うものだけ）
    data = _load_mkdocs(out)
    assert {k: v for k, v in data.items() if k not in ("site_name", "nav")} == MKDOCS_COMMON
    assert 'site_name: "%s"' % site in _file_lines(Path(out) / "mkdocs.yml")
    top = {"both": ["ホーム", "要求仕様書", "内部設計書", "既存の設計書", "確認の一覧"],
           "source": ["ホーム", "要求仕様書", "内部設計書", "確認の一覧"],
           "pdf": ["ホーム", "既存の設計書", "確認の一覧"]}[mode]
    assert [list(item)[0] for item in data["nav"]] == top and data["nav"][0] == {"ホーム": "index.md"}
    review = [{"不明点の一覧": "review/unknowns.md"}]
    if mode == "both":
        review.insert(0, {"食い違いの一覧": "review/discrepancies.md"})
    assert _nav(data, "確認の一覧") == review


def test_mkdocs_nav_and_split_module(tmp_path):
    """A-8：ユニットが5個を超えるモジュールの入口のページができ、mkdocs.yml の nav が決まった順と形になる（SR-56、SR-68）。"""
    layout = {"kernel/f%d.c" % k: 1001 for k in range(1, 7)}  # 1ファイルが1ユニット。6ユニットで、部分は5個と1個。
    layout["lib/timer.cpp"] = 20
    src = helpers.make_source_tree(tmp_path / "src", layout)
    out = tmp_path / "out"
    r = helpers.run_to_done(out, src=src)
    assert r.ok and r.data["state"] == "done", r.data
    docs = Path(out) / "docs"
    for folder in ("design/modules", "requirements/3-1-functions"):
        entry = _file_lines(docs / folder / "kernel.md")
        assert entry[0] == "# kernel"
        items = _nonempty(entry[1:])
        assert len(items) == 2 and items[0].startswith("- [kernel/1](kernel/1.md)：") \
            and items[1].startswith("- [kernel/2](kernel/2.md)："), items
        assert all("f%d.c" % k in items[0] for k in range(1, 6)) and "f6.c" in items[1], items
    assert _items(_file_lines(docs / "index.md"), "## モジュールの一覧") == [
        "- [kernel](design/modules/kernel.md)：kernel", "- [lib](design/modules/lib.md)：lib"]
    assert _check(out)["passed"] is True

    def module_nav(folder):
        return [{"kernel": [{"入口": folder + "/kernel.md"}, {"1": folder + "/kernel/1.md"},
                            {"2": folder + "/kernel/2.md"}]},
                {"lib": folder + "/lib.md"}]

    reqs = [{f[1][2:]: f[0]} for f in helpers.OVERALL_FILES[1:]]
    reqs.insert(2, {"3.1 機能": module_nav("requirements/3-1-functions")})
    data = _load_mkdocs(out)
    assert data["nav"] == [
        {"ホーム": "index.md"},
        {"要求仕様書": reqs},
        {"内部設計書": [{"全体": "design/architecture.md"}, {"モジュール": module_nav("design/modules")}]},
        {"確認の一覧": [{"不明点の一覧": "review/unknowns.md"}]},
    ]


def test_review_lists_split(tmp_path):
    """A-8：食い違いの一覧と不明点の一覧が 1,000 行を超えると、続きのファイルに分かれ、件数は通して数えられ、nav に続きが載る（SR-46、SR-66、SR-68。8.7、10章）。"""
    pdf = helpers.make_image_pdf(tmp_path / "pdf" / "spec.pdf", pages=1)
    out = _start(tmp_path, "convert", pdf=pdf)
    job = helpers.jobs_with(out, status="issued", kind="convert")[0]
    _write(out, job["outputs"][0], "\n".join(_body("A", 150)) + "\n")
    assert helpers.revdoc("next", out).ok and helpers.read_state(out)["stage"] == "match"
    for j in helpers.jobs_with(out, status="issued", kind="match"):  # 全部の行を「食い違い」にする（150 件）
        count = helpers.read_json(Path(out) / ".work" / "match" / (j["id"] + ".json"))["count"]
        _write(out, j["outputs"][0], "".join(DISCREPANCY.replace("## 1 ", "## %d " % n, 1) for n in range(1, count + 1)))
    assert helpers.revdoc("next", out).ok and helpers.read_state(out)["stage"] == "write_module"
    helpers.fake_agent(out)
    written = ["- `ActivateTask` の不明点 %d。" % k for k in range(1, 1101)]
    _write(out, next(rel for rel in _part_job(out, "kernel")["outputs"] if rel.startswith(".work/unknowns/")),
           "\n".join(written) + "\n")
    r = _drive(out)
    assert r.data["state"] == "done", r.data

    review = Path(out) / "docs" / "review"
    disc = [_file_lines(review / "discrepancies.md"), _file_lines(review / "discrepancies~p2.md")]
    unk = [_file_lines(review / "unknowns.md"), _file_lines(review / "unknowns~p2.md")]
    assert not (review / "discrepancies~p3.md").exists() and not (review / "unknowns~p3.md").exists()
    assert all(len(lines) <= 1000 for lines in disc + unk)
    # 食い違いの一覧：続きは「## <番号>.」の見出しから始まる
    assert disc[1][0] == "# 食い違いの一覧（続き 2）"
    assert re.match(r"## [0-9]+\. ", _nonempty(disc[1][1:])[0]), disc[1][:5]
    assert len([x for x in disc[0] + disc[1] if re.match(r"## [0-9]+\. ", x)]) == 150
    # 不明点の一覧：続きは、切った所の ## と ### の見出しをもう一度書く
    assert unk[1][0] == "# 不明点の一覧（続き 2）"
    assert _nonempty(unk[1][1:])[:2] == ["## 不明点", "### 執筆担当が書いた不明点"]
    assert [x for x in unk[0] + unk[1] if x.startswith("- kernel：")] == ["- kernel：" + x[2:] for x in written]
    # 件数は、続きのファイルも通して数える
    index = _file_lines(Path(out) / "docs" / "index.md")
    assert "| 食い違い | 150 |" in index
    assert "| 不明点 | %d |" % _unknown_count(unk[0] + unk[1]) in index
    assert _nav(_load_mkdocs(out), "確認の一覧") == [
        {"食い違いの一覧": "review/discrepancies.md"}, {"食い違いの一覧（続き 2）": "review/discrepancies~p2.md"},
        {"不明点の一覧": "review/unknowns.md"}, {"不明点の一覧（続き 2）": "review/unknowns~p2.md"}]
    assert _check(out)["passed"] is True


# ---------------------------------------------------------------------------
# 9章 check
# ---------------------------------------------------------------------------

def test_check_finds_problems(tmp_path):
    """A-8：done の後に決まりに反するように docs/ を書き換えると、check が、ファイルと検査の名前を付けて不合格を返す。推測の6つの言い回しは、どれも不合格になり、docs/legacy/ の語とモジュールの名前の語は、名前の検査に合格する（SR-58、SR-65、SR-69）。"""
    pdf = helpers.make_image_pdf(tmp_path / "pdf" / "spec.pdf", pages=2)
    src = helpers.make_source_tree(tmp_path / "src", dict(LAYOUT, **{"main.c": 10}))  # main.c はモジュール _root になる
    out = tmp_path / "out"
    r = helpers.run_to_done(out, src=src, pdf=pdf)
    assert r.ok and r.data["state"] == "done", r.data
    assert _check(out)["passed"] is True
    docs = Path(out) / "docs"
    # s1 は docs/legacy/ の Mermaid にだけある語、_root はモジュールの名前の語である（5.8）
    names = _file_lines(Path(out) / ".work" / "names.txt")
    assert "s1" not in names and "_root" not in names
    assert "s1" in re.findall(r"[A-Za-z0-9_]+", helpers.read_text(docs / "legacy" / "spec" / "001.md"))

    def edit(rel, old, new):
        text = helpers.read_text(docs / rel)
        assert old in text, (rel, old)
        _write(out, "docs/" + rel, text.replace(old, new, 1))

    guesses = ["- `ActivateTask` は、呼ばれると思われる。", "- `ActivateTask` は、呼ばれると考えられる。",
               "- `ActivateTask` は、おそらく呼ばれる。", "- `ActivateTask` は、呼ばれるかもしれない。",
               "- `ActivateTask` は、呼ばれるはずである。", "- `ActivateTask` は、呼ばれると推測する。"]
    edit("design/modules/kernel.md", "## 役割\n",
         "## 役割\n\n" + "\n".join(guesses) + "\n\n### `s1`\n\n### `_root`\n")
    kernel = _file_lines(docs / "design" / "modules" / "kernel.md")
    guess_lines = [kernel.index(x) + 1 for x in guesses]
    edit("legacy/spec/001.md", "<!-- page: 1 -->\n", "<!-- page: 1 -->\n\n本文に __ がある。\n")
    edit("requirements/3-1-functions/kernel.md", "## 機能の要求\n",
         "## 機能の要求\n\n- FR-KERNEL-901: `ActivateTask` を呼ぶ。\n- FR-KERNEL-901: `ActivateTask` を呼ぶ。\n")
    edit("design/modules/lib.md", "# lib\n", "# lib\n\n```mermaid\nflowchart LR\n    a -->|yes| b\n```\n")
    edit("design/architecture.md", "# 全体の内部設計書\n", "# 全体の内部設計書\n\n### `NoSuchName`\n")
    edit("index.md", "## 件数\n", "## 件数\n\n- [説明](nosuch.md)\n")
    (docs / "review" / "discrepancies.md").unlink()
    c = _check(out)
    assert c["passed"] is False and c["failed_jobs"] == 0 and c["problem_count"] == len(c["problems"]), c
    assert {(p["file"], p["rule"]) for p in c["problems"]} == {
        ("docs/design/modules/kernel.md", "speculation"),
        ("docs/legacy/spec/001.md", "double_underscore"),
        ("docs/requirements/3-1-functions/kernel.md", "duplicate_id"),
        ("docs/design/modules/lib.md", "bad_mermaid"),
        ("docs/design/architecture.md", "unknown_name"),
        ("docs/index.md", "broken_link"),
        ("docs/review/discrepancies.md", "missing_file"),
    }, c["problems"]
    assert sorted(p["line"] for p in c["problems"]
                  if p["file"] == "docs/design/modules/kernel.md" and p["rule"] == "speculation") == guess_lines
