# tree-sitter-ruby

Ruby の tree-sitter 文法パーサー。

## プロジェクト構成

| パス | 説明 |
|------|------|
| `grammar.js` | Ruby 文法定義（メインファイル） |
| `src/` | tree-sitter generate で生成されるパーサーコード（手動編集不可） |
| `src/scanner.c` | 外部スキャナー（手動管理、heredoc・リテラル・空白処理・状態シリアライズ） |
| `scripts/` | テストランナー（corpus_test.py）とユニットテスト |
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
pnpm run lint              # lint チェック（Biome）
```

### テスト実行

**`tree-sitter test` は直接実行禁止。** tree-sitter-cli 0.26 系は大規模パーサー（parser.c 15MB）で RSS 8GB+/VSIZE 400GB+ を消費しハングする既知の問題がある。

代わりに以下の方法でテストすること:

```bash
# コーパステスト（推奨）— tree-sitter parse ベース、低メモリ
pnpm run test

# corpus_test.py のユニットテスト
# - 壊れた corpus 入力の抽出（空ファイル、空白のみコード、:error タグ）
# - tree-sitter CLI の setup error / 一般失敗 / PermissionError 伝播
# - expected ERROR / TIMEOUT / 非 .txt スキップの分岐
# - パス/失敗混在時の集計結果、複数ファイルまたぎの集計
# - 区切り線検出・コマンド失敗要約の境界値テスト
# - エッジケース: 空の AST セクション、AST なし連続テスト、空の corpus
# - 追加カバレッジ: 空テスト名、末尾改行なし、MISSING のみ検出、
#   bool/float/空文字列の失敗詳細、ノイズ後の有意行抽出
pnpm run test:unit

# 個別ファイルのパース検証
TREE_SITTER_LIBDIR=/tmp/ts-lib tree-sitter parse example.rb

# pnpm が tree-sitter-cli の install script を止めた場合は
# ローカル CLI バイナリを取得する
node node_modules/tree-sitter-cli/install.js
```

`pnpm run test` は実行前に `tree-sitter --version` を確認し、CLI が見つからない場合や 10 秒以内に起動できない場合は setup error で終了する。関連する setup/failure 分岐は `pnpm run test:unit` で回帰確認できる。

プリコンパイル済み dylib が `/tmp/ts-lib/ruby.dylib` に必要:

```bash
cc -shared -fPIC -O0 -o /tmp/ts-lib/ruby.dylib -I src src/parser.c src/scanner.c
touch -t 209901010000 /tmp/ts-lib/ruby.dylib
```

やむを得ず `tree-sitter test` を実行する場合は、**必ず RSS と VSIZE の両方を監視**し、VSIZE 50GB または RSS 6GB 超過で即座に kill すること。

## 重要なルール

- `src/` 配下は自動生成ファイルのため直接編集しない（ただし `src/scanner.c` は手動管理の外部スキャナー）
- `grammar.js` を変更した場合は必ず `tree-sitter generate` を実行する
- `queries/` の変更はテストで検証する（上記テスト方法を参照）
- `biome.jsonc` で grammar.js のフォーマッタは無効化されている（正規表現の互換性のため）
- `src/scanner.c` のシリアライズを変更した場合は `test/corpus/literals.txt` の長い heredoc 終端語ケースを含めて `pnpm run test` で確認する
- `src/scanner.c` の `deserialize()` はバッファ境界チェックを行うため、新しいフィールドを追加する際は対応する境界チェックも追加すること
- `tree-sitter test` をメモリ監視なしで実行してはならない
