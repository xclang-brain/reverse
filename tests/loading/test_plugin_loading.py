"""読み込みのテスト（B）。

確かめる受入条件は B-1、B-2、B-3 である。根拠は、要件の文書の 5.3、設計の 2章、6章、8章である。
`claude` と `copilot` がない環境（GitHub Actions など）では飛ばす。飛ばしたテストは、合格に数えない（5.1）。

- ツールの設定のフォルダは、テストごとに分ける（CLAUDE_CONFIG_DIR、COPILOT_HOME）。
- B-2 と B-3 では、Copilot CLI を、ログインなしのオフラインのモードで、偽の OpenAI 互換サーバー（fake_openai.py）に
  つなぐ。偽のサーバーは、ユーザーのメッセージの `CALL` の行（台本）のとおりに、ツールの呼び出しを返す。
- 入力は、テストの中で作った画像だけの PDF を、日本語と空白を含むフォルダに置いて使う。
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import helpers
from fake_openai import FakeServer, text_of

REPO = helpers.REPO
SKILL = "reverse:make-design-docs"
CONVERTER = "reverse:pdf-converter"
OTHERS = ["reverse:code-analyst", "reverse:doc-matcher", "reverse:doc-writer", "reverse:doc-verifier"]
# 設計の8章：エージェントの tools の指定から、Copilot CLI が渡すツール
CONVERTER_TOOLS = {"view", "create", "edit"}
OTHER_TOOLS = {"view", "grep", "glob", "create", "edit"}
# B のテストは、Claude のモデルの名前を使う（設計の8章。GPT の族ではツールの名前が変わる）
MODEL = "claude-sonnet-4.5"

needs_claude = pytest.mark.skipif(shutil.which("claude") is None, reason="claude がない")
needs_copilot = pytest.mark.skipif(shutil.which("copilot") is None, reason="copilot がない")


# ---------------------------------------------------------------------------
# このファイルだけで使う道具
# ---------------------------------------------------------------------------

def _marketplace():
    """リポジトリの直下のマーケットプレイスのマニフェストにある、マーケットプレイスの名前。"""
    return helpers.read_json(REPO / ".claude-plugin" / "marketplace.json")["name"]


def _ok(argv, env, cwd=None, timeout=300):
    """コマンドを動かし、終了コードが 0 であることを確かめて、標準出力を返す。"""
    p = subprocess.run(argv, env=env, cwd=None if cwd is None else str(cwd),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    out = p.stdout.decode("utf-8", "replace")
    assert p.returncode == 0, "%s が失敗した：\n%s\n%s" % (argv, out, p.stderr.decode("utf-8", "replace"))
    return out


def _claude_env(home):
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(Path(home).resolve())
    return env


def _copilot_env(home):
    env = dict(os.environ)
    env["COPILOT_HOME"] = str(Path(home).resolve())  # 絶対パスだけを渡す
    env["COPILOT_AUTO_UPDATE"] = "false"
    return env


def _install_copilot(home):
    """Copilot CLI に、手元のリポジトリをマーケットプレイスとして登録し、プラグインを入れる。環境変数を返す。"""
    env = _copilot_env(home)
    _ok(["copilot", "plugin", "marketplace", "add", str(REPO)], env)
    _ok(["copilot", "plugin", "install", "reverse@" + _marketplace()], env)
    return env


def _call(tool, **arguments):
    """偽のサーバーの台本の1行。"""
    return "CALL " + json.dumps({"name": tool, "arguments": arguments}, ensure_ascii=False)


def _agent_of(request):
    """リクエストが、どの担当エージェントのものかを返す。統括のリクエストは None。

    担当に渡す台本の1行目に `AGENT <名前>` を書いておき、ユーザーのメッセージから探す。
    """
    for m in request.get("messages", []):
        if m.get("role") == "user":
            for line in text_of(m.get("content")).splitlines():
                if line.startswith("AGENT "):
                    return line[len("AGENT "):].strip()
    return None


def _tool_names(request):
    return {t["function"]["name"] for t in request.get("tools", [])}


def _images(request):
    """リクエストに入っている画像のバイト列を、メッセージの順に返す。"""
    found = []
    for m in request.get("messages", []):
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    found.append(base64.b64decode(part["image_url"]["url"].split(",", 1)[1]))
    return found


def _last_call(request):
    """リクエストの最後のアシスタントのメッセージの、ツールの呼び出し（名前と引数）を返す。"""
    for m in reversed(request.get("messages", [])):
        if m.get("role") == "assistant":
            calls = m.get("tool_calls") or []
            if calls:
                f = calls[-1]["function"]
                return f["name"], json.loads(f["arguments"] or "{}")
            return None
    return None


# ---------------------------------------------------------------------------
# B-1
# ---------------------------------------------------------------------------

@needs_claude
def test_claude_installs_and_validates_plugin(tmp_path):
    """B-1：Claude Code にマーケットプレイスから入れたプラグインが読み込まれ、validate が通る（SR-73、SR-82）。"""
    env = _claude_env(tmp_path / "claude-config")
    name = _marketplace()
    _ok(["claude", "plugin", "marketplace", "add", str(REPO)], env)
    _ok(["claude", "plugin", "install", "reverse@" + name], env)
    listed = json.loads(_ok(["claude", "plugin", "list", "--json"], env))
    assert [p for p in listed if p["id"] == "reverse@" + name and p["enabled"]], listed

    root = _ok(["claude", "plugin", "validate", str(REPO)], env)
    assert "Validation passed" in root, root
    plugin = _ok(["claude", "plugin", "validate", str(REPO / "plugin")], env)
    assert "Validation passed" in plugin, plugin
    assert re.findall(r">\s*skills:\s*(\S+)", plugin) == [SKILL], plugin
    assert sorted(re.findall(r">\s*agents:\s*(\S+)", plugin)) == sorted([CONVERTER] + OTHERS), plugin


@needs_copilot
def test_copilot_installs_plugin_and_skill(tmp_path):
    """B-1：Copilot CLI にマーケットプレイスから入れたプラグインとスキルが、plugin list と skill list に出る（SR-73、SR-82）。"""
    env = _install_copilot(tmp_path / "copilot-home")
    plugins = json.loads(_ok(["copilot", "plugin", "list", "--json"], env))
    assert [p for p in plugins if p["name"] == "reverse" and p["marketplace"] == _marketplace() and p["enabled"]], \
        plugins
    skills = json.loads(_ok(["copilot", "skill", "list", "--json"], env))
    mine = [s for s in skills if s["source"] == "plugin" and s["enabled"]
            and Path(s["path"]).resolve() == (REPO / "plugin" / "skills" / "make-design-docs").resolve()]
    assert [s["name"] for s in mine] == ["make-design-docs"], skills


# ---------------------------------------------------------------------------
# B-2、B-3：Copilot CLI で、仕事を1周させる
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def copilot_round(tmp_path_factory):
    """Copilot CLI を偽のサーバーにつなぎ、next から変換担当の仕事までを1周させ、ほかの4つの担当を1回ずつ呼ぶ。

    戻り値は、届いたリクエストのリスト、出力先、ページの画像と Markdown のパス。
    """
    if shutil.which("copilot") is None:
        pytest.skip("copilot がない")
    env = _install_copilot(tmp_path_factory.mktemp("copilot_home"))
    base = tmp_path_factory.mktemp("round") / "読み込み の確認"
    pdf = helpers.make_image_pdf(base / "既存 の設計書" / "仕様 書.pdf", pages=2)
    out = base / "出力 先"
    r = helpers.run_cli(["init", "--out", out, "--pdf", pdf])
    assert r.ok, r.data
    # init の do の next のコマンド。<python> は、テストの Python の絶対パスに置き換える
    command = r.data["do"][r.data["do"].index("Run: ") + len("Run: "):]
    command = "'%s'%s" % (Path(sys.executable).as_posix(), command[command.index(" '"):])

    # 1.4 の作業フォルダの表と、2.7 の仕事の決まりから決まるパス（PDF だけ、2ページなので、仕事は J00001 の1件）
    folder = Path(os.path.abspath(str(out))) / ".work" / "pdf" / "D01"
    pngs = [folder / "0001.png", folder / "0002.png"]
    mds = [folder / "0001.md", folder / "0002.md"]
    converter = "\n".join([
        "AGENT " + CONVERTER,
        _call("view", path=str(pngs[0])),
        _call("create", path=str(mds[0]), file_text="# ページ 1\n"),
        _call("view", path=str(pngs[1])),
        _call("create", path=str(mds[1]), file_text="# ページ 2\n"),
    ])
    main = [_call("bash", command=command, description="next"),
            _call("task", agent_type=CONVERTER, name="converter", description="convert pages",
                  prompt=converter, mode="sync")]
    for agent in OTHERS:
        main.append(_call("task", agent_type=agent, name=agent.split(":")[1], description="reply done",
                          prompt="AGENT %s\nReply done." % agent, mode="sync"))

    with FakeServer() as server:
        env.update({"COPILOT_OFFLINE": "true", "COPILOT_PROVIDER_BASE_URL": server.url, "COPILOT_MODEL": MODEL,
                    "COPILOT_PROVIDER_VISION": "true"})
        _ok(["copilot", "-p", "\n".join(main), "--allow-all-tools", "--allow-all-paths", "--no-ask-user", "--no-auto-update"],
            env, cwd=base, timeout=600)
        requests = list(server.requests)
    return {"requests": requests, "out": out, "pngs": pngs, "mds": mds}


@needs_copilot
def test_copilot_round_passes_tools_to_agents(copilot_round):
    """B-2：シェルで next を呼んで変換担当の仕事を渡せ、各担当に渡るツールが決まりどおりである（SR-73、SR-74）。"""
    requests = copilot_round["requests"]
    # シェルで呼んだ next の結果が、変換担当の仕事を返した
    results = [m["content"] for r in requests for m in r.get("messages", [])
               if m.get("role") == "tool" and isinstance(m.get("content"), str)
               and m["content"].startswith("{") and '"jobs"' in m["content"]]
    assert results, "next の結果がツールの結果にない"
    data = json.loads(results[0].splitlines()[0])
    assert data["ok"] is True and [j["agent"] for j in data["jobs"]] == [CONVERTER], data
    assert [j["status"] for j in helpers.read_state(copilot_round["out"])["jobs"]] == ["issued"]

    # 担当ごとに、渡ったツールが決まりどおりである
    seen = {}
    for r in requests:
        agent = _agent_of(r)
        if agent is not None:
            seen.setdefault(agent, []).append(_tool_names(r))
    assert sorted(seen) == sorted([CONVERTER] + OTHERS), sorted(seen)
    for agent, tool_sets in seen.items():
        expected = CONVERTER_TOOLS if agent == CONVERTER else OTHER_TOOLS
        assert all(s == expected for s in tool_sets), (agent, tool_sets)


@needs_copilot
def test_copilot_round_reads_page_images_and_writes_pages(copilot_round):
    """B-3：変換担当が、next の作ったフォルダにファイルを作れ、読んだ直後のリクエストにそのページの画像が入る（SR-09、SR-25）。"""
    for md, page in zip(copilot_round["mds"], ("1", "2")):
        assert md.is_file(), "変換担当がファイルを作れなかった：%s" % md
        assert helpers.read_text(md) == "# ページ %s\n" % page

    requests = [r for r in copilot_round["requests"] if _agent_of(r) == CONVERTER]
    for png in copilot_round["pngs"]:
        after = [r for r in requests if _last_call(r) == ("view", {"path": str(png)})]
        assert after, "%s を読んだ直後のリクエストがない" % png.name
        images = _images(after[0])
        assert images and images[-1] == png.read_bytes(), "%s を読んだ直後のリクエストに、そのページの画像がない" % png.name
