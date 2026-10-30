# 新規フルパース比較と保守記録（2026-10-25）

新規フルパースで最新安定版Prismを上回る目標は未達。最終候補は、Rustの最適化プロファイルで
生成lexerの最適化を有効にするビルド修正、依存更新、テストと検証基盤を含む。
scannerの配列再利用は採用していない。構文・AST・クエリ・保存形式は変更しない。

## 主比較

Windows 11 / Ryzen 7 5700X / Rust 1.99.1 / MSVC 19.51.36260。
単一スレッドで入力読込後に、新しいParserの作成・言語設定・parse(None)・木とParserの解放を測る。
Prismは公開Rust APIのparseとParseResultの解放。I/O、AST出力、クエリ、VM起動は除く。
両者の木の構造・提供機能は異なり、ASTの同一性は要求しない。
ウォームアップ2回、本測定7回。実装ごとの独立プロセスを交互に動かす。
中央値［最小–最大］。全体は同じ反復内の5コーパスの合計から中央値を求める。

| コーパス |   件数 |   バイト数 |          Prism ms（範囲） |          tree-sitter ms（範囲） | Prism/TS |
| -------- | -----: | ---------: | ------------------------: | ------------------------------: | -------: |
| Rails    |  3,481 | 19,969,246 | 182.841 [177.335–204.697] |    2842.796 [2753.742–3170.107] |   0.0643 |
| Ruby     |  7,456 | 35,991,793 | 372.778 [360.533–437.018] |    6737.040 [6601.850–7068.405] |   0.0553 |
| RuboCop  |  1,791 | 11,567,191 |    90.028 [83.055–98.834] |    1113.932 [1081.602–1177.627] |   0.0808 |
| Homebrew |  2,403 | 13,531,218 | 144.778 [135.069–183.708] |    2121.994 [2072.912–2191.140] |   0.0682 |
| Mastodon |  3,350 |  6,062,212 |    70.601 [63.842–78.850] |     1027.828 [939.557–1049.026] |   0.0687 |
| 合計     | 18,481 | 87,121,660 | 864.078 [824.900–980.548] | 13739.942 [13683.859–14471.962] |   0.0629 |

倍率はPrism中央値÷TS中央値。全体0.0629、1超がTS優位。
全体のTSスループットは6.047 MiB/s。
旧ビルドの全体14683.674 msに対し、最適化済み候補13739.942 ms（この実行の観測差6.43%）。
速度差はマシンのばらつきを含むため、ビルドの正しさと速度の目標達成を区別する。

## 独立した再測定

同じ入力・依存・コンパイラで最初の実行順を反転した。ビルド用helperの整理前後で、
実際にCコンパイラへ渡すparser-optimized.cのSHA256が同じことを確認した。
本測定7回の全体中央値の観測差は-5.86%。両実行の範囲・CPU時間はJSONに保存した。
独立再測定では旧ビルド比の差が逆転したため、この修正による全体の速度向上は確定できない。
採用理由はCargoの最適化設定をCのlexerへ反映することと、最適化済みの比較条件を満たすことである。

| 対象     |     TS ms | Prism ms | Prism/TS | 旧ビルド比の観測差 |
| -------- | --------: | -------: | -------: | -----------------: |
| Rails    |  3544.942 |  221.048 |   0.0624 |             -3.27% |
| Ruby     |  9192.297 |  461.111 |   0.0502 |             -9.36% |
| RuboCop  |  1608.561 |   94.975 |   0.0590 |             -1.20% |
| Homebrew |  2623.447 |  168.762 |   0.0643 |              4.60% |
| Mastodon |  1171.246 |   81.281 |   0.0694 |              5.03% |
| Total    | 18744.984 | 1021.021 |   0.0545 |             -5.86% |


## 正確性

| 対象     |  総数 | TS失敗 | Prism診断あり | 共通集合 |
| -------- | ----: | -----: | ------------: | -------: |
| Rails    | 3,481 |      0 |             0 |    3,481 |
| Ruby     | 7,462 |      5 |             3 |    7,456 |
| RuboCop  | 1,791 |      0 |             0 |    1,791 |
| Homebrew | 2,403 |      0 |             0 |    2,403 |
| Mastodon | 3,350 |      0 |             0 |    3,350 |


全18,487件について、変更前・依存更新後・試作・最適化済みで匿名ノードを含む種別、フィールド、
バイト/行列範囲、named/extra属性のFNV-1a 64bitハッシュと、ERROR/MISSING件数、Prism診断が一致した。
[入力の再確認](input-recheck.txt)でも相対パス・バイト数・SHA256に変更なし。
異常終了・setup error・タイムアウトは0件。Rubyの5件は既知の2負例・2 UTF-16入力・1束縛依存構文。
UTF-16の2件はCLIへ正しいencodingを指定すると成功する。
- `spec/ruby/command_line/fixtures/bad_syntax.rb`、`spec/ruby/core/exception/fixtures/syntax_error.rb`: 意図的な負例。
- `spec/ruby/language/fixtures/utf16-be-nobom.rb`、`utf16-le-nobom.rb`: 主比較のUTF-8入力条件とは別。
- `sample/trick2018/04-colin/entry.rb`: ローカル変数の束縛に依存する三項演算子。既知の文法制限。
- `tool/fetch-bundled_gems.rb`: shebangの `-n` で使うトップレベルnext。実行時フラグを渡さないPrism既定APIでは診断される。

速度のために原本や除外集合を変えていない。初回に両者が受理した18,481件を固定し、新しい失敗があれば測定を止める。
検証器は不正な `def (` を両者で検出する自己確認を行う。
[Ruby 4.0 NEWS](https://docs.ruby-lang.org/en/4.0/NEWS_md.html)を確認し、*nil・行頭論理演算子と
Ruby 3.4のit・添字代入制限は既存回帰で確認した。Ruby実行系は4.0.9。

## 調査と採否

1. Releaseフラグだけでは最適化されなかった。[Issue #20](https://github.com/owayo/tree-sitter-ruby/issues/20)。
   [生成器](https://github.com/tree-sitter/tree-sitter/blob/v0.27.1/crates/generate/src/render.rs#L335)は、
   lexerが300状態を超えるとコンパイル負荷を抑えるためoff/O0のpragmaを挿入する。
   [MSVCの仕様](https://learn.microsoft.com/en-us/cpp/preprocessor/optimize?view=msvc-170)でもoffは
   コマンドラインの最適化を無効にする。最適化するCargoプロファイルだけOUT_DIRのコピーで既知4形式を外し、
   元の生成物・他のpragma・改行を保つ。実コンパイル引数とコピーの内容を確認し、Debug/Releaseの回帰を実行した。
2. scannerの状態復元で配列を毎回解放していた。計測用コピーのカウンターで、deserializeの割り当ては
   2,552,701回、配列再利用の試作では257,562回に減った。しかし2回の交互測定で速度差の95%区間が0をまたぎ、
   試作は採用しなかった。これはlexer無最適化の旧条件での試行であり、主比較とは区別する。
   [不採用パッチ](scanner-reuse-rejected.patch)、[計測結果](scanner-profile-baseline.json)、
   [試作後の計測結果](scanner-profile-candidate.json)、[速度差の監査](timing-audit.txt)を保存した。
3. 有効なRails入力のloggerではlex_external 47,660回、reduce 107,371回、condense 679回などを記録した。
   detect_errorイベントは最終木のERROR件数ではない。汎用パーサーの分岐・木の構築と解放を含む差が残る。
   PrismのarenaとRust側の初期化・解放も参照したが、安全な追加変更を実測で裏付けるには至らなかった。
   WPRのCPUサンプリングは0xc5585011で起動できず、関数別のCPU割合は未測定。
   根拠のない文法の簡略化やruntime本体の変更へは広げていない。

生成はCLI 0.27.1で実行し、JSONをBiomeで整形した。parser.cは25,654,062→25,654,077バイト、
状態数9,135は不変。差はGCCのO0指定にjump-tablesを維持する1行だけで、手編集していない。
Rustのビルド用コピーでは無効化指定を外す。CMake/CLIの生成物の扱いは従来どおり。

Windowsのunit起動は[Issue #19](https://github.com/owayo/tree-sitter-ruby/issues/19)・
[PR #21](https://github.com/owayo/tree-sitter-ruby/pull/21)で修正。単一引用符が残って0件になる状態から、
143件（1件skip）を検出して成功する。Issue対応はresolve-github-issuesでPR・CI・マージを進める。

## 環境・入力・版

- [environment.json](environment.json): コンパイラ、最適化、依存、バイナリSHA256、ソースSHA256と制限。
- [snapshots.json](snapshots.json): 5リポジトリのHEAD・source_sha・クリーン状態。
- [manifest.jsonl](manifest.jsonl): 全入力の相対パス、サイズ、SHA256。
- [common.jsonl](common.jsonl): 固定した共通集合。
- [acceptance-differences.json](acceptance-differences.json): 両者の受理差と診断。
- [native-build-commands.json](native-build-commands.json): cargo -vvから抽出した実際のCコンパイル引数。パスは伏字。
- [専用ハーネス](../../../tools/parse-benchmark/README.md): ロックファイル・計測区間・再現コマンド。

最新版は2026-10-25にcrates.ioと[公式v2.0.0](https://github.com/ruby/prism/releases/tag/v2.0.0)で確認。
crate/sys/Cとも2.0.0、リリースSHAはe2727368fd9fc2486e2acc8aa513f0cd9e7e02cf。
参照原本30a255539e81842b2b7f12b4fd3c62a7b4d64165は3コミット先で、計測には使わず読取専用。
Prismは既定API、tree-sitterはUTF-8、新規パースのみ。再利用・増分応答・I/O込みの速度比較はしていない。
増分パースの正確性は既存Rust回帰で確認した。

## 生データと検証

`final-timings.jsonl` / `final-summary.json` が最適化済み主比較、`repeat-*`が独立再測定。
`control`は同じRust・依存・フラグで、生成pragmaが残る旧ビルド。`baseline-*`は依存更新前。
`unoptimized-final-*`と`reuse-trial-*`はlexer無最適化の調査用で、主比較の結果として使わない。
最初の起動待ち60秒で入力読込が完了しなかった試行は0標本で中止し、起動待ちを600秒にして全標本を取り直した。
`optimized-startup-timeout-timings.jsonl`は空であり、成功の測定に含めない。

[サイズ層ごとの初回診断](diagnostic-size-bands.json)には中央値とp95も保存した。
validationのJSONLはgzipで保存。ファイル別ts_ns/prism_nsは初回の診断用で解放を含まず、主比較には使わない。
プロセス別peak RSS/commitは入力とウォームアップを含む累積値であり、コーパス単独のpeakではない。
commitは仮想アドレス空間のサイズではない。他のローカル作業が同居するデスクトップでの値で、
時間のばらつきとCPU時間をそのまま残した。計測中にローカルビルド・テスト・プロファイルは実行していない。

コーパス427件、Python143件（1 skip）、Rust98件（doc testを含む、Debug/Release）を検証する。
Biome、Ruff、Rust fmt/Clippy、astro-sight review/impact。Cバインディングは未変更でCMake再検証は省略。
CIは既存のLinux/macOS Rust検査にReleaseも追加し、最適化された経路を確認する。
WindowsのReleaseはローカルで確認。Sonicopに関係する構文変更はなく、全木のハッシュが一致したため追加の差分検証は省略。
開始前にあったCargo.lockの版差分は、検証原本で保持して作業を区別した。
