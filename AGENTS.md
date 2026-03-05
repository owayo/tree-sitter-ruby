# tree-sitter-ruby

Ruby の tree-sitter 文法パーサー。

## プロジェクト構成

| パス | 説明 |
|------|------|
| `grammar.js` | Ruby 文法定義（メインファイル） |
| `src/` | tree-sitter generate で生成されるパーサーコード（手動編集不可） |
| `queries/highlights.scm` | シンタックスハイライトクエリ |
| `queries/tags.scm` | コードナビゲーション用タグクエリ（定義・参照） |
| `queries/locals.scm` | ローカル変数スコープクエリ |
| `bindings/` | Rust/Node.js バインディング |
| `test/corpus/` | パーサーのコーパステスト |
| `test/highlight/` | ハイライトクエリのテスト |
| `test/tags/` | タグクエリのテスト |

## 開発コマンド

```bash
pnpm install --ignore-scripts  # 依存関係インストール
tree-sitter generate       # grammar.js からパーサー生成
@biomejs/biome check grammar.js  # lint チェック
```

### テスト実行

**`tree-sitter test` は直接実行禁止。** tree-sitter-cli v0.26.6 は大規模パーサー（parser.c 15MB）で RSS 8GB+/VSIZE 400GB+ を消費しハングする既知の問題がある。

代わりに以下の方法でテストすること:

```bash
# コーパステスト（推奨）— tree-sitter parse ベース、低メモリ
python3 scripts/corpus_test.py

# 個別ファイルのパース検証
TREE_SITTER_LIBDIR=/tmp/ts-lib tree-sitter parse example.rb
```

プリコンパイル済み dylib が `/tmp/ts-lib/ruby.dylib` に必要:

```bash
cc -shared -fPIC -O0 -o /tmp/ts-lib/ruby.dylib -I src src/parser.c src/scanner.c
touch -t 209901010000 /tmp/ts-lib/ruby.dylib
```

やむを得ず `tree-sitter test` を実行する場合は、**必ず RSS と VSIZE の両方を監視**し、VSIZE 50GB または RSS 6GB 超過で即座に kill すること。

## 重要なルール

- `src/` 配下は自動生成ファイルのため直接編集しない
- `grammar.js` を変更した場合は必ず `tree-sitter generate` を実行する
- `queries/` の変更はテストで検証する（上記テスト方法を参照）
- `biome.jsonc` で grammar.js のフォーマッタは無効化されている（正規表現の互換性のため）
- `tree-sitter test` をメモリ監視なしで実行してはならない
