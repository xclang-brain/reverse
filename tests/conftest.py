"""pytest の共通の設定。道具の本体は helpers.py にある（使い方は README.md）。"""
import pytest

import helpers


@pytest.fixture
def revdoclib():
    """スクリプトの本体（revdoclib）を読み込んで返す。"""
    return helpers.import_revdoclib()


@pytest.fixture(autouse=True)
def _encoding_guard():
    """どのテストでも、スクリプトのモジュールが文字コードを指定せずにファイルを読み書きしたら、失敗にする（A-10）。"""
    with helpers.EncodingGuard() as guard:
        yield guard
    if guard.found:
        pytest.fail("文字コードを指定しないファイルの読み書きがある：\n" + "\n".join(guard.found), pytrace=False)
