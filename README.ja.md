# tree-sitter-ruby

[![CI][ci]](https://github.com/owayo/tree-sitter-ruby/actions/workflows/ci.yml)

[tree-sitter](https://github.com/tree-sitter/tree-sitter) 用の Ruby 文法パーサー。Ruby 3/4 構文に対応。

検証したリポジトリの版、回帰確認、残る構文上の制約は
[構文検証レポート](docs/validation.md)に記録しています。

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

## 既知の制約

### 空白付き添字代入とローカル変数

この文法は Ruby のローカル変数の束縛を解決しません。裸の識別子と `[` の間に
空白がある場合、Ruby はその位置で有効な束縛を使い、添字のレシーバか、配列を
引数に取るメソッド呼び出しかを区別します。次の2つをそれぞれ単独でパースすると、
Ruby では構文エラーになります。

```ruby
v [0] = 1
```

```ruby
v [0] += 1
```

先行する代入や仮引数による束縛があれば、空白付きの形も Ruby で有効です。

```ruby
v = []
v [0] = 1
v [0] += 1

def update(v)
  v [0] += 1
end
```

この文法は宣言の有無にかかわらず、どちらも `ERROR` ノードなしで受理します。
`assignment` または `operator_assignment` の `left` フィールドが
`element_reference` になり、その `object` フィールドに `identifier` が入ります。
空白のない `v[0] = 1` も名前付きノードの構造は同じですが、Ruby では先行する
束縛がなくても構文として有効です。そのレシーバは実行時にメソッド呼び出しに
なり得ます。代入演算子のない `v [0]` は、この文法では `call` の
`argument_list` に配列が入る形になります。

Ruby の構文として有効かを判定する利用側では、追加の検証が必要です。
裸の識別子については上記フィールドを確認し、`object` の終端バイト位置と
開始 `[` トークンの開始バイト位置を比較します。間隔があれば `v[0]` と区別できるため、
そのソース位置での Ruby の束縛を、仮引数・外側のブロックスコープ・宣言順序も
含めて解決してください。後ろの代入はそれより前の参照を束縛せず、メソッド・
クラス・モジュールは外側のローカル変数を引き継ぎません。登録は実行時ではなく
パース時に行われるため、`v = [] if false` でも後続の文に対して `v` が登録されます。
詳しくは [Ruby のローカル変数の規則](https://docs.ruby-lang.org/en/4.0/syntax/assignment_rdoc.html#label-Local+Variables+and+Methods)を参照してください。

[`queries/locals.scm`](queries/locals.scm) のキャプチャは束縛解析の手がかりになりますが、
Ruby の登録・スコープ規則すべてを実装しているわけではありません。また、上の確認は
裸の識別子に限ったもので、すべてのレシーバを検証する完全な規則ではありません。
例えば、この文法は Ruby が拒否する `Foo [0] = 1` や `obj.foo [0] = 1` も受理します。
`ERROR` ノードがない AST でも、Ruby の構文として有効だとは限りません。
束縛を考慮するパースを導入する際には、これらの制約と対応するテストを見直してください。

### ローカル変数の後の演算子と利用側の手がかり

識別子の後に空白があり、演算子の直後に空白がない形 (`foo +value`、`foo -1`、`foo *args`、
`foo **opts`、`foo &blk`、`foo [0]`、`foo <<X`、`foo /re/`、`foo %w[a]`) は、
この文法では `foo` の引数の始まりとして読みます。未知の識別子に対する Ruby の読み方と同じですが、
`foo` がその位置でローカル変数なら、Ruby はこれらを二項演算や添字として読みます
(`count = 1; count +1` は `count + 1`)。

束縛を解決できる利用側は、演算子の直前の空白の最後の 1 文字を改ページ (U+000C) に置き換えて
パースし直すと、その演算子を二項演算 (`+`・`-`・`*`・`**`・`&`・`<<`・`/`・`%`) として、
`[` を添字として読ませられます。演算子の直前が行継続 (`\` と改行) なら、その前の空白を置き換えます
(行継続は改行を消すだけなので、手がかりは改行を越えて残ります)。Ruby は改ページを空白として扱う
ので、本文の意味とバイト位置は変わりません。改ページの直後に空白や改行 (行継続を除く) があるときと、
式の始まりのように二項演算が成立しない位置では、手がかりを使いません。それ以外の位置の改ページは
空白として読みます。

本文がもともと改ページを含む場合は、トークンの外 (字句の空白) にある改ページを、手がかりを置く前に
空白へ置き換えてください。置き換えないと、その改ページも手がかりとして扱われます。文字列・コメント・
heredoc の終端語の中の改ページは文字そのものなので残します。手がかりで `<<` や `%` の読み方が
変わると、後ろの heredoc や percent literal の範囲も変わるので、手がかりと置き換える改ページは
読み直した木で確かめ直してください。`?` で始まる三項演算子と文字リテラルの区別、`::` の区別は
内部の字句解析で決まるため、この手がかりの対象外です。

## 新規フルパースの性能比較（2026-10-25）

Windows 11・Ryzen 7 5700X上で、Rust APIを単一スレッドで測定した。
ファイルごとのパーサー初期化・言語設定・木の構築と解放を含み、入力I/O・
AST出力・クエリ・Ruby VM起動は含まない。両者のCコードをRelease最適化した。
Rust 1.99.1、tree-sitter 0.27.1、
[ruby-prism 2.0.0](https://github.com/ruby/prism/releases/tag/v2.0.0)を使用。
ウォームアップ2回の後に交互に7回測定し、中央値［最小–最大］を示す。

| コーパス | 件数 | バイト数 | Prism ms（範囲） | tree-sitter ms（範囲） | Prism/TS |
|---|---:|---:|---:|---:|---:|
| Rails | 3,481 | 19,969,246 | 182.841 [177.335–204.697] | 2842.796 [2753.742–3170.107] | 0.0643 |
| Ruby | 7,456 | 35,991,793 | 372.778 [360.533–437.018] | 6737.040 [6601.850–7068.405] | 0.0553 |
| RuboCop | 1,791 | 11,567,191 | 90.028 [83.055–98.834] | 1113.932 [1081.602–1177.627] | 0.0808 |
| Homebrew | 2,403 | 13,531,218 | 144.778 [135.069–183.708] | 2121.994 [2072.912–2191.140] | 0.0682 |
| Mastodon | 3,350 | 6,062,212 | 70.601 [63.842–78.850] | 1027.828 [939.557–1049.026] | 0.0687 |
| 合計 | 18,481 | 87,121,660 | 864.078 [824.900–980.548] | 13739.942 [13683.859–14471.962] | 0.0629 |

全体のPrism/TSは0.0629で、1超ならtree-sitterが速い。
**新規フルパースでPrismを上回る目標は未達**。
主比較は両者が受理する18,481件に固定した。全18,487入力に対し、
既知のtree-sitterの失敗5件が残り、新しい失敗はない。
最適化するCargoプロファイルでは、生成された最適化無効化pragmaを
`OUT_DIR`のコピーだけで外すよう修正した。生成物の原本は維持する。2回の測定では旧ビルド比の差が逆転しており、
この修正による全体の速度向上は確定していない。
独立した再測定を含む[生データと調査記録](docs/benchmarks/2026-10-25/README.md)、
[再現用ハーネス](tools/parse-benchmark/README.md)も保存した。
scannerの割り当て削減の試作は速度差を確定できず採用していない。

## 前提条件

```bash
mise install
```

Node.js、pnpm、Python、Ruff、Rust の版は `mise.toml` で管理します。tree-sitter CLI は pnpm でプロジェクト内に導入します。

## 開発

```bash
# 依存関係のインストール（tree-sitter CLI バイナリの取得まで実行）
mise exec -- pnpm install

# grammar.js からパーサーを生成
mise exec -- pnpm exec tree-sitter generate

# 生成した JSON をコミット済みと同じタブ字下げに整形
mise exec -- pnpm exec biome format --write src/grammar.json src/node-types.json

# grammar.js を lint
mise exec -- pnpm run lint

# ファイルをパース
mise exec -- pnpm exec tree-sitter parse example.rb
```

### テスト

**`tree-sitter test` は実行しないでください。** この大規模パーサーでは
RSS 8GB+、VSIZE 400GB+ を消費してハングします。以下の parse ベースの
コーパスランナーを使い、共有ライブラリを先にビルドしてください。
ランナーはライブラリを暗黙に再ビルドしません。

```bash
# macOS: parse 用の共有ライブラリを先に作成する
mkdir -p /tmp/ts-lib
cc -shared -fPIC -O0 -o /tmp/ts-lib/ruby.dylib -I src src/parser.c src/scanner.c

# コーパス・ランナー・Rust バインディングを検証する
mise exec -- python3 scripts/corpus_test.py
mise exec -- pnpm run test:unit
mise exec -- cargo test

# lint とフォーマットを確認する
mise exec -- pnpm run lint
mise exec -- ruff check scripts
mise exec -- ruff format --check scripts
mise exec -- cargo fmt --check
```

Linux では `ruby.so`、Windows では `ruby.dll` を作成します。
別のファイルを使う場合は `TREE_SITTER_LIB_PATH` を指定してください。
未指定の場合は `TREE_SITTER_LIBDIR`、次に POSIX の `/tmp/ts-lib` または
Windows のネイティブ TEMP 配下を使います。Windows のネイティブプログラムには
ネイティブパスを渡す必要があるため、CI では Git Bash のパスを
`cygpath -am` で変換しています。

コーパスでは Ruby 3/4 構文、Unicode 識別子、引数転送、endless method、
行継続、リテラル、heredoc を検証します。期待 AST にフィールド名がある場合は、
ノード構造に加えてフィールド名も比較します。フィールド名のない既存ケースでは
従来の比較方法を維持します。Rust テストはクエリのキャプチャ、heredoc の
増分パース（heredoc 本文の中で開いた入れ子の heredoc を含む）、リテラルと
heredoc の合計保存容量、切り詰められた保存状態や余分な末尾データ、
段の並びが不正な保存状態も検証します。ランナーのユニットテストはセットアップ失敗、
タイムアウト、メモリ上限、出力のデコード、AST 比較を検証します。

CLI は `TREE_SITTER_CLI`、ローカルのネイティブバイナリ、pnpm の shim、
PATH の順に解決します。共有ライブラリがない場合や CLI が 10 秒以内に
起動できない場合は、コーパス実行前にセットアップエラーで終了します。

### C バインディング

CMake はコミット済みのパーサーをビルドするため、通常のビルドに CLI は不要です。
C/C++ ヘッダー、ライブラリ、pkg-config メタデータをインストールします。
配布物のバージョンは `Cargo.toml` と同期します。

```bash
cmake -S . -B build/c -DCMAKE_INSTALL_PREFIX="$HOME/.local"
cmake --build build/c
cmake --install build/c

# Python 3.7 以降と tree-sitter CLI がある環境でコーパスを検証する
cmake --build build/c --target ts-test
```

`ts-test` はビルドしたライブラリのパスを `scripts/corpus_test.py` に渡します。
Python が見つかった共有ライブラリビルドで利用できます。静的ライブラリを
作る場合は `BUILD_SHARED_LIBS=OFF` を指定してください。CLI が見つかった場合の
`ts-generate` は、明示的に実行したときだけ `grammar.js` から再生成します。

### スキャナー

外部スキャナー（`src/scanner.c`）は、`grammar.js` だけでは表現できない文脈依存トークンを処理します: heredoc、区切りリテラル（文字列、正規表現、サブシェル、シンボル/文字列配列）、改行、空白依存の演算子、およびそれらを正しく再開するためのスキャナー状態シリアライズです。`src/` 配下の他のファイルとは異なり、手動管理のため新しいトークン型を追加する際は直接編集してください。

heredoc 本文の補間の中で開いた heredoc は Ruby と同じ順に読みます。その本文は開いた行の次の行から始まり、外側の本文の続きや、外側の行で開いた後続の heredoc より先に読みます（`foo(<<~A, <<~B)` の A の本文に `#{<<~C}` があれば、C、A の残り、B の順）。スキャナーは開いた heredoc を行ごとの段として持ち、入れ子の段の先頭を既存のフラグバイトのビットで示すため、保存状態の 7 バイトのヘッダーと終端語の容量は変わりません。入れ子の `heredoc_body` は外側の `heredoc_body` の中に extra として現れます。外側の本文の行が行継続（`\`）で終わるときは、`\` を外側の本文に残し、その行末から入れ子の本文を始めます。走査で作られない段の並びは復元時に破棄します。

heredoc を開いた行が改行以外の形で続くときも、本文はその行の次の行から読みます。コード中の行継続（`foo(<<~A, \` の直後の改行）や、heredoc の開始の後で改行をまたぐリテラル（文字列・正規表現・シンボル・サブシェル・`%w` などの配列。`[<<~A, "x` の直後の改行。リテラルの中の `\` + 改行を含む）が対象です。リテラルの中では、本文は extra としてリテラルのノードに入ります。行継続で開いた行の改行が消えた段では、最後の終端の後に終端行の改行を表す隠しトークンが続き、コードやリテラルは Ruby と同じく次の行へつながります。`heredoc_end` は従来どおり終端語だけです。コード中の単独 CR は Ruby と同じく空白として扱い、本文を始めません。

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
