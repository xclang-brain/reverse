"""材料に固有の語のテスト。

確かめる受入条件は A-13 である。根拠は、要件の文書の 5.2 と、禁止事項 P-13 である。
語は、evals/fetch_materials.py にあるリポジトリと PDF の名前と、正解のファイル（evals/truth/*.json）の関数名である。
"""
import ast
import re

import helpers

EVALS = helpers.REPO / "evals"
PLUGIN = helpers.REPO / "plugin"


def _material_words():
    """(リポジトリと PDF の名前, 正解のファイルの関数名) を返す。"""
    # fetch_materials.py は動かさずに、REPOS（リポジトリの名前が鍵）と PDFS（PDF の名前）の値を読む
    tree = ast.parse(helpers.read_text(EVALS / "fetch_materials.py"))
    values = {t.id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
              for t in node.targets if isinstance(t, ast.Name) and t.id in ("REPOS", "PDFS")}
    names = set(values["REPOS"]) | set(values["PDFS"])
    functions = set()
    for path in sorted((EVALS / "truth").glob("*.json")):
        for change in helpers.read_json(path)["changes"]:
            functions.update(change["names"])
    return names, functions


def test_plugin_has_no_material_words():
    """A-13：plugin/ の全部のファイルに、材料のリポジトリと PDF の名前、正解のファイルの関数名がない（P-13）。"""
    names, functions = _material_words()
    assert names and functions
    files = sorted(p for p in PLUGIN.rglob("*") if p.is_file())
    assert files, "plugin/ にファイルがない"
    found = []
    for path in files:
        rel = path.relative_to(PLUGIN).as_posix()
        text = rel + "\n" + path.read_bytes().decode("utf-8", "replace")
        lower = text.lower()
        # ファイルとリポジトリの名前は、大文字と小文字を区別せずに探す
        found += ["%s：%s" % (rel, w) for w in sorted(names) if w.lower() in lower]
        # 関数名は、識別子の全体として、大文字と小文字を区別して探す
        found += ["%s：%s" % (rel, w) for w in sorted(functions)
                  if re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(w), text)]
    assert not found, "plugin/ に材料に固有の語がある：\n" + "\n".join(found)
