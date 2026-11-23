"""テストの共通の道具。

根拠は docs/script-spec.md（スクリプトの仕様）である。使い方は tests/README.md に書く。
revdoclib、pypdfium2、Pillow は、使う関数の中で読み込む（実装がなくても、テストの収集が通るようにする）。
"""
import builtins
import contextlib
import ctypes
import dataclasses
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO / "plugin" / "skills" / "make-design-docs" / "scripts"
REVDOC_PY = SCRIPTS_DIR / "revdoc.py"
A4 = (595.32, 841.92)

# 6.1 の解析メモの見出し（この順）
MEMO_HEADINGS = ["役割", "公開インターフェース", "データ構造", "処理の流れ", "設定値と定数",
                 "外部とのやり取り", "ユニットの外で定義されている名前", "分からなかったこと"]
# 6.4 の内部設計書の必須の見出し（この順）
MODULE_HEADINGS = ["役割", "公開インターフェース", "データ構造", "処理の流れ", "状態", "依存関係",
                   "エラー処理", "並行性とタイミング", "設定値と定数", "外部とのやり取り"]
# 6.5 の表：(docs/ からのパス, 1行目, 必須の見出し, 要求の接頭辞)
OVERALL_FILES = [
    ("design/architecture.md", "# 全体の内部設計書",
     ["## システムの概要と境界", "## モジュールの構成", "## 依存関係", "## 実行の構造",
      "## 主なデータの流れ", "## 共通の仕組み", "## ビルドと構成"], None),
    ("requirements/1-introduction.md", "# 1 はじめに",
     ["## 1.1 目的", "## 1.2 範囲", "## 1.3 製品の概要", "### 1.3.1 製品の位置づけ",
      "### 1.3.2 製品の機能", "### 1.3.3 利用者の特性", "### 1.3.4 制限", "## 1.4 定義"], None),
    ("requirements/2-references.md", "# 2 参考文献", [], None),
    ("requirements/3-2-performance.md", "# 3.2 性能の要求", [], "PR-"),
    ("requirements/3-3-usability.md", "# 3.3 ユーザビリティの要求", [], "UR-"),
    ("requirements/3-4-interfaces.md", "# 3.4 インターフェースの要求", [], "IR-"),
    ("requirements/3-5-database.md", "# 3.5 論理データベースの要求", [], "DR-"),
    ("requirements/3-6-design-constraints.md", "# 3.6 設計の制約", [], "DC-"),
    ("requirements/3-7-attributes.md", "# 3.7 ソフトウェアシステムの属性", [], "SA-"),
    ("requirements/3-8-supporting.md", "# 3.8 補足の情報", [], None),
    ("requirements/4-verification.md", "# 4 検証", [], None),
    ("requirements/5-appendices.md", "# 5 付録", ["## 5.1 前提と依存関係", "## 5.2 頭字語と略語"], None),
]


# ---------------------------------------------------------------------------
# 1. スクリプトを呼ぶ
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Result:
    """スクリプトの1回の結果。data は標準出力の JSON、code は終了コード。"""
    code: int
    data: dict
    stdout: str
    stderr: str = ""

    @property
    def ok(self):
        return self.data.get("ok") is True


def import_revdoclib():
    """revdoclib を読み込んで返す。revdoc.py と同じく、バイトコードのファイルを書かない。"""
    sys.dont_write_bytecode = True
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import revdoclib
    return revdoclib


def parse_stdout(text, code):
    """標準出力が 1.2 の形（ASCII の JSON 1つを1行）で、終了コードと合うことを確かめ、値を返す。"""
    assert text.endswith("\n") and text.count("\n") == 1, "標準出力が JSON の1行でない：%r" % text[:300]
    assert all(ord(c) < 128 for c in text), "標準出力に ASCII でない文字がある：%r" % text[:300]
    data = json.loads(text)
    assert isinstance(data, dict), "標準出力が JSON のオブジェクトでない：%r" % text[:300]
    assert text == json.dumps(data, ensure_ascii=True, separators=(",", ":")) + "\n", \
        "標準出力が 1.2 の作り方でない：%r" % text[:300]
    assert code == (0 if data.get("ok") is True else 1), "終了コード %r と ok が合わない" % code
    return data


@contextlib.contextmanager
def _cwd(path):
    old = os.getcwd()
    if path is not None:
        os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(old)


def run_main(argv, cwd=None):
    """同じプロセスの中で revdoclib.main(argv) を呼び、Result を返す。"""
    mod = import_revdoclib()
    buf = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n", write_through=True)
    with _cwd(cwd), contextlib.redirect_stdout(buf):
        code = mod.main([str(a) for a in argv])
    text = buf.buffer.getvalue().decode("utf-8")
    return Result(code, parse_stdout(text, code), text)


def run_cli(argv, cwd=None, env=None, timeout=600):
    """コマンドとして `python revdoc.py <argv>` を動かし、Result を返す。

    Windows の標準出力の改行（\\r\\n）は \\n に直してから確かめる。
    PYTHONWARNDEFAULTENCODING=1 で文字コードの警告を出させ（効くのは Python 3.10 以上）、スクリプトの警告を EncodingGuard に渡す。
    """
    e = dict(os.environ)
    e["PYTHONWARNDEFAULTENCODING"] = "1"
    e.update(env or {})
    p = subprocess.run([sys.executable, str(REVDOC_PY)] + [str(a) for a in argv],
                       cwd=None if cwd is None else str(cwd), env=e,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    stderr = p.stderr.decode("utf-8", "replace")
    for guard in EncodingGuard.active:
        guard.add_stderr(stderr)
    text = p.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    return Result(p.returncode, parse_stdout(text, p.returncode), text, stderr)


def revdoc(sub, out, src=None, pdf=None, extra=(), cli=False, cwd=None):
    """サブコマンドを `sub --out <out> [--src <src>] [--pdf <pdf>] <extra>` の引数で呼ぶ。"""
    argv = [sub, "--out", out]
    if src is not None:
        argv += ["--src", src]
    if pdf is not None:
        argv += ["--pdf", pdf]
    argv += list(extra)
    return run_cli(argv, cwd=cwd) if cli else run_main(argv, cwd=cwd)


def mkdocs_build(out, timeout=600):
    """11.1 と同じ決まり（カレントフォルダは出力先、NO_MKDOCS_2_WARNING=1）で mkdocs build を動かす。"""
    e = dict(os.environ)
    e["NO_MKDOCS_2_WARNING"] = "1"
    return subprocess.run([sys.executable, "-m", "mkdocs", "build", "-f", str(Path(out) / "mkdocs.yml"), "-q"],
                          cwd=str(out), env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


# ---------------------------------------------------------------------------
# 文字コードを指定しないファイルの読み書きを見つける（A-10。設計の8章「文字コードの警告」）
# ---------------------------------------------------------------------------

def _std_dirs():
    paths = sysconfig.get_paths()
    std = {os.path.normcase(paths["stdlib"]), os.path.normcase(paths["platstdlib"])}
    site = {os.path.normcase(paths["purelib"]), os.path.normcase(paths["platlib"])}
    return std, site


_STD, _SITE = _std_dirs()
_HERE = os.path.normcase(os.path.abspath(__file__))


def _is_skipped(filename):
    """標準ライブラリとこのファイルのフレームは、呼び出し元を探すときに飛ばす。"""
    if filename.startswith("<"):
        return True
    name = os.path.normcase(os.path.abspath(filename))
    if name == _HERE:
        return True
    if any(name.startswith(s + os.sep) for s in _SITE):
        return False
    return any(name.startswith(s + os.sep) for s in _STD)


class EncodingGuard:
    """roots（既定はスクリプトのフォルダ）のモジュールが、文字コードを指定せずに
    ファイルを開いた所（`ファイル:行`）を found に集める。with の間だけ open を差し替える。"""
    active = []

    def __init__(self, roots=None):
        self.roots = [os.path.normcase(str(Path(r).resolve())) for r in (roots or [SCRIPTS_DIR])]
        self.found = []

    def _inside(self, filename):
        name = os.path.normcase(os.path.abspath(filename))
        return any(name.startswith(r + os.sep) for r in self.roots)

    def _check(self):
        f = sys._getframe(1)
        while f is not None and _is_skipped(f.f_code.co_filename):
            f = f.f_back
        if f is not None and self._inside(f.f_code.co_filename):
            self.found.append("%s:%d" % (f.f_code.co_filename, f.f_lineno))

    def add_stderr(self, stderr):
        """コマンドの標準エラーの EncodingWarning のうち、roots のファイルのものを足す。"""
        for line in stderr.splitlines():
            if "EncodingWarning" in line and any(r in os.path.normcase(line) for r in self.roots):
                self.found.append(line.strip())

    def __enter__(self):
        self._open = builtins.open
        self._io_open = io.open
        self._text_encoding = getattr(io, "text_encoding", None)
        guard, orig_open, orig_te = self, self._open, self._text_encoding

        def open_(file, mode="r", buffering=-1, encoding=None, *args, **kwargs):
            if "b" not in mode and encoding in (None, "locale"):
                guard._check()
            return orig_open(file, mode, buffering, encoding, *args, **kwargs)

        builtins.open = io.open = open_
        if orig_te is not None:  # Python 3.10 以上の pathlib などは、ここを通る
            def text_encoding(encoding, stacklevel=2):
                if encoding is None:
                    guard._check()
                return orig_te(encoding, stacklevel + 1)
            io.text_encoding = text_encoding
        EncodingGuard.active.append(self)
        return self

    def __exit__(self, *exc):
        EncodingGuard.active.remove(self)
        builtins.open = self._open
        io.open = self._io_open
        if self._text_encoding is not None:
            io.text_encoding = self._text_encoding
        return False


# ---------------------------------------------------------------------------
# 2. 入力を作る
# ---------------------------------------------------------------------------

DEFAULT_LAYOUT = {
    "main.c": 40,
    "kernel/task.c": 120,
    "kernel/task.h": 30,
    "lib/timer.cpp": 80,
    "lib/timer.hpp": 30,
}


def _ident(stem):
    s = re.sub(r"[^A-Za-z0-9_]", "_", stem) or "x"
    return "f_" + s if s[0].isdigit() else s


def _fill(head, block, tail, n):
    """先頭、繰り返しの塊、末尾で、ちょうど n 行にする。足りない所は注釈の行で埋める。"""
    lines = list(head)
    k = 1
    while len(lines) + len(block(k)) + len(tail) <= n:
        lines += block(k)
        k += 1
    while len(lines) + len(tail) < n:
        lines.append("/* filler */")
    return (lines + list(tail))[:n]


def source_text(rel, n):
    """相対パス rel の拡張子に合う、ちょうど n 行の合成のソースコードを返す。"""
    stem = _ident(Path(rel).stem)
    ext = Path(rel).suffix.lower()
    cls = stem[:1].upper() + stem[1:]
    up = stem.upper()
    if ext in (".hpp", ".hh", ".hxx"):
        lines = _fill(["// " + rel, "#pragma once", "namespace %s_ns {" % stem, "class %s {" % cls, "public:"],
                      lambda k: ["    int method_%04d(int x);" % k], ["};", "}  // namespace %s_ns" % stem], n)
    elif ext in (".cpp", ".cc", ".cxx"):
        lines = _fill(["// " + rel, '#include "%s.hpp"' % stem, "namespace %s_ns {" % stem],
                      lambda k: ["int %s::method_%04d(int x)" % (cls, k), "{", "    return x * %d;" % k, "}"],
                      ["}  // namespace %s_ns" % stem], n)
    elif ext == ".h":
        lines = _fill(["/* %s */" % rel, "#ifndef %s_H" % up, "#define %s_H" % up, "#define %s_MAX 16" % up],
                      lambda k: ["int %s_func_%04d(int x);" % (stem, k)], ["#endif"], n)
    else:
        lines = _fill(["/* %s */" % rel, '#include "%s.h"' % stem, "#define %s_LIMIT 16" % up,
                       "static int %s_count = 0;" % stem],
                      lambda k: ["int %s_func_%04d(int x)" % (stem, k), "{",
                                 "    return x + %s_count + %d;" % (stem, k), "}"], [], n)
    return "".join(line + "\n" for line in lines)


def make_source_tree(root, layout=None):
    """合成のソースツリーを root に作り、root を返す。

    layout は {相対パス: 中身}。中身が int なら、その行数の C か C++ のコード（.c、.h、.cpp、.hpp。
    .cpp と .hpp はクラスと名前空間を含む）。str なら UTF-8 で、bytes ならそのまま書く。
    省略すると DEFAULT_LAYOUT（C と C++ の5ファイル）を使う。
    """
    root = Path(root)
    for rel, body in (DEFAULT_LAYOUT if layout is None else layout).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, int):
            data = source_text(rel, body).encode("utf-8")
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = bytes(body)
        with open(p, "wb") as f:
            f.write(data)
    return root


def scaled_layout(total_lines, lines_per_file=1000, files_per_folder=20):
    """合計 total_lines 行の layout（make_source_tree に渡す）を返す。拡張子は .c、.h、.cpp、.hpp を順に使う。"""
    exts = [".c", ".h", ".cpp", ".hpp"]
    layout = {}
    i = 0
    left = total_lines
    while left > 0:
        n = min(lines_per_file, left)
        layout["mod%03d/file%04d%s" % (i // files_per_folder, i, exts[i % 4])] = n
        left -= n
        i += 1
    return layout


def _default_page(n, size):
    num = str(n)
    return [
        (56, 40, "SPEC-DOC-0001"),
        (56, 120, "Chapter %d Scheduler" % n),
        (56, 150, "The task manager starts task %d." % n),
        (size[0] - 56 - len(num) * 6.2, size[1] - 30, num),
    ]


def make_text_pdf(path, pages=3, size=A4):
    """埋め込みテキストつきの PDF を pypdfium2 で作り、path を返す（標準フォントの Helvetica。フォントのファイルは使わない）。

    pages は、ページの数か、ページごとの [(x, y, 文字列) か (x, y, 文字列, 大きさ)] のリスト。
    x と y は左上からのポイントで、y は文字の下端。文字列は ASCII にする。
    ページの数のときは、どのページにも、上端の文書番号、本文の2行、右下のページ番号を置く。
    """
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    specs = [_default_page(i + 1, size) for i in range(pages)] if isinstance(pages, int) else pages
    final = pdfium.PdfDocument.new()
    for c in range(0, len(specs), 50):  # 1つの文書に多くのページを作ると遅くなるので、50 ページずつ作ってつなぐ
        doc = pdfium.PdfDocument.new()
        font = raw.FPDFText_LoadStandardFont(doc.raw, b"Helvetica")
        for i, items in enumerate(specs[c:c + 50]):
            page = raw.FPDFPage_New(doc.raw, i, size[0], size[1])
            for item in items:
                x, y, text = item[:3]
                obj = raw.FPDFPageObj_CreateTextObj(doc.raw, font, ctypes.c_float(item[3] if len(item) > 3 else 11))
                data = text.encode("utf-16-le") + b"\x00\x00"
                buf = ctypes.create_string_buffer(data, len(data))
                raw.FPDFText_SetText(obj, ctypes.cast(buf, raw.FPDF_WIDESTRING))
                raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, size[1] - y)
                raw.FPDFPage_InsertObject(page, obj)
            raw.FPDFPage_GenerateContent(page)
            raw.FPDF_ClosePage(page)
        raw.FPDFFont_Close(font)
        final.import_pages(doc)
        doc.close()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    final.save(str(path))
    final.close()
    return Path(path)


def make_image_pdf(path, pages=2, size=A4):
    """画像だけの PDF（埋め込みテキストがない）を Pillow で作り、path を返す。各ページに、箱と線の図を描く。"""
    from PIL import Image, ImageDraw

    w, h = int(round(size[0])), int(round(size[1]))
    images = []
    for n in range(1, pages + 1):
        img = Image.new("RGB", (w, h), "white")
        d = ImageDraw.Draw(img)
        d.rectangle([60, 100, 260, 180], outline="black", width=3)
        d.rectangle([330, 100, 530, 180], outline="black", width=3)
        d.line([260, 140, 330, 140], fill="black", width=3)
        for k in range(n):  # ページごとに違う絵にする
            d.rectangle([60 + 30 * k, 300, 80 + 30 * k, 320], fill="black")
        images.append(img)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    images[0].save(str(path), "PDF", resolution=72.0, save_all=True, append_images=images[1:])
    return Path(path)


def make_unmapped_pdf(path, pages=1, text="ABCDEF", mapped=""):
    """文字を Unicode に対応づけられない PDF（Type3 のフォントで、ToUnicode がない）を作り、path を返す。

    text の全部の文字で FPDFText_HasUnicodeMapError が 1 になる（SR-37 の判定に当たる）。text は A〜Z だけにする。
    mapped は、各ページの text の下の行に、標準フォントの Helvetica で書く ASCII の文字列である。
    この文字は対応づけられるので、対応づけられない文字の割合を決められる。
    """
    glyphs = sorted(set(text))
    first, last = ord(glyphs[0]), ord(glyphs[-1])
    names = " ".join("/g%d" % c for c in range(first, last + 1))
    procs = " ".join("/g%d %d 0 R" % (c, 4 + 2 * pages) for c in range(first, last + 1))
    widths = " ".join("600" for _ in range(first, last + 1))
    kids = " ".join("%d 0 R" % (3 + 2 * i) for i in range(pages))
    content = b"BT /F1 12 Tf 72 700 Td (" + text.encode("ascii") + b") Tj ET"
    if mapped:
        content += b" BT /F2 12 Tf 72 600 Td (" + mapped.encode("ascii") + b") Tj ET"
    glyph = b"600 0 0 0 500 500 d1 0 0 500 500 re f"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [" + kids.encode() + b"] /Count %d >>" % pages]
    for i in range(pages):
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 %d 0 R"
                    b" /F2 %d 0 R >> >> /Contents %d 0 R >>" % (3 + 2 * pages, 5 + 2 * pages, 4 + 2 * i))
        objs.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 1000 1000] /FontMatrix [0.001 0 0 0.001 0 0]"
                b" /CharProcs << " + procs.encode() + b" >> /Encoding << /Type /Encoding /Differences [%d " % first
                + names.encode() + b"] >> /FirstChar %d /LastChar %d /Widths [" % (first, last)
                + widths.encode() + b"] >>")
    objs.append(b"<< /Length %d >>\nstream\n" % len(glyph) + glyph + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    data = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(data))
        data += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    data += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    data += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return Path(path)


# ---------------------------------------------------------------------------
# 5. 出力先の状態を読む
# ---------------------------------------------------------------------------

def read_text(path):
    """UTF-8 のファイルを読む（先頭の BOM と行末の \\r を外す）。"""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return f.read().replace("\r\n", "\n")


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_state(out):
    """.work/state.json を読む。"""
    return read_json(Path(out) / ".work" / "state.json")


def read_plan(out):
    """.work/plan.json を読む。"""
    return read_json(Path(out) / ".work" / "plan.json")


def jobs_with(out, status=None, kind=None):
    """state.json の仕事のうち、status と kind（省いたものは問わない）に合うものを、ID の順に返す。"""
    return [j for j in read_state(out)["jobs"]
            if (status is None or j["status"] == status) and (kind is None or j["kind"] == kind)]


def tree_hashes(root):
    """root の下の全部のファイルの {相対パス: SHA-1} を返す。前後で比べて、ファイルが変わらないことを確かめる。"""
    root = Path(root)
    result = {}
    for d, dirs, files in os.walk(str(root)):
        dirs.sort()
        for name in sorted(files):
            p = Path(d) / name
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                result[rel] = "symlink:" + os.readlink(str(p))
            else:
                result[rel] = hashlib.sha1(p.read_bytes()).hexdigest()
    return result


# ---------------------------------------------------------------------------
# 3. 担当エージェントの代わり
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-z0-9_]+")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_SCOPED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*::[A-Za-z_][A-Za-z0-9_]*")
_KEYWORDS = {"include", "define", "ifndef", "endif", "pragma", "once", "int", "return", "static", "void",
             "const", "namespace", "class", "public", "struct", "char", "unsigned", "for", "while", "else"}


def _split_lines(text):
    """1.4 の行の数え方で分ける。"""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def code_spans(line):
    """5.1 のコードスパンを返す。"""
    parts = line.split("`")
    return [parts[i] for i in range(1, len(parts) - 1, 2)]


def _span_words(line):
    """コードスパンの語を、(語, 直後が * か) の組で返す。"""
    found = []
    for span in code_spans(line):
        for m in re.finditer(r"([A-Za-z0-9_]+)(\*?)", span):
            found.append((m.group(1), m.group(2) == "*"))
    return found


def _has(words, word, prefix):
    return any(w.startswith(word) for w in words) if prefix else word in words


class _Sources:
    """対象のソースファイル（UTF-8 に直した内容）を読む。"""

    def __init__(self, out, plan):
        self.out = Path(out)
        self.plan = plan
        self.order = [f["path"] for f in plan["files"]]
        self._lines = {}
        self._tokens = {}
        self.path_words = set()
        for rel in self.order:
            self.path_words.update(_WORD.findall(rel))

    def lines(self, rel):
        if rel not in self._lines:
            copy = self.out / ".work" / "src-utf8" / rel
            p = copy if copy.exists() else Path(self.plan["src"]) / rel
            data = p.read_bytes()
            if data.startswith(b"\xef\xbb\xbf"):
                data = data[3:]
            self._lines[rel] = [s.rstrip("\r") for s in _split_lines(data.decode("utf-8", "replace"))]
        return self._lines[rel]

    def tokens(self, rel):
        if rel not in self._tokens:
            self._tokens[rel] = set(_WORD.findall("\n".join(self.lines(rel))))
        return self._tokens[rel]

    def find_name(self, rel, start, end):
        """行の範囲から、名前を1つ（Foo::bar の形を先に）探し、(行, 名前) を返す。なければ None。"""
        lines = self.lines(rel)[start - 1:end]
        for i, line in enumerate(lines, start):
            m = _SCOPED.search(line)
            if m:
                return i, m.group(0)
        for i, line in enumerate(lines, start):
            if line.lstrip().startswith(("//", "/*", "#include")):
                continue
            for w in _NAME.findall(line):
                if w not in _KEYWORDS:
                    return i, w
        return None

    def first_facts(self):
        """ファイルごとに、最初の 150 行から名前を1つ探し、(相対パス, 行, 名前) を返す。"""
        facts = []
        for rel in self.order:
            hit = self.find_name(rel, 1, min(150, len(self.lines(rel))))
            if hit:
                facts.append((rel, hit[0], hit[1]))
        return facts

    def locate(self, words):
        """語の検査（5.3）に合格する根拠の場所を1つ返す。見つからなければ None。"""
        for rel in self.order:
            known = self.tokens(rel) | self.path_words
            if not all(_has(known, w, p) for w, p in words):
                continue
            if any(_has(set(_WORD.findall(rel)), w, p) for w, p in words):
                return "[%s:1-1]" % rel
            for i, line in enumerate(self.lines(rel), 1):
                if any(_has(set(_WORD.findall(line)), w, p) for w, p in words):
                    return "[%s:%d-%d]" % (rel, i, i)
        return None

    def any_location(self):
        return "[%s:1-1]" % self.order[0]


class _Ctx:
    def __init__(self, out):
        self.out = Path(out)
        self.plan = read_plan(out)
        self.state = read_state(out)
        self._src = None

    @property
    def src(self):
        if self._src is None:
            self._src = _Sources(self.out, self.plan)
        return self._src

    @property
    def none_sentence(self):
        return self.plan["none_sentence"]

    def write(self, rel, text):
        # 本物の担当と同じく、親フォルダは作らない（SR-09 は next が作る）。
        with open(self.out / rel, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


def _join(lines):
    return "".join(line + "\n" for line in lines)


def _write_analyze(ctx, job, bad):
    unit = next(u for u in ctx.plan["units"] if u["id"] == job["target"])
    items = []
    spans = []  # ユニットの通し番号での範囲と、ファイルの範囲
    g = 1
    for r in unit["files"]:
        n = r["end"] - r["start"] + 1
        spans.append((g, g + n - 1, r))
        g += n
    for b in range(1, g, 200):  # 200 行ごとの区間に、項目を1つずつ書く
        for gs, ge, r in spans:
            if ge < b or gs > b + 199:
                continue
            s = r["start"] + max(b, gs) - gs
            e = min(r["start"] + min(b + 199, ge) - gs, s + 149)
            hit = ctx.src.find_name(r["path"], s, e)
            text = "`%s` を定義する。" % hit[1] if hit else "この範囲の処理を書く。"
            items.append("- [%s:%d-%d] %s" % (r["path"], s, e, text))
            break
    if bad:
        r = unit["files"][0]
        n = len(ctx.src.lines(r["path"]))
        items.append("- [%s:%d-%d] 範囲がファイルの外を指す。" % (r["path"], n + 1, n + 1))
    lines = ["# " + unit["id"], ""]
    for k, h in enumerate(MEMO_HEADINGS):
        lines += ["## " + h] + ((items or ["- なし"]) if k == 0 else ["- なし"]) + [""]
    ctx.write(job["outputs"][0], _join(lines))


_NEEDS_TICKS = re.compile(r"[<>|*_\\\[\]!#`]")
_LIST_LIKE = re.compile(r"\s*([-+>=]|[0-9]+[.)])")


def _write_convert(ctx, job, bad):
    for rel in job["outputs"]:
        info = read_json(ctx.out / (rel[:-3] + ".json"))
        n = info["page"]
        lines = []
        for u in info["units"]:
            t = u["text"].replace("\r", " ").replace("\n", " ").strip()
            if u["margin"] or not t:
                continue
            if _NEEDS_TICKS.search(t) or _LIST_LIKE.match(t):
                t = "`%s`" % t.replace("`", "'")
            lines += [t, ""]
        if not info["check"]:  # 文字列の検査がないページには、表と図も書く
            lines += ["| 項目 | 値 |", "| --- | --- |", "| ページ | %d |" % n, "",
                      "![ページ %d の図](figure:0.1,0.1,0.9,0.3)" % n, "",
                      "図の説明：ページ %d の箱と線の図である。" % n, "",
                      "```mermaid", "stateDiagram-v2", "    [*] --> s1", "    s1 --> [*]", "```", ""]
        if bad:
            lines += ["__", ""]
        ctx.write(rel, _join(lines))


def _range(a, b):
    return str(a) if a == b else "%d-%d" % (a, b)


def _write_match(ctx, job, bad):
    info = read_json(ctx.out / (job["outputs"][0][:-3] + ".json"))
    facts = ctx.src.first_facts()
    fact = facts[0] if facts else None
    cats = []
    for e in info["lines"]:
        t = e["text"].lstrip()
        if t.startswith("```mermaid"):
            cats.append("一致")
        elif fact and not t.startswith("![") and "食い違い" not in cats:
            cats.append("食い違い")
        else:
            cats.append("既存設計書のみ")
    lines = []
    legacy_count = 0
    i = 0
    while i < len(cats):
        j = i
        while cats[i] != "食い違い" and j + 1 < len(cats) and cats[j + 1] == cats[i]:
            j += 1
        head = "## %s %s" % (_range(info["lines"][i]["n"], info["lines"][j]["n"]), cats[i])
        if cats[i] == "一致":
            lines += [head, "- 場所: " + ctx.src.any_location(), ""]
        elif cats[i] == "食い違い":
            lines += [head, "- 場所: [%s:%d-%d]" % (fact[0], fact[1], fact[1]), "- 名前: " + fact[2],
                      "- 既存の設計書: 既存の設計書では、上限は 1 である。",
                      "- ソースコード: ソースコードでは、上限は 2 である。", ""]
        else:
            module = ctx.plan["modules"][0]["name"] if legacy_count == 0 else "全体"
            legacy_count += 1
            lines += [head, "- モジュール: " + module, "- 内容:", ""]
            in_table = False
            for e in info["lines"][i:j + 1]:
                t = e["text"]
                row = t.lstrip().startswith("|")
                if row and not in_table:  # 表のデータの行が本文の行になるように、見出しの行と区切りの行を付ける
                    cells = len(t.strip().strip("|").split("|"))
                    lines += ["|" + " 列 |" * cells, "|" + " --- |" * cells]
                elif not row and in_table:
                    lines.append("")
                in_table = row
                lines += [t] if row else [t, ""]
            if in_table:
                lines.append("")
        i = j + 1
    if bad:
        lines += ["## 形の違う見出し", ""]
    ctx.write(job["outputs"][0], _join(lines))


def _fact_lines(facts, prefix=None):
    if prefix is None:
        return ["- `%s` を定義する。" % f[2] for f in facts]
    return ["- %s%03d: `%s` を定義する。" % (prefix, k, f[2]) for k, f in enumerate(facts, 1)]


def _sections(headings, bodies, none_sentence):
    lines = []
    for h, body in zip(headings, bodies):
        lines += ["", h, ""] + (body or [none_sentence])
    return lines


def _write_module(ctx, job, bad):
    part = next(p for m in ctx.plan["modules"] for p in m["parts"] if p["name"] == job["target"])
    units = {u["id"]: u for u in ctx.plan["units"]}
    facts = []
    for uid in part["units"]:
        for r in units[uid]["files"]:
            hit = ctx.src.find_name(r["path"], r["start"], min(r["end"], r["start"] + 149))
            if hit and len(facts) < 20:
                facts.append((r["path"], hit[0], hit[1]))
    ns = ctx.none_sentence
    for rel in job["outputs"]:
        if rel.startswith(".work/unknowns/"):
            text = ["- なし"]
        elif rel.startswith("docs/design/"):
            text = ["# " + part["name"]]
            if not bad:
                bodies = [_fact_lines(facts[:1]), _fact_lines(facts)] + [[]] * 8
                text += _sections(["## " + h for h in MODULE_HEADINGS], bodies, ns)
        else:
            text = ["# 3.1 機能（%s）" % part["name"]]
            if not bad:
                text += _sections(["## 機能の要求"], [_fact_lines(facts, part["fr_prefix"])], ns)
        ctx.write(rel, _join(text))


def _write_overall(ctx, job, bad):
    facts = ctx.src.first_facts()
    picked = facts[:1] + [f for f in facts[1:] if "::" in f[2]][:1]
    for rel in job["outputs"]:
        if rel.startswith(".work/unknowns/"):
            ctx.write(rel, "- なし\n")
            continue
        path, title, headings, prefix = next(x for x in OVERALL_FILES if "docs/" + x[0] == rel)
        text = [title]
        if not bad:
            body = _fact_lines(picked, prefix)
            if headings:
                text += _sections(headings, [body] + [[]] * (len(headings) - 1), ctx.none_sentence)
            else:
                text += [""] + (body or [ctx.none_sentence])
        ctx.write(rel, _join(text))


def _fixed(t):
    """NG の直した文：形（表の行、箇条書き、要求の行、段落）を変えずに、文を変える。"""
    t = t.rstrip()
    if t.endswith("|"):
        return t[:-1].rstrip() + "（直した） |"
    return t + "（直した）"


def _write_verify(ctx, job, bad, verdict):
    info = read_json(ctx.out / (job["outputs"][0][:-3] + ".json"))
    lines = []
    for e in info["lines"]:
        t = e["text"]
        n = e["n"]
        if bad:
            lines.append("[%d] OK" % n)
            continue
        block = t.lstrip().startswith("```")
        words = [] if block else _span_words(t)
        has_span = bool(code_spans(t)) and not block
        loc = ctx.src.locate(words) if words else ctx.src.any_location()
        choice = verdict(dict(e, file=info["file"])) if verdict else None
        if choice is None:
            choice = "OK" if (block or has_span) else "対象外"
            if loc is None:
                choice = "不明"
        if choice in ("OK", "NG") and loc is None:
            choice = "不明"
        if choice == "OK":
            lines.append("[%d] OK %s" % (n, loc))
        elif choice == "NG":
            lines.append("[%d] NG %s" % (n, loc) + ("" if block else " " + _fixed(t)))
        elif choice == "不明":
            lines.append("[%d] 不明 %s" % (n, "、".join(w for w, _ in words) or "根拠の語"))
        else:
            lines.append("[%d] 対象外" % n)
    ctx.write(job["outputs"][0], _join(lines))


def _selected(job, sel):
    if isinstance(sel, str):
        sel = (sel,)
    return job["id"] in sel or job["kind"] in sel


def fake_agent(out, bad=(), skip=(), verdict=None):
    """担当エージェントの代わり（12章の最後の項目）。state.json の issued の仕事の outputs に、6章の形式の出力を書く。

    - 出力は、計画と合成の入力から機械的に作り、検査（5章、6章）に合格する。名前は `Foo::bar` の形も書く。
    - bad：仕事の ID か種類（kind）の集まり。当たる仕事には、行数のほかの検査に反する出力を書く
      （analyze は bad_location、convert は double_underscore、match は bad_record、
      write_module と write_overall は missing_heading か empty_section、verify は bad_verdict）。
    - skip：当たる仕事には、何も書かない。
    - verdict：検証の判定を選ぶ関数。番号の行（.work/verify/<ID>.json の lines の項目に "file" を足した辞書）を受け取り、
      "OK"、"NG"、"不明"、"対象外" か None（既定の判定）を返す。
    戻り値は、出力を書いた仕事（state.json の項目）のリスト。
    """
    ctx = _Ctx(out)
    done = []
    for job in ctx.state["jobs"]:
        if job["status"] != "issued" or _selected(job, skip):
            continue
        is_bad = _selected(job, bad)
        kind = job["kind"]
        if kind == "analyze":
            _write_analyze(ctx, job, is_bad)
        elif kind == "convert":
            _write_convert(ctx, job, is_bad)
        elif kind == "match":
            _write_match(ctx, job, is_bad)
        elif kind == "write_module":
            _write_module(ctx, job, is_bad)
        elif kind == "write_overall":
            _write_overall(ctx, job, is_bad)
        elif kind == "verify":
            _write_verify(ctx, job, is_bad, verdict)
        else:
            raise AssertionError("知らない仕事の種類：%r" % kind)
        done.append(job)
    return done


# ---------------------------------------------------------------------------
# 4. init から done まで進める
# ---------------------------------------------------------------------------

def run_to_done(out, src=None, pdf=None, stop_at=None, steps=None, cli=False, cwd=None, **agent):
    """init を呼び、next と fake_agent を、state が done になるまで繰り返す。最後の Result を返す。

    - init が状態を見つけたときは、続きから進む（再開）。
    - エラー（ok が false）の結果が出たら、そこで返す。
    - stop_at：段階の名前（4.2 の stage）。next の後に state.json の段階がこれになったら、代わりの関数を呼ばずに返す。
    - steps：next をこの回数だけ呼んだら返す。
    - agent：fake_agent に渡す引数（bad、skip、verdict）。
    """
    r = revdoc("init", out, src=src, pdf=pdf, cli=cli, cwd=cwd)
    if not r.ok:
        return r
    count = 0
    while True:
        r = revdoc("next", out, cli=cli, cwd=cwd)
        count += 1
        if not r.ok or r.data.get("state") == "done":
            return r
        if stop_at is not None and read_state(out)["stage"] == stop_at:
            return r
        if steps is not None and count >= steps:
            return r
        assert count < 3000, "next を 3,000 回呼んでも done にならない"
        fake_agent(out, **agent)
