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
# - 匿名 `*` / `**` / `&` 転送のような最近の Ruby 構文回帰もここで確認する
# - Ruby 4.0 の `*nil` splat パースもここで確認する
# - Ruby 3.4 の index assignment で keyword / block 引数を拒否する回帰もここで確認する
# - `%=` 文字列、空 heredoc 終端語、不正な regexp option、
#   不正な `..` method/operator 名の scanner 回帰もここで確認する
# - Ruby 4.0 の行頭論理演算子による式・if 条件の行継続もここで確認する
# - scanner.c の行継続判定（行頭 `and` / `or` キーワードと識別子、
#   行頭 `||` / `&&` 演算子、継続しない単独 `&`、行頭 `..`）の回帰もここで確認する
# - scanner.c の `is_iden_char` が ASCII 外の Unicode 識別子文字
#   （例: `:Ĩ` U+0128 や `:漢字`）を char 切り詰めで誤って
#   NON_IDENTIFIER_CHARS に衝突させない symbol パース回帰もここで確認する
# - `tree-sitter parse --no-ranges` の AST 出力を正規化して期待 AST と比較する
# - corpus ソース内の単独 CR 文字を LF に正規化せず検証する
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
# - :error タグ単独動作、コード内区切り線、複数 ERROR/MISSING カウント、
#   パース中 PermissionError 伝播
# - __main__ ガード呼び出し、期待 ERROR だがパース成功、
#   非ゼロ終了でエラーノードなし
# - コード内 --- 区切り、ヘッダー区切りでファイル終端、
#   インデント付き Error: 行、stderr のみのエラー、長い区切り線、
#   複数 error タグテスト、期待 ERROR が MISSING で一致
# - CLI タイムアウト直接テスト、複数空行名前セクション、
#   KeyboardInterrupt 伝播、Emitted 'error' event のみ出力、
#   コード末尾空白トリム、空コードテストのスキップ確認
# - corpus ディレクトリ不在時の setup error、
#   一時ファイル作成失敗時の OSError 伝播（UnboundLocalError 防止）
# - tree-sitter CLI 解決（TREE_SITTER_CLI 上書き、ローカルネイティブバイナリ、
#   ローカル shim、PATH フォールバック）、AST 正規化、単独 CR 保持の検証
# - CORPUS_DIR パッチによる環境非依存テスト、TREE_SITTER_LIBDIR 環境変数の伝播検証、
#   ENOENT 部分一致の分岐テスト、隠しファイル・非 .txt ファイルのスキップ確認
# - 隠し .txt / .txt ディレクトリのスキップと、
#   一時ファイル削除時の OSError が握りつぶされてクラッシュしないことの検証
# - summarize_command_failure の空 output / 全フィルター対象行のみケースが exit code だけを返すこと
# - _resolve_memory_limit_mb の TS_MEMORY_LIMIT_MB 解析（未設定 / 空文字 / 数値以外 /
#   0 以下 / 有効値 / os.environ フォールバック）の境界ケース検証
# - run_with_memory_guard の正常終了、大きな pipe 出力での非デッドロック、
#   子プロセス RSS 超過 kill、タイムアウト強制終了（kill_reason 設定）の検証
pnpm run test:unit

# Rust バインディングテスト
# - 文法ロード、基本 Ruby コードのパース、heredoc・パターンマッチング
# - highlights/locals/tags クエリの妥当性検証、node-types.json の存在確認
# - locals クエリの singleton_method スコープキャプチャ検証
# - locals クエリの for ループ変数・as_pattern 変数束縛の definition キャプチャ検証
# - locals クエリの block/do_block/lambda スコープキャプチャ検証
# - locals クエリの keyword_parameter / optional_parameter の definition キャプチャ検証
# - locals クエリの splat_parameter / hash_splat_parameter / block_parameter の
#   definition キャプチャ検証
# - locals クエリの destructured_parameter の definition キャプチャ検証
# - locals クエリのパターンマッチ束縛・rescue 例外変数の definition キャプチャ検証
# - tags クエリのネスト定義、組み込み擬似メソッド除外、method/alias 定義キャプチャ検証
# - tags クエリの擬似定数（`__FILE__` / `__LINE__` / `__ENCODING__`）reference.call 除外検証
# - highlights クエリのキーワード・演算子・グローバル変数キャプチャ実行検証
# - scanner.c が特殊グローバル変数シンボル（$" $; $, $$ 等）を誤エラーなくパースすることの検証
# - Ruby 4.0 の `*nil` splat パースの corpus 回帰検証
# - heredoc EOF/引用/空終端語境界、深いリテラルネストのシリアライズ、
#   長すぎる heredoc 終端語、symbol setter suffix、regexp option、`%=` 文字列の scanner 回帰検証
# - scanner.c のバックスラッシュ行継続が CRLF 改行（`\\\r\n`）でも動作することの検証
# - scanner.c の改行判定で行頭 `&.`（safe navigation）が改行継続として扱われることの検証
# - scanner.c の `is_iden_char` が ASCII 外 Unicode 識別子文字を char 切り詰めで
#   NON_IDENTIFIER_CHARS と誤一致させない symbol パース回帰の検証
cargo test

# 個別ファイルのパース検証
TREE_SITTER_LIBDIR=/tmp/ts-lib tree-sitter parse example.rb

# pnpm が tree-sitter-cli の install script を止めた場合は
# ローカル CLI バイナリを取得する
node node_modules/tree-sitter-cli/install.js
```

`pnpm run test` は実行前に `tree-sitter --version` を確認し、CLI が見つからない場合や 10 秒以内に起動できない場合は setup error で終了する。関連する setup/failure 分岐は `pnpm run test:unit` で回帰確認できる。
`scripts/corpus_test.py` を直接実行する場合、CLI は `TREE_SITTER_CLI`、`node_modules/tree-sitter-cli/tree-sitter`、`node_modules/.bin/tree-sitter`、PATH 上の `tree-sitter` の順に解決する。

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
- tree-sitter の scanner serialization buffer に収まらない heredoc 終端語は、状態喪失による誤パースを避けるため ERROR として扱う
- `src/scanner.c` の `deserialize()` はバッファ境界チェックを行うため、新しいフィールドを追加する際は対応する境界チェックも追加すること
- `tree-sitter test` をメモリ監視なしで実行してはならない
- `scripts/` 配下の Python コードは Python 3.7 互換を維持するため、`ruff.toml` で `target-version = "py37"` を指定している。parenthesized context manager などの新しい構文を自動書き換えされないよう、新規コードでも Python 3.7 互換を崩さないこと
