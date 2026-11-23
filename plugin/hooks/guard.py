"""Claude Code のフック：担当エージェントの Write と Edit を、出力先の .work/ と docs/ の下に限る。"""
import json
import os
import sys


def output_folder(path):
    """書く先の親のフォルダを上へたどり、.work/state.json があるフォルダを返す。"""
    folder = os.path.dirname(path)
    while not os.path.isfile(os.path.join(folder, ".work", "state.json")):
        parent = os.path.dirname(folder)
        if parent == folder:
            return None
        folder = parent
    return folder


def allowed(path):
    # シンボリックリンクを解いたパスで比べる（リンクを通して出力先の外に書かせない）
    path = os.path.realpath(path)
    out = output_folder(path)
    if out is None:
        return False
    parts = os.path.relpath(path, out).split(os.sep)
    return len(parts) > 1 and parts[0] in (".work", "docs") and parts not in (
        [".work", "state.json"], [".work", "plan.json"])


def main():
    data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    # ほかの作業の書き込みには触らない
    if not (data.get("agent_type") or "").startswith("reverse:"):
        return
    path = os.path.abspath(os.path.join(data.get("cwd", ""), data["tool_input"]["file_path"]))
    if allowed(path):
        return
    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "Write only to the files listed as write targets in your instruction file.",
    }}, sys.stdout)


main()
