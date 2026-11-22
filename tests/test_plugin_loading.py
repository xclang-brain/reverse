"""プラグインの読み込みのテスト（受入条件の B）。

Claude Code と GitHub Copilot CLI が、プラグイン、スキル、5つの担当エージェントを
読み込めることを確かめる。CLI がない環境では、CLI を使うテストを飛ばす。
"""
import http.server
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugin"
AGENTS_DIR = PLUGIN / "com.github.copilot" / "agents"
AGENTS = ["code-analyst", "pdf-converter", "doc-matcher", "doc-writer", "doc-verifier"]
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"


def front_matter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, f"{path} にフロントマターがない"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, text[match.end():]


# ---- CLI を使わないテスト ----

def test_manifests_agree():
    copilot = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    claude = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert copilot["$schema"] == SCHEMA
    for key in ("name", "version", "description"):
        assert copilot[key] == claude[key]
    assert copilot["name"] == "reverse"


def test_claude_manifest_lists_every_agent_file():
    claude = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    listed = sorted(claude["agents"])
    actual = sorted(f"./com.github.copilot/agents/{p.name}" for p in AGENTS_DIR.glob("*.md"))
    assert listed == actual
    assert sorted(p.name for p in AGENTS_DIR.glob("*.md")) == sorted(f"{a}.agent.md" for a in AGENTS)


@pytest.mark.parametrize("agent", AGENTS)
def test_agent_definition(agent):
    fields, body = front_matter(AGENTS_DIR / f"{agent}.agent.md")
    assert fields["name"] == agent
    assert fields["description"]
    tools = [t.strip() for t in fields["tools"].strip("[]").split(",")]
    assert "Read" in tools
    # 担当エージェントには、スキルを呼ぶツールと、ほかのエージェントを呼ぶツールを渡さない
    assert not {"Skill", "Agent", "Task"} & set(tools)
    assert "## 禁止事項" in body


def test_skill_front_matter():
    skill_dir = PLUGIN / "skills" / "make-design-docs"
    fields, body = front_matter(skill_dir / "SKILL.md")
    assert fields["name"] == skill_dir.name
    assert 0 < len(fields["description"]) <= 1024
    assert "## 禁止事項" in body


# ---- Claude Code ----

needs_claude = pytest.mark.skipif(shutil.which("claude") is None, reason="claude がない")
needs_copilot = pytest.mark.skipif(shutil.which("copilot") is None, reason="copilot がない")


@needs_claude
def test_claude_loads_skill_and_agents():
    result = subprocess.run(["claude", "plugin", "validate", str(PLUGIN)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "reverse:make-design-docs" in result.stdout
    for agent in AGENTS:
        assert f"reverse:{agent}" in result.stdout


# ---- GitHub Copilot CLI（ログインせずに、偽物のモデルにつないで確かめる） ----

class FakeModel:
    """届いた求めを記録し、決まった返事を返す、モデルの代わりのサーバー。

    task ツールを持つ求め（統括）には、指定の担当エージェントを呼ぶ返事を1回だけ返す。
    """

    def __init__(self, agent_type):
        self.requests = []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self._send({"data": [{"id": "fake-model", "object": "model"}]})

            def _send(self, payload):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                request = json.loads(body)
                fake.requests.append(request)
                names = tool_names(request)
                answered = any(m.get("role") == "tool" for m in request.get("messages", []))
                if agent_type and "task" in names and not answered:
                    arguments = {"description": "probe", "prompt": "hi", "agent_type": agent_type, "name": "probe"}
                    message = {"role": "assistant", "content": None, "tool_calls": [{
                        "index": 0, "id": "call_1", "type": "function",
                        "function": {"name": "task", "arguments": json.dumps(arguments)}}]}
                    finish = "tool_calls"
                else:
                    message, finish = {"role": "assistant", "content": "DONE"}, "stop"
                if request.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    chunk = {"id": "c", "object": "chat.completion.chunk", "model": "fake-model",
                             "choices": [{"index": 0, "delta": message, "finish_reason": None}]}
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    chunk["choices"][0] = {"index": 0, "delta": {}, "finish_reason": finish}
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                else:
                    self._send({"id": "c", "object": "chat.completion", "model": "fake-model",
                                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


def tool_names(request):
    return [(t.get("function") or t).get("name") for t in request.get("tools", [])]


def copilot_env(tmp_path, url=None):
    env = dict(os.environ, COPILOT_HOME=str(tmp_path / "copilot-home"), COPILOT_OFFLINE="true",
               COPILOT_AUTO_UPDATE="false")
    (tmp_path / "copilot-home").mkdir(exist_ok=True)
    if url:
        env.update(COPILOT_PROVIDER_BASE_URL=url, COPILOT_MODEL="claude-sonnet-5.5")
    return env


@needs_copilot
def test_copilot_loads_plugin_and_skill(tmp_path):
    env = copilot_env(tmp_path)
    base = ["copilot", "--plugin-dir", str(PLUGIN)]
    plugins = json.loads(subprocess.run(base + ["plugin", "list", "--json"], capture_output=True,
                                        text=True, timeout=120, env=env).stdout)
    assert any(p["name"] == "reverse" and p["enabled"] for p in plugins)
    skills = json.loads(subprocess.run(base + ["skill", "list", "--json"], capture_output=True,
                                       text=True, timeout=120, env=env).stdout)
    assert any(s["name"] == "make-design-docs" and s["source"] == "plugin" for s in skills)


@needs_copilot
@pytest.mark.parametrize("agent,must_have,must_not_have", [
    ("code-analyst", {"view", "grep", "glob", "create"}, {"bash", "skill", "task"}),
    ("pdf-converter", {"view", "create", "bash"}, {"skill", "task"}),
    ("doc-matcher", {"view", "grep", "glob", "create"}, {"bash", "skill", "task"}),
    ("doc-writer", {"view", "grep", "glob", "create", "edit"}, {"bash", "skill", "task"}),
    ("doc-verifier", {"view", "grep", "glob", "create", "edit"}, {"bash", "skill", "task"}),
])
def test_copilot_agent_gets_only_its_tools(tmp_path, agent, must_have, must_not_have):
    fake = FakeModel(f"reverse:{agent}")
    try:
        work = tmp_path / "work"
        work.mkdir()
        subprocess.run(["copilot", "--plugin-dir", str(PLUGIN), "--no-auto-update", "--allow-all-tools",
                        "-p", "hello"], capture_output=True, text=True, timeout=180,
                       env=copilot_env(tmp_path, fake.url), cwd=work, stdin=subprocess.DEVNULL)
    finally:
        fake.close()
    main = [r for r in fake.requests if "task" in tool_names(r)]
    assert main, "統括への求めが届いていない"
    task_tool = next((t.get("function") or t) for t in main[0]["tools"]
                     if (t.get("function") or t).get("name") == "task")
    for name in AGENTS:
        assert f"reverse:{name}" in task_tool["description"]
    sub = [r for r in fake.requests if "task" not in tool_names(r)]
    assert sub, "担当エージェントへの求めが届いていない"
    names = set(tool_names(sub[0]))
    assert must_have <= names, names
    assert not (must_not_have & names), names
