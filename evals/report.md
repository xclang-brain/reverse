# 評価の報告

公開されている OSS を材料にして、Claude Code でスキルを最後まで動かし、要件の文書（`docs/requirements/specification.md`）の 5.4 の条件（C-1 〜 C-15）で確かめた結果である。評価の進め方と道具は、`evals/README.md` に書いてある。

- 回ごとに、`plugin/` のコミット、モデル、Claude Code のバージョン、条件ごとの件数と合否を載せる。不合格の回も、全部載せる。
- 統括と担当エージェントは `claude-sonnet-5-5`、判定する独立したエージェントは `claude-opus-5-5` で動かした。
- 回の後にプラグインを直したときは、直したことを、その回の下に書く。合否は、PR に入れる `plugin/` と同じ内容で動かした回で決める。

## まとめ

（評価は進行中である。この節は、最後の回が終わったときに書く。）

## 自動テストと読み込みのテスト（A、B、D）

| 確かめ方 | 結果 |
| --- | --- |
| A（スクリプトの自動テスト） | この環境（Linux、Python 3.13）で全部通る。件数は、コミットごとに `python3 -m pytest -q --ignore=tests/loading` で分かる。 |
| B（読み込みのテスト。`tests/loading`） | Claude Code 2.1.330 と GitHub Copilot CLI 1.0.114 で、4 件が全部通る。 |
| D（GitHub Actions） | `windows-latest` と `ubuntu-latest` の Python 3.x、`windows-latest` と `ubuntu-24.04` の Python 3.9 の、4 つの組み合わせで通る。 |

## 回の一覧

| 回 | `plugin/` のコミット | 合格の数 | 不合格の条件 |
| --- | --- | --- | --- |
| 小さい材料 1回目 | 17fd041 | 7 / 12 | C-2、C-6、C-8、C-10、C-5 |
| ソースコードだけ（C++）1回目 | 4881d17 | 1 / 2 | C-2 |
| 小さい材料 2回目 | dddfede | 8 / 12 | C-2、C-8、C-9、C-5 |
| 途中で止めて再開 1回目 | dddfede | 1 / 1 | なし |
| コンパクション 1回目 | dddfede | 1 / 1 | なし |
| 小さい材料 3回目 | 344550a | 10 / 12 | C-7、C-9 |
| 小さい材料 4回目 | b793f69 | 11 / 12 | C-7 |
| 小さい材料 5回目 | b840a15 | 11 / 12 | C-8 |
| 小さい材料 6回目 | 6d57772 | 11 / 12 | C-9 |
| 小さい材料 7回目 | a4c0fba | 8 / 12 | C-2、C-8、C-9、C-10 |
| 小さい材料 8回目 | 50f4ee1 | 11 / 12 | C-15 |
| 小さい材料 9回目 | 73b319b | 11 / 12 | C-8 |
| 小さい材料 10回目 | 86ff0f5 | 12 / 12 | なし |
| PDF だけ 2回目 | 86ff0f5 | 1 / 1 | なし |
| ソースコードだけ（C++）2回目 | 86ff0f5 | 2 / 2 | なし |
| 途中で止めて再開 2回目 | 86ff0f5 | 1 / 1 | なし |
| コンパクション 2回目 | 86ff0f5 | 1 / 1 | なし |
| 大きい材料 1回目 | 86ff0f5 | 9 / 12 | C-1、C-9、C-10 |

## 回ごとの結果

### 小さい材料 1回目

- `plugin/` のコミット：17fd041d4391266893edf095d31dbbd48b70bdee
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 1619 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-1 | done: true、check: true、problems: 0、failed: {"解析": "0/7", "変換": "0/3", "執筆（モジュール）": "0/3", "執筆（全体）": "0/12", "照合": "0/2", "検証": "0/46"}、questions: 0、denials: 0、early_next: 0、reply: true、restarts: {}、models: ["claude-sonnet-5-5"] | 合格 |
| C-2 | lines: 30、facts: 30、correct: 26、no_basis: 3、not_fact: 0、empty_kinds: []、fr_three_yes: "6/10"、tries: 1 | 不合格 |
| C-4 | extern: "54/54"、removed: "9/1041"、missing: [] | 合格 |
| C-6 | items: 4、complete: 4、sampled: "3/4" | 不合格 |
| C-7 | marked: "8/10"、rows: 71、unverifiable: "8/10" | 合格 |
| C-8 | rows: 24、not_found: "7/10" | 不合格 |
| C-9 | ok_pages: "9/10" | 合格 |
| C-10 | pages: "24/24"、mermaid_failed: "0/7"、blocked: 0、words: 3、search: {"プログラムコード末": 0, "スケジューリングポリシ": 2, "復帰時": 2} | 不合格 |
| C-11 | all: "25865/27301" | 合格 |
| C-15 | input_changed: 0、plugin_changed: 0、new_files: []、main_file_tools: 0、names_in_plugin: []、agent_tools: []、agents_without_log: 0 | 合格 |

#### 既知の変更に頼る条件

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-3 | wrong: "5/5"、tries: 1 | 合格 |
| C-5 | listed: "3/10"、candidates: 164、writes_before: 0 | 不合格 |

正解：変えた場所 10 か所（`<`→`<=`、`RUNNING`→`READY`、`UINT_C(0)`→`UINT_C(1)`、`>=`→`>`、`0U`→`1U`、`<`→`<=`、`<=`→`<`、`0U`→`1U`、`maxval + 1U`→`maxval`、`0U`→`1U`）、誤りの文 5 件、既存の設計書にしかない記述 10 件

記録した数：next: 26、jobs_by_stage: {"analyze": 7, "convert": 3, "write_module": 3, "write_overall": 12, "match": 2, "verify_module": 27, "verify_overall": 19}、verify_rounds: {"verify_module": {"1": 4, "2": 12, "3": 5, "4": 3, "5": 1, "6": 2}, "verify_overall": {"1": 9, "2": 6, "3": 4}}、max_context: 97732、compactions: 0、elapsed_sec: 1619、next_max_sec: 1.7、largest_match_record: 243、next_per_million_lines: 2180、none_sentence_sections: 6、figure_switched: 0、verify_removed: 9

この回の後に直したこと：照合の進め方を番号の順に書く。照合の仕事を 50 行までにする。一致した図を検証から外す。検索の設定を変える。機能の要求の形、不明点の探し方、図の検証のしかたを指示に書く。採点の誤り3つを直す（引用の省略、表の行の見出し、断られたツールの数え方）。

### ソースコードだけ（C++）1回目

- `plugin/` のコミット：4881d1726b1a08f903a922dde14290acde369a09
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 1185 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-2 | lines: 30、facts: 30、correct: 25、no_basis: 0、not_fact: 0、empty_kinds: []、fr_three_yes: "6/10"、tries: 1 | 不合格 |
| C-14 | questions: 0、done: true、check: true、failed: 0、site: true | 合格 |

この回の後に直したこと：（小さい材料の直しと同じ）

### 小さい材料 2回目

- `plugin/` のコミット：dddfedeb85bf248017ee37097536db15b21f302d
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 1620 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-1 | done: true、check: true、problems: 0、failed: {"解析": "0/7", "変換": "0/3", "執筆（モジュール）": "0/3", "執筆（全体）": "0/12", "照合": "0/4", "検証": "0/47"}、questions: 0、denials: 0、early_next: 0、reply: true、restarts: {}、models: ["claude-sonnet-5-5"] | 合格 |
| C-2 | lines: 30、facts: 30、correct: 26、no_basis: 0、not_fact: 0、empty_kinds: []、fr_three_yes: "10/10"、tries: 1 | 不合格 |
| C-4 | extern: "54/54"、removed: "7/1247"、missing: [] | 合格 |
| C-6 | items: 8、complete: 8、sampled: "8/8" | 合格 |
| C-7 | marked: "8/10"、rows: 87、unverifiable: "8/10" | 合格 |
| C-8 | rows: 25、not_found: "7/10" | 不合格 |
| C-9 | ok_pages: "8/10" | 不合格 |
| C-10 | pages: "24/24"、mermaid_failed: "0/11"、blocked: 0、words: 3、search: {"ペンディング": 1, "スケジューリングタイミング": 1, "後処理": 5} | 合格 |
| C-11 | all: "28644/30236" | 合格 |
| C-15 | input_changed: 0、plugin_changed: 0、new_files: []、main_file_tools: 0、names_in_plugin: []、agent_tools: []、agents_without_log: 0 | 合格 |

#### 既知の変更に頼る条件

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-3 | wrong: "5/5"、tries: 1 | 合格 |
| C-5 | listed: "7/10"、candidates: 182、writes_before: 0 | 不合格 |

正解：変えた場所 10 か所（`<`→`<=`、`RUNNING`→`READY`、`UINT_C(0)`→`UINT_C(1)`、`>=`→`>`、`0U`→`1U`、`<`→`<=`、`<=`→`<`、`0U`→`1U`、`maxval + 1U`→`maxval`、`0U`→`1U`）、誤りの文 5 件、既存の設計書にしかない記述 10 件

記録した数：next: 27、jobs_by_stage: {"analyze": 7, "convert": 3, "write_module": 3, "write_overall": 12, "match": 4, "verify_module": 30, "verify_overall": 17}、verify_rounds: {"verify_module": {"1": 5, "2": 14, "3": 5, "4": 3, "5": 2, "6": 1}, "verify_overall": {"1": 10, "2": 5, "3": 2}}、max_context: 100940、compactions: 0、elapsed_sec: 1620、next_max_sec: 1.8、largest_match_record: 184、next_per_million_lines: 2264、none_sentence_sections: 8、figure_switched: 0、verify_removed: 7

この回の後に直したこと：照合を2回行う。コンパイルの条件の注を足す。番号のない見出しのレベルを保つ。全体の文書でのモジュールの指し方、行の一部を確かめられたときの判定を指示に書く。採点で渡す行に、見出しの並びを付ける。

### 途中で止めて再開 1回目

- `plugin/` のコミット：dddfedeb85bf248017ee37097536db15b21f302d
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：2 回（1：c12_stop、2：finished）。かかった時間 1755 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-12 | stopped: true、done: true、unchanged: "3/3" | 合格 |

この回の後に直したこと：なし

### コンパクション 1回目

- `plugin/` のコミット：dddfedeb85bf248017ee37097536db15b21f302d
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 1984 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-13 | compactions: 2、done: true、check: true | 合格 |

この回の後に直したこと：なし

### 小さい材料 3回目

- `plugin/` のコミット：344550ace4d76b4e5b38a42290cc5437da8ae186
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 1674 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-1 | done: true、check: true、problems: 0、failed: {"解析": "0/7", "変換": "0/3", "執筆（モジュール）": "0/3", "執筆（全体）": "0/12", "照合": "0/8", "検証": "0/48"}、questions: 0、denials: 0、early_next: 0、reply: true、restarts: {}、models: ["claude-sonnet-5-5"] | 合格 |
| C-2 | lines: 30、facts: 30、correct: 29、no_basis: 0、not_fact: 0、empty_kinds: []、fr_three_yes: "10/10"、tries: 1 | 合格 |
| C-4 | extern: "54/54"、removed: "7/1296"、missing: [] | 合格 |
| C-6 | items: 11、complete: 11、sampled: "9/10" | 合格 |
| C-7 | marked: "8/10"、rows: 74、unverifiable: "7/10" | 不合格 |
| C-8 | rows: 29、not_found: "9/10" | 合格 |
| C-9 | ok_pages: "5/10" | 不合格 |
| C-10 | pages: "24/24"、mermaid_failed: "0/15"、blocked: 0、words: 3、search: {"メインエラーコード名": 3, "ソフトウェア": 5, "文字列": 6} | 合格 |
| C-11 | all: "34151/35988" | 合格 |
| C-15 | input_changed: 0、plugin_changed: 0、new_files: []、main_file_tools: 0、names_in_plugin: []、agent_tools: []、agents_without_log: 0 | 合格 |

#### 既知の変更に頼る条件

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-3 | wrong: "5/5"、tries: 1 | 合格 |
| C-5 | listed: "9/10"、candidates: 185、writes_before: 0 | 合格 |

正解：変えた場所 10 か所（`<`→`<=`、`RUNNING`→`READY`、`UINT_C(0)`→`UINT_C(1)`、`>=`→`>`、`0U`→`1U`、`<`→`<=`、`<=`→`<`、`0U`→`1U`、`maxval + 1U`→`maxval`、`0U`→`1U`）、誤りの文 5 件、既存の設計書にしかない記述 10 件

記録した数：next: 27、jobs_by_stage: {"analyze": 7, "convert": 3, "write_module": 3, "write_overall": 12, "match": 8, "verify_module": 32, "verify_overall": 16}、verify_rounds: {"verify_module": {"1": 4, "2": 17, "3": 4, "4": 3, "5": 2, "6": 2}, "verify_overall": {"1": 10, "2": 3, "3": 3}}、max_context: 101274、compactions: 0、elapsed_sec: 1674、next_max_sec: 1.8、largest_match_record: 154、next_per_million_lines: 2264、none_sentence_sections: 13、figure_switched: 0、verify_removed: 7

この回の後に直したこと：照合を文ごとに行う。2回目の照合が「一致」とした「既存設計書のみ」の記録を外す。識別子の形の語の検査を足す。画像で載せる図の決まりをはっきりさせる。

### 小さい材料 4回目

- `plugin/` のコミット：b793f69816f047c09566d75d3e7ad2221b9a0dc0
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 1947 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-1 | done: true、check: true、problems: 0、failed: {"解析": "0/7", "変換": "0/3", "執筆（モジュール）": "0/3", "執筆（全体）": "0/12", "照合": "0/12", "検証": "0/50"}、questions: 0、denials: 0、early_next: 0、reply: true、restarts: {}、models: ["claude-sonnet-5-5"] | 合格 |
| C-2 | lines: 30、facts: 30、correct: 28、no_basis: 1、not_fact: 0、empty_kinds: []、fr_three_yes: "10/10"、tries: 1 | 合格 |
| C-4 | extern: "54/54"、removed: "5/1242"、missing: [] | 合格 |
| C-6 | items: 11、complete: 11、sampled: "9/10" | 合格 |
| C-7 | marked: "10/10"、rows: 103、unverifiable: "7/10" | 不合格 |
| C-8 | rows: 31、not_found: "10/10" | 合格 |
| C-9 | ok_pages: "10/10" | 合格 |
| C-10 | pages: "24/24"、mermaid_failed: "0/10"、blocked: 0、words: 3、search: {"メモリ領域": 2, "セット": 3, "未定義判定": 10} | 合格 |
| C-11 | all: "32715/34255" | 合格 |
| C-15 | input_changed: 0、plugin_changed: 0、new_files: []、main_file_tools: 0、names_in_plugin: []、agent_tools: []、agents_without_log: 0 | 合格 |

#### 既知の変更に頼る条件

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-3 | wrong: "5/5"、tries: 1 | 合格 |
| C-5 | listed: "9/10"、candidates: 176、writes_before: 0 | 合格 |

正解：変えた場所 10 か所（`<`→`<=`、`RUNNING`→`READY`、`UINT_C(0)`→`UINT_C(1)`、`>=`→`>`、`0U`→`1U`、`<`→`<=`、`<=`→`<`、`0U`→`1U`、`maxval + 1U`→`maxval`、`0U`→`1U`）、誤りの文 5 件、既存の設計書にしかない記述 10 件

記録した数：next: 28、jobs_by_stage: {"analyze": 7, "convert": 3, "write_module": 3, "write_overall": 12, "match": 12, "verify_module": 31, "verify_overall": 19}、verify_rounds: {"verify_module": {"1": 4, "2": 14, "3": 5, "4": 2, "5": 2, "6": 1, "7": 2, "8": 1}, "verify_overall": {"1": 11, "2": 4, "3": 4}}、max_context: 105823、compactions: 0、elapsed_sec: 1947、next_max_sec: 1.8、largest_match_record: 141、next_per_million_lines: 2348、none_sentence_sections: 8、figure_switched: 0、verify_removed: 5

この回の後に直したこと：「既存設計書のみ」にする前に解析メモを探し直す。「既存設計書のみ」の記録を文ごとに分ける。解析メモの検査を、名前の集まりと照らす形に直す（大きい材料の解析の失敗が多かったため）。

### 小さい材料 5回目

- `plugin/` のコミット：b840a153d25e239fc5d724b58fa2cdd47ed5599e
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 1800 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-1 | done: true、check: true、problems: 0、failed: {"解析": "0/7", "変換": "0/3", "執筆（モジュール）": "0/3", "執筆（全体）": "0/12", "照合": "0/12", "検証": "0/44"}、questions: 0、denials: 0、early_next: 0、reply: true、restarts: {}、models: ["claude-sonnet-5-5"] | 合格 |
| C-2 | lines: 30、facts: 30、correct: 27、no_basis: 0、not_fact: 0、empty_kinds: []、fr_three_yes: "10/10"、tries: 1 | 合格 |
| C-4 | extern: "54/54"、removed: "14/1220"、missing: [] | 合格 |
| C-6 | items: 13、complete: 13、sampled: "9/10" | 合格 |
| C-7 | marked: "10/10"、rows: 82、unverifiable: "8/10" | 合格 |
| C-8 | rows: 32、not_found: "7/10" | 不合格 |
| C-9 | ok_pages: "10/10" | 合格 |
| C-10 | pages: "24/24"、mermaid_failed: "0/11"、blocked: 0、words: 3、search: {"メッセージ": 1, "セット時": 1, "時間保護": 3} | 合格 |
| C-11 | all: "31045/32701" | 合格 |
| C-15 | input_changed: 0、plugin_changed: 0、new_files: []、main_file_tools: 0、names_in_plugin: []、agent_tools: []、agents_without_log: 0 | 合格 |

#### 既知の変更に頼る条件

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-3 | wrong: "5/5"、tries: 1 | 合格 |
| C-5 | listed: "10/10"、candidates: 158、writes_before: 0 | 合格 |

正解：変えた場所 10 か所（`<`→`<=`、`RUNNING`→`READY`、`UINT_C(0)`→`UINT_C(1)`、`>=`→`>`、`0U`→`1U`、`<`→`<=`、`<=`→`<`、`0U`→`1U`、`maxval + 1U`→`maxval`、`0U`→`1U`）、誤りの文 5 件、既存の設計書にしかない記述 10 件

記録した数：next: 25、jobs_by_stage: {"analyze": 7, "convert": 3, "write_module": 3, "write_overall": 12, "match": 12, "verify_module": 31, "verify_overall": 13}、verify_rounds: {"verify_module": {"1": 5, "2": 13, "3": 6, "4": 3, "5": 1, "6": 2, "7": 1}, "verify_overall": {"1": 9, "2": 2, "3": 2}}、max_context: 98107、compactions: 0、elapsed_sec: 1800、next_max_sec: 1.7、largest_match_record: 175、next_per_million_lines: 2096、none_sentence_sections: 6、figure_switched: 0、verify_removed: 14

この回の後に直したこと：「既存設計書のみ」の文と不明点を、検証担当が確かめる。Mermaid の図にもコンパイルの条件の注を足す。行番号のある PDF から行番号を除く（大きい PDF の変換の試しで分かった）。

### 小さい材料 6回目

- `plugin/` のコミット：6d57772bd87050bf598c165fe5e935b8feb314c8
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 2057 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-1 | done: true、check: true、problems: 0、failed: {"解析": "0/7", "変換": "0/3", "執筆（モジュール）": "0/3", "執筆（全体）": "0/12", "照合": "0/12", "検証": "0/54"}、questions: 0、denials: 0、early_next: 0、reply: true、restarts: {}、models: ["claude-sonnet-5-5"] | 合格 |
| C-2 | lines: 30、facts: 30、correct: 27、no_basis: 1、not_fact: 0、empty_kinds: []、fr_three_yes: "10/10"、tries: 1 | 合格 |
| C-4 | extern: "54/54"、removed: "5/1217"、missing: [] | 合格 |
| C-6 | items: 13、complete: 13、sampled: "8/10" | 合格 |
| C-7 | marked: "9/10"、rows: 91、unverifiable: "9/10" | 合格 |
| C-8 | rows: 12、not_found: "8/10" | 合格 |
| C-9 | ok_pages: "8/10" | 不合格 |
| C-10 | pages: "24/24"、mermaid_failed: "0/14"、blocked: 0、words: 3、search: {"リンク": 1, "タイミング保護": 2, "本仕様": 8} | 合格 |
| C-11 | all: "31681/33272" | 合格 |
| C-15 | input_changed: 0、plugin_changed: 0、new_files: []、main_file_tools: 0、names_in_plugin: []、agent_tools: []、agents_without_log: 0 | 合格 |

#### 既知の変更に頼る条件

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-3 | wrong: "5/5"、tries: 1 | 合格 |
| C-5 | listed: "9/10"、candidates: 173、writes_before: 0 | 合格 |

正解：変えた場所 10 か所（`<`→`<=`、`RUNNING`→`READY`、`UINT_C(0)`→`UINT_C(1)`、`>=`→`>`、`0U`→`1U`、`<`→`<=`、`<=`→`<`、`0U`→`1U`、`maxval + 1U`→`maxval`、`0U`→`1U`）、誤りの文 5 件、既存の設計書にしかない記述 10 件

記録した数：next: 29、jobs_by_stage: {"analyze": 7, "convert": 3, "write_module": 3, "write_overall": 12, "match": 12, "verify_module": 31, "verify_overall": 23}、verify_rounds: {"verify_module": {"1": 4, "2": 16, "3": 4, "4": 2, "5": 2, "6": 1, "7": 2}, "verify_overall": {"1": 14, "2": 1, "3": 1, "4": 5, "5": 2}}、max_context: 106137、compactions: 0、elapsed_sec: 2057、next_max_sec: 1.8、largest_match_record: 191、next_per_million_lines: 2431、none_sentence_sections: 6、figure_switched: 0、verify_removed: 5

この回の後に直したこと：コンパイルの条件の注を、範囲の半分を超える行が条件の中にあれば足す。ページの中でコードブロックを閉じる検査を足す。

### 小さい材料 7回目

- `plugin/` のコミット：a4c0fbafd014a1cdaa45d8fa4389d3777989cc45
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 2098 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-1 | done: true、check: true、problems: 0、failed: {"解析": "0/7", "変換": "0/3", "執筆（モジュール）": "0/3", "執筆（全体）": "0/12", "照合": "0/12", "検証": "0/54"}、questions: 0、denials: 0、early_next: 0、reply: true、restarts: {}、models: ["claude-sonnet-5-5"] | 合格 |
| C-2 | lines: 30、facts: 30、correct: 26、no_basis: 0、not_fact: 0、empty_kinds: []、fr_three_yes: "9/10"、tries: 1 | 不合格 |
| C-4 | extern: "54/54"、removed: "27/1162"、missing: [] | 合格 |
| C-6 | items: 13、complete: 13、sampled: "10/10" | 合格 |
| C-7 | marked: "9/10"、rows: 83、unverifiable: "10/10" | 合格 |
| C-8 | rows: 31、not_found: "5/10" | 不合格 |
| C-9 | ok_pages: "8/10" | 不合格 |
| C-10 | pages: "24/24"、mermaid_failed: "2/9"、blocked: 0、words: 3、search: {"モード": 1, "ソフトウェアカウンタ": 3, "最下位ビット": 8} | 不合格 |
| C-11 | all: "30069/31594" | 合格 |
| C-15 | input_changed: 0、plugin_changed: 0、new_files: []、main_file_tools: 0、names_in_plugin: []、agent_tools: []、agents_without_log: 0 | 合格 |

#### 既知の変更に頼る条件

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-3 | wrong: "5/5"、tries: 1 | 合格 |
| C-5 | listed: "9/10"、candidates: 146、writes_before: 0 | 合格 |

正解：変えた場所 10 か所（`<`→`<=`、`RUNNING`→`READY`、`UINT_C(0)`→`UINT_C(1)`、`>=`→`>`、`0U`→`1U`、`<`→`<=`、`<=`→`<`、`0U`→`1U`、`maxval + 1U`→`maxval`、`0U`→`1U`）、誤りの文 5 件、既存の設計書にしかない記述 10 件

記録した数：next: 27、jobs_by_stage: {"analyze": 7, "convert": 3, "write_module": 3, "write_overall": 12, "match": 12, "verify_module": 34, "verify_overall": 20}、verify_rounds: {"verify_module": {"1": 5, "2": 15, "3": 4, "4": 2, "5": 2, "6": 2, "7": 2, "8": 2}, "verify_overall": {"1": 11, "2": 1, "3": 1, "4": 1, "5": 4, "6": 2}}、max_context: 104255、compactions: 0、elapsed_sec: 2098、next_max_sec: 2.2、largest_match_record: 232、next_per_million_lines: 2264、none_sentence_sections: 9、figure_switched: 0、verify_removed: 27

この回の後に直したこと：Mermaid の中のバッククォートを検査する。名前の囲み方を前後のページとそろえる。執筆担当は「既存設計書のみ」の内容を本文に書かない。

### 小さい材料 8回目

- `plugin/` のコミット：50f4ee1b7afa9f65bca324ba55164e9cb37a8030
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 2465 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-1 | done: true、check: true、problems: 0、failed: {"解析": "0/7", "変換": "0/3", "執筆（モジュール）": "0/3", "執筆（全体）": "0/12", "照合": "0/12", "検証": "0/62"}、questions: 0、denials: 0、hook_blocked: 0、early_next: 0、reply: true、restarts: {}、models: ["claude-sonnet-5-5"] | 合格 |
| C-2 | lines: 30、facts: 30、correct: 29、no_basis: 0、not_fact: 0、empty_kinds: []、fr_three_yes: "10/10"、tries: 1 | 合格 |
| C-4 | extern: "54/54"、removed: "14/1318"、missing: [] | 合格 |
| C-6 | items: 13、complete: 13、sampled: "10/10" | 合格 |
| C-7 | marked: "9/10"、rows: 87、unverifiable: "9/10" | 合格 |
| C-8 | rows: 21、not_found: "8/10" | 合格 |
| C-9 | ok_pages: "9/10" | 合格 |
| C-10 | pages: "24/24"、mermaid_failed: "0/14"、blocked: 0、words: 3、search: {"メモリ領域": 2, "ソースファイル": 5, "指定可能": 6} | 合格 |
| C-11 | all: "34526/36337" | 合格 |
| C-15 | input_changed: 0、plugin_changed: 0、new_files: ["scratch_fix.txt"]、main_file_tools: 0、names_in_plugin: []、agent_tools: []、agents_without_log: 0 | 不合格 |

#### 既知の変更に頼る条件

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-3 | wrong: "5/5"、tries: 1 | 合格 |
| C-5 | listed: "10/10"、candidates: 224、writes_before: 0 | 合格 |

正解：変えた場所 10 か所（`<`→`<=`、`RUNNING`→`READY`、`UINT_C(0)`→`UINT_C(1)`、`>=`→`>`、`0U`→`1U`、`<`→`<=`、`<=`→`<`、`0U`→`1U`、`maxval + 1U`→`maxval`、`0U`→`1U`）、誤りの文 5 件、既存の設計書にしかない記述 10 件

記録した数：next: 31、jobs_by_stage: {"analyze": 7, "convert": 3, "write_module": 3, "write_overall": 12, "match": 12, "verify_module": 38, "verify_overall": 24}、verify_rounds: {"verify_module": {"1": 4, "2": 19, "3": 5, "4": 2, "5": 2, "6": 2, "7": 2, "8": 2}, "verify_overall": {"1": 11, "2": 1, "3": 1, "4": 6, "5": 5}}、max_context: 111772、compactions: 0、elapsed_sec: 2465、next_max_sec: 1.6、largest_match_record: 195、next_per_million_lines: 2599、none_sentence_sections: 5、figure_switched: 0、verify_removed: 14

この回の後に直したこと：担当エージェントの書き込みを、フックで出力先の中に限る（解析担当が、作業フォルダに関係のないファイルを1つ作ったため）。採点で、フックが止めた書き込みを、許可を断られた呼び出しに数えない。

### 小さい材料 9回目

- `plugin/` のコミット：73b319bc4eb4639886f1087f342ef27cdcf19e4e
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 2649 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-1 | done: true、check: true、problems: 0、failed: {"解析": "0/7", "変換": "0/3", "執筆（モジュール）": "0/3", "執筆（全体）": "0/12", "照合": "0/12", "検証": "0/58"}、questions: 0、denials: 0、hook_blocked: 0、early_next: 0、reply: true、restarts: {}、models: ["claude-sonnet-5-5"] | 合格 |
| C-2 | lines: 30、facts: 30、correct: 29、no_basis: 0、not_fact: 0、empty_kinds: []、fr_three_yes: "8/10"、tries: 1 | 合格 |
| C-4 | extern: "54/54"、removed: "7/1314"、missing: [] | 合格 |
| C-6 | items: 14、complete: 14、sampled: "10/10" | 合格 |
| C-7 | marked: "9/10"、rows: 89、unverifiable: "8/10" | 合格 |
| C-8 | rows: 8、not_found: "5/8" | 不合格 |
| C-9 | ok_pages: "9/10" | 合格 |
| C-10 | pages: "24/24"、mermaid_failed: "0/14"、blocked: 0、words: 3、search: {"リンク": 1, "タイミングチャート": 2, "最高優先度": 4} | 合格 |
| C-11 | all: "35255/36936" | 合格 |
| C-15 | input_changed: 0、plugin_changed: 0、new_files: []、main_file_tools: 0、names_in_plugin: []、agent_tools: []、agents_without_log: 0 | 合格 |

#### 既知の変更に頼る条件

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-3 | wrong: "5/5"、tries: 1 | 合格 |
| C-5 | listed: "10/10"、candidates: 182、writes_before: 0 | 合格 |

正解：変えた場所 10 か所（`<`→`<=`、`RUNNING`→`READY`、`UINT_C(0)`→`UINT_C(1)`、`>=`→`>`、`0U`→`1U`、`<`→`<=`、`<=`→`<`、`0U`→`1U`、`maxval + 1U`→`maxval`、`0U`→`1U`）、誤りの文 5 件、既存の設計書にしかない記述 10 件

記録した数：next: 31、jobs_by_stage: {"analyze": 7, "convert": 3, "write_module": 3, "write_overall": 12, "match": 12, "verify_module": 33, "verify_overall": 25}、verify_rounds: {"verify_module": {"1": 5, "2": 16, "3": 4, "4": 2, "5": 2, "6": 1, "7": 2, "8": 1}, "verify_overall": {"1": 14, "2": 1, "3": 6, "4": 4}}、max_context: 110000、compactions: 0、elapsed_sec: 2649、next_max_sec: 2.0、largest_match_record: 233、next_per_million_lines: 2599、none_sentence_sections: 5、figure_switched: 0、verify_removed: 7

この回の後に直したこと：不明の判定は、別の検証担当がもう一度確かめ、2回続いたときに行を消す。

### 小さい材料 10回目

- `plugin/` のコミット：86ff0f5970eda74309c37961b373252585f46563
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：2 回（1：api_error、2：finished）。かかった時間 3681 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-1 | done: true、check: true、problems: 0、failed: {"解析": "0/7", "変換": "0/3", "執筆（モジュール）": "0/3", "執筆（全体）": "0/12", "照合": "0/12", "検証": "0/56"}、questions: 0、denials: 0、hook_blocked: 0、early_next: 0、reply: true、restarts: {"api_error": 1}、models: ["claude-sonnet-5-5"] | 合格 |
| C-2 | lines: 30、facts: 30、correct: 27、no_basis: 1、not_fact: 0、empty_kinds: []、fr_three_yes: "10/10"、tries: 1 | 合格 |
| C-4 | extern: "54/54"、removed: "3/1329"、missing: [] | 合格 |
| C-6 | items: 9、complete: 9、sampled: "9/9" | 合格 |
| C-7 | marked: "10/10"、rows: 99、unverifiable: "9/10" | 合格 |
| C-8 | rows: 13、not_found: "9/10" | 合格 |
| C-9 | ok_pages: "10/10" | 合格 |
| C-10 | pages: "24/24"、mermaid_failed: "0/10"、blocked: 0、words: 3、search: {"モジュール": 5, "ソフトウェアカウンタ": 4, "最大数": 11} | 合格 |
| C-11 | all: "35338/37050" | 合格 |
| C-15 | input_changed: 0、plugin_changed: 0、new_files: []、main_file_tools: 0、names_in_plugin: []、agent_tools: []、agents_without_log: 0 | 合格 |

#### 既知の変更に頼る条件

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-3 | wrong: "5/5"、tries: 1 | 合格 |
| C-5 | listed: "8/10"、candidates: 173、writes_before: 0 | 合格 |

正解：変えた場所 10 か所（`<`→`<=`、`RUNNING`→`READY`、`UINT_C(0)`→`UINT_C(1)`、`>=`→`>`、`0U`→`1U`、`<`→`<=`、`<=`→`<`、`0U`→`1U`、`maxval + 1U`→`maxval`、`0U`→`1U`）、誤りの文 5 件、既存の設計書にしかない記述 10 件

記録した数：next: 30、jobs_by_stage: {"analyze": 7, "convert": 3, "write_module": 3, "write_overall": 12, "match": 12, "verify_module": 35, "verify_overall": 21}、verify_rounds: {"verify_module": {"1": 4, "2": 16, "3": 6, "4": 2, "5": 2, "6": 2, "7": 2, "8": 1}, "verify_overall": {"1": 13, "2": 1, "3": 4, "4": 3}}、max_context: 89349、compactions: 0、elapsed_sec: 3681、next_max_sec: 1.9、largest_match_record: 233、next_per_million_lines: 2515、none_sentence_sections: 8、figure_switched: 0、verify_removed: 3

この回の後に直したこと：なし（12 の条件が全部合格。途中で、API の認証エラーで1回止まり、続きから呼び直した）

### PDF だけ 2回目

- `plugin/` のコミット：86ff0f5970eda74309c37961b373252585f46563
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 126 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-14 | questions: 0、done: true、check: true、failed: 0、site: true | 合格 |

この回の後に直したこと：なし

### ソースコードだけ（C++）2回目

- `plugin/` のコミット：86ff0f5970eda74309c37961b373252585f46563
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 1460 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-2 | lines: 30、facts: 30、correct: 30、no_basis: 0、not_fact: 0、empty_kinds: []、fr_three_yes: "9/10"、tries: 1 | 合格 |
| C-14 | questions: 0、done: true、check: true、failed: 0、site: true | 合格 |

この回の後に直したこと：なし

### 途中で止めて再開 2回目

- `plugin/` のコミット：86ff0f5970eda74309c37961b373252585f46563
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：2 回（1：c12_stop、2：finished）。かかった時間 2550 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-12 | stopped: true、done: true、unchanged: "4/4" | 合格 |

この回の後に直したこと：なし

### コンパクション 2回目

- `plugin/` のコミット：86ff0f5970eda74309c37961b373252585f46563
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 2661 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-13 | compactions: 2、done: true、check: true | 合格 |

この回の後に直したこと：なし

### 大きい材料 1回目

- `plugin/` のコミット：86ff0f5970eda74309c37961b373252585f46563
- モデル：claude-sonnet-5-5（記録にあったモデル：claude-sonnet-5-5。独立したエージェント：claude-opus-5-5）
- Claude Code：2.1.330 (Claude Code)
- 実行：1 回（1：finished）。かかった時間 31477 秒

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-1 | done: true、check: false、problems: 9、failed: {"解析": "1/169", "変換": "0/39", "執筆（モジュール）": "0/102", "執筆（全体）": "0/12", "照合": "0/444", "検証": "0/879"}、questions: 0、denials: 0、hook_blocked: 0、early_next: 0、reply: true、restarts: {}、models: ["claude-sonnet-5-5"] | 不合格 |
| C-2 | lines: 30、facts: 30、correct: 28、no_basis: 0、not_fact: 0、empty_kinds: []、fr_three_yes: "8/10"、tries: 1 | 合格 |
| C-4 | extern: "103/103"、removed: "225/18373"、missing: [] | 合格 |
| C-6 | items: 103、complete: 103、sampled: "10/10" | 合格 |
| C-7 | marked: "8/10"、rows: 4639、unverifiable: "9/10" | 合格 |
| C-8 | rows: 173、not_found: "8/10" | 合格 |
| C-9 | ok_pages: "5/10" | 不合格 |
| C-10 | pages: "260/260"、mermaid_failed: "0/101"、blocked: 0、words: 3、search: {"初期化データ": 0, "パケット型": 6, "仕様上": 14} | 不合格 |
| C-11 | all: "548282/580960"、zybo: "11619/13516" | 合格 |
| C-15 | input_changed: 0、plugin_changed: 0、new_files: []、main_file_tools: 0、names_in_plugin: []、agent_tools: []、agents_without_log: 0 | 合格 |

#### 既知の変更に頼る条件

| 条件 | 件数 | 合否 |
| --- | --- | --- |
| C-3 | wrong: "5/5"、tries: 1 | 合格 |
| C-5 | listed: "9/10"、candidates: 1663、writes_before: 0 | 合格 |

正解：変えた場所 10 か所（`16`→`8`、`<=`→`<`、`<`→`<=`、`E_ILUSE`→`E_OBJ`、`<=`→`<`、`<`→`>`、`(intpri) <= TIPM_ENAALL`→`(intpri) < TIPM_ENAALL`、`E_QOVR`→`E_OBJ`、`0U`→`1U`、`==`→`!=`）、誤りの文 5 件、既存の設計書にしかない記述 10 件

記録した数：next: 451、jobs_by_stage: {"analyze": 169, "convert": 39, "write_module": 102, "write_overall": 12, "match": 444, "verify_module": 775, "verify_overall": 104}、verify_rounds: {"verify_module": {"1": 3, "2": 2, "3": 3, "4": 15, "5": 5, "6": 5, "7": 13, "8": 4, "9": 4, "10": 11, "11": 5, "12": 4, "13": 3, "14": 9, "15": 9, "16": 6, "17": 4, "18": 4, "19": 10, "20": 2, "21": 3, "22": 2, "23": 4, "24": 17, "25": 12, "26": 5, "27": 4, "28": 6, "29": 3, "30": 4, "31": 4, "32": 5, "33": 4, "34": 6, "35": 9, "36": 3, "37": 4, "38": 10, "39": 3, "40": 4, "41": 8, "42": 5, "43": 5, "44": 4, "45": 4, "46": 2, "47": 5, "48": 5, "49": 3, "50": 4, "51": 9, "52": 4, "53": 2, "54": 9, "55": 18, "56": 8, "57": 3, "58": 4, "59": 3, "60": 4, "61": 5, "62": 7, "63": 4, "64": 4, "65": 5, "66": 6, "67": 3, "68": 8, "69": 3, "70": 6, "71": 3, "72": 5, "73": 3, "74": 4, "75": 4, "76": 3, "77": 5, "78": 3, "79": 2, "80": 2, "81": 3, "82": 3, "83": 4, "84": 3, "85": 5, "86": 3, "87": 2, "88": 3, "89": 4, "90": 2, "91": 7, "92": 11, "93": 9, "94": 12, "95": 9, "96": 7, "97": 3, "98": 2, "99": 5, "100": 4, "101": 4, "102": 4, "103": 1, "104": 3, "105": 4, "106": 4, "107": 5, "108": 2, "109": 3, "110": 2, "111": 2, "112": 5, "113": 2, "114": 2, "115": 4, "116": 3, "117": 3, "118": 2, "119": 3, "120": 3, "121": 2, "122": 3, "123": 2, "124": 2, "125": 5, "126": 2, "127": 2, "128": 3, "129": 2, "130": 2, "131": 2, "132": 2, "133": 2, "134": 2, "135": 4, "136": 3, "137": 2, "138": 3, "139": 2, "140": 3, "141": 3, "142": 3, "143": 4, "144": 2, "145": 2, "146": 3, "147": 2, "148": 6, "149": 4, "150": 2, "151": 2, "152": 3, "153": 2, "154": 2, "155": 2, "156": 2, "157": 2, "158": 6, "159": 6, "160": 3, "161": 3, "162": 2, "163": 5, "164": 2, "165": 7, "166": 9, "167": 2, "168": 2, "169": 3, "170": 2, "171": 5, "172": 2, "173": 5, "174": 2, "175": 4, "176": 3, "177": 2, "178": 5, "179": 3, "180": 2, "181": 2, "182": 3}, "verify_overall": {"1": 30, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 1, "8": 1, "9": 1, "10": 1, "11": 1, "12": 1, "13": 1, "14": 1, "15": 1, "16": 1, "17": 1, "18": 1, "19": 1, "20": 1, "21": 1, "22": 1, "23": 1, "24": 1, "25": 1, "26": 1, "27": 1, "28": 1, "29": 1, "30": 1, "31": 1, "32": 1, "33": 1, "34": 1, "35": 1, "36": 1, "37": 1, "38": 1, "39": 1, "40": 1, "41": 1, "42": 1, "43": 1, "44": 1, "45": 1, "46": 1, "47": 1, "48": 1, "49": 1, "50": 1, "51": 1, "52": 1, "53": 1, "54": 11, "55": 1, "56": 2, "57": 8}}、max_context: 965050、compactions: 1、elapsed_sec: 31477、next_max_sec: 3.7、largest_match_record: 463、next_per_million_lines: 2198、none_sentence_sections: 6、figure_switched: 0、verify_removed: 225

この回の後に直したこと：図のページだけが文字化けしている PDF で、ページごとに、埋め込みテキストを使うかを決める（図の 9 ページの文字化けを、変換担当がそのまま写していた）。変換の指示を直す（図の題、画像にした図の説明文、線が 30 本を超える図、列に分かれた図、前のページから続く表）。検索の索引の、漢字で終わる語の後ろに U+2060 を入れる（漢字で始まり、カタカナが続く語の検索が 0 件になった）。最後の検査では、前後のページで囲んだ語を調べない（変換の検査だけで調べる）。
