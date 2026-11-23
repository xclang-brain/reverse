"""Markdown の読み方と、共通の検査（スクリプトの仕様の5章）。"""
import bisect
import collections
import os
import posixpath
import re

from . import files, values

WORD = re.compile(r"[A-Za-z0-9_]+")
LOCATION = re.compile(r"\[(.+?):([0-9]+)-([0-9]+)\]")
_HEADING = re.compile(r"(#{1,6})\s")
FENCE = re.compile(r" {0,3}```")
BULLET = re.compile(r"\s*([-*+]|[0-9]+\.) ")
IMAGE_LINE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_SPAN_WORD = re.compile(r"([A-Za-z0-9_]+)(\*?)")
_QUOTED = re.compile(r'"[^"]*"')
_ENTITY = re.compile(r"#[A-Za-z0-9]+;")
_LABEL = re.compile(r"[\[({][^\[\](){}]*[A-Za-z0-9][^\[\](){}]*[\])}]")
_FILE_LINE = re.compile(r"[A-Za-z0-9_\-]+\.[A-Za-z0-9]+:[0-9]+")
_RECORD_NO = re.compile(r"E[0-9]{4,}")
_MARK_LIKE = re.compile(r"【(既存|判読)[^】]*】")
_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]*)")
_SPAN = re.compile(r"`[^`]*`")
_NAME_SPAN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\*?")

# 本文の行（5.2）になる要素の種類
BODY = ("text", "table_row", "code")

# 1つの要素。行番号（start、end）は 0 からの添え字。code の end は閉じる行（閉じていなければ最後の行）。
Elem = collections.namedtuple("Elem", "kind start end level closed")

MERMAID_DETAILS = {
    "M1": "ブロックが閉じていない。",
    "M2": "1行目が、使える図の種類でない。",
    "M3": "図の中身がない。",
    "M4": "二重引用符の数が奇数である。",
    "F1": "引用符の外に、ASCII でない文字がある。",
    "F2": "引用符で囲んでいないラベルがある。",
    "F3": "引用符で囲んでいない矢印のラベルがある。",
    "F4": "予約語（end、class、graph、style、subgraph）を ID に使っている。",
    "S1": "ラベルの外に、ASCII でない文字がある。",
    "S2": "ラベルに ; がある。",
    "Q1": "メッセージに ; か # がある。",
    "Q2": "参加者の ID に、ASCII でない文字がある。",
}


# ---------------------------------------------------------------------------
# 5.1、5.2 読み方
# ---------------------------------------------------------------------------

def code_spans(line):
    parts = line.split("`")
    return [parts[i] for i in range(1, len(parts) - 1, 2)]


def outside_spans(line):
    """コードスパンを空白1つに置き換えた行。"""
    parts = line.split("`")
    keep = parts[0::2]
    if len(parts) % 2 == 0:  # 対にならない最後のバッククォートの後ろは、コードスパンの外
        keep.append(parts[-1])
    return " ".join(keep)


def span_words(text):
    """コードスパンの語を、(語, 直後が * か) の組で返す。"""
    return [(m.group(1), m.group(2) == "*") for s in code_spans(text) for m in _SPAN_WORD.finditer(s)]


def heading_level(line):
    m = _HEADING.match(line)
    return len(m.group(1)) if m else 0


def parse(lines):
    """行を、5.1 と 5.2 の要素（Elem）の並びにする。"""
    elems, i, row = [], 0, 0
    while i < len(lines):
        line = lines[i]
        if FENCE.match(line):
            j = i + 1
            while j < len(lines) and lines[j].strip() != "```":
                j += 1
            closed = j < len(lines)
            elems.append(Elem("code", i, j if closed else len(lines) - 1, 0, closed))
            i, row = j + 1, 0
            continue
        s = line.strip()
        level = heading_level(line)
        if s.startswith("|"):
            kind = ("table_head", "table_sep", "table_row")[min(row, 2)]
            row += 1
        else:
            row = 0
            if not s:
                kind = "blank"
            elif level:
                kind = "heading"
            elif s.startswith("<!--") and s.endswith("-->"):
                kind = "comment"
            else:
                kind = "text"
        elems.append(Elem(kind, i, i, level, True))
        i += 1
    return elems


def elem_text(lines, e):
    return "\n".join(lines[e.start:e.end + 1])


def is_mermaid(lines, e):
    return e.kind == "code" and lines[e.start].strip().startswith("```mermaid")


def outside_code(lines, elems):
    """コードブロックの外の行を、(添え字, 行) で返す。"""
    return [(e.start, lines[e.start]) for e in elems if e.kind != "code"]


# ---------------------------------------------------------------------------
# 5.3 根拠の場所と、語の検査
# ---------------------------------------------------------------------------

class Words:
    """語の集まり。「その語で始まる語」も探せるように、並べたものも持つ。"""

    def __init__(self, words):
        self.set = set(words)
        self.sorted = sorted(self.set)

    def has(self, word, prefix=False):
        if not prefix:
            return word in self.set
        i = bisect.bisect_left(self.sorted, word)
        return i < len(self.sorted) and self.sorted[i].startswith(word)


class Sources:
    """対象のソースファイル（UTF-8 に直した内容）を読む。"""

    def __init__(self, out, plan):
        self.out, self.plan = out, plan
        self.files = {f["path"]: f for f in plan["files"]}
        self.path_words = Words(w for rel in self.files for w in WORD.findall(rel))
        self._lines, self._words, self._names = {}, {}, None

    def read_path(self, rel):
        """担当エージェントに読ませるパス（2.2）。"""
        if self.files[rel]["encoding"] != "utf-8":
            return os.path.join(self.out, ".work", "src-utf8", *rel.split("/"))
        return os.path.join(self.plan["src"], *rel.split("/"))

    def lines(self, rel):
        if rel not in self._lines:
            self._lines[rel] = files.split_lines(files.read_text(self.read_path(rel)))
        return self._lines[rel]

    def words(self, rel):
        if rel not in self._words:
            self._words[rel] = Words(WORD.findall("\n".join(self.lines(rel))))
        return self._words[rel]

    @property
    def names(self):
        """名前の集まり（2.9）。"""
        if self._names is None:
            self._names = Words(files.split_lines(files.read_text(os.path.join(self.out, ".work", "names.txt"))))
        return self._names

    def location_problem(self, rel, start, end, limit=True):
        """根拠の場所が正しくないときは、その説明を返す。"""
        loc = "`[%s:%d-%d]`" % (rel, start, end)
        if rel not in self.files:
            return "根拠の場所 %s のファイルが、対象のソースファイルにない。相対パスを直す。" % loc
        n = self.files[rel]["lines"]
        if not 1 <= start <= end <= n:
            return "根拠の場所 %s の行番号が、ファイルの行数（%d 行）の範囲にない。行番号を直す。" % (loc, n)
        if limit and end - start + 1 > values.MAX_LOCATION_LINES:
            return "根拠の場所 %s の範囲が %d 行を超える。範囲を狭める。" % (loc, values.MAX_LOCATION_LINES)
        return None

    def word_problems(self, locations, text, memo=False):
        """語の検査（5.3）。locations は正しい根拠の場所の (相対パス, 開始行, 終了行)。(検査の名前, 説明) を返す。
        memo のとき（解析メモ）は、(a) を根拠のファイルの代わりに名前の集まりと照らす。"""
        words = span_words(text)
        if not words:
            return []
        found = []
        known = [self.names] if memo else [self.words(r) for r, _, _ in locations]
        unknown = [w for w, p in words if not (self.path_words.has(w, p) or any(k.has(w, p) for k in known))]
        if unknown:
            found.append(("unknown_word", "`%s` が、%sにない。" % ("`、`".join(unknown), "ソースコード" if memo else "根拠のファイル")))
        ranges = [Words(WORD.findall("\n".join(self.lines(r)[s - 1:e]) + "\n" + r)) for r, s, e in locations]
        if not any(r.has(w, p) for r in ranges for w, p in words):
            found.append(("no_word_in_range", "バッククォートの中の語が、根拠の場所の行の範囲に1つもない。"))
        return found


# ---------------------------------------------------------------------------
# 5.4 Mermaid の検査
# ---------------------------------------------------------------------------

def _first_word(text):
    m = WORD.search(text)
    return m.group(0) if m else ""


def _non_ascii(text):
    return any(ord(c) > 127 for c in text)


def _row_codes(kind, s):
    """図の中身の1行に当たる番号の並び。s は前後の空白を除いた行。"""
    q = _QUOTED.sub('""', s)
    codes = ["M4"] if s.count('"') % 2 else []
    if kind == "flowchart":
        words = WORD.findall(q)
        if _non_ascii(q):
            codes.append("F1")
        if not s.startswith(values.FLOWCHART_UNCHECKED) and _LABEL.search(q.replace('""', "")):
            codes.append("F2")
        if "|" in q.replace('|""|', ""):
            codes.append("F3")
        if any(w in values.FLOWCHART_RESERVED for w in words[1:]) or (words[:1] == ["end"] and s != "end"):
            codes.append("F4")
    elif kind == "stateDiagram-v2":
        if _non_ascii(q.split(":", 1)[0]):
            codes.append("S1")
        if ";" in _ENTITY.sub("", q):
            codes.append("S2")
    elif kind == "sequenceDiagram":
        e = _ENTITY.sub("", s)
        if ";" in e or "#" in e:
            codes.append("Q1")
        if _first_word(s) not in values.SEQUENCE_UNCHECKED and _non_ascii(s.split(":", 1)[0].split(" as ", 1)[0]):
            codes.append("Q2")
    return codes


def mermaid_problems(lines, elems):
    """Mermaid のブロックの検査。(行番号, 番号, 説明) のリストを返す。行番号は 1 から。"""
    found = []
    for e in elems:
        if not is_mermaid(lines, e):
            continue
        stop = e.end if e.closed else e.end + 1
        rows = [(k, lines[k].strip()) for k in range(e.start + 1, stop)]
        rows = [(k, s) for k, s in rows if s and not s.startswith("%%")]
        codes = [] if e.closed else ["M1"]
        header = rows[0][1] if rows else ""
        if header not in values.MERMAID_HEADERS:
            codes.append("M2")
        if len(rows) < 2:
            codes.append("M3")
        found += [(e.start + 1, c) for c in codes]
        kind = header.split()[0] if header in values.MERMAID_HEADERS else ""
        for k, s in rows[1:]:
            found += [(k + 1, c) for c in _row_codes(kind, s)]
    return [(n, c, "%s：%s" % (c, MERMAID_DETAILS[c])) for n, c in found]


# ---------------------------------------------------------------------------
# 5.5 行の検査
# ---------------------------------------------------------------------------

def checked_body(lines, elems):
    """行の検査と検証の対象になる範囲の要素（スクリプトが入れた見出しより前）。"""
    for e in elems:
        if e.kind == "heading" and lines[e.start].strip() == values.LEGACY_HEADING:
            return
        yield e


def line_problems(lines, elems):
    """本文の行（コードブロックを除く）の検査。(行番号, 検査の名前, 説明) のリストを返す。"""
    found = []
    for e in checked_body(lines, elems):
        if e.kind not in ("text", "table_row"):
            continue
        found += [(e.start + 1, rule, detail) for rule, detail in sentence_problems(lines[e.start])]
    return found


def sentence_problems(line):
    """1行の文の検査（5.5）。検証の「直した文」にも使う。"""
    found = []
    if any(w in line for w in values.SPECULATIONS):
        found.append(("speculation", "推測の言い回しがある。ソースコードで確かめた事実だけを書く。"))
    if _FILE_LINE.search(line) or any(_RECORD_NO.fullmatch(w) for w in WORD.findall(outside_spans(line))):
        found.append(("file_line", "ファイル名と行番号か、照合の記録の番号を書いている。消す。"))
    if any(m.group(0) not in values.MARKS for m in _MARK_LIKE.finditer(line)) or values.MARKS[0] in line:
        found.append(("bad_mark", "印の書き方が違う。【既存設計書のみ】は書かない。"))
    return found


# ---------------------------------------------------------------------------
# 5.6 番号を振った行
# ---------------------------------------------------------------------------

# 番号を振る1個（照合では文、検証では行）。elem は、それがある要素。
Row = collections.namedtuple("Row", "elem text")


def span_positions(line):
    """コードスパン（対になるバッククォートとその間）の文字の位置の集まり。"""
    ticks = [i for i, c in enumerate(line) if c == "`"]
    return {i for a, b in zip(ticks[0::2], ticks[1::2]) for i in range(a, b + 1)}


def sentences(lines, e):
    """要素を文に分けた Row のリスト。段落と箇条書きの項目だけを、コードスパンの外の文の終わりのすぐ後ろで分ける。"""
    text = elem_text(lines, e)
    s = text.strip()
    if e.kind != "text" or IMAGE_LINE.fullmatch(s) or s.startswith(values.FIGURE_NOTE):
        return [Row(e, text)]
    inside = span_positions(text)
    found, start = [], 0
    for i, c in enumerate(text):
        if c in values.SENTENCE_ENDS and i not in inside and text[i + 1:].strip():
            found.append(Row(e, text[start:i + 1]))
            start = i + 1
    return found + [Row(e, text[start:])]


def split_numbered(elems, rows, limit):
    """番号を振る Row（rows。対象にする要素から、その Row のリストへの辞書）を、節の切れ目で limit 個までの仕事に分ける。"""
    sections, cur = [], []
    for e in elems:
        if e.kind == "heading":
            sections.append(cur)
            cur = []
        elif e in rows:
            cur += rows[e]
    sections.append(cur)
    jobs, cur = [], []
    for sec in sections:
        if cur and len(cur) + len(sec) > limit:
            jobs.append(cur)
            cur = []
        cur = cur + sec
        while len(cur) > limit:
            jobs.append(cur[:limit])
            cur = cur[limit:]
    if cur:
        jobs.append(cur)
    return jobs


def write_numbered(out, folder, job_id, rel, lines, elems, chunk, extra):
    """番号を振った行の2つのファイルを書く。chunk は Row のリスト。extra は、要素を受け取り、JSON の項目に足す値を返す関数。"""
    first, last = chunk[0].elem, chunk[-1].elem
    head = ["# " + rel]
    before = [e for e in elems if e.start < first.start]
    heading = next((e for e in reversed(before) if e.kind == "heading"), None)
    if heading is not None:
        head.append(lines[heading.start])
    if first.kind == "table_row":
        table_head = next(e for e in reversed(before) if e.kind == "table_head")
        head += [lines[table_head.start], lines[table_head.start + 1]]
    numbers = {}
    for n, r in enumerate(chunk, 1):
        numbers.setdefault(r.elem.start, []).append("[%d] %s" % (n, r.text.split("\n")[0]))
    body = []
    for k in range(first.start, last.end + 1):
        if lines[k].strip():
            body += numbers.get(k, [lines[k]])
    base = os.path.join(out, *folder.split("/"))
    files.write_text(os.path.join(base, job_id + ".lines.md"), "".join(x + "\n" for x in head + body))
    entries = [dict({"n": n, "line": r.elem.start + 1, "text": r.text}, **extra(r.elem))
               for n, r in enumerate(chunk, 1)]
    files.write_text(os.path.join(base, job_id + ".json"),
                     files.dumps({"file": rel, "count": len(chunk), "lines": entries}))


# ---------------------------------------------------------------------------
# 5.7 リンクの検査、5.8 名前の検査
# ---------------------------------------------------------------------------

def _checked_links(line):
    """5.7 で調べるリンクの match。コードスパンを同じ長さの空白にして探すので、位置は元の行と同じである。"""
    masked = _SPAN.sub(lambda m: " " * len(m.group()), line)
    return [m for m in _LINK.finditer(masked)
            if not m.group(1).startswith(("http:", "https:", "mailto:", "#"))]


def _resolve(rel, path):
    """rel のファイルからのリンクのパスを、出力先からの相対パスにする。# より後ろは取り除く。"""
    return posixpath.normpath(posixpath.join(posixpath.dirname(rel), path.split("#", 1)[0]))


def link_problems(rel, lines, elems, known):
    """rel は出力先からの相対パス。known は、出力先からの相対パスを受け取り、あるか決まった出力かを返す関数。"""
    return [(k + 1, "broken_link", "リンク先 %s がない。" % m.group(1))
            for k, line in outside_code(lines, elems) for m in _checked_links(line)
            if not known(_resolve(rel, m.group(1)))]


def rebase_links(line, rel, folder):
    """rel のファイルの1行のリンクのパスを、folder（出力先からの相対パス）からの相対パスに書き換える。"""
    found, last = [], 0
    for m in _checked_links(line):
        frag = m.group(1).partition("#")
        found += [line[last:m.start(1)], posixpath.relpath(_resolve(rel, m.group(1)), folder) + frag[1] + frag[2]]
        last = m.end(1)
    return "".join(found) + line[last:]


def load_names(out, plan):
    """名前の検査（5.8）で照らす語の集まり。"""
    words = set(files.split_lines(files.read_text(os.path.join(out, ".work", "names.txt"))))
    for m in plan["modules"]:
        for name in [m["name"]] + [p["name"] for p in m["parts"]]:
            words.update(WORD.findall(name))
    legacy = os.path.join(out, "docs", "legacy")
    for d, _, names in os.walk(legacy):
        for name in names:
            if name.endswith(".md"):
                words.update(WORD.findall(files.read_text(os.path.join(d, name))))
    return Words(words)


def name_problems(line, names):
    """1行のコードスパンの名前の検査（5.8）。不合格の名前のリストを返す。"""
    bad = []
    for span in code_spans(line):
        if _NAME_SPAN.fullmatch(span):
            prefix = span.endswith("*")
            if not names.has(span.rstrip("*"), prefix):
                bad.append(span)
    return bad
