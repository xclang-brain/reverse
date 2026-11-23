# 評価（C）

実際に材料を使って、Claude Code でスキルを最後まで動かす評価である。進め方、合格の条件、使うモデルは、要件の文書の 5.4 と 5.7 に従う（`docs/requirements/specification.md`）。

## 進め方

1. 材料を取得する（`fetch_materials.py`）。
2. 正解のファイル（`truth/small.json`、`truth/large.json`）を、実装する担当とは別のエージェントが作り、評価の前にコミットする。
3. 回ごとに、材料のコピーを入力にして、スキルを動かす（`run.py`。コピーは `prepare.py` で作る）。
4. 出力を採点する（`grade.py`）。`result.json` と、評価の報告に貼る表（`report.md`）ができる。

## 道具

| スクリプト | 使い方 | すること |
| --- | --- | --- |
| `fetch_materials.py` | `python evals/fetch_materials.py` | 材料を `evals/materials/`（Git の管理外）に取得する。 |
| `prepare.py` | `python evals/prepare.py <small\|large\|cpp> <コピー先>` | 材料のコピーを作る。small と large では、正解のファイルの変えた場所を当てる。 |
| `run.py` | `python evals/run.py <small\|large\|c12\|c13\|c14-src\|c14-pdf> <回のフォルダ>` | 回のフォルダ（リポジトリの外）に材料とプラグインをコピーし、`claude -p` でスキルを動かして、実行の記録を残す。止まったら、同じ引数で続きから動く。 |
| `grade.py` | `python evals/grade.py <回のフォルダ>` | C-1 〜 C-15 を判定する。独立したエージェントの判定は `judge/` に残し、採点し直すときに使い回す。 |

C-2 と C-3 で渡す行には、設計書のファイル名と見出しの並びを付ける（要件の 5.4）。誤りと分かっている文には、文のコードスパンの名前を前から順に見て、同じ名前を含む検証の対象の行が最初に見つかった名前で、その行の1つ（乱数の種で選ぶ）のファイル名と見出しの並びを付ける。どの名前を含む行もないときは、検証の対象の行の1つを、同じく乱数の種で選ぶ。

`run.py` は数時間かかるので、端末から切り離して動かす（`setsid nohup python evals/run.py small /tmp/eval/small > /tmp/eval/small.out 2>&1 &`）。`common.py` は、2つのスクリプトが共に使う関数である。

材料は次の3つである。

| 名前 | ソースコード | PDF |
| --- | --- | --- |
| small | ATK2-SC1 の `kernel` と `include` | ATK2 外部仕様書の抜粋（25 ページ） |
| large | ASP3 カーネル | 統合仕様書（385 ページ） |
| cpp | QP/C++ 8.1.6 の `src` と `include` の `.cpp` と `.hpp`（25 ファイル、6,658 行。GPL-3.0-or-later） | なし |

`prepare.py` のコピー先は、リポジトリの外の、まだないフォルダか空のフォルダにする。コピーには `src/`（と `pdf/`）ができる。変える前の行が正解のファイルと合わないときは、コピーを作らずに止まる。

## 正解のファイルの形式

UTF-8 の JSON で書く。ページは、評価に使う PDF（`materials/<材料>/pdf/` の PDF）で、1 から数えた通しのページである。

```json
{
  "changes": [
    {
      "file": "kernel/alarm.c",
      "names": ["SetRelAlarm"],
      "line": 120,
      "before_line": "\tif (cycle > MAXCYC) {",
      "after_line": "\tif (cycle >= MAXCYC) {",
      "before_value": ">",
      "after_value": ">=",
      "pages": [23],
      "spec_text": "cycle が MAXCYC より大きいときは、E_OS_VALUE を返す。"
    }
  ],
  "false_statements": [
    "SetRelAlarm は、cycle が MAXCYC より大きいときに E_OS_VALUE を返す。"
  ],
  "legacy_only": [
    {"words": ["アラーム", "満了"], "page": 25, "text": "アラームが満了すると、…"}
  ],
  "check_pages": [3, 5, 8, 10, 12, 14, 17, 19, 21, 24]
}
```

| キー | 中身 | 件数 |
| --- | --- | --- |
| `changes` | 変えた場所。値か条件の1か所ずつ。コメントは変えない。 | 10（large は5まで減らせる） |
| `changes[].file` | ソースファイルの、`src/` からの相対パス（`/` で区切る）。 | |
| `changes[].names` | 関数名。関数の外の内容は、定義の名前。複数書ける。 | 1以上 |
| `changes[].line` | 変えた行の番号（1 から数える）。 | |
| `changes[].before_line`、`after_line` | 変える前と後の行の全体。行末の改行は含めない。 | |
| `changes[].before_value`、`after_value` | 変える前と後の値か条件。 | |
| `changes[].pages` | 値か条件を書いている仕様書のページ。複数書ける。 | 1以上 |
| `changes[].spec_text` | 仕様書の文（もとの文のまま）。 | |
| `false_statements` | 誤りと分かっている文。変える前の内容を書いた文。 | 5 |
| `legacy_only` | 既存の設計書にしかない記述。 | 10 |
| `legacy_only[].words` | 目印の語。 | 2以上 |
| `legacy_only[].page`、`text` | ページと、もとの文。 | |
| `check_pages` | C-9 で確かめるページ。状態遷移図、タイミングチャート、文字の細かい図のうち、その材料にある種類のページを入れる。 | 10 |
