# テストの共通の道具

スクリプトの自動テスト（要件の文書の 5.2、A）で使う道具である。本体は `helpers.py`、fixture は `conftest.py` にある。テストからは `import helpers` で使う。根拠は [スクリプトの仕様](../docs/script-spec.md) である。

## 決まり

- revdoclib は、テストの関数か fixture の中で読み込む（`helpers` の関数は、呼んだときに読み込む）。実装がなくても、`pytest --collect-only` が通る。
- 入力は `tmp_path` の下に作る。出力先も `tmp_path` の下にする。
- どのテストでも、スクリプトのモジュールが文字コードを指定せずにファイルを読み書きすると、テストが失敗する（下の「文字コードの見張り」）。

## スクリプトを呼ぶ

| 関数 | 使い方 |
| --- | --- |
| `run_main(argv, cwd=None)` | 同じプロセスで `revdoclib.main(argv)` を呼び、`Result` を返す。`argv` はサブコマンドから後ろ（例：`["next", "--out", out]`）。 |
| `run_cli(argv, cwd=None, env=None)` | `python revdoc.py <argv>` をコマンドとして動かし、`Result` を返す。`env` は足す環境変数。 |
| `revdoc(sub, out, src=None, pdf=None, extra=(), cli=False, cwd=None)` | 上の2つを短く書く形。`--out`、`--src`、`--pdf` を付けて呼ぶ。`cli=True` でコマンドとして動かす。 |
| `Result` | `code`（終了コード）、`data`（標準出力の JSON）、`ok`（`data["ok"]` が真か）、`stdout`、`stderr`。 |
| `parse_stdout(text, code)` | 上の関数が中で使う。標準出力が 1.2 の形（ASCII の JSON 1つを1行、`json.dumps` の作り方）で、`ok` と終了コードが合うことを確かめる。合わないときは AssertionError。 |
| `import_revdoclib()` | revdoclib を読み込んで返す（バイトコードを書かない）。fixture `revdoclib` も同じものを返す。差し替え（`monkeypatch.setattr(revdoclib.packages, "missing", …)`）に使う。 |
| `mkdocs_build(out)` | 11.1 と同じ決まり（カレントフォルダは出力先、`NO_MKDOCS_2_WARNING=1`）で `mkdocs build` を動かし、`subprocess.CompletedProcess` を返す。 |

定数：`REPO`、`SCRIPTS_DIR`（`plugin/skills/make-design-docs/scripts`）、`REVDOC_PY`、`A4`（ポイントの幅と高さ）。

## 入力を作る

| 関数 | 使い方 |
| --- | --- |
| `make_source_tree(root, layout=None)` | 合成のソースツリーを作り、`root` を返す。`layout` は `{相対パス: 中身}`。中身が int ならその行数ちょうどの C か C++ のコード、str なら UTF-8、bytes ならそのまま書く（Shift_JIS、バイナリーなど）。省くと `DEFAULT_LAYOUT`（`main.c`、`kernel/task.c`、`kernel/task.h`、`lib/timer.cpp`、`lib/timer.hpp`）。 |
| `source_text(rel, n)` | `rel` の拡張子に合う n 行のコードを返す。`.cpp` は `namespace timer_ns` の中に `int Timer::method_0001(int x)` の形、`.hpp` は `class Timer`、`.c` は `int task_func_0001(int x)` の形、`.h` は `#define TASK_MAX 16` とプロトタイプ。 |
| `scaled_layout(total_lines, lines_per_file=1000, files_per_folder=20)` | 合計 `total_lines` 行の `layout` を返す（A-2 の 100 万行など）。100 万行のツリーは1秒ほどで作れる。 |
| `make_text_pdf(path, pages=3, size=A4)` | 埋め込みテキストつきの PDF を作る。`pages` がページの数なら、どのページにも上端の `SPEC-DOC-0001`、本文の2行、右下のページ番号を置く。`[(x, y, 文字列[, 大きさ]), …]` のページのリストで、置く所を決められる（左上からのポイント。y は文字の下端。文字列は ASCII）。2,000 ページで1秒ほど。 |
| `make_image_pdf(path, pages=2, size=A4)` | 画像だけの PDF（文字の数が 0）を Pillow で作る。各ページに箱と線の図がある。 |
| `make_unmapped_pdf(path, pages=1, text="ABCDEF", mapped="")` | 文字を Unicode に対応づけられない PDF を作る。`text` の全部の文字で `FPDFText_HasUnicodeMapError` が 1 になる（SR-37、A-9）。`text` は英大文字だけ。`mapped` は、対応づけられる文字（Helvetica）として足す ASCII の文字列で、対応づけられない文字の割合を決めるのに使う。 |

## 担当エージェントの代わり

`fake_agent(out, bad=(), skip=(), verdict=None)`：`.work/state.json` の `issued` の仕事を読み、`outputs` に6章の形式の出力を書く。書いた仕事のリストを返す。

- 何も指定しないと、検査（5章、6章）に合格する出力を書く。根拠の場所と語は、ソースファイルにある行と語から作る。名前は `Timer::method_0001` の形（A-3）も書く。
- 照合の記録は、Mermaid のブロックを「一致」、画像以外の最初の行を「食い違い」、残りを「既存設計書のみ」にする（最初の記録はモジュール、ほかは `全体`）。
- 変換では、文字列の検査がないページ（画像だけのページ）に、表、画像の図（`figure:`）、Mermaid の図も書く。
- `bad`：仕事の ID（`"J00001"`）か種類（`"analyze"` など）の集まり。当たる仕事には、行数のほかの検査に反する出力を書く。反する検査は、`analyze` が `bad_location`、`convert` が `double_underscore`、`match` が `bad_record`、`write_module` と `write_overall` が `missing_heading` か `empty_section`、`verify` が `bad_verdict`。
- `skip`：当たる仕事には、何も書かない（出力がない仕事）。
- `verdict`：検証の判定を選ぶ関数。`.work/verify/<ID>.json` の `lines` の項目に `"file"` を足した辞書を受け取り、`"OK"`、`"NG"`、`"不明"`、`"対象外"`、`None`（既定）を返す。既定は、コードスパンかコードブロックがある行が OK、ない行が対象外、根拠が見つからない行が不明。NG の直した文は、形を変えずに `（直した）` を足した文になる（`【既存設計書のみ】` の印は除く）。
- 設計書の行を直接書き換える場面（A-8）は、テストの中でファイルを書き換えて作る。
- 書く先の親フォルダは作らない（SR-09 は `next` が作る）。

## init から done まで進める

`run_to_done(out, src=None, pdf=None, stop_at=None, steps=None, cli=False, cwd=None, **agent)`：`init` を呼び、`next` と `fake_agent` を `state` が `done` になるまで繰り返して、最後の `Result` を返す。

- 状態があれば `init` が続きから進めるので、もう一度呼ぶと再開になる。
- エラー（`ok` が偽）の結果が出たら、そこで返す。
- `stop_at`：段階の名前（4.2 の `stage`。例：`"match"`）。`next` の後にその段階になったら、代わりの関数を呼ばずに返す。
- `steps`：`next` をその回数だけ呼んだら返す。
- `agent`：`fake_agent` に渡す `bad`、`skip`、`verdict`。

## 出力先を読む

| 関数 | 使い方 |
| --- | --- |
| `read_state(out)`、`read_plan(out)` | `.work/state.json`、`.work/plan.json` を読む。 |
| `jobs_with(out, status=None, kind=None)` | 状態の仕事のうち、`status` と `kind` に合うものを ID の順に返す。 |
| `read_json(path)`、`read_text(path)` | UTF-8 の JSON とテキストを読む（`read_text` は BOM と `\r` を外す）。 |
| `tree_hashes(root)` | `root` の下の全部のファイルの `{相対パス: SHA-1}` を返す。実行の前後で比べる（A-3、A-11）。 |
| `code_spans(line)` | 5.1 のコードスパンのリストを返す。 |

定数：`MEMO_HEADINGS`（6.1）、`MODULE_HEADINGS`（6.4）、`OVERALL_FILES`（6.5 の表。パス、1行目、必須の見出し、接頭辞）。

## 文字コードの見張り（A-10）

- `conftest.py` の autouse の fixture が、どのテストでも `EncodingGuard` を有効にする。スクリプトのフォルダのモジュールが、文字コードを指定せずにテキストのファイルを開くと、テストの終わりに失敗にする。ほかのパッケージ（pypdfium2 など）の呼び出しは数えない。
- `run_cli` では、`PYTHONWARNDEFAULTENCODING=1` を付け（効くのは Python 3.10 以上）、標準エラーの、スクリプトのファイルの `EncodingWarning` を同じく数える。
- 見張りそのものを確かめるときは、`with helpers.EncodingGuard(roots=[tmp_path]) as g:` の中で、`tmp_path` に置いたモジュールを呼び、`g.found`（`ファイル:行` のリスト）を見る。
