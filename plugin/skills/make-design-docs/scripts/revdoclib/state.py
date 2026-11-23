"""next：渡した仕事の出力を検査し、次の仕事を渡す（スクリプトの仕様の4章）。"""
import os

from . import files, finish, instructions, jobchecks, markdown, scriptwork, values
from . import pdf as pdfmod
from .common import Fail, cmd

JOBS_DO = ("Start one foreground subagent per job in a single message: type = the job's agent,"
           " prompt = \"Read the file OUT/FILE and follow it.\" (OUT: the --out folder below,"
           " FILE: the job's file). When all of them have returned, run: ")
DONE_DO = "All jobs are finished. Run: "


class Ctx:
    """1回の next で使う、出力先と計画と状態。"""

    def __init__(self, out):
        self.out = out
        self.plan = files.read_json(self.abs(".work/plan.json"))
        self.state = files.read_json(self.abs(".work/state.json"))
        self._sources = None
        self._names = None

    def abs(self, rel):
        return os.path.join(self.out, *rel.split("/"))

    @property
    def sources(self):
        if self._sources is None:
            self._sources = markdown.Sources(self.out, self.plan)
        return self._sources

    @property
    def names(self):
        """名前の検査（5.8）で照らす語の集まり。"""
        if self._names is None:
            self._names = markdown.load_names(self.out, self.plan)
        return self._names

    def pdf_path(self, pdf):
        root = self.plan["pdf"]
        return os.path.join(root, *pdf["path"].split("/")) if os.path.isdir(root) else root

    def save(self):
        files.write_atomic(self.abs(".work/state.json"), files.dumps(self.state))


# ---------------------------------------------------------------------------
# 4.5 不合格と失敗
# ---------------------------------------------------------------------------

def _substitute(ctx, job, rel):
    """3回目に出力がなかったファイルの、代わりの中身（4.5 の表）。"""
    kind, target = job["kind"], job["target"]
    if rel.startswith(".work/unknowns/"):
        lines = ["- なし"]
    elif kind == "analyze":
        unit = next(u for u in ctx.plan["units"] if u["id"] == target)
        lines = ["# " + target, "", "解析できなかった。ソースコードを直接読む。", ""]
        lines += ["- %s（%d-%d 行）" % (r["path"], r["start"], r["end"]) for r in unit["files"]]
    elif kind == "convert":
        n = int(rel.rpartition("/")[2][:-3])
        lines = ["## 変換できなかったページ", "", "![ページ %d](figure:0,0,1,1)" % n, "",
                 "図の説明：このページは変換できなかった。ページの全体を画像で載せる。"]
    elif kind == "match":
        count = files.read_json(ctx.abs(".work/match/%s.json" % job["id"]))["count"]
        lines = ["## 1-%d 照合していない" % count]
    elif kind == "write_module" and rel.startswith("docs/design/"):
        units = [u for m in ctx.plan["modules"] for p in m["parts"] if p["name"] == target for uid in p["units"]
                 for u in ctx.plan["units"] if u["id"] == uid]
        paths = list(dict.fromkeys(r["path"] for u in units for r in u["files"]))
        lines = ["# " + target, "", "この設計書は作れなかった。ソースコードを直接読む。", ""] + ["- " + p for p in paths]
    elif kind == "write_module":
        lines = ["# 3.1 機能（%s）" % target, "", "この文書は作れなかった。"]
    else:
        lines = files.split_lines(files.read_text(ctx.abs(".work/templates/" + target.rpartition("/")[2])))
    return "".join(x + "\n" for x in lines)


def _apply(ctx, job, found):
    """検査の結果で、仕事の状態を変え、ファイルを動かす。"""
    job["reasons"] = found
    if not found:
        job["status"] = "done"
        return
    job["tries"] += 1
    if (job["tries"] == values.MAX_TRIES and job["kind"] == "analyze"
            and all(x["rule"] == "too_long" for x in found)):
        job["status"] = "done"  # 行数だけが多い解析メモは、3回目にはそのまま使う（SR-11）
        return
    job["outputs"] = [rel for rel in job["outputs"] if any(x["file"] == rel for x in found)]
    if job["tries"] < values.MAX_TRIES:
        for rel in job["outputs"]:
            if os.path.isfile(ctx.abs(rel)):
                dest = ctx.abs(".work/rejected/%s-%d/%s" % (job["id"], job["tries"], rel))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                files.fs_op(os.replace, ctx.abs(rel), dest)
        job["status"] = "pending"
        return
    job["status"] = "failed"
    # 検証の仕事には代わりのファイルを置かない。その仕事の行は、次の回の対象になる（8.5）。
    job["substitute"] = [rel for rel in job["outputs"] if job["kind"] != "verify" and not os.path.isfile(ctx.abs(rel))]
    for rel in job["substitute"]:
        files.write_text(ctx.abs(rel), _substitute(ctx, job, rel))


def _settle(ctx, jobs, empty):
    """渡した仕事の出力を調べる。empty は、全部の仕事に出力がない回（4.6）か。"""
    if not empty and jobs[0]["kind"] == "verify":
        scriptwork.apply_verdicts(ctx, jobs)
        return
    # 変換の欠けと余分は、前後のページの出力も見るので、全部を検査してからファイルを動かす。
    results = [(job, [jobchecks.missing(rel) for rel in job["outputs"]] if empty else jobchecks.check(ctx, job))
               for job in jobs]
    for job, found in results:
        _apply(ctx, job, found)
    for job, _ in results:
        if job["kind"] in ("write_module", "write_overall") and job["status"] != "pending":
            scriptwork.insert_legacy(ctx, job)


# ---------------------------------------------------------------------------
# 4.2、4.4 段階と、仕事を渡す
# ---------------------------------------------------------------------------

ENTER = {"match": scriptwork.make_match_jobs, "verify_module": scriptwork.enter_verify,
         "verify_overall": scriptwork.enter_verify}
EXIT = {"convert": scriptwork.assemble, "match": scriptwork.distribute, "verify_module": scriptwork.write_digest}
VERIFY_STAGES = ("verify_module", "verify_overall")


def _advance(ctx):
    """今の段階を終え、次の段階に入る。最後の段階の後は、仕上げをして done にする。"""
    st = ctx.state
    EXIT.get(st["stage"], lambda c: None)(ctx)
    st["round"] = 0
    stages = values.STAGES
    nxt = next(s for s in stages[stages.index(st["stage"]) + 1:] if ctx.plan["mode"] in values.STAGE_MODES[s])
    if nxt == "done":
        finish.run(ctx)
    st["stage"] = nxt
    ENTER.get(nxt, lambda c: None)(ctx)


def _issue(ctx, jobs):
    for job in jobs:
        for rel in job["outputs"]:
            path = ctx.abs(rel)
            if os.path.isfile(path):
                files.fs_op(os.remove, path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
        if job["kind"] == "convert":
            pdf = next(p for p in ctx.plan["pdfs"] if p["id"] == job["target"].split(":")[0])
            pages = {int(rel.rpartition("/")[2][:-3]) + d for rel in job["outputs"] for d in (-1, 0, 1)}
            pdfmod.prepare_pages(ctx.pdf_path(pdf), pdf, sorted(p for p in pages if 1 <= p <= pdf["pages"]),
                                 ctx.abs(".work/pdf/" + pdf["id"]))
        instructions.write(ctx, job)
        job["status"] = "issued"
    ctx.save()


def _running(out, jobs):
    return {"ok": True, "state": "running",
            "jobs": [{"agent": j["agent"], "file": ".work/jobs/%s.md" % j["id"]} for j in jobs],
            "do": JOBS_DO + cmd("next", out)}


def _done(out):
    return {"ok": True, "state": "done", "jobs": [], "do": DONE_DO + cmd("serve", out)}


def run(out):
    ctx = Ctx(out)
    st = ctx.state
    if st["stage"] == "done":
        return _done(out)
    issued = [j for j in st["jobs"] if j["status"] == "issued"]
    if issued:
        empty = not any(os.path.isfile(ctx.abs(rel)) for j in issued for rel in j["outputs"])
        st["no_output"] = st["no_output"] + 1 if empty else 0
        if st["no_output"] == 1:
            ctx.save()
            return _running(out, issued)
        st["no_output"] = 0
        _settle(ctx, issued, empty)
        if empty:
            ctx.save()
            raise Fail("no_output", "担当エージェントが、出力のファイルを1つも書かなかった。")
    while st["stage"] != "done":
        pending = [j for j in st["jobs"] if j["stage"] == st["stage"] and j["status"] == "pending"]
        if pending:
            _issue(ctx, pending[:values.MAX_JOBS])
            return _running(out, pending[:values.MAX_JOBS])
        if st["stage"] in VERIFY_STAGES and scriptwork.next_round(ctx):
            continue
        _advance(ctx)
    ctx.save()
    return _done(out)
