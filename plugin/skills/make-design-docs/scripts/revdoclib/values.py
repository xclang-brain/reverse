"""スクリプトの仕様に書いた値（行数、大きさ、回数、割合、名前の一覧）。値は、ここだけに置く。"""

# 2.1 対象のソースファイル
VCS_DIRS = (".git", ".svn", ".hg")
EXCLUDED_EXTENSIONS = ("md", "markdown", "txt", "rst", "adoc", "html", "htm", "csv", "tsv", "log", "svg",
                       "map", "lst", "dep", "su", "hex", "srec", "s19", "mot", "pdf")
BINARY_PROBE_BYTES = 8192
MAX_FILE_BYTES = 2097152
MAX_LINE_BYTES = 102400

# 2.2 文字コード（この順に試す。どれでも読めないときは最後のもの）
ENCODINGS = ("utf-8", "euc_jp", "cp932")
FALLBACK_ENCODING = "latin-1"

# 2.3 ユニット
UNIT_MAX_LINES = 2000
UNIT_MAX_BYTES = 102400

# 2.4 モジュール
RESERVED_NAME_HEADS = ("analysis", "report", "summary", "findings")
UNITS_PER_PART = 5

# 2.5、2.6 PDF
CONVERT_PAGES = 10
UNMAPPED_RATIO = 0.05
POSITION_SCALE = 10000
EDGE = 1000
MARGIN_BAND = 100
MARGIN_MIN_PAGES = 4

# 1.3 path_too_long
WINDOWS_MAX_PATH = 247

# 1.4 ファイルの置き換えのやり直し
FS_RETRIES = 10
FS_RETRY_WAIT = 0.1

# 6.5 全体の執筆のファイル（docs/ からのパス、要求の接頭辞）。
# 1行目と必須の見出しは、templates/docs/ の同じ名前のひな形に書いてある。
OVERALL_FILES = (
    ("design/architecture.md", None),
    ("requirements/1-introduction.md", None),
    ("requirements/2-references.md", None),
    ("requirements/3-2-performance.md", "PR-"),
    ("requirements/3-3-usability.md", "UR-"),
    ("requirements/3-4-interfaces.md", "IR-"),
    ("requirements/3-5-database.md", "DR-"),
    ("requirements/3-6-design-constraints.md", "DC-"),
    ("requirements/3-7-attributes.md", "SA-"),
    ("requirements/3-8-supporting.md", None),
    ("requirements/4-verification.md", None),
    ("requirements/5-appendices.md", None),
)

# 4.1〜4.5 next、段階、回数
MAX_JOBS = 4
MAX_TRIES = 3
MAX_ROUNDS = 3
STAGES = ("analyze", "convert", "match", "write_module", "verify_module", "write_overall", "verify_overall",
          "done")
STAGE_MODES = {
    "analyze": ("both", "source"),
    "convert": ("both", "pdf"),
    "match": ("both",),
    "write_module": ("both", "source"),
    "verify_module": ("both", "source"),
    "write_overall": ("both", "source"),
    "verify_overall": ("both", "source"),
    "done": ("both", "source", "pdf"),
}
AGENTS = {
    "analyze": "reverse:code-analyst",
    "convert": "reverse:pdf-converter",
    "match": "reverse:doc-matcher",
    "write_module": "reverse:doc-writer",
    "write_overall": "reverse:doc-writer",
    "verify": "reverse:doc-verifier",
}

# 2.8 決まった1文
NONE_SENTENCES = {
    "both": "ソースコードと既存の設計書から読み取れる内容はない。",
    "source": "ソースコードから読み取れる内容はない。",
    "pdf": None,
}

# 5.3 根拠の場所（6.6 の判定には、3個まで書ける）
MAX_LOCATION_LINES = 150
MAX_VERDICT_LOCATIONS = 3

# 5.4 Mermaid の検査
MERMAID_HEADERS = ("stateDiagram-v2", "sequenceDiagram", "flowchart TB", "flowchart TD", "flowchart BT",
                   "flowchart LR", "flowchart RL")
FLOWCHART_RESERVED = ("end", "class", "graph", "style", "subgraph")
FLOWCHART_UNCHECKED = ("style", "classDef", "linkStyle", "click")
SEQUENCE_UNCHECKED = ("loop", "alt", "else", "opt", "par", "and", "critical", "option", "break", "rect", "box",
                      "title")

# 5.5 行の検査
SPECULATIONS = ("と思われる", "と考えられる", "おそらく", "かもしれない", "はずである", "と推測")
MARKS = ("【既存設計書のみ】", "【判読できない】")
LEGACY_HEADING = "## 既存の設計書にだけ書かれている内容"

# 5.6 番号を振った行の上限（照合も検証も）
NUMBERED_LINES = 50

# 6.1 解析メモ
MEMO_HEADINGS = ("役割", "公開インターフェース", "データ構造", "処理の流れ", "設定値と定数", "外部とのやり取り",
                 "ユニットの外で定義されている名前", "分からなかったこと")
MEMO_MAX_LINES = 200
COVER_BLOCK = 200

# 6.2 変換
PAGE_DPI = 150
FIGURE_DPI = 200
FIGURE_PAD = 0.04
# 検査する文字（NFKC で正規化した後の文字。正規表現の [] の中身）
CHECK_CHARS = "0-9A-Za-z\u3041-\u3096\u30a1-\u30fa\u30fc\u3005\u3400-\u4dbf\u4e00-\u9fff"
REASON_STRINGS = 10
REASON_STRING_CHARS = 40

# 6.4 モジュールの執筆
MODULE_HEADINGS = ("役割", "公開インターフェース", "データ構造", "処理の流れ", "状態", "依存関係", "エラー処理",
                   "並行性とタイミング", "設定値と定数", "外部とのやり取り")
FUNCTIONS_HEADING = "## 機能の要求"
REQUIREMENT_HEADS = ("FR-", "PR-", "UR-", "IR-", "DR-", "DC-", "SA-")

# 7章 指示のファイル
MAX_JOB_BYTES = 20480
MAX_REASONS = 50
JOB_TEMPLATES = {
    "analyze": "job-analyze.md",
    "convert": "job-convert.md",
    "match": "job-match.md",
    "write_module": "job-write-module.md",
    "write_overall": "job-write-overall.md",
    "verify": "job-verify.md",
}

# 1ファイルの行の上限（6.4 の設計書、8.1 の既存の設計書、8.4 の差し込み、8.7 の一覧）
MAX_DOC_LINES = 1000

# 8.1 既存の設計書の組み立て
LEGACY_PART_LINES = 998
MAX_HEADING_LEVEL = 6
MARKER_LEVEL = 7

# 8.4「既存設計書のみ」の記録の差し込み
MARK_BEFORE = {"table": "【既存設計書のみ】次の表は、既存の設計書の内容である。",
               "figure": "【既存設計書のみ】次の図は、既存の設計書の内容である。"}

# 8.6 要約
DIGEST_DEPS = 10
DIGEST_LINES = 2000

# 8.7 仕上げ
COMMENT_MISMATCH = "コメントと実装の食い違い："
STAGE_LABELS = {"analyze": "解析", "convert": "変換", "match": "照合", "write_module": "執筆（モジュール）",
                "write_overall": "執筆（全体）", "verify": "検証"}
# 2.1 の表の順
EXCLUDED_LABELS = {"symlink": "シンボリックリンク", "extension": "文書、データ、ビルドの出力の拡張子", "empty": "空のファイル",
                   "utf16": "UTF-16", "binary": "バイナリー", "too_large": "2MB を超える",
                   "long_line": "1行が 100KB を超える"}
UNREADABLE_REASONS = {"utf16": "UTF-16 のため、読んでいない。", "too_large": "2MB を超えるため、読んでいない。",
                      "long_line": "1行が 100KB を超えるため、読んでいない。",
                      FALLBACK_ENCODING: "文字コードが分からない。ASCII のほかの文字は読めていない。"}

# 9章 check
MAX_PROBLEMS = 100

# 10章 mkdocs.yml
NAV_LABEL_CHARS = 40

# 11章 serve と stop
SERVE_FRESH = 15
SERVE_WAIT = 20
SERVE_POLL = 0.5
SERVE_BEAT = 5
SERVE_PORTS = range(8000, 8100)
SERVE_LOG_LINES = 20
STOP_WAIT = 5
STOP_POLL = 0.1
HTTP_TIMEOUT = 3
