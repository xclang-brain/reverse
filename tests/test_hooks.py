"""Claude Code のフックのテスト。

確かめる要件は SR-86（担当エージェントが書けるファイルを、出力先の `.work/` と `docs/` の下に限る）である。
根拠は、設計（docs/design.md）の6章の「Claude Code では、フックで、…」の箇条書きである。

- guard.py は、標準入力の JSON を読むスクリプトなので、テストを動かしている Python で、コマンドとして動かす。
- 出力先は、`.work/state.json` があるフォルダである。作業フォルダの下に、出力先とソースコードのフォルダを作る。
- 動かすときのカレントフォルダは、作業フォルダと別のフォルダにする（相対パスを、入力の cwd から解決することを確かめるため）。
"""
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import sysconfig

import pytest

import helpers

HOOKS = helpers.REPO / "plugin" / "hooks"
HOOKS_JSON = HOOKS / "hooks.json"
GUARD_PY = HOOKS / "guard.py"
AGENT = "reverse:code-analyst"


# ---------------------------------------------------------------------------
# このファイルだけで使う道具
# ---------------------------------------------------------------------------

@pytest.fixture
def work(tmp_path):
    """作業フォルダを作って返す。中に、出力先（out）とソースコードのフォルダ（src）がある。"""
    root = tmp_path / "作業 フォルダ"
    out = root / "out"
    for folder in (out / ".work" / "memo", out / "docs" / "design" / "modules"):
        folder.mkdir(parents=True)
    (out / ".work" / "state.json").write_text("{}\n", encoding="utf-8")
    (out / ".work" / "plan.json").write_text("{}\n", encoding="utf-8")
    (out / "mkdocs.yml").write_text("site_name: x\n", encoding="utf-8")
    helpers.make_source_tree(root / "src")
    (tmp_path / "elsewhere").mkdir()
    return root


def _run_guard(stdin, cwd):
    """guard.py に stdin（バイト列）を渡して動かし、CompletedProcess を返す。"""
    return subprocess.run([sys.executable, str(GUARD_PY)], input=stdin, cwd=str(cwd),
                          capture_output=True, timeout=60)


def _hook_input(file_path, cwd, agent_type=AGENT, tool_name="Write"):
    """PreToolUse のフックの入力の JSON（バイト列）を作る。agent_type が None なら、項目を入れない。"""
    if tool_name == "Edit":
        tool_input = {"file_path": str(file_path), "old_string": "a", "new_string": "b"}
    else:
        tool_input = {"file_path": str(file_path), "content": "# 役割\n"}
    data = {"session_id": "s1", "transcript_path": str(cwd / "t.jsonl"), "cwd": str(cwd),
            "hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input}
    if agent_type is not None:
        data["agent_type"] = agent_type
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _assert_allowed(proc):
    """書き込みを通したこと（何も出さずに、終了コード 0 で終わったこと）を確かめる。"""
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout.strip() == b"", proc.stdout


def _assert_denied(proc):
    """書き込みを止めたこと（終了コード 0 で、deny の JSON を標準出力に書いたこと）を確かめる。"""
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    data = json.loads(proc.stdout.decode("utf-8"))
    output = data["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == "deny"
    # 理由は、英語の1文で、指示のファイルの「書く先」だけに書くように伝える
    reason = output["permissionDecisionReason"]
    assert isinstance(reason, str) and reason.strip() and reason.isascii(), reason


def _is_stdlib(name):
    """モジュールが標準ライブラリかどうかを返す（Python 3.9 には sys.stdlib_module_names がないので、場所で見る）。

    組み込みのモジュールは標準ライブラリに数える。そのほかは、標準ライブラリのフォルダ（stdlib と、拡張モジュールの platstdlib）の下にあれば数える。
    site-packages（purelib と platlib）の下は、標準ライブラリのフォルダの中にあっても数えない。
    """
    spec = importlib.util.find_spec(name.split(".")[0])
    if spec is None:
        return False
    if spec.origin in ("built-in", "frozen"):
        return True
    paths = sysconfig.get_paths()

    def under(key):
        return os.path.normcase(os.path.realpath(spec.origin)).startswith(
            os.path.normcase(os.path.realpath(paths[key])) + os.sep)

    return (under("stdlib") or under("platstdlib")) and not (under("purelib") or under("platlib"))


# 出力先の中で、書き込みを通す場所（出力先からの相対パス）
ALLOWED = [".work/memo/U0001.md", "docs/design/modules/a.md"]
# 書き込みを止める場所（作業フォルダからの相対パス）
DENIED = [
    pytest.param("note.md", id="work_folder"),
    pytest.param("src/main.c", id="source_folder"),
    pytest.param("out/mkdocs.yml", id="output_top"),
    pytest.param("out/.work/state.json", id="state_json"),
    pytest.param("out/.work/plan.json", id="plan_json"),
]


# ---------------------------------------------------------------------------
# 担当エージェントでない書き込み
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("agent_type", [None, "", "general-purpose", "reverse", "reverse-x:code-analyst"])
@pytest.mark.parametrize("rel", ["note.md", "src/main.c", "out/.work/state.json", "out/docs/design/modules/a.md"])
def test_other_agents_are_not_touched(work, agent_type, rel):
    """SR-86：agent_type がないか、reverse: で始まらないときは、どこへの書き込みでも、何も出さずに終了コード 0 で終わる。"""
    proc = _run_guard(_hook_input(work / rel, work, agent_type=agent_type), work.parent / "elsewhere")
    _assert_allowed(proc)


# ---------------------------------------------------------------------------
# 担当エージェントの書き込み
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool_name", ["Write", "Edit"])
@pytest.mark.parametrize("agent_type", [AGENT, "reverse:doc-verifier"])
@pytest.mark.parametrize("rel", ALLOWED)
def test_writes_inside_output_are_allowed(work, rel, agent_type, tool_name):
    """SR-86：担当エージェントが、出力先の .work/ と docs/ の下に書くときは、何も出さずに通す。"""
    proc = _run_guard(_hook_input(work / "out" / rel, work, agent_type=agent_type, tool_name=tool_name),
                      work.parent / "elsewhere")
    _assert_allowed(proc)


@pytest.mark.parametrize("tool_name", ["Write", "Edit"])
@pytest.mark.parametrize("rel", DENIED)
def test_writes_outside_output_are_denied(work, rel, tool_name):
    """SR-86：出力先の外、出力先の直下、.work/state.json、.work/plan.json への書き込みは、deny で止める。"""
    proc = _run_guard(_hook_input(work / rel, work, tool_name=tool_name), work.parent / "elsewhere")
    _assert_denied(proc)


@pytest.mark.parametrize("tool_name", ["Write", "Edit"])
@pytest.mark.parametrize("cwd, rel, allowed", [
    pytest.param("out", ".work/memo/U0001.md", True, id="out_memo"),
    pytest.param("out", "docs/design/modules/a.md", True, id="out_docs"),
    pytest.param(".", "out/.work/memo/U0001.md", True, id="work_memo"),
    pytest.param("out", "mkdocs.yml", False, id="out_mkdocs"),
    pytest.param("out", ".work/state.json", False, id="out_state"),
    pytest.param(".", "note.md", False, id="work_note"),
    pytest.param(".", "src/main.c", False, id="work_source"),
])
def test_relative_paths_use_input_cwd(work, cwd, rel, allowed, tool_name):
    """SR-86：書く先の相対パスは、入力の cwd から解決する（動かしたときのカレントフォルダからではない）。"""
    base = work / cwd
    proc = _run_guard(_hook_input(rel, base, tool_name=tool_name), work.parent / "elsewhere")
    if allowed:
        _assert_allowed(proc)
    else:
        _assert_denied(proc)


@pytest.mark.parametrize("link, target, rel", [
    pytest.param("docs/link", "elsewhere", "docs/link/evil.md", id="docs_to_outside"),
    pytest.param(".work/up", "work", ".work/up/note.md", id="work_to_work_folder"),
])
def test_writes_through_symlink_to_outside_are_denied(work, link, target, rel):
    """SR-86：出力先の docs/ や .work/ の下にある、外を指すシンボリックリンクを通した書き込みは、deny で止める。"""
    out = work / "out"
    to = work.parent / "elsewhere" if target == "elsewhere" else work
    try:
        (out / link).symlink_to(to, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("シンボリックリンクを作れない")
    proc = _run_guard(_hook_input(out / rel, work), work.parent / "elsewhere")
    _assert_denied(proc)


@pytest.mark.parametrize("stdin", [b"", b"not json", b"{\"agent_type\": \"reverse:code-analyst\""])
def test_broken_input_denies_nothing(work, stdin):
    """SR-86：標準入力が JSON でないときは、何も止めない（終了コードは問わない。書き込みを止める JSON を出さない）。"""
    proc = _run_guard(stdin, work.parent / "elsewhere")
    assert b"deny" not in proc.stdout, proc.stdout


# ---------------------------------------------------------------------------
# フックの設定と、guard.py の書き方
# ---------------------------------------------------------------------------

def test_hooks_json_runs_guard_before_write_and_edit():
    """SR-86：hooks.json の PreToolUse に、Write と Edit に当たるフックが1つあり、guard.py を動かす。"""
    data = json.loads(helpers.read_text(HOOKS_JSON))
    entries = data["hooks"]["PreToolUse"]
    matched = [e for e in entries
               if all(re.fullmatch(e.get("matcher", ""), tool) for tool in ("Write", "Edit"))]
    assert len(matched) == 1, entries
    commands = [h for h in matched[0]["hooks"] if h.get("type") == "command"]
    assert len(commands) == 1, matched[0]
    command = commands[0]["command"]
    assert "guard.py" in command and "${CLAUDE_PLUGIN_ROOT}" in command, command
    # Python が見つからないときと、スクリプトが失敗したときは、書き込みを通す（最後が exit 0）
    parts = [p.strip() for p in command.split("||")]
    assert len(parts) == 4, command
    script = '"${CLAUDE_PLUGIN_ROOT}/hooks/guard.py"'
    assert parts[0] == "python3 " + script, command
    assert parts[1] == "py -3 " + script, command
    assert parts[2] == "python " + script, command
    assert parts[3] == "exit 0", command


def test_guard_py_has_old_python_syntax():
    """SR-86：guard.py は、標準ライブラリだけを使い、古い Python でも構文エラーにならない書き方にする（f 文字列と型の注釈を使わない）。"""
    tree = ast.parse(helpers.read_text(GUARD_PY))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            found.append("%d 行：f 文字列" % node.lineno)
        elif isinstance(node, ast.AnnAssign):
            found.append("%d 行：変数の型の注釈" % node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            args += [a for a in (node.args.vararg, node.args.kwarg) if a is not None]
            if node.returns is not None or any(a.annotation is not None for a in args):
                found.append("%d 行：関数の型の注釈" % node.lineno)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                if not _is_stdlib(name):
                    found.append("%d 行：標準ライブラリでない %s" % (node.lineno, name))
    assert not found, "guard.py の書き方：\n" + "\n".join(found)
