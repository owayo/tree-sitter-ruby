# tree-sitter-ruby

[![CI][ci]](https://github.com/owayo/tree-sitter-ruby/actions/workflows/ci.yml)

[tree-sitter](https://github.com/tree-sitter/tree-sitter) 用の Ruby 文法パーサー。Ruby 3/4 構文に対応。

## 使い方 (Rust)

`Cargo.toml` に追加:

```toml
[dependencies]
tree-sitter = "0.27"
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
# 依存関係のインストール（tree-sitter CLI バイナリの取得まで実行）
pnpm install

# grammar.js からパーサーを生成
tree-sitter generate

# grammar.js を lint
pnpm run lint

# ファイルをパース
tree-sitter parse example.rb
```

### テスト

> **警告:** `tree-sitter test` は、このパーサーでは過剰なメモリを消費します（RSS 8GB+、VSIZE 400GB+）。パーサーテーブルが大きいため（現在 parser.c 約21MB、STATE_COUNT 8235）、`test` サブコマンドが内部でパースツリー全体を S 式文字列に変換し差分比較を行うことで、大量のメモリ確保が発生します。`tree-sitter parse` は影響を受けません（約10MB RSS）。これは特定の upstream issue としては追跡されていませんが、関連するメモリ問題が [tree-sitter#1890](https://github.com/tree-sitter/tree-sitter/issues/1890)、[tree-sitter#1185](https://github.com/tree-sitter/tree-sitter/issues/1185)、[zed#47880](https://github.com/zed-industries/zed/issues/47880) で報告されています。代わりに以下のテストランナーを使用してください。

```bash
# 推奨: tree-sitter parse によるコーパステスト（低メモリ）
# - 匿名 `*` / `**` / `&` 転送のような最近の Ruby 構文回帰もここで確認する
# - Ruby 4.0 の `*nil` splat パースもここで確認する
# - Ruby 3.4 の index assignment で keyword / block 引数を拒否する回帰もここで確認する
# - `%=` 文字列、空 heredoc 終端語、不正な regexp option、
#   不正な `..` method/operator 名の scanner 回帰もここで確認する
# - Ruby 4.0 の行頭論理演算子による式・if 条件の行継続もここで確認する
#   （if 条件内の `and` / `or` キーワード演算子を含む）
# - scanner.c の行継続判定（行頭 `and` / `or` キーワードと識別子、
#   行頭 `||` / `&&` 演算子、継続しない単独 `&`、行頭 `..`）の回帰もここで確認する
# - scanner.c の `is_iden_char` が ASCII 外の Unicode 識別子文字
#   （例: `:Ĩ` U+0128 や `:漢字`）を char 切り詰めで誤って
#   NON_IDENTIFIER_CHARS に衝突させない symbol パース回帰もここで確認する
# - tree-sitter-cli 0.26.11 が生成時に汎用文字集合から除外していた
#   `ſ`（U+017F）と `K`（U+212A）を含む正当な Ruby 識別子も回帰確認する
#   （0.27.0 では除外されなくなったが、明示許可は保険として残している）
# - endless method definition（`def m = foo 1`）の括弧なしコマンド呼び出しと
#   その rescue 修飾・splat / block 引数もここで確認する
# - scanner.c の正規表現オプション判定が ASCII 外 Unicode 文字
#   （`ど` U+3069 / `ũ` U+0169 は下位 8 bit が 0x69 = 'i'）を
#   char 切り詰めで誤って消費しないこともここで確認する
# - scanner.c の短縮 interpolation 判定が EOF 直後の `$` を
#   特殊グローバル変数として誤判定しないこともここで確認する
# - scanner.c の短縮 interpolation 判定が ASCII 外 Unicode 文字
#   （`Ĥ` U+0124 や `Ŀ` U+0140 など）を char 切り詰めで `@` / `$` と
#   誤一致させないこともここで確認する
# - 非引用・引用付き Unicode heredoc 終端語を UTF-8 のまま照合できることを確認する
# - `$名前` や `$-名` などの Unicode グローバル変数と短縮 interpolation を確認する
# - Ruby 3.4 の `it` 暗黙ブロックパラメータも回帰確認する
# - Ruby Box 例で使われる式ベースの scope resolution（`box::Foo`）も回帰確認する
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
#   非有限値 / 0 以下 / 有効値 / os.environ フォールバック）の境界ケース検証
# - Windows tasklist CSV の引用符付き桁区切りと POSIX プロセスグループ合算を含む
#   OS ごとの RSS 解析検証
# - run_with_memory_guard の正常終了、大きな pipe 出力での非デッドロック、
#   子プロセス RSS 超過 kill、タイムアウト強制終了（kill_reason 設定）の検証
# - Windows の taskkill / POSIX のプロセスグループ kill が失敗した場合に、
#   対象プロセスの直接 kill へフォールバックすることの検証
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
# NON_IDENTIFIER_CHARS と誤一致させない symbol パース回帰検証、
# scanner.c の `scan_short_interpolation` が ASCII 外 Unicode 文字
# （`Ĥ` U+0124、`Ŀ` U+0140 など）を `@` / `$` と誤判定しない回帰検証、
# Unicode heredoc 終端語を UTF-8 バイト列として保持・照合する回帰検証、
# `$名前` / `$-名` の通常参照と短縮 interpolation の回帰検証、
# Ruby 3.4 の `it` 暗黙ブロックパラメータのパース検証、
# Ruby 3.4 の index assignment（`arr[i, k: v] = x` / `arr[i, &b] = x`）拒否の検証、
# Ruby 4.0 の `*nil` splat 引数のパース検証、
# Ruby 4.0 の行頭論理演算子（`||` / `&&` / `and` / `or`）による行継続のパース検証、
# if 条件内のキーワード演算子を含む、
# 正規表現オプション読み（imxouesn）が末尾に改行のない EOF 直後で終わる正規表現
# （`a = /x/` 等）で strchr の終端 NUL マッチによる無限ループに陥らないことの検証、
# endless method definition の括弧なしコマンド呼び出しのパース検証と
# `def m = foo 1 rescue 2` の rescue が本体側に束縛されることの検証、
# ブロック付きコマンド呼び出しのチェーン（`1.upto 0 do end.foo(1)`）の回帰検証、
# 正規表現オプション判定（imxouesn）が ASCII 外 Unicode 文字を char 切り詰めで
# 誤って消費せず、正当なオプションと EOF は従来どおり扱われることの検証）
cargo test

# tree-sitter-cli の install script は `pnpm-workspace.yaml` の `allowBuilds` で
# 許可済みなので通常は不要。何らかの理由で止まったときだけ手動で取得する。
# install.js はカレントディレクトリに tree-sitter を書き出すため、
# 必ずパッケージディレクトリで実行する（リポジトリルートで実行すると
# 18MB のバイナリが作業ツリーに落ちる。`.gitignore` 済み）。
(cd node_modules/tree-sitter-cli && node install.js)
```

`pnpm run test` はコーパス実行前に `tree-sitter --version` を確認し、CLI が見つからない場合や 10 秒以内に起動できない場合は setup error で終了します。関連する setup/failure 分岐は `pnpm run test:unit` で回帰確認できます。

`scripts/corpus_test.py` を直接実行する場合、CLI は
`TREE_SITTER_CLI`、`node_modules/tree-sitter-cli/tree-sitter`、`node_modules/.bin/tree-sitter`、
PATH 上の `tree-sitter` の順に解決します。依存関係をインストール済みの環境では、
`python3 scripts/corpus_test.py` の直接実行でもプロジェクトで固定した CLI を使います。

### スキャナー

外部スキャナー（`src/scanner.c`）は、`grammar.js` だけでは表現できない文脈依存トークンを処理します: heredoc、区切りリテラル（文字列、正規表現、サブシェル、シンボル/文字列配列）、改行、空白依存の演算子、およびそれらを正しく再開するためのスキャナー状態シリアライズです。`src/` 配下の他のファイルとは異なり、手動管理のため新しいトークン型を追加する際は直接編集してください。

255 文字を超える heredoc 終端語は `test/corpus/literals.txt` の回帰ケースで検証しています。tree-sitter の scanner serialization buffer に収まらない終端語は、状態喪失による誤パースを避けるため ERROR にしますが、1024 バイトのバッファ上限ぴったりに収まる状態は有効として扱います。Unicode 終端語は UTF-8 バイト列として保持・照合し、ASCII 終端語の 1 文字 1 バイト表現と容量を維持します。スキャナーのシリアライズを変更した場合は `pnpm run test` で必ず確認してください。`deserialize()` 関数にはバッファ境界チェックが含まれており、切り詰められた・破損したバッファを安全に処理します。word_length の境界チェックは加算 (`size + word_length > length`) ではなく減算 (`word_length > length - size`) で行い、攻撃者が制御可能な `word_length` で符号なし整数オーバーフローを起こしてもチェックを回避できないようにしています。また正規表現オプション読み（`imxouesn`）と特殊グローバル変数の短縮 interpolation 読みでは、`lexer->lookahead` を `strchr` に直接渡しません。strchr は第 2 引数を `char` へ変換するため、EOF（`0`）が終端 NUL に一致するだけでなく、下位 8 bit がオプション文字と衝突する ASCII 外のコードポイント（`ど` U+3069 と `ũ` U+0169 はいずれも 0x69 = `'i'`）まで消費されてしまいます。前者は `int32_t` のまま列挙比較し、後者は `c > 0 && c < 0x80` で ASCII 範囲に絞ってから照合します。

### Unicode 識別子

tree-sitter-cli 0.26.11 は、case-insensitive keyword を正しく抽出するため、
`s` へ単純 case fold される `ſ`（U+017F）と、`k` へ単純 case fold される
`K`（U+212A）を汎用の lexer 文字集合から除外していました。Ruby ではどちらも
有効な識別子文字なので、`grammar.js` の先頭文字・継続文字ルールで明示的に
許可しています。0.27.0 ではこの除外が無くなり、明示許可は no-op（`src/parser.c` は
1 バイトも変わらない）ですが、CLI 側で再発したときに黙って壊れないよう残しています。
識別子 token のルールを変更する場合は、
`test/corpus/identifiers.txt` の回帰ケースと必ず同期してください。
名前付きグローバル変数も同じ Unicode 識別子ルールを使い、1 文字の option 形式
（`$-名`）と短縮 interpolation（`"#$名前"`）にも対応します。

### endless method definition

Ruby 3.1 以降、endless method definition の本体には括弧なしのコマンド呼び出しを
書けます（`parse.y` の `endless_command : command`）。例えば
`def greet(person) = "Hi, ".dup.concat person` です。この位置に既存の `command_call`
をそのまま使うことはできません。`command_call` の引数リストが `_expression` へ
戻る相互再帰のため、パターンマッチ（`x in [1] | [2]`）やブロック束縛まで
endless body の文脈に流れ込み、LR conflict が連鎖するからです。そのため文法側では
`_arg` を leaf としてだけ再利用する `_endless_command_call` /
`_endless_command_argument_list` / `_endless_command_argument` を専用に定義しています。

`pair`（`def m = foo a: 1`）は endless の引数リストから意図的に除外しています。
`_arg => _arg` の形が `match_pattern` と競合し、この文脈だけで LR 状態が倍増して
`src/parser.c` が 21MB から 32MB へ膨らむためです。splat / 二重 splat / block 引数は
ほとんどコストがかからないので対応しています。括弧付きの `def m = foo(a: 1)` は
従来どおり解析できます。

`call` や `command_call_with_block` のレシーバに `_chained_command_call` を
追加してはいけません。`1.upto 0 do end.foo(1)` の AST は改善しますが、
Rails・Homebrew・ruby 本体でファイル全体がパース失敗するようになり、
`src/parser.c` も 37MB へ倍増します。

## 参考資料

- [Whitequark パーサーの AST フォーマット](https://github.com/whitequark/parser/blob/master/doc/AST_FORMAT.md)

[ci]: https://img.shields.io/github/actions/workflow/status/owayo/tree-sitter-ruby/ci.yml?logo=github&label=CI
