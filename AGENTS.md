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
| `bindings/` | Rust バインディングと C/C++ ヘッダー・pkg-config テンプレート |
| `bindings/rust/build_support.rs` | 最適化するCargoプロファイル向けに、生成Cのビルド用コピーを準備する |
| `test/corpus/` | パーサーのコーパステスト |
| `test/highlight/` | ハイライトクエリのテスト |
| `test/tags/` | タグクエリのテスト |
| `tools/parse-benchmark/` | Prism と比較する独立した開発用ハーネス（通常の利用依存には含めない）。関数別の CPU 採取・reduce の記号別集計・交互測定も含む |
| `.depup` | `depup` をリポジトリ直下で実行したときに、直下に加えて依存を更新するディレクトリ（計測ハーネス） |
| `docs/benchmarks/` | 入力のハッシュ・受理差・新規フルパースの測定記録 |

## 開発コマンド

```bash
mise install                              # mise.toml の開発ツールを導入
mise exec -- pnpm install                 # 依存関係と CLI バイナリを導入
mise exec -- pnpm exec tree-sitter generate # grammar.js からパーサー生成
# 生成した JSON はタブ字下げで管理している。生成の後に Biome で整形し直す
mise exec -- pnpm exec biome format --write src/grammar.json src/node-types.json
mise exec -- pnpm run lint                # lint チェック（Biome）
```

### テスト実行

**`tree-sitter test` は直接実行禁止。** tree-sitter-cli は大規模パーサーで RSS 8GB+/VSIZE 400GB+ を消費しハングする既知の問題がある。0.26 系で確認し、0.27 系でも解消していない。

代わりに以下の方法でテストすること:

```bash
# 共有ライブラリを先にビルドする（macOS。Linux は ruby.so、Windows は ruby.dll）
mkdir -p /tmp/ts-lib
cc -shared -fPIC -O0 -o /tmp/ts-lib/ruby.dylib -I src src/parser.c src/scanner.c

# コーパステスト（推奨）— tree-sitter parse ベース、低メモリ
# - 匿名 `*` / `**` / `&` 転送のような最近の Ruby 構文回帰もここで確認する
# - Ruby 4.0 の `*nil` splat パースもここで確認する
# - Ruby 3.4 の index assignment で keyword / block 引数を拒否する回帰もここで確認する
# - 空白付き添字代入の括弧内にある改行・コメントと、配列引数との区別も確認する
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
# - endless method definition (`def m = foo 1`) の括弧なしコマンド呼び出しと
#   その rescue 修飾・splat / block 引数もここで確認する
# - scanner.c の正規表現オプション判定が ASCII 外 Unicode 文字
#   （`ど` U+3069 / `ũ` U+0169 は下位 8 bit が 0x69 = 'i'）を
#   char 切り詰めで誤って消費しないこともここで確認する
# - scanner.c の短縮 interpolation 判定が EOF 直後の `$` を
#   特殊グローバル変数として誤判定しないこともここで確認する
# - scanner.c の短縮 interpolation 判定が ASCII 外 Unicode 文字
#   （`Ĥ` U+0124 や `Ŀ` U+0140 など）を char 切り詰めで '@'/'$' と
#   誤一致させないこともここで確認する
# - 非引用・引用付き Unicode heredoc 終端語を UTF-8 バイト列として保持・照合する回帰も確認する
# - `$名前` / `$-名` の Unicode グローバル変数と短縮 interpolation も回帰確認する
# - Ruby Box 例で使われる式ベースの scope resolution（`box::Foo`）も回帰確認する
# - `tree-sitter parse --no-ranges` の AST 出力を正規化して期待 AST と比較する
# - corpus ソース内の単独 CR 文字を LF に正規化せず検証する
# - heredoc の行途中・末尾空白・単独 CR・部分一致直後のエスケープを確認する
# - heredoc 本文の補間で開いた heredoc（同じ行の複数 heredoc、同じ本文行の複数 heredoc、
#   多段、複数行の補間、同じ終端語、補間しない heredoc、修飾子 if、行継続で終わる行、
#   補間直後の `#`）を Ruby と同じ順に読むことを確認する
# - heredoc を開いた行がコードの行継続で続く場合（括弧内・二項演算・修飾子 if・複数 heredoc）と、
#   開始の後で改行をまたぐリテラル（文字列・正規表現・%w・文字列の行継続・補間の中の文字列）で、
#   本文をその行の次から読み、本文の後で元の行を続けることを確認する
python3 scripts/corpus_test.py

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
#   非有限値 / 0 以下 / 有効値 / os.environ フォールバック）の境界ケース検証
# - Windows API の現在の working set 取得、失敗時も含むハンドル解放、無効な PID、
#   外部コマンドを使わないことと POSIX プロセスグループ合算を含む RSS 取得検証
# - run_with_memory_guard の正常終了、大きな pipe 出力での非デッドロック、
#   子プロセス RSS 超過 kill、タイムアウト強制終了（kill_reason 設定）の検証
# - Windows の taskkill / POSIX のプロセスグループ kill が失敗した場合に、
#   対象プロセスの直接 kill へフォールバックすることの検証
# - 中断・監視処理の例外時の子プロセス回収と元の例外の伝播、
#   終了後もパイプが閉じない場合の期限付き再試行の検証
# - resolve_lib_dir の解決順（env 上書き / 空白のみ / POSIX 既定 / Windows は
#   POSIX パスではなくネイティブ TEMP 配下 / os.environ フォールバック）
# - resolve_library_path と library_suffix のプラットフォーム別解決、
#   TREE_SITTER_LIB_PATH が TREE_SITTER_LIBDIR より優先されること
# - configure_stdio_encoding の UTF-8 化（reconfigure 非対応ストリームの無視、
#   例外の握り潰し、既定で sys.stdout/sys.stderr を対象にすること）
# - root_cause_line / summarize_command_failure の ANSI 除去と
#   Caused by チェーン最深部（例: os error 126）の抽出
# - main() が --lib-path / --lang-name と NO_COLOR=1 を渡すこと、
#   共有ライブラリ不在を setup error（exit 2）で即座に報告すること
# - ツリーが出ないままの非 0 終了を、期待 ERROR ケースでも
#   「expected ERROR but parsed OK」と誤分類しないこと
# - 期待 AST にフィールド名がある場合の保持・入れ替わり・欠落を検証する
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
# - scanner.c の `scan_short_interpolation` が ASCII 外 Unicode 文字
#   （例: `Ĥ` U+0124 → 下位 8 bit 0x24 = '$',
#    `Ŀ` U+0140 → 下位 8 bit 0x40 = '@'）を char 切り詰めで
#   '@'/'$' と誤一致させて短縮 interpolation として誤判定しないことの検証
# - scanner.c が Unicode heredoc 終端語を UTF-8 バイト列で保持・照合することの検証
# - `$名前` / `$-名` の通常参照と短縮 interpolation のパース検証
# - Ruby 3.4 の `it` ブロックパラメータ（パイプ仮引数なしブロック内）のパース検証
# - Ruby 3.4 の index assignment（`arr[i, k: v] = x` / `arr[i, &b] = x`）拒否の検証
# - Ruby 4.0 の `*nil` splat 引数のパース検証
# - Ruby 4.0 の行頭論理演算子（`||` / `&&` / `and` / `or`）による行継続のパース検証
#   （if 条件内のキーワード演算子を含む）
# - scanner.c の正規表現オプション読み（imxouesn）が、EOF 直後で終わる正規表現
#   （`a = /x/` など末尾に改行がない）で strchr の終端 NUL マッチによる
#   無限ループに陥らないことの検証
# - endless method definition の括弧なしコマンド呼び出し
#   （`def greet(person) = "Hi, ".dup.concat person`）のパース検証と、
#   `def m = foo 1 rescue 2` の rescue が本体側に束縛されることの検証
# - ブロック付きコマンド呼び出しのチェーン（`1.upto 0 do end.foo(1)`）が
#   パースできることの回帰検証（`call` のレシーバ拡張による退行の検出用）
# - scanner.c の正規表現オプション判定（imxouesn）が ASCII 外 Unicode 文字を
#   char 切り詰めで誤って消費しないこと、正当なオプションと EOF は
#   従来どおり扱われることの検証
# - heredoc の増分パースと、リテラル追加時の合計保存容量超過を検証する
#   （補間の中で開く区切りシンボル `:"` / `:'` でも、開始待ちの heredoc 本文を保つ）
# - scanner 保存状態の空終端語・Unicode・容量上限の往復、切り詰め・末尾ゴミを検証する
# - 入れ子の heredoc 本文の位置（LF・CRLF・単独 CR・行継続）と、入れ子の追加・削除・編集後の
#   増分パースが新規パースの全ノード範囲と一致することを検証する
# - 段の印（nested・continued）を含む保存状態の往復と、走査で作られない段の並びの破棄を検証する
# - コードの行継続の後の本文と終端行の改行の範囲（LF・CRLF）、コード中の単独 CR の後の
#   外部トークンの範囲、改行をまたぐ各種リテラル（配列の `\` + 改行・単独 CR・FF を含む）の
#   本文の所属先、それらの編集後の増分パースを検証する
# - 演算子の直前の改ページ（利用側の手がかり）で `+`・`-`・`*`・`**`・`&`・`<<`・`/`・`%` を
#   二項演算、`[` を添字として読み、演算子がもとのバイト位置に残ることを検証する。
#   手がかりのない入力と、式の始まりなど二項演算が成立しない位置の改ページは従来どおり読む
cargo test

# C バインディング: ビルド済みライブラリを使う低メモリのコーパステスト
cmake -S . -B build/c
cmake --build build/c --target ts-test

# 個別ファイルのパース検証
TREE_SITTER_LIBDIR=/tmp/ts-lib tree-sitter parse example.rb

# tree-sitter-cli の install script は `pnpm-workspace.yaml` の `allowBuilds` で
# 許可済みなので通常は不要。何らかの理由で止まったときだけ手動で取得する。
# install.js はカレントディレクトリに tree-sitter を書き出すため、
# 必ずパッケージディレクトリで実行する（リポジトリルートで実行すると
# 18MB のバイナリが作業ツリーに落ちる。`.gitignore` 済み）。
(cd node_modules/tree-sitter-cli && node install.js)
```

`pnpm run test` は実行前に `tree-sitter --version` を確認し、CLI が見つからない場合や 10 秒以内に起動できない場合は setup error で終了する。関連する setup/failure 分岐は `pnpm run test:unit` で回帰確認できる。
`scripts/corpus_test.py` を直接実行する場合、CLI は `TREE_SITTER_CLI`、`node_modules/tree-sitter-cli/tree-sitter`、`node_modules/.bin/tree-sitter`、PATH 上の `tree-sitter` の順に解決する。

プリコンパイル済み dylib が `/tmp/ts-lib/ruby.dylib` に必要:

```bash
mkdir -p /tmp/ts-lib
cc -shared -fPIC -O0 -o /tmp/ts-lib/ruby.dylib -I src src/parser.c src/scanner.c
```

`corpus_test.py` はこの共有ライブラリを `tree-sitter parse --lib-path <lib> --lang-name ruby` で
明示的に読み込む。CLI 側の暗黙の再ビルド（Windows では MSVC の `-O2` コンパイル）に落ちるのを
防ぐため。ライブラリが見つからない場合は 1 件もパースせず setup error（exit 2）で終わる。
場所は次の順で解決する:

| 優先度 | 指定方法 | 例 |
|---|---|---|
| 1 | `TREE_SITTER_LIB_PATH`（ファイル） | `/tmp/ts-lib/ruby.dylib` |
| 2 | `TREE_SITTER_LIBDIR`（ディレクトリ）+ プラットフォーム既定名 | `/tmp/ts-lib` → `ruby.dylib` |
| 3 | 既定（POSIX は `/tmp/ts-lib`、Windows は TEMP 配下の `ts-lib`） | — |

やむを得ず `tree-sitter test` を実行する場合は、**必ず RSS と VSIZE の両方を監視**し、VSIZE 50GB または RSS 6GB 超過で即座に kill すること。

## 重要なルール

- `src/` 配下は自動生成ファイルのため直接編集しない（ただし `src/scanner.c` は手動管理の外部スキャナー）
- `grammar.js` を変更した場合は必ず `tree-sitter generate` を実行する
- tree-sitter-cli 0.26.11 は `ſ`（U+017F）と `K`（U+212A）を汎用 lexer 文字集合から除外していたが、Ruby では有効な識別子文字である。0.27.0 ではこの除外が無くなり、明示許可の有無で parser.c は 1 バイトも変わらない（no-op）。ただし CLI 側で再発したときに黙って壊れないよう明示許可は残し、`test/corpus/identifiers.txt` の回帰ケースと同期すること
- endless method definition (`def m = ...`) の本体に括弧なしコマンド呼び出しを許すルールは、既存の `command_call` を流用せず専用の `_endless_command_call` / `_endless_command_argument_list` / `_endless_command_argument` で入口を絞ってある。`command_call` を直接持ち込むと引数リストが `_expression` へ戻る相互再帰でパターン構文まで流れ込み、LR conflict が連鎖するため。引数に `pair`（`def m = foo a: 1`）を足すと parser.c が 21MB から 32MB へ膨らむので意図的に除外している（括弧付き `def m = foo(a: 1)` は従来どおり解析できる）
- `call` / `command_call_with_block` のレシーバに `_chained_command_call` を足してはならない。`1.upto 0 do end.foo(1)` の AST は改善するが、Rails / Homebrew / ruby 本体で広範なパース失敗（ファイル全体が ERROR）を引き起こし、parser.c も 37MB へ倍増する
- ブロック付きコマンド後の連結は専用ルール内で扱う。再帰するレシーバには named rule `chained_command_call` を挟み、内側の method フィールドが外側の `child_by_field_name()` に漏れないことを Rust テストで確認する
- 裸の呼び出しの method には identifier・constant・super とメソッド名の suffix だけを許可する。self・非ローカル変数を許すと空白なし三項演算子を文字リテラル引数と誤認する
- `+` / `-` の単項・二項トークンを混同しない。`foo +value` は引数、`foo + value` は二項演算で、`foo + value, 2` は構文エラー。数値直結の符号と空白付きの符号では、後続メソッドの束縛も異なる
- 文法はローカル変数の束縛を解決しない。利用側が演算子の直前の空白の最後の 1 文字を改ページ（U+000C）に置き換えたときだけ、`scan_whitespace()` が `binary_operator_hint` を立て、`+`・`-`・`*`・`**`・`&`・`<<`・`/`・`%` を二項演算、`[` を添字として読む（Ruby の EXPR_END と同じ）。手がかりは `skip()`・改行・`scan()` の先頭で消える一時的な状態で（行継続の `\` と改行は越えて保つ）、保存状態には入れない。`is_expression_start()` の位置や、二項演算のトークンが有効でない位置では使わない。`?` の三項演算子と文字リテラル、`::` は内部の字句解析が決めるので対象外
- 単項 `+` は `**` より強く、単項 `-` は弱く結合する。範囲演算子の後は `_range_operand` のヒントで式の開始として扱い、`1..-1` / `1..+value` を二項演算と誤認しない
- `return` / `break` / `next` の直後も `_jump_argument` で式の開始を伝える。符号や正規表現をキーワードの外側の演算とせず、改行では引数を継続しない。`yield` は同じ字句状態ではない
- 外部トークンを追加するときは `externals` と `TokenType` の末尾へ同じ順序で追加し、保存状態に入る既存のリテラルトークンの番号を変えない
- 隠し規則は reduce のたびに見えない部分木を割り当てる。`inline` には、supertype でも `conflicts` の対象でもなく、優先順位を持たない隠し規則だけを加える。supertype の隠しノードはクエリの supertype 照合に使うので inline にしない。追加したら `src/node-types.json` が変わらないことと、実ソース全体の木のハッシュ（`tools/parse-benchmark` の `validate`）が一致することを確認し、速度は `paired.py` で対照と交互に測る
- `queries/` の変更はテストで検証する（上記テスト方法を参照）
- `biome.jsonc` で grammar.js のフォーマッタは無効化されている（正規表現の互換性のため）
- `src/scanner.c` のシリアライズを変更した場合は `test/corpus/literals.txt` の長い heredoc 終端語ケースを含めて `python3 scripts/corpus_test.py` で確認する
- scanner の保存状態は、長い終端語・Unicode・複数リテラル・復元途中の破損を交互に復元しても、以前の要素を残さないことを繰り返し復元の Rust テストで確認する
- Rustの最適化プロファイルでは、生成器が入れた最適化無効化pragmaをOUT_DIRのコピーだけで外す。src/parser.cを手編集せず、最適化フラグと実際のコピーの両方を確認し、cargo test --releaseも実行する。opt-level=0では生成物の原本を使う
- Unicode heredoc 終端語は UTF-8 バイト列として保存・照合し、ASCII 終端語の 1 文字 1 バイト表現と serialization buffer 容量を維持すること
- `global_variable` の名前部分は共通の Unicode 識別子文字ルールと同期し、`scan_short_interpolation()` の `$name` / `$-x` 判定でも ASCII 外文字を locale 非依存で許可すること
- tree-sitter の scanner serialization buffer に収まらない heredoc 終端語は、状態喪失による誤パースを避けるため ERROR として扱う。heredoc は `scan_heredoc_start()` で開き、保存容量の確認を迂回しない
- scanner serialization buffer の上限ぴったりに収まる状態は有効として扱い、超過した場合だけ ERROR として扱う
- リテラルは `open_literal()` で開き、開いている heredoc と合計した保存容量の確認を迂回しない。終端行の再開フラグは既存の started バイトに詰め、7 バイトのヘッダーサイズを維持する
- heredoc 終端語は物理行の先頭でだけ認識し、直後は LF・CRLF・EOF に限る。末尾空白や単独 CR は本文とし、空終端語の EOF を架空の空行として受理しない
- heredoc 本文の補間で開いた heredoc は、開いた行の次の行から、外側の本文の続きや外側の行で開いた後続の heredoc より先に読む（Ruby と同じ順）。`open_heredocs` は同じ行で開いた heredoc の列（段）を外側から順に連結し、index 0 以外の段の先頭にフラグバイトの bit 2（`nested`）を立てる。開始済みになれるのは段の先頭だけで、最後の段以外の先頭は開始済みである。追加と終了は `open_heredoc()` / `close_heredoc()` を通し、本文を読む heredoc は `find_current_heredoc()`、次の改行で本文を始める heredoc は `pending_heredoc()` で求める。外側の本文は入れ子の本文が始まる行末（CRLF は `\r`、単独 CR は本文）の手前で区切る。その行が行継続の `\` で終わるときは、`\` を本文として返して行末を escape_sequence に飲ませない。`deserialize()` は走査で作られない段の並びと未使用のフラグを破棄する
- heredoc の本文は、heredoc を開いた行が改行以外の形で続くときも、その行の次の行から読む。コード中の行継続（`foo(<<~A, \` の直後の改行）、heredoc の開始の後で改行をまたぐリテラル（文字列・正規表現・シンボル・サブシェル・`%w` などの配列。`[<<~A, "x` の直後の改行）、その中の `\` + 改行のどれでも、改行（CRLF は `\r`）の位置の幅 0 の `_heredoc_body_start` から本文を始める。リテラルの中では本文が extra としてリテラルのノードに入り、配列の語の間の空白は改行の手前まで読み飛ばす
- 行継続（コードの `\`、補間するリテラルの `\`、補間しない配列の `\`）で改行が消えた行で開いた段には、フラグバイトの bit 3（`continued`）を段の先頭に付けて引き継ぐ。その段の最後の終端は `_heredoc_end_continued`（`heredoc_end` の別名）と、終端行の改行を表す隠しトークン `_heredoc_line_end` で返し、終端行の改行をコードやリテラルへ戻さない（戻すと行継続でつながる次の行との間に文の区切りや配列の区切りができる）。「本文の後の改行を読み飛ばす」印を保存状態に持たせてはならない。外部スキャナーの保存状態は最後の外部トークンに結び付くので、内部トークンだけが続くと印が残り、別の改行まで読み飛ばす
- コード中の単独 CR は Ruby と同じく空白として読み飛ばし、本文は次の改行から始める。CRLF の本文開始位置（`\r`）を保つため、`scan_whitespace()` は `\r` の手前で `mark_end` を呼んでから CR を読む。単独 CR だったときはその終端が残るので、`scan()` が返すトークンは既定の終端（返したときの位置）に頼らず、`accept_token()` などで終端を必ず明示する。新しいトークンを足すときもこの約束を守ること
- `src/scanner.c` の `deserialize()` はバッファ境界チェックを行うため、新しいフィールドを追加する際は対応する境界チェックも追加すること
- 破損した保存状態は途中まで復元したリテラル・heredoc もすべて破棄する。余分な末尾データを assert で処理してはならない
- `deserialize()` のバッファ境界チェックで `size + word_length > length` のような符号なし整数の和を使うと、`word_length` が極端に大きい場合に整数オーバーフローしてチェックを潜り抜けるため、`word_length > length - size` の引き算で比較すること（`size <= length` は手前のヘッダーサイズチェックで保証されている前提）
- `tree-sitter test` をメモリ監視なしで実行してはならない
- `scripts/` 配下の Python コードは Python 3.7 互換を維持するため、`ruff.toml` で `target-version = "py37"` を指定している。parenthesized context manager などの新しい構文を自動書き換えされないよう、新規コードでも Python 3.7 互換を崩さないこと
- 終了コードと stdout/stderr を結果として解析する `subprocess.run()` 呼び出しは `check=False` を明示し、非 0 終了を例外ではなく戻り値として扱う契約を保つこと
- POSIX パス（`/tmp/ts-lib` など）をネイティブ Windows プロセスに渡してはならない。Git Bash が解決する `/tmp` とネイティブプロセスが解決する `/tmp`（ドライブレターの無い root 相対パスとしてカレントドライブ基準になる）は別物で、共有ライブラリを見失う。CI では `cygpath -am` で変換したパスを `GITHUB_ENV` 経由で渡すこと
- Windows の Python は stdout の既定エンコーディングが cp1252/cp932 のため、日本語を含むコーパスのテスト名を print すると `UnicodeEncodeError` でランナーごと落ちる。`scripts/` の出力側は `configure_stdio_encoding()` で UTF-8 化し、CI では `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` も設定すること
- tree-sitter CLI はパイプ出力でも `Error:` 行を着色し、`NO_COLOR` でも抑止できない。CLI 出力を解析する場合は ANSI エスケープを除去してから判定すること。真の失敗理由は `Caused by:` チェーンの最深部にあるため、先頭の `Error:` 行だけを見ないこと
- `.github/workflows/ci.yml` の `paths` フィルターには `scripts/**`、`tests/**`（cargo test の統合テスト）、`queries/**`、`Cargo.lock`、`bindings/c/**`、`CMakeLists.txt`、`tree-sitter.json`、`.github/workflows/ci.yml` 自身を含めること。含めないと CI 自体・テストランナー・クエリ・C バインディングだけを変更した push で CI が起動しない
- `src/scanner.c` で `strchr(set, lexer->lookahead)` を直接呼ばないこと。strchr は第 2 引数を `char` へ変換するため、(1) `lexer->lookahead == 0`（EOF）が終端の NUL に一致して無限ループになり、(2) 下位 8 bit が一致する ASCII 外の文字（`ど` U+3069 / `ũ` U+0169 → 0x69 = `'i'`）が誤って一致する。文字集合が小さければ `is_regex_option_char()` のように `int32_t` のまま列挙比較し、大きければ `is_special_global_variable_char()` のように `c > 0 && c < 0x80` で ASCII 範囲へ絞り込んでから照合すること
- `src/scanner.c` で `lexer->lookahead`（`int32_t`）を ASCII 文字と比較するときは `char` に切り詰めないこと。Unicode コードポイントの下位 8 bit が ASCII 制御文字（`'@'` 0x40, `'$'` 0x24, `'('` 0x28 など）と一致すると、`Ĥ` (U+0124) / `Ŀ` (U+0140) / `Ĩ` (U+0128) のような文字が誤判定されてしまう（短縮 interpolation 起点や識別子文字判定の誤動作の原因になる）。`int32_t` のまま比較するか、ASCII 範囲（`< 0x80`）を事前に切り分けること
