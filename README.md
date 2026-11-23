# reverse

ソースコードと既存の設計書（PDF）から、新しい設計書を作るエージェントプラグインです。Claude Code と GitHub Copilot CLI で使えます。

使い方は、[plugin/README.md](plugin/README.md) を読んでください。

## フォルダ

| フォルダ | 中身 |
| --- | --- |
| `plugin/` | プラグインの本体（スキル、担当エージェント、スクリプト）。 |
| `.claude-plugin/` | マーケットプレイスのマニフェスト。 |
| `docs/` | 要件（`requirements/specification.md`）、設計（`design.md`）、スクリプトの仕様（`script-spec.md`）。 |
| `tests/` | スクリプトの自動テストと、プラグインの読み込みのテスト。 |
| `evals/` | 公開されている OSS を使った評価の道具と、評価の報告（`report.md`）。 |

## 開発

開発の原則は、`.specify/memory/constitution.md` に従います。

テストは、次のコマンドで動かします。前提のパッケージは、[plugin/README.md](plugin/README.md) の「前提」と pytest です。

```
python3 -m pytest -q --ignore=tests/loading
```

`tests/loading` は、Claude Code と GitHub Copilot CLI が入っている PC で動かします。評価の動かし方は、[evals/README.md](evals/README.md) を読んでください。
