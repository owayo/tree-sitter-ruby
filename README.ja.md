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

> **警告:** `tree-sitter test` は、このパーサーでは過剰なメモリを消費します（RSS 8GB+、VSIZE 400GB+）。パーサーテーブルが大きいため（parser.c 約15MB、STATE_COUNT 6013）、`test` サブコマンドが内部でパースツリー全体を S 式文字列に変換し差分比較を行うことで、大量のメモリ確保が発生します。`tree-sitter parse` は影響を受けません（約10MB RSS）。これは特定の upstream issue としては追跡されていませんが、関連するメモリ問題が [tree-sitter#1890](https://github.com/tree-sitter/tree-sitter/issues/1890)、[tree-sitter#1185](https://github.com/tree-sitter/tree-sitter/issues/1185)、[zed#47880](https://github.com/zed-industries/zed/issues/47880) で報告されています。代わりに以下のテストランナーを使用してください。

```bash
# 推奨: tree-sitter parse によるコーパステスト（低メモリ）
# - 匿名 `*` / `**` / `&` 転送のような最近の Ruby 構文回帰もここで確認する
# - Ruby 4.0 の `*nil` splat パースもここで確認する
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

# scripts/corpus_test.py のユニットテスト
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
# - 隠し .txt / .txt ディレクトリのスキップと、
#   一時ファイル削除時の OSError が握りつぶされてクラッシュしないことの検証
# - summarize_command_failure の空 output / 全フィルター行のみの場合に exit code のみ返すことの検証
# - _resolve_memory_limit_mb の TS_MEMORY_LIMIT_MB 解析（未設定 / 空文字 / 数値以外 /
#   0 以下 / 有効値 / os.environ フォールバック）の境界ケース検証
# - run_with_memory_guard の正常終了、大きな pipe 出力での非デッドロック、
#   子プロセス RSS 超過 kill、タイムアウト強制終了（kill_reason 設定）の検証
pnpm run test:unit

# パーサーライブラリの事前コンパイル（parse ベーステストに必要）
mkdir -p /tmp/ts-lib
cc -shared -fPIC -O0 -o /tmp/ts-lib/ruby.dylib -I src src/parser.c src/scanner.c

# Rust バインディングテスト（文法ロード、パース、クエリ検証、
# locals クエリの singleton_method/for/as_pattern/block/do_block/lambda キャプチャ検証、
# locals クエリの keyword/optional/splat/hash_splat/block/destructured
# パラメータ、パターンマッチ束縛、rescue 例外変数の definition キャプチャ検証、
# highlights クエリのキーワード・演算子・グローバル変数キャプチャ検証、
# tags クエリのネスト定義・method/alias 定義・組み込み擬似メソッド除外の回帰検証、
# tags クエリの擬似定数（__FILE__/__LINE__/__ENCODING__）の reference.call 除外検証、
# scanner.c の特殊グローバル変数シンボル（:$" :$; :$$ 等）のパース回帰検証、
# Ruby 4.0 の `*nil` splat パースの corpus 回帰検証、
# heredoc EOF/引用/空終端語境界、深いリテラルネストのシリアライズ、
# 長すぎる heredoc 終端語、symbol setter suffix、regexp option、`%=` 文字列の scanner 回帰検証、
# scanner.c のバックスラッシュ行継続が CRLF 改行（\\\r\n）でも動作する回帰検証、
# 行頭 `&.` （safe navigation）が改行継続として扱われる scanner.c 改行判定の回帰検証、
# scanner.c の `is_iden_char` が ASCII 外 Unicode 識別子文字を char 切り詰めで
# NON_IDENTIFIER_CHARS と誤一致させない symbol パース回帰検証）
cargo test

# pnpm が tree-sitter-cli の install script を止めた場合は
# ローカル CLI バイナリを取得する
node node_modules/tree-sitter-cli/install.js
```

`pnpm run test` はコーパス実行前に `tree-sitter --version` を確認し、CLI が見つからない場合や 10 秒以内に起動できない場合は setup error で終了します。関連する setup/failure 分岐は `pnpm run test:unit` で回帰確認できます。

`scripts/corpus_test.py` を直接実行する場合、CLI は
`TREE_SITTER_CLI`、`node_modules/tree-sitter-cli/tree-sitter`、`node_modules/.bin/tree-sitter`、
PATH 上の `tree-sitter` の順に解決します。依存関係をインストール済みの環境では、
`python3 scripts/corpus_test.py` の直接実行でもプロジェクトで固定した CLI を使います。

### スキャナー

外部スキャナー（`src/scanner.c`）は、`grammar.js` だけでは表現できない文脈依存トークンを処理します: heredoc、区切りリテラル（文字列、正規表現、サブシェル、シンボル/文字列配列）、改行、空白依存の演算子、およびそれらを正しく再開するためのスキャナー状態シリアライズです。`src/` 配下の他のファイルとは異なり、手動管理のため新しいトークン型を追加する際は直接編集してください。

255 文字を超える heredoc 終端語は `test/corpus/literals.txt` の回帰ケースで検証しています。tree-sitter の scanner serialization buffer に収まらない終端語は、状態喪失による誤パースを避けるため ERROR にします。スキャナーのシリアライズを変更した場合は `pnpm run test` で必ず確認してください。`deserialize()` 関数にはバッファ境界チェックが含まれており、切り詰められた・破損したバッファを安全に処理します。

## 参考資料

- [Whitequark パーサーの AST フォーマット](https://github.com/whitequark/parser/blob/master/doc/AST_FORMAT.md)

[ci]: https://img.shields.io/github/actions/workflow/status/owayo/tree-sitter-ruby/ci.yml?logo=github&label=CI
