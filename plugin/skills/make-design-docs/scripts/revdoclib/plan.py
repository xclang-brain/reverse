"""計画を作る（スクリプトの仕様の2章）。同じ入力からは、どの OS でも同じ計画になる。"""
import hashlib
import os
import re

from . import pdf as pdfmod
from . import values
from .common import Fail

WORD = re.compile(r"[A-Za-z0-9_]+")
_NOT_NAME_CHAR = re.compile(r"[^A-Za-z0-9._\-\u0080-\U0010ffff]")
_NOT_PREFIX_CHAR = re.compile(r"[^A-Z0-9]+")


def rel_path(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


# ---------------------------------------------------------------------------
# 2.1、2.2 対象のソースファイルと文字コード
# ---------------------------------------------------------------------------

def _decode(data):
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    for enc in values.ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return data.decode(values.FALLBACK_ENCODING), values.FALLBACK_ENCODING


def _line_bytes(text):
    """行ごとのバイト数（行末の \\n と \\r を含む）。"""
    parts = text.split("\n")
    sizes = [len(p.encode("utf-8")) + 1 for p in parts[:-1]]
    if parts[-1]:
        sizes.append(len(parts[-1].encode("utf-8")))
    return sizes


def _classify(path):
    """(外す理由,) か、(None, 元のバイト列, UTF-8 に直した内容, 文字コード, 行ごとのバイト数) を返す。"""
    size = os.path.getsize(path)
    if size == 0:
        return ("empty",)
    with open(path, "rb") as f:
        head = f.read(values.BINARY_PROBE_BYTES)
        if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return ("utf16",)
        if b"\x00" in head:
            return ("binary",)
        if size > values.MAX_FILE_BYTES:
            return ("too_large",)
        data = head + f.read()
    text, enc = _decode(data)
    sizes = _line_bytes(text)
    if any(n > values.MAX_LINE_BYTES for n in sizes):
        return ("long_line",)
    return None, data, text, enc, sizes


def scan_sources(src, out):
    """(files, excluded, 行ごとのバイト数, UTF-8 のコピーの内容, 語の集まり) を返す。files は 2.3 の 1 の順。"""
    out_key = os.path.normcase(os.path.abspath(out))
    found, excluded, sizes, copies, words = [], [], {}, {}, set()
    for d, dirs, names in os.walk(src):
        keep = []
        for name in sorted(dirs):
            full = os.path.join(d, name)
            if name in values.VCS_DIRS or os.path.normcase(os.path.abspath(full)) == out_key:
                continue
            if os.path.islink(full):
                excluded.append({"path": rel_path(full, src), "reason": "symlink"})
            else:
                keep.append(name)
        dirs[:] = keep
        for name in names:
            full = os.path.join(d, name)
            rel = rel_path(full, src)
            if os.path.islink(full):
                reason = ("symlink",)
            elif not os.path.isfile(full):
                continue
            elif "." in name and name.rsplit(".", 1)[1].lower() in values.EXCLUDED_EXTENSIONS:
                reason = ("extension",)
            else:
                reason = _classify(full)
            if reason[0]:
                excluded.append({"path": rel, "reason": reason[0]})
                continue
            _, data, text, enc, line_sizes = reason
            sizes[rel] = line_sizes
            if enc != "utf-8":
                copies[rel] = text
            words.update(WORD.findall(text))
            words.update(WORD.findall(rel))
            found.append({"path": rel, "sha1": hashlib.sha1(data).hexdigest(), "lines": len(line_sizes),
                          "bytes": sum(line_sizes), "encoding": enc})
    found.sort(key=lambda f: f["path"].rpartition("/")[::2])
    excluded.sort(key=lambda e: e["path"])
    return found, excluded, sizes, copies, words


# ---------------------------------------------------------------------------
# 2.3 ユニット
# ---------------------------------------------------------------------------

def _ranges(sizes):
    """ファイルを、上限に収まる最大の行数ずつに分ける。[(開始行, 終了行, バイト数)] を返す。"""
    ranges = []
    start, n, b = 1, 0, 0
    for size in sizes:
        if n + 1 > values.UNIT_MAX_LINES or b + size > values.UNIT_MAX_BYTES:
            ranges.append((start, start + n - 1, b))
            start, n, b = start + n, 0, 0
        n += 1
        b += size
    if n:
        ranges.append((start, start + n - 1, b))
    return ranges


def make_units(files, sizes):
    units = []
    cur = None
    for f in files:
        folder = f["path"].rpartition("/")[0]
        for s, e, b in _ranges(sizes[f["path"]]):
            n = e - s + 1
            if (cur is None or cur["folder"] != folder or cur["lines"] + n > values.UNIT_MAX_LINES
                    or cur["bytes"] + b > values.UNIT_MAX_BYTES):
                cur = {"folder": folder, "lines": 0, "bytes": 0, "files": []}
                units.append(cur)
            cur["lines"] += n
            cur["bytes"] += b
            cur["files"].append({"path": f["path"], "start": s, "end": e})
    return units


# ---------------------------------------------------------------------------
# 2.4 モジュールと名前
# ---------------------------------------------------------------------------

def _clean(segment):
    segment = _NOT_NAME_CHAR.sub("_", segment)
    return "_" + segment[1:] if segment.startswith(".") else segment


def _reserved(segment):
    # 担当エージェントのツールが、この語で始まるファイル名を書けないため（SR-79）。
    return "m-" + segment if segment.lower().startswith(values.RESERVED_NAME_HEADS) else segment


def _unique(base, taken):
    """大文字と小文字を区別せずに重なりを調べ、重なるときは -2、-3、…を付ける。"""
    name, k = base, 2
    while name.lower() in taken:
        name, k = "%s-%d" % (base, k), k + 1
    taken.add(name.lower())
    return name


def folder_name(folder, taken):
    segments = [_clean(s) for s in folder.split("/")] if folder else ["_root"]
    segments[-1] = _reserved(segments[-1])
    return _unique("/".join(segments), taken)


def _fr_prefix(name, order, part, used):
    core = _NOT_PREFIX_CHAR.sub("-", name.upper()).strip("-") or "M%03d" % order
    if part:
        core += "-P%d" % part
    base, k = core, 2
    while "FR-%s-" % core in used:
        core, k = "%s-%d" % (base, k), k + 1
    used.add("FR-%s-" % core)
    return "FR-%s-" % core


def make_modules(files, units):
    """files は 2.3 の 1 の順、units はユニットの順（どちらもフォルダの順に並んでいる）。"""
    folders = {}
    for f in files:
        m = folders.setdefault(f["path"].rpartition("/")[0], {"files": 0, "lines": 0, "units": []})
        m["files"] += 1
        m["lines"] += f["lines"]
    for u in units:
        folders[u["folder"]]["units"].append(u)
    taken, used, modules = set(), set(), []
    for order, (folder, m) in enumerate(folders.items(), 1):
        name = folder_name(folder, taken)
        ids = [u["id"] for u in m["units"]]
        chunks = [ids[i:i + values.UNITS_PER_PART] for i in range(0, len(ids), values.UNITS_PER_PART)] or [[]]
        split = len(chunks) > 1
        parts = [{"name": _unique("%s/%d" % (name, k), taken) if split else name, "units": chunk,
                  "fr_prefix": _fr_prefix(name, order, k if split else 0, used)}
                 for k, chunk in enumerate(chunks, 1)]
        modules.append({"name": name, "folder": folder, "files": m["files"], "lines": m["lines"], "parts": parts})
        for u in m["units"]:
            u["module"] = name
    return modules


# ---------------------------------------------------------------------------
# 2.5 PDF
# ---------------------------------------------------------------------------

def list_pdfs(path):
    if os.path.isfile(path):
        return [os.path.basename(path)]
    found = []
    for d, _, names in os.walk(path):
        found += [rel_path(os.path.join(d, n), path) for n in names if n.lower().endswith(".pdf")]
    return sorted(found)


def make_pdfs(path):
    rels = list_pdfs(path)
    if not rels:
        raise Fail("no_pdf_files", "PDF のフォルダに、PDF のファイルが1つもない。")
    root = path if os.path.isdir(path) else os.path.dirname(path)
    taken, pdfs = set(), []
    for k, rel in enumerate(rels, 1):
        full = os.path.join(root, *rel.split("/"))
        try:
            pages, text_check, margins = pdfmod.read_pdf(full)
        except ValueError as e:
            raise Fail("pdf_unreadable", "PDF を開けない：%s（%s）" % (rel, e))
        with open(full, "rb") as f:
            sha1 = hashlib.sha1(f.read()).hexdigest()
        name = rel.rpartition("/")[2]
        stem = name[:-len(".pdf")]
        pdfs.append({"id": "D%02d" % k, "path": rel, "name": name,
                     "folder": _unique(_reserved(_clean(stem)), taken), "sha1": sha1, "pages": pages,
                     "text_check": text_check, "margins": margins})
    return pdfs


# ---------------------------------------------------------------------------
# 2.7、2.8 仕事と計画のファイル
# ---------------------------------------------------------------------------

def make_jobs(units, pdfs, modules, with_src):
    jobs = [("analyze", u["id"]) for u in units]
    for p in pdfs:
        for first in range(1, p["pages"] + 1, values.CONVERT_PAGES):
            last = min(first + values.CONVERT_PAGES - 1, p["pages"])
            jobs.append(("convert", "%s:%d-%d" % (p["id"], first, last)))
    jobs += [("write_module", part["name"]) for m in modules for part in m["parts"]]
    if with_src:
        jobs += [("write_overall", path) for path, _ in values.OVERALL_FILES]
    return [{"id": "J%05d" % k, "kind": kind, "target": t} for k, (kind, t) in enumerate(jobs, 1)]


def build(src, pdf, out):
    """計画を作る。(計画, UTF-8 のコピーの内容, 語の集まり) を返す。src と pdf は絶対パスか None。"""
    mode = "both" if src and pdf else ("source" if src else "pdf")
    pdfs = make_pdfs(pdf) if pdf else []
    files, excluded, units, modules, copies, words = [], [], [], [], {}, set()
    if src:
        files, excluded, sizes, copies, words = scan_sources(src, out)
        if not files:
            raise Fail("no_source_files", "ソースコードのフォルダに、対象のソースファイルが1つもない。")
        units = make_units(files, sizes)
        for k, u in enumerate(units, 1):
            u["id"] = "U%04d" % k
        modules = make_modules(files, units)
        units = [{"id": u["id"], "module": u["module"], "lines": u["lines"], "bytes": u["bytes"],
                  "files": u["files"]} for u in units]
    plan = {"version": 1, "mode": mode, "src": src, "pdf": pdf, "none_sentence": values.NONE_SENTENCES[mode],
            "files": files, "excluded": excluded, "units": units, "modules": modules, "pdfs": pdfs,
            "jobs": make_jobs(units, pdfs, modules, bool(src))}
    return plan, copies, words


def changed_paths(old, new):
    """2つの計画で、片方にしかないパスと、sha1 が違うパス（3章）。文字の順。"""
    a = {f["path"]: f["sha1"] for key in ("files", "pdfs") for f in old[key]}
    b = {f["path"]: f["sha1"] for key in ("files", "pdfs") for f in new[key]}
    return sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))


def path_too_long(out, plan, windows):
    """Windows で、作るファイルのパスが長すぎるか（1.3）。"""
    if not windows:
        return False
    rels = []
    parts = [p["name"] for m in plan["modules"] for p in m["parts"]]
    if parts:
        job = max((j["id"] for j in plan["jobs"]), key=len)
        part = max(parts, key=len)
        rels.append(".work/rejected/%s-2/docs/requirements/3-1-functions/%s.md" % (job, part))
    if plan["files"]:
        rels.append(".work/src-utf8/" + max((f["path"] for f in plan["files"]), key=len))
    return any(len(os.path.join(out, rel)) > values.WINDOWS_MAX_PATH for rel in rels)
