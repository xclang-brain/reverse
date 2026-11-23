"""シェルから動かすテストと、serve と stop のテスト。

確かめる受入条件は A-11（シェル）である。根拠は、要件の文書の 5.2 と、スクリプトの仕様（docs/script-spec.md）の
1.5（do の文）、11章（serve と stop）、12章（テストの入口）である。

- SKILL.md のコードブロックから取り出した init のコマンドを、日本語と空白を含むパスで、シェルから動かす。
  その後は、結果の do に書かれたコマンドを、そのままシェルで動かす（統括と同じ進め方）。
- シェルは、Linux では bash、Windows では Windows PowerShell 5.1、PowerShell 7、Git の bash である。
- コマンドの先頭の <python> は、1.5 の決まりの文字列であることを確かめてから、テストを動かしている Python の
  絶対パスに置き換える（Windows の `py -3` は、テストの Python と別の Python を選ぶことがあるため）。
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

import helpers

SKILL_MD = helpers.REPO / "plugin" / "skills" / "make-design-docs" / "SKILL.md"
SERVING_DO = ("Tell the user in Japanese: the site URL (url), the folder of the documents (docs), the two review"
              " lists (discrepancies, unknowns), the counts (counts) and the number of failed jobs (failed_jobs)."
              " To stop the server, run: ")
# 要件の文書の A-11 のシェル。OS ごとに、その OS のシェルだけを集める（飛ばすテストを作らない）。
SHELLS = ["powershell", "pwsh", "git-bash"] if os.name == "nt" else ["bash"]


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


def _git_bash():
    """Git の bash のパスを返す（System32 の WSL の bash と取り違えないように、Git のフォルダから探す）。"""
    git = shutil.which("git")
    places = [Path(git).resolve().parent.parent / "bin" / "bash.exe"] if git else []
    places.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe")
    for p in places:
        if p.is_file():
            return str(p)
    pytest.fail("Git の bash が見つからない")


def _shell_argv(shell, command):
    """シェルに1行のコマンドを渡して動かす引数を返す。"""
    if shell == "bash":
        return [shutil.which("bash") or "bash", "-c", command]
    if shell == "git-bash":
        return [_git_bash(), "-c", command]
    exe = shutil.which("powershell.exe" if shell == "powershell" else "pwsh")
    if exe is None:
        pytest.fail("%s が見つからない" % shell)
    return [exe, "-NoProfile", "-NonInteractive", "-Command", command]


def _assert_one_command(command, placeholders=False):
    """P-12：`&&`、パイプ、リダイレクト、環境変数の前置き、行の継続のない、1行のコマンドである。

    単引用符の中は値なので調べない。placeholders が真のときは、`<python>` のような置き換える所も除く。
    """
    assert "\n" not in command and "\r" not in command, "コマンドが1行でない：%r" % command
    outside = re.sub(r"'[^']*'", "''", command)
    if placeholders:
        outside = re.sub(r"<[^<>\s]+>", "", outside)
    for bad in ("&&", "|", ">", "<"):
        assert bad not in outside, "コマンドに %r がある：%r" % (bad, command)
    assert not outside.rstrip().endswith(("\\", "`")), "コマンドが行の継続で終わる：%r" % command
    assert not re.match(r"\s*[A-Za-z_][A-Za-z0-9_]*=", outside), "コマンドに環境変数の前置きがある：%r" % command


def _skill_init_command():
    """SKILL.md のコードブロックから、revdoc.py の init を呼ぶ行を取り出す。"""
    text = helpers.read_text(SKILL_MD)
    lines = []
    in_block = False
    for line in text.split("\n"):
        if re.match(r" {0,3}```", line):
            in_block = not in_block
            continue
        if in_block and "revdoc.py" in line and re.search(r"(^|\s)init(\s|$)", line):
            lines.append(line.strip())
    assert lines, "SKILL.md のコードブロックに、revdoc.py の init を呼ぶ行がない"
    return lines[0]


def _fill(line, out, src, pdf):
    """SKILL.md の行の、単引用符で囲んだ所を、意味に合う値に置き換える。

    - revdoc.py を含む所は revdoc.py の絶対パス、`--out`、`--src`、`--pdf` の後ろの所はその値にする。
    - 省いてよい所を表す `[` と `]` は取る。
    - 先頭の <python> の部分は、そのまま返す（_runnable で置き換える）。
    """
    head, body = line[:line.index("'")], line[line.index("'"):]
    values = {"--out": out, "--src": src, "--pdf": pdf}

    def repl(m):
        if m.group(0) in "[]":
            return ""
        if "revdoc.py" in m.group(0):
            return "'%s'" % helpers.REVDOC_PY
        words = body[:m.start()].replace("[", " ").split()
        option = words[-1] if words else ""
        assert option in values, "SKILL.md の行の %s が何の値か分からない：%r" % (m.group(0), line)
        return "'%s'" % os.path.abspath(str(values[option]))

    filled = head + re.sub(r"'[^']*'|[\[\]]", repl, body)
    assert "--out '" in filled and "--src '" in filled, "SKILL.md の init の行に --out か --src がない：%r" % line
    return re.sub(r"  +", " ", filled)


def _runnable(command, shell):
    """先頭の <python> を、テストの Python の絶対パスに置き換える。PowerShell では、呼び出しの & を付ける。"""
    rest = command[command.index(" '"):]
    exe = "'%s'" % Path(sys.executable).as_posix()
    return ("& " + exe if shell in ("powershell", "pwsh") else exe) + rest


def _command_in(do):
    """do の文の最後にあるコマンドを取り出す。<python> で始まり、P-12 に合うことを確かめる。"""
    start = do.find(_python() + " '")
    assert start >= 0, "do にコマンドがない：%r" % do
    command = do[start:]
    _assert_one_command(command)
    return command


def _run(shell, command, cwd):
    """シェルでコマンドを動かし、helpers.Result を返す。スクリプトの文字コードの警告は、見張りに渡す。"""
    env = dict(os.environ)
    env["PYTHONWARNDEFAULTENCODING"] = "1"
    p = subprocess.run(_shell_argv(shell, _runnable(command, shell)), cwd=str(cwd), env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    stderr = p.stderr.decode("utf-8", "replace")
    for guard in helpers.EncodingGuard.active:
        guard.add_stderr(stderr)
    text = p.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    assert text, "標準出力がない。標準エラー：%s" % stderr[-2000:]
    return helpers.Result(p.returncode, helpers.parse_stdout(text, p.returncode), text, stderr)


def _port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _stop_quietly(out):
    """テストが途中で失敗したときに、サーバーを残さない。"""
    if (Path(out) / ".work" / "serve.json").exists():
        subprocess.run([sys.executable, str(helpers.REVDOC_PY), "stop", "--out", str(out)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)


# ---------------------------------------------------------------------------
# テスト
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shell", SHELLS)
def test_skill_command_runs_from_init_to_stop(tmp_path, shell):
    """A-11：SKILL.md のコマンドが、日本語と空白を含むパスで、init から serve、stop まで動く（SR-15、SR-70、SR-71、SR-76）。"""
    base = tmp_path / "設計 書"
    src = helpers.make_source_tree(base / "ソース コード")
    pdf = helpers.make_image_pdf(base / "既存 の設計書" / "仕様 書.pdf")
    out = base / "出力 先"
    cwd = base / "空の フォルダ"
    cwd.mkdir()
    before_src = helpers.tree_hashes(src)
    before_pdf = helpers.tree_hashes(pdf.parent)

    line = _skill_init_command()
    _assert_one_command(line, placeholders=True)
    command = _fill(line, out, src, pdf)
    try:
        # init と next を、do のとおりに、serve のコマンドが来るまで動かす
        for _ in range(3000):
            r = _run(shell, command, cwd)
            assert r.ok, r.data
            if r.data.get("jobs"):
                helpers.fake_agent(out)
            command = _command_in(r.data["do"])
            if command == _cmd("serve", out):
                break
        else:
            pytest.fail("serve のコマンドまで進まない")
        assert r.data.get("state") == "done", r.data

        # serve：building のあいだは、do のとおりに呼び直す
        for _ in range(10):
            r = _run(shell, command, cwd)
            assert r.ok, r.data
            if r.data["state"] == "serving":
                break
            assert r.data["state"] == "building", r.data
            command = _command_in(r.data["do"])
            assert command == _cmd("serve", out)
        else:
            pytest.fail("serve が serving にならない")
        data = r.data
        root = os.path.abspath(str(out))
        port = int(re.fullmatch(r"http://127\.0\.0\.1:(\d+)/", data["url"]).group(1))
        assert 8000 <= port <= 8099
        assert data["site"] == os.path.join(root, "site")
        assert data["docs"] == os.path.join(root, "docs")
        assert data["discrepancies"] == os.path.join(root, "docs", "review", "discrepancies.md")
        assert data["unknowns"] == os.path.join(root, "docs", "review", "unknowns.md")
        assert sorted(data["counts"]) == ["changed_inputs", "discrepancies", "modules", "unknowns"]
        assert data["failed_jobs"] == 0
        assert data["do"] == SERVING_DO + _cmd("stop", out)
        with urllib.request.urlopen(data["url"], timeout=10) as res:
            assert res.status == 200

        # SR-68：site/ に mermaid の JS がある（privacy プラグインが取得したもの）
        assert [p for p in (out / "site").rglob("*.js") if p.name.startswith("mermaid")], \
            "site/ に mermaid の JS がない"

        # 11.1 の 2：動いている間にもう一度呼ぶと、新しいプロセスを始めずに、同じ状態を返す
        pid = helpers.read_json(out / ".work" / "serve.json")["pid"]
        again = _run(shell, command, cwd)
        assert again.data["state"] == "serving" and again.data["url"] == data["url"]
        assert helpers.read_json(out / ".work" / "serve.json")["pid"] == pid

        # stop：サーバーが止まり、ポートが閉じる
        r = _run(shell, _command_in(data["do"]), cwd)
        assert r.data == {"ok": True, "stopped": True}
        assert not _port_open(port), "stop の後も、ポート %d が開いている" % port
        assert not (out / ".work" / "serve.json").exists()
    finally:
        _stop_quietly(out)

    # P-01、P-02：カレントフォルダにファイルが増えず、入力が変わらない
    assert list(cwd.rglob("*")) == [], "カレントフォルダにファイルができた"
    assert helpers.tree_hashes(src) == before_src
    assert helpers.tree_hashes(pdf.parent) == before_pdf


def test_serve_before_done_is_refused(tmp_path):
    """A-11：段階が done でないときの serve は、not_done のエラーを返す（SR-70、11.1 の 1）。"""
    out = tmp_path / "out"
    src = helpers.make_source_tree(tmp_path / "src")
    assert helpers.revdoc("init", out, src=src).ok
    r = helpers.revdoc("serve", out)
    assert r.code == 1 and r.data["error"] == "not_done"
    assert not (out / ".work" / "serve.json").exists()


def test_stop_ignores_stale_server_record(tmp_path):
    """A-11：serve.json の time が 15 秒より前のとき、stop はプロセスを止めずに記録を消す（SR-71、11.2）。"""
    out = tmp_path / "out"
    src = helpers.make_source_tree(tmp_path / "src")
    assert helpers.revdoc("init", out, src=src).ok
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **kw)
    try:
        record = '{"state":"serving","pid":%d,"port":8000,"url":"http://127.0.0.1:8000/","time":%d}' \
                 % (child.pid, int(time.time()) - 100)
        with open(out / ".work" / "serve.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(record)
        r = helpers.revdoc("stop", out)
        assert r.data == {"ok": True, "stopped": False}
        assert not (out / ".work" / "serve.json").exists()
        assert child.poll() is None, "古い記録の pid のプロセスが止められた"
    finally:
        child.kill()
        child.wait()
