"""検索のフック（スクリプトの仕様の 10章）。仕上げで .work/search_hook.py にコピーし、mkdocs.yml の hooks で読み込む。

ビルドが終わるたびに、検索の索引の、漢字で終わる所の後ろに U+2060（幅のない文字）を入れる。
mkdocs-material の検索が、問い合わせの漢字の並びを、索引にある短い語に書き換えないようにするためである。
mkdocs が1つのファイルとして読み込むので、標準ライブラリと mkdocs だけを使う。
"""
import json
import os
import re

from mkdocs.plugins import event_priority

KANJI = "\u2e80-\u2fdf\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134f"
# mkdocs.yml の search の separator と同じ文字。変えるときは、revdoclib/finish.py の MKDOCS_FIXED も直す。
SEPARATOR = r'[\s\-,:!=\[\]()"/\u3000-\u303f\u3041-\u309f\uff00-\uffef]'
WORD_JOINER = "\u2060"
# 漢字の直後が、区切りの文字、`<`、文字列の終わりである所
_KANJI_END = re.compile("([%s])(?=%s|<|\\Z)" % (KANJI, SEPARATOR))


@event_priority(-100)  # ほかのプラグインが索引を書いた後に動く
def on_post_build(config, **kwargs):
    path = os.path.join(config["site_dir"], "search", "search_index.json")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        index = json.load(f)
    for doc in index["docs"]:
        for key in ("title", "text"):
            doc[key] = _KANJI_END.sub("\\1" + WORD_JOINER, doc[key])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
