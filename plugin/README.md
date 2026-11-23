# reverse

ソースコードと既存の設計書（PDF）から、新しい設計書を作るプラグインです。Claude Code と GitHub Copilot CLI で使えます。

- 要求仕様書（ISO/IEC/IEEE 29148:2018 の SRS の構成で書く）と、モジュールごとと全体の内部設計書を、日本語で作ります。図は Mermaid で書きます。
- ソースコードと既存の設計書が食い違う点を、食い違いの一覧にします。分からなかった点と、処理に失敗した部分を、不明点の一覧にします。
- 既存の設計書にしか書かれていない内容は、`【既存設計書のみ】` の印を付けて、新しい設計書に入れます。
- できた設計書を静的サイトにして、その PC で表示します。
- ソースコードだけ、PDF だけでも使えます。

## 始め方

1. 前提のもの（下の「前提」）をインストールします。
2. プラグインをインストールします（下の「インストール」）。
3. ソースコード、PDF、出力先を含むフォルダで、ツールを起動し、スキルを呼びます。

```
/reverse:make-design-docs ソースコードは src、既存の設計書は spec.pdf、出力先は design-docs
```

終わると、サイトの URL と、設計書と2つの一覧の場所が表示されます。

## 前提

- Python 3.9 以上と、次のパッケージ。

  ```
  python3 -m pip install "pypdfium2>=5" Pillow mkdocs-material
  ```

  Windows では `py -3 -m pip install …` です。Linux で pip がインストールを断るときは、仮想環境を作って有効にしてから、ツールを起動します。
- GitHub Copilot CLI では、画像を読めるモデルを選びます。PDF のページを画像で読むためです。
- サイトを作る PC が unpkg.com につながること。つながらないときは、図が Mermaid のテキストのまま表示されることがあります。

## インストール

Claude Code：

```
claude plugin marketplace add xclang-brain/reverse
claude plugin install reverse@reverse
```

GitHub Copilot CLI：

```
copilot plugin marketplace add xclang-brain/reverse
copilot plugin install reverse@reverse
```

## 使い方の注意

- ソースコードのフォルダには、ビルドの出力のフォルダを含まないフォルダを指示します。
- スキルが動いている間、Python のコマンドとファイルの読み書きは、場所を問わず確認なしで通ります。
- 止まったら、同じ頼みでスキルをもう一度呼びます。続きから進みます。作業が終わるまで、ソースコードと PDF を変えないでください。
- `'` を含むパスは使えません。Windows では、出力先を短いパスにします。
- サーバー：サンドボックスを有効にした Linux の Copilot CLI では、ブラウザーからつながらない見込みです。Windows では、ツールを終えるとサーバーも止まることがあります。

## 確かめる範囲

- Claude Code（Linux）では、スキルを最後まで動かして確かめます。
- GitHub Copilot CLI では、プラグインの読み込みと、担当エージェントの呼び出しまでを確かめます。スキルを最後まで動かすことは、確かめていません。
- Windows では、スクリプトの自動テストを GitHub Actions で動かして確かめます。Windows の PC でスキルを最後まで動かすことは、確かめていません。
- 要求仕様書は、29148:2018 の SRS の構成（1 はじめに、2 参考文献、3 要求、4 検証、5 付録）で書きます。構成は、規格を引用した資料で確かめたもので、規格の本文とは照らしていません。
