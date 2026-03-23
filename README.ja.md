# tree-sitter-ruby

[![CI][ci]](https://github.com/owayo/tree-sitter-ruby/actions/workflows/ci.yml)

[tree-sitter](https://github.com/tree-sitter/tree-sitter) 用の Ruby 文法パーサー。Ruby 3/4 構文に対応。

## 使い方 (Rust)

`Cargo.toml` に追加:

```toml
[dependencies]
tree-sitter = "0.26"
tree-sitter-ruby = { git = "https://github.com/owayo/tree-sitter-ruby.git" }
```

```rust
use tree_sitter::Parser;
use tree_sitter_ruby::LANGUAGE;

let mut parser = Parser::new();
parser.set_language(&LANGUAGE.into()).unwrap();

let tree = parser.parse("puts 'hello'", None).unwrap();
println!("{}", tree.root_node().to_sexp());
```

## クエリ

`queries/` ディレクトリに以下のクエリファイルが含まれています:

| ファイル | 説明 |
|----------|------|
| `highlights.scm` | シンタックスハイライト（キーワード、リテラル、演算子等） |
| `tags.scm` | コードナビゲーション用タグ（メソッド、クラス、モジュール、定数の定義・参照） |
| `locals.scm` | ローカル変数のスコープ |

## 前提条件

```bash
cargo install tree-sitter-cli
```

## 開発

```bash
# 依存関係のインストール
pnpm install --ignore-scripts

# grammar.js からパーサーを生成
tree-sitter generate

# grammar.js を lint
pnpm run lint

# ファイルをパース
tree-sitter parse example.rb
```

### テスト

> **警告:** `tree-sitter test` は、このパーサーでは過剰なメモリを消費します（RSS 8GB+、VSIZE 400GB+）。パーサーテーブルが大きいため（parser.c 約15MB、STATE_COUNT 5989）、`test` サブコマンドが内部でパースツリー全体を S 式文字列に変換し差分比較を行うことで、大量のメモリ確保が発生します。`tree-sitter parse` は影響を受けません（約10MB RSS）。これは特定の upstream issue としては追跡されていませんが、関連するメモリ問題が [tree-sitter#1890](https://github.com/tree-sitter/tree-sitter/issues/1890)、[tree-sitter#1185](https://github.com/tree-sitter/tree-sitter/issues/1185)、[zed#47880](https://github.com/zed-industries/zed/issues/47880) で報告されています。代わりに以下のテストランナーを使用してください。

```bash
# 推奨: tree-sitter parse によるコーパステスト（低メモリ）
pnpm run test

# scripts/corpus_test.py のユニットテスト
pnpm run test:unit

# パーサーライブラリの事前コンパイル（parse ベーステストに必要）
mkdir -p /tmp/ts-lib
cc -shared -fPIC -O0 -o /tmp/ts-lib/ruby.dylib -I src src/parser.c src/scanner.c

# pnpm が tree-sitter-cli の install script を止めた場合は
# ローカル CLI バイナリを取得する
node node_modules/tree-sitter-cli/install.js
```

`pnpm run test` はコーパス実行前に `tree-sitter --version` を確認し、CLI が見つからない場合や 10 秒以内に起動できない場合は setup error で終了します。

### スキャナー

外部スキャナー（`src/scanner.c`）は、`grammar.js` だけでは表現できない文脈依存トークンを処理します: heredoc、区切りリテラル（文字列、正規表現、サブシェル、シンボル/文字列配列）、改行、空白依存の演算子、およびそれらを正しく再開するためのスキャナー状態シリアライズです。`src/` 配下の他のファイルとは異なり、手動管理のため新しいトークン型を追加する際は直接編集してください。

255 文字を超える heredoc 終端語は `test/corpus/literals.txt` の回帰ケースで検証しているため、スキャナーのシリアライズを変更した場合は `pnpm run test` で必ず確認してください。

## 参考資料

- [Whitequark パーサーの AST フォーマット](https://github.com/whitequark/parser/blob/master/doc/AST_FORMAT.md)

[ci]: https://img.shields.io/github/actions/workflow/status/owayo/tree-sitter-ruby/ci.yml?logo=github&label=CI
