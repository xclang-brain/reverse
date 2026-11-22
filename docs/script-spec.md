# スクリプトの仕様

スキルが実行するスクリプト `revdoc.py` の入出力を決める。自動テスト（[要件と受入条件](requirements/specification.md) の A）と実装は、この仕様に従う。

## 1. 共通の決まり

- 置き場所は `plugin/skills/make-design-docs/scripts/revdoc.py`。本体は同じフォルダの `revdoc/` パッケージに置く。
- 呼び方は `python revdoc.py <サブコマンド> [オプション]`。Python 3.9 以上で動く。
- 標準出力には、JSON のオブジェクトを1つだけ書く。文字は ASCII だけを使う（日本語は `\uXXXX` の形にする）。
- 成功したときは `"ok": true` を含め、終了コードを 0 にする。
- 失敗したときは `{"ok": false, "error": "<エラーの名前>", "message": "<日本語の説明>"}` を書き、終了コードを 1 にする。
- ファイルは UTF-8（BOM なし）、改行 `\n` で書く。読むときは BOM を外す。
- 状態を書き換えるときは、一時ファイルに書いてから置き換える。
- ソースコードのフォルダと PDF には書き込まない。書き込むのは出力先の中だけとする。
- `<出力先>/.work/` を作業フォルダと呼ぶ。以下の `.work/` は、このフォルダを指す。

## 2. `init`

```
python revdoc.py init --out <出力先> [--src <フォルダ>] [--pdf <フォルダまたはファイル>]
                      [--unit-lines 2000] [--module-units 12] [--pdf-chunk-pages 10]
```

入力を確かめ、作業の計画を作る。

### 2.1 エラー

| エラーの名前 | 起きる条件 |
| --- | --- |
| `no_input` | `--src` と `--pdf` の両方がない。 |
| `src_not_found` | `--src` のフォルダがない。 |
| `pdf_not_found` | `--pdf` のパスがない。 |
| `no_pdf_files` | `--pdf` のフォルダに PDF が1つもない。 |
| `no_source_files` | `--src` のフォルダに、対象のソースファイルが1つもない。 |
| `missing_packages` | 必要な Python パッケージがない。JSON に `"packages"`（足りないパッケージ名の配列）と `"install"`（インストールのコマンドの文字列）を含める。 |
| `state_mismatch` | 出力先に前の状態があり、`--src` か `--pdf` が前と違う。 |

- 必要なパッケージは、`mkdocs` と `material`（mkdocs-material）。`--pdf` があるときは、`pypdfium2` と `PIL`（Pillow）も必要とする。
- 環境変数 `REVDOC_SKIP_PACKAGE_CHECK=1` があるときは、パッケージの確認を飛ばす（テスト用）。

### 2.2 成功したときの出力

```json
{"ok": true, "resumed": false, "mode": "both", "out": "<出力先の絶対パス>",
 "units": 12, "modules": 4, "source_files": 30, "source_lines": 21000,
 "pdf_files": 1, "pdf_pages": 40}
```

- `mode` は、`both`（両方）、`source`（ソースコードだけ）、`pdf`（PDF だけ）のいずれか。
- 出力先に同じ入力の状態がすでにあるときは、計画を作り直さずに `"resumed": true` を返す。

### 2.3 対象のソースファイル

`--src` のフォルダを再帰的に調べ、次のすべてに当てはまるファイルを対象にする。

- `.git`、`.svn`、`.hg` のフォルダの中にない。
- 出力先のフォルダの中にない（出力先がソースコードのフォルダの中にあるとき）。
- 先頭の 8,192 バイトに NUL（0x00）がない。
- 大きさが 2MB 以下である。
- 拡張子（小文字にして比べる）が、次のどれでもない：`md`、`markdown`、`txt`、`rst`、`adoc`、`html`、`htm`、`css`、`csv`、`tsv`、`log`、`svg`、`lock`、`map`、`lst`、`hex`、`srec`、`s19`、`mot`、`pdf`。

行数は、改行（`\n`）の数で数える。最後の行に改行がないときは、1行足す。空のファイルは対象から外す。

### 2.4 文字コード

対象のファイルごとに、`utf-8`、`euc_jp`、`cp932` の順に読めるかを試し、最初に読めたものをそのファイルの文字コードとする。どれでも読めないときは `latin-1` とする。

UTF-8 でないファイルは、UTF-8 に直した写しを `.work/src-utf8/<ソースコードのフォルダからの相対パス>` に作る。

### 2.5 ユニット

- 対象のファイルを、ソースコードのフォルダからの相対パス（区切りは `/`）の文字コード順に並べる。フォルダごとにまとめ、フォルダも相対パスの文字コード順に並べる。直下のファイルのフォルダは `.` とし、最初に置く。
- 1つのフォルダの中で、ファイルを順に足していく。足すと行数の合計が `--unit-lines` を超えるときは、そこでユニットを閉じ、次のユニットを始める。
- 行数が `--unit-lines` を超えるファイルは、ほかのファイルと混ぜない。先頭から `--unit-lines` 行ずつに分け、範囲ごとに1ユニットとする。
- ユニットの ID は、並び順に `U0001`、`U0002`、…とする。

### 2.6 モジュール

- 対象のファイルを直接含むフォルダ1つを、1モジュールとする。
- モジュールの ID は、フォルダの相対パスの `/` を `-` に置き換え、英数字・`.`・`_`・`-` 以外の文字を `_` に置き換えたものとする。直下（`.`）は `root` とする。ID が重なるときは、後のものに `-2`、`-3`、…を付ける。
- ユニットの数が `--module-units` を超えるモジュールは、先頭から `--module-units` 個ずつに分ける。分けたものの ID は `<元の ID>-part1`、`<元の ID>-part2`、…とする。
- 機能の要求の ID の接頭辞は、`FR-<モジュールの ID を大文字にし、英数字以外を - に置き換えたもの>-` とする。

### 2.7 PDF

- `--pdf` がフォルダのときは、再帰的に `.pdf`（大文字小文字を区別しない）を探し、相対パスの文字コード順に並べる。ファイルのときは、その1つを使う。
- PDF の ID は、並び順に `D01`、`D02`、…とする。
- PDF ごとに、表示用の名前（拡張子を除いたファイル名）と、フォルダ名を決める。フォルダ名は、表示用の名前の `/ \ : * ? " < > |` と空白を `_` に置き換えたものとする。重なるときは、後のものに `-2`、`-3`、…を付ける。
- 各ページを PNG にして `.work/pages/<PDF の ID>/p0001.png`（4桁のページ番号）に置く。解像度は 150 dpi とし、長い辺が 2,000 ピクセルを超えるときは、2,000 ピクセルになるように縮める。
- 各ページに埋め込まれたテキストを `.work/pages/<PDF の ID>/p0001.txt` に置く。テキストがないページは、空のファイルにする。
- すでにあるファイルは作り直さない。

### 2.8 計画のファイル

`.work/inventory.json` に、次の形で書く。

```json
{
  "src": "<絶対パス または null>", "pdf": "<絶対パス または null>", "mode": "both",
  "params": {"unit_lines": 2000, "module_units": 12, "pdf_chunk_pages": 10},
  "files": [{"path": "kernel/task.c", "lines": 812, "encoding": "utf-8"}],
  "skipped": [{"path": "tools/big.bin", "reason": "binary"}],
  "units": [{"id": "U0001", "module": "kernel", "lines": 1650,
             "files": [{"path": "kernel/task.c", "start": 1, "end": 812}]}],
  "modules": [{"id": "kernel", "path": "kernel", "title": "kernel", "units": ["U0001"],
               "lines": 1650, "fr_prefix": "FR-KERNEL-"}],
  "pdfs": [{"id": "D01", "file": "<絶対パス>", "title": "spec", "folder": "spec", "pages": 40}]
}
```

- `skipped` の `reason` は、`binary`、`too_large`、`excluded_extension`、`empty` のいずれか。バージョン管理のフォルダと出力先の中のファイルは、`skipped` に載せない。
- 分けたモジュールの `title` は、`<フォルダの相対パス>（1/3）` の形にする。直下のモジュールの `title` は `（直下）` とする。

## 3. `next`

```
python revdoc.py next --out <出力先> [--count 4]
```

前に渡した仕事の出来を検査し、次の仕事を返す。

### 3.1 出力

```json
{"ok": true, "done": false, "stage": "analyze_convert",
 "progress": {"done": 3, "total": 16, "failed": 0},
 "tasks": [{"id": "T0004", "agent": "reverse:code-analyst", "file": "<指示のファイルの絶対パス>"}]}
```

- `tasks` は、最大で `--count` 件。
- `done` が `false` のときは、`"instruction"` に、次に行うことを英語の1文で入れる（例：`Run every task with its agent in parallel, then call next again. Do not stop until done is true.`）。統括のエージェントが途中で止まらないようにするためである。
- すべての段階が終わったときは、`{"ok": true, "done": true, "stage": "done", "check_passed": true, "summary": {...}}` を返す。`summary` は、`status` の `summary` と同じ。
- `init` をしていない出力先では、エラー `not_initialized` を返す。

### 3.2 段階

| 段階の名前 | 仕事の種類 | 行う条件 |
| --- | --- | --- |
| `analyze_convert` | `analyze`（ユニットごと）、`convert`（PDF の `--pdf-chunk-pages` ページごと） | いつも |
| `match` | `match`（`docs/legacy/` の本文のファイルごと） | `mode` が `both` |
| `write_modules` | `write_module`（モジュールごと） | `mode` が `both` か `source` |
| `verify_modules` | `verify_module`（モジュールごと） | `mode` が `both` か `source` |
| `write_overall` | `write_architecture`、`write_srs`（1件ずつ） | `mode` が `both` か `source` |
| `fix` | `fix`（1件） | 仕上げの検査が不合格のとき |
| `done` | なし | すべてが終わったとき |

- `next` は、渡した仕事がすべて合格か失敗になるまで、同じ段階の仕事を返す。段階の仕事がなくなったら、次の段階へ進む。
- 段階の変わり目で、スクリプトだけの処理を行う。
  - `analyze_convert` の後：既存の設計書の組み立て（5章）。
  - `match` の後：照合の記録の振り分け（6章）。
  - `verify_modules` の後：要約（7章）。
  - `write_overall` の後（`mode` が `pdf` のときは `analyze_convert` の後）：仕上げ（8章）と検査（9章）。
- 検査が不合格のときは、`fix` の仕事を1件渡す。`fix` の後にもう一度仕上げと検査を行う。`fix` は2回までとする。2回目の後も不合格のときは、`"check_passed": false` で `done` にする。
- 仕事の ID は、作った順に `T0001`、`T0002`、…とする。

### 3.3 仕事の状態と検査

- 仕事の状態は、`pending`（まだ）、`issued`（渡した）、`done`（合格）、`failed`（失敗）のいずれか。
- `next` を呼ぶと、まず `issued` の仕事の出力を検査する。合格なら `done` にする。不合格なら、試した回数を1増やす。
- 試した回数が3になった仕事は `failed` にする。3未満なら、不合格の理由を指示のファイルの末尾に `## 前回の不合格の理由` の見出しで書き足し、もう一度渡す。
- 状態は `.work/state.json` に書く。形は次のとおり。

```json
{"stage": "analyze_convert", "fix_rounds": 0, "check_passed": null,
 "tasks": [{"id": "T0001", "kind": "analyze", "target": "U0001", "agent": "reverse:code-analyst",
            "status": "pending", "attempts": 0, "outputs": ["notes/U0001.md"]}]}
```

- `outputs` は、出力先からの相対パス（区切りは `/`）で書く。

### 3.4 仕事の種類ごとの決まり

「必須の見出し」は、行の全体がその文字列と同じ行があることを指す。

| 種類 | 担当エージェント | 出力のファイル | 合格の条件 |
| --- | --- | --- | --- |
| `analyze` | `reverse:code-analyst` | `.work/notes/<ユニットの ID>.md` | ファイルがあり、必須の見出しがすべてある。 |
| `convert` | `reverse:pdf-converter` | `.work/converted/<PDF の ID>/c0001.md`（4桁の通し番号） | ファイルがあり、担当のページの目印が番号順にすべてある。埋め込まれたテキストの再現率が 0.8 以上である。 |
| `match` | `reverse:doc-matcher` | `.work/match/M0001.md`（4桁の通し番号） | ファイルがあり、4.1 の形式になっている。 |
| `write_module` | `reverse:doc-writer` | `docs/design/modules/<モジュールの ID>.md`、`docs/requirements/3-1-functions/<モジュールの ID>.md`、`.work/unknowns/<モジュールの ID>.md` | 3つのファイルがあり、必須の見出しがすべてある。要求の ID が接頭辞に合い、重なりがない。不明点が 4.2 の形式になっている。設計書の2つは 1,000 行以下である。 |
| `verify_module` | `reverse:doc-verifier` | `.work/verify/<モジュールの ID>.md` | ファイルがあり、必須の見出しがすべてある。`write_module` の合格の条件も、引き続き満たしている。 |
| `write_architecture` | `reverse:doc-writer` | `docs/design/architecture.md`、`.work/unknowns/_architecture.md` | ファイルがあり、必須の見出しがすべてある。 |
| `write_srs` | `reverse:doc-writer` | `docs/requirements/` の 3.1 以外の章のファイル（下の表）、`.work/unknowns/_srs.md` | ファイルがすべてあり、必須の見出しがすべてある。 |
| `fix` | `reverse:doc-writer` | なし | いつも合格とする（結果は、次の検査で判定する）。 |

必須の見出しは、次のとおり。

| ファイル | 必須の見出し |
| --- | --- |
| 解析メモ | `## 役割`、`## 公開している関数と型`、`## データ構造`、`## 処理の流れ`、`## 定数と設定値`、`## 外部とのやり取り`、`## 分からないこと` |
| モジュールの内部設計書 | `## 役割`、`## 公開インターフェース`、`## データ構造`、`## 処理の流れ`、`## 状態`、`## 依存関係`、`## エラー処理`、`## 並行性とタイミング`、`## 設定値と定数`、`## 外部とのやり取り` |
| 機能の要求（`3-1-functions/`） | `## 機能の要求` |
| 検証の記録 | `## 確かめた範囲`、`## 直した点` |
| 全体の内部設計書 | `## システムの概要と境界`、`## モジュールの構成`、`## 依存関係`、`## 実行の構造`、`## 主なデータの流れ`、`## 共通の仕組み`、`## ビルドと構成` |
| `1-introduction.md` | `## 1.1 目的`、`## 1.2 範囲`、`## 1.3 製品の概要`、`### 1.3.1 製品の位置づけ`、`### 1.3.2 製品の機能`、`### 1.3.3 利用者の特性`、`### 1.3.4 制限`、`## 1.4 定義` |
| `2-references.md` | `# 2 参考文献` |
| `3-2-performance.md` | `# 3.2 性能の要求` |
| `3-3-usability.md` | `# 3.3 ユーザビリティの要求` |
| `3-4-interfaces.md` | `# 3.4 インターフェースの要求` |
| `3-5-database.md` | `# 3.5 論理データベースの要求` |
| `3-6-design-constraints.md` | `# 3.6 設計制約` |
| `3-7-attributes.md` | `# 3.7 ソフトウェアシステム属性` |
| `3-8-supporting.md` | `# 3.8 補足情報` |
| `4-verification.md` | `# 4 検証` |
| `5-appendices.md` | `## 5.1 前提と依存関係`、`## 5.2 略語` |

- モジュールの内部設計書、全体の内部設計書、機能の要求、`1-introduction.md`、`5-appendices.md` は、1行目が `# ` で始まる見出しであること。
- 要求の ID は、行の先頭の `- **<ID>**：` の形で書く（コロンは全角でも半角でもよい）。機能の要求の ID は、`<接頭辞><3桁の番号>`（例：`FR-KERNEL-001`）とする。
- ページの目印は、行の全体が `<!-- page: N -->`（N はページ番号）の行とする。
- 埋め込まれたテキストの再現率は、次のように求める。担当のページの `.txt` をつなぎ、`str.isalnum()` が真の文字だけを数える。その文字ごとの個数のうち、出力のファイルにも現れる個数（少ないほう）の合計を、全体の個数で割る。数える文字が 50 個未満のときは、再現率を検査しない。

### 3.5 指示のファイル

`next` は、仕事ごとに `.work/tasks/<仕事の ID>.md` を書く。担当エージェントは、このファイルだけを読んで仕事を始める。指示のファイルには、次を書く。

- 仕事の種類と対象（ユニット、モジュールなど）。
- 読むもの（絶対パス）。`analyze` では、ファイルごとの行の範囲も書く。UTF-8 でないファイルは、`.work/src-utf8/` の写しのパスを書く。
- 書き出し先（絶対パス）と、必須の見出し。
- `write_module` では、要求の ID の接頭辞。
- `match` と `write_module` では、モジュールの ID と題の一覧。
- `convert` では、ページの画像とテキストのパス、ページの目印の書き方、`zoom` の呼び方。
- `fix` では、検査で不合格になった項目の一覧。

## 4. 担当エージェントが書く記録の形式

### 4.1 照合の記録

```markdown
# 照合の記録

## 食い違い

### <題>
- 既存の設計書の記述: <内容>
- ソースコードの内容: <内容>
- 既存の設計書での場所: <文書名とページ>
- ソースコードでの場所: <ファイル名と関数名>
- モジュール: <モジュールの ID または 全体>

## 既存の設計書にしかない内容

### <題>
- 内容: <内容>
- 既存の設計書での場所: <文書名とページ>
- モジュール: <モジュールの ID または 全体>
```

- 2つの `## ` の見出しは必須とする。項目（`### `）は、0件でもよい。
- 項目のキーは、上に示したものがすべて必要である。キーと値の区切りは `: `（半角）とする。
- `モジュール` の値は、計画にあるモジュールの ID か、`全体` とする。

### 4.2 不明点

```markdown
# 不明点

### <題>
- 内容: <内容>
- 場所: <ファイル名や章>
```

- 1行目の見出しは必須とする。項目は、0件でもよい。項目のキーは、`内容` と `場所` が必要である。

## 5. 既存の設計書の組み立て

PDF ごとに、次を行う。

1. `.work/converted/<PDF の ID>/` のファイルを、番号順につなぐ。失敗した仕事の分は、`> このページ範囲（p.N〜p.M）は変換できなかった。` の1行に置き換える。
2. 行が `# `（レベル1の見出し）で始まる位置で分ける。最初の見出しより前に内容があれば、それも1つの部分にする。
3. 1,000 行を超える部分は、`## ` の位置で分ける。まだ超える部分は、`### ` の位置で分ける。まだ超える部分は、1,000 行ごとに分ける。
4. コードブロック（` ``` ` で囲まれた範囲）の中では分けない。見出しの判定でも、コードブロックの中の行は見出しとして扱わない。
5. 部分を、順に `docs/legacy/<PDF のフォルダ名>/001.md`、`002.md`、…（3桁の通し番号）に書く。
6. `docs/legacy/<PDF のフォルダ名>/index.md` に、`# <PDF の表示用の名前>` と、各部分へのリンクの一覧を書く。リンクの文字は、部分の最初の見出しの文字とする。見出しがない部分は、`（続き）` とする。

`match` の仕事は、`index.md` を除く部分のファイルごとに作る。

## 6. 照合の記録の振り分け

- 合格した `match` の記録の項目を、`モジュール` の値ごとに集める。
- モジュールごとに `.work/match-by-module/<モジュールの ID>.md` に書く。`全体` の項目は `.work/match-by-module/_overall.md` に書く。
- ファイルの形式は 4.1 と同じとする。項目がないモジュールのファイルも作る。

## 7. 要約

`.work/digest.md` に、モジュールごとに次を書く。

- `## <モジュールの題>（<モジュールの ID>）` の見出し。
- モジュールの内部設計書の `## 役割` の内容。
- 機能の要求のファイルにある、要求の行（`- **<ID>**：` で始まる行）。

## 8. 仕上げ

次のファイルを作る。毎回、作り直す。

| ファイル | 内容 |
| --- | --- |
| `docs/review/discrepancies.md` | `# 食い違いの一覧`。合格した `match` の記録の「食い違い」の全項目を、4.1 の順のキーで、項目ごとに `## <題>` と箇条書きで載せる。0件のときは「食い違いは見つからなかった。」と書く。`mode` が `both` のときだけ作る。 |
| `docs/review/unknowns.md` | `# 不明点の一覧`。`.work/unknowns/` の全項目と、失敗した仕事（種類と対象）を載せる。0件のときは「不明点はない。」と書く。`mode` が `pdf` のときは作らない。 |
| `docs/requirements/index.md` | `# 要求仕様書`。章のファイルへのリンクの一覧。`mode` が `pdf` のときは作らない。 |
| `docs/design/index.md` | `# 内部設計書`。全体の内部設計書と、モジュールの内部設計書へのリンクの一覧。`mode` が `pdf` のときは作らない。 |
| `docs/legacy/index.md` | `# 既存の設計書`。PDF ごとの `index.md` へのリンクの一覧。PDF があるときだけ作る。 |
| `docs/index.md` | `# <サイトの名前>`。設計書の構成（上の各 `index.md` へのリンク）、印 `【既存設計書のみ】` の意味、使った入力（ソースコードのフォルダの名前、PDF の名前）、件数（モジュール、食い違い、不明点）。 |
| `mkdocs.yml` | 10章のとおり。 |

サイトの名前は、`<ソースコードのフォルダの名前> 設計書` とする。`mode` が `pdf` のときは、`<最初の PDF の表示用の名前> 設計書` とする。

## 9. `check`

```
python revdoc.py check --out <出力先>
```

出来上がった設計書の構造を検査する。出力は次のとおり。

```json
{"ok": true, "passed": false,
 "problems": [{"file": "docs/design/modules/kernel.md", "rule": "missing_heading", "detail": "## 状態"}]}
```

| `rule` | 不合格の条件 | 対象 |
| --- | --- | --- |
| `missing_file` | 8章と 3.4 で決めたファイルがない（`mode` に応じて判定する。失敗した仕事の出力は除く）。 | 全体 |
| `missing_heading` | 必須の見出しがない。 | 3.4 の表のファイル |
| `too_long` | 1,000 行を超えている。 | `docs/requirements/` と `docs/design/` と `docs/legacy/` の `.md` |
| `broken_link` | Markdown のリンク `[文字](パス)` のうち、`http` で始まらず `#` だけでもない相対パスの先のファイルがない（`#` より後ろは見ない）。 | `docs/` の `.md` |
| `bad_marker` | `【既存` で始まる印のうち、`【既存設計書のみ】` でないものがある。 | `docs/requirements/` と `docs/design/` の `.md` |
| `bad_mermaid` | ` ```mermaid ` のブロックの最初の空でない行が、Mermaid の図の種類（`flowchart`、`graph`、`sequenceDiagram`、`stateDiagram`、`stateDiagram-v2`、`classDiagram`、`erDiagram`、`gantt`、`timeline`、`block-beta`、`mindmap`、`pie`、`journey`、`gitGraph`、`quadrantChart`、`xychart-beta`、`packet-beta`）で始まっていない。または、ブロックが閉じていない。 | `docs/` の `.md` |
| `duplicate_id` | 要求の ID が、`docs/requirements/` の中で重なっている。 | `docs/requirements/` の `.md` |
| `evidence_location` | 本文に `<ファイル名>.<拡張子>:<行番号>` の形（例：`task.c:120`）がある。 | `docs/requirements/` と `docs/design/` の `.md` |

- コードブロックの中は、`broken_link`、`bad_marker`、`evidence_location` の検査をしない。
- `problems` が空のとき、`"passed": true` とする。

## 10. `mkdocs.yml`

次の内容で作る。`nav` は、仕上げのたびに作り直す。

- `site_name`：サイトの名前。`docs_dir: docs`、`site_dir: site`。
- `theme`：`name: material`、`language: ja`、`font: false`。
- `plugins`：`search`（`lang: ja`）と `privacy`。
- `markdown_extensions`：`tables`、`toc`（`permalink: true`）、`pymdownx.superfences`（`mermaid` の独自フェンス）。
- `nav`：入口、要求仕様書（章の順）、内部設計書（全体、モジュールの ID 順）、既存の設計書（PDF ごと、部分の番号順）、確認の一覧（食い違い、不明点）の順。ない部分は載せない。ナビゲーションの文字は、各ファイルの最初の見出しの文字とする。見出しがないファイルは、ファイル名とする。

## 11. `serve` と `stop`

```
python revdoc.py serve --out <出力先> [--port 8000] [--build-only]
python revdoc.py stop --out <出力先>
```

- `serve` は、`mkdocs build` で `site/` を作る。失敗したときは、エラー `build_failed` を返す。
- `--build-only` のときは、`{"ok": true, "site": "<site の絶対パス>"}` を返して終わる。
- それ以外のときは、前に起動したサーバーが動いていれば止める。`--port` から順に空いているポートを探し、`mkdocs serve` を `127.0.0.1` で、スクリプトの終了後も動き続ける形で起動する。
- サーバーが応答するまで、最長 60 秒待つ。応答したら `.work/server.json` に `pid`、`port`、`url` を書き、`{"ok": true, "url": "http://127.0.0.1:<ポート>/", "pid": <数>}` を返す。応答しないときは、エラー `serve_failed` を返す。
- `stop` は、`.work/server.json` のサーバーを止め、`{"ok": true, "stopped": true}` を返す。動いていないときは `"stopped": false` を返す。
- `mkdocs` は、環境変数 `NO_MKDOCS_2_WARNING=1` を付けて呼ぶ。

## 12. `status`

```
python revdoc.py status --out <出力先>
```

```json
{"ok": true, "stage": "write_modules", "mode": "both", "check_passed": null,
 "summary": {"units": 12, "modules": 4, "pdf_pages": 40, "tasks_done": 20, "tasks_failed": 0,
             "tasks_total": 31, "discrepancies": 0, "unknowns": 0, "out": "<出力先の絶対パス>"}}
```

- `discrepancies` と `unknowns` は、仕上げの前は 0 とする。

## 13. `zoom`

```
python revdoc.py zoom --out <出力先> --pdf <PDF の ID> --page <ページ番号> --region <範囲>
```

- `--region` は、`top`、`bottom`、`left`、`right`、または `x0,y0,x1,y1`（ページの幅と高さに対する 0〜1 の割合）。`top` と `bottom` は上下の半分、`left` と `right` は左右の半分とする。
- 指定した範囲を 300 dpi の PNG にして `.work/pages/<PDF の ID>/zoom-p0001-<連番>.png` に書き、`{"ok": true, "file": "<絶対パス>"}` を返す。
- PDF の ID やページ番号が正しくないときは、エラー `bad_argument` を返す。
