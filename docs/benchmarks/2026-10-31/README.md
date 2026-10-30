# 2026-10-31 tree-sitter-ruby 点検

Ruby 4.1 のメソッド仮引数の末尾カンマと、デフォルト仮引数を多重代入として読む AST を修正した
（[PR #32](https://github.com/owayo/tree-sitter-ruby/pull/32)、[Issue #31](https://github.com/owayo/tree-sitter-ruby/issues/31)）。
CPUプロファイラーの EOF 待機と例外時の回収も修正した（[PR #33](https://github.com/owayo/tree-sitter-ruby/pull/33)）。
性能の試作は最終候補で効果を再現できず、不採用とした。新規フルパースで Prism を上回る目標は未達である。

## 最終候補と最新安定版 Prism

Windows 11 Home 10.0.26300、Ryzen 7 5700X、Rust 1.99.1、MSVC 19.51.36260。
tree-sitter 0.27.1 と ruby-prism / ruby-prism-sys / Prism C 2.1.0 を使う。
[crates.io](https://crates.io/crates/ruby-prism)と[公式リリース](https://github.com/ruby/prism/releases/tag/v2.1.0)で
2026-10-31 に最新安定版を確認した。通常の依存には Prism を追加していない。

単一スレッドの Rust 公開 API で、入力を読み込んでから、ファイルごとに新しいパーサーを作る。
初期化・言語設定・木の構築と解放を含み、I/O・AST出力・クエリ・Ruby VM起動を除く。
両者の AST と機能は異なる。両 C 実装の -O2 と生成器の最適化無効化 pragma の除去を、
実際のビルド引数と出力コピーで確認した（[build-evidence.json](build-evidence.json)）。
LTO・独自allocator・CPU固有の追加最適化は使っていない。

2回のウォームアップ後、順序を反転しながら7回測定した。以下は中央値 [最小–最大]。
全体は各反復で5コーパスを合計してから中央値を求める。倍率は Prism / tree-sitter、1超が tree-sitter の高速を表す。

| Corpus | Files | Bytes | Prism ms (range) | tree-sitter ms (range) | Prism/TS |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rails | 3,481 | 20,022,696 | 171.074 [169.354–173.668] | 2473.682 [2441.950–2551.166] | 0.0692 |
| Ruby | 7,480 | 36,175,846 | 355.654 [350.429–375.481] | 5918.070 [5819.242–6079.022] | 0.0601 |
| RuboCop | 1,791 | 11,643,866 | 80.209 [79.897–83.588] | 996.305 [987.912–1030.638] | 0.0805 |
| Homebrew | 2,419 | 13,716,704 | 132.423 [130.931–134.118] | 1903.235 [1889.473–1981.197] | 0.0696 |
| Mastodon | 3,355 | 6,072,014 | 60.088 [59.250–63.316] | 868.516 [849.404–963.090] | 0.0692 |
| Total | 18,526 | 87,631,126 | 799.690 [791.080–822.075] | 12308.813 [11996.863–12462.721] | 0.0650 |

全体は tree-sitter 12.309 秒、Prism 0.800 秒、倍率 0.0650。
全体の処理速度はそれぞれ 6.790 MiB/s と 104.505 MiB/s。
同じ依存版の変更前対照（control）は 12.194 秒で、最終候補は所要時間が 0.94% 長い。範囲は重なり、AST是正110件も含むため、性能改善とは扱わない。

依存更新前（cc 1.9.0 / Prism 2.0.0）の別測定は baseline-*.json に保存した。
同じ入力だが最終測定と交互に走らせていないため、両者の差を cc 更新の効果と解釈しない。
メモリは実装別の独立プロセスで採取した（[memory-summary.json](memory-summary.json)）。
CPU時間とメモリも次のとおり確認した。CPU時間は反復内の合計の中央値、メモリは全反復の最大値である。

| 実装 | CPU ms | peak RSS MiB | peak commit MiB |
| --- | ---: | ---: | ---: |
| 最終候補 | 12296.875 | 239.344 | 242.875 |
| Prism 2.1.0 | 796.875 | 108.219 | 113.426 |
| 構文修正前の対照 | 12140.625 | 237.934 | 242.766 |

peak は入力保持・前のコーパス・前の反復を含む。peak commit は仮想アドレス空間のサイズではない。
入力読込待ち600秒、以後の応答待ち60秒、RSS/commit 6 GiB の上限を設けた。中断・超過はなかった。
パーサー再利用・増分パースの速度・I/O込みの時間は測定していない。増分パースは正確性のテストで確認した。

## 正確性と入力

取得済みの5リポジトリの全18,532件を使用した。原本は変更せず、再取得もしなかった。
HEADと .source_sha は一致し、作業ツリーはすべてclean。今回のSHAは前回の測定と異なるため、前日の数値と直接比較しない。
[snapshots.json](snapshots.json)と、相対パス・バイト数・SHA256を持つ [manifest.jsonl](manifest.jsonl) に固定した。
最終測定前の再走査でも全18,532件のハッシュが一致した。比較集合は [common.jsonl](common.jsonl) の18,526件である。

| Corpus | All .rb | TS failures | Prism diagnostics | Common | New failures |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rails | 3,481 | 0 | 0 | 3,481 | 0 |
| Ruby | 7,486 | 5 | 3 | 7,480 | 0 |
| RuboCop | 1,791 | 0 | 0 | 1,791 | 0 |
| Homebrew | 2,419 | 0 | 0 | 2,419 | 0 |
| Mastodon | 3,355 | 0 | 0 | 3,355 | 0 |
| Total | 18,532 | 5 | 3 | 18,526 | 0 |

TSの既知の5件は Ruby 本体の意図的な負例2件、UTF-16入力2件、ローカル変数の束縛に依存する
sample/trick2018/04-colin/entry.rb である。Prismの3件は負例2件と、shebangの -n を前提にする
tool/fetch-bundled_gems.rb。Prismは既定オプション、TSはUTF-8で読み、VMの起動オプションは渡していない。
失敗を追加で除外して速度を改善したものではない。

変更前と最終候補で、ERROR/MISSING と Prism 診断の件数は一致する。全ノード（匿名ノードを含む）の
種類・フィールド・バイト/行列範囲・named/extra 属性のハッシュが変わる110ファイルは、デフォルト仮引数の是正である。
全110件の XML を比較し、method_parameters 以外は一致し、内部では仮引数が増えて誤った代入が減ることを確認した
（[parameter-ast-changes.json](parameter-ast-changes.json)）。
文法は引き続きローカル変数の束縛を解決しない。node-types.json は1バイトも変わっていない。

[Ruby 4.0.9の公式情報](https://www.ruby-lang.org/en/news/2026/10/23/ruby-4-0-9-released/)と、
[PrismのRuby 4.1対応](https://github.com/ruby/prism/releases/tag/v2.0.0)を確認した。
仮引数末尾カンマは4.1向けで、Prism 2.1.0を構文の判定に使った。通常・特異・endlessメソッド、匿名・keyword引数を検証し、
block/forward引数の後、空リスト、分割代入用仮引数、lambdaまで受理範囲を広げていない。
29件の構文例と両者の診断は [syntax-probes.jsonl](syntax-probes.jsonl) に保存した。
Ruby 4.0.9の `ruby -c` でもnilのデフォルト値は有効、4.1向けの末尾カンマは未対応であることを確認した。
Ruby 3.4のit/index assignment、4.0の `*nil`・行頭論理演算子等は既存のコーパスとRustテストで回帰確認した。
Sonicopの差分に由来する修正ではないため、Sonicop側の差分計測は行っていない。

## プロファイルと試作

[profile-before.json](profile-before.json)と [profile-final.json](profile-final.json) は、ウォームアップ後の主スレッドの
命令位置を約1ミリ秒ごとに採取した、2反復の記録。数えるのは最内の関数だけである。
採取用の時間を主比較の所要時間には使わない。PDBのないntdllの関数名は最寄りのexportになる。
主な負荷はGLRスタック、部分木の割当・解放、parse table参照、ヒープ操作にある。
Prismの参照ソースは37d2d0d、計測したcrateは公開タグca15cb3由来の2.1.0で、同一HEADとは扱っていない。
Prismのarenaによる割当・一括解放と、TSのGLR/共有部分木の管理の違いを確認した。

| 試作 | 根拠と結果 | 判定 |
| --- | --- | --- |
| `_statements` のinline | 前回のreduce集計で約54.6万回の単位reduce。展開するとrescueの既存構文に新しいLR conflictが生じる | 不採用。conflictを追加して押し通していない |
| `_body_statement` のinline | 前回の集計で約31.6万回の単位reduce。今回の全18,532件の木とnode-types.jsonが一致 | 初回と独立再測定で小さな改善。最終構文との組合せでは再現せず不採用 |

次の比は候補/対照で、1未満が候補の高速。4件に1件の部分集合で、同じCPUに固定し、順序を反転して30組測定した。

| 比較 | CPU | 部分集合 | 比の中央値 | 95% bootstrap区間 | 候補が速い組 |
| --- | ---: | --- | ---: | --- | ---: |
| body inline / 依存更新後の変更前 | 6 | 0行目から4行ごと、4,632件 | 0.986424 | 0.984703–0.988504 | 29 / 30 |
| 独立した再測定 | 10 | 2行目から4行ごと、4,631件 | 0.998354 | 0.996766–0.999556 | 20 / 30 |
| 構文修正+inline / 構文修正のみ | 6 | 0行目から4行ごと、4,632件 | 1.000736 | 0.999722–1.001897 | 12 / 30 |


最終候補では区間が1を含むため、inlineを取り込まなかった。supertype・conflict対象・優先順位付きの規則を
inlineにする案は採らず、意味とASTを守った。scannerの配列再利用等、前回効果を確定できなかった案も再採用していない。
実行系やallocatorの変更には範囲を広げていない。

## 依存・構造・検証

depup --install --include-pinned は cc 1.9.0 → 1.10.0 の1件を更新し、13件をスキップした。
ベンチマーク用Prismは依存更新のリリース経過日数フィルターに従うと2.0.0に留まるため、最新安定版の比較用に
独立ハーネスだけ2.1.0へ更新した。Prismのparse APIは変更不要だった。
baselineのハーネスlockに残っていた自パッケージ版26.10.104は、実際の26.10.105へ合わせてビルドした。その他の依存版は維持した。

astro-sightでscanner・文法・ビルド・ランナーの構造を確認した。複雑度だけを理由とするscannerの整理は行わず、
EOF待機と例外時の回収を妨げていたプロファイラーの重複だけを整理した。差分レビューにAPI変更・取り残しはない。
生成Cは手編集していない。最終文法の再生成は8.072秒（mise/pnpmの起動込み）で、再生成前後のparser.cは同一だった。
状態数は9,337→9,361、large stateは3,552→3,556、記号は374→377、production IDは161のまま。
parser.cは26,163,506→26,191,107バイト。サイズの変化を高速化の根拠には使っていない。

- コーパス432件: pass。
- Rust debug/release全106件（doctestを含む）: pass。クエリcapture、scanner保存状態、Unicode/heredoc、増分パースの全ノード比較を含む。
- Pythonランナー160件: pass、既定の1件skip。プロファイラーの追加10件を含む。
- lint、Ruff lint/format、cargo fmt、Python 3.7構文確認: pass。
- プロファイラー起動失敗の回帰は変更前に5秒の期限超過で失敗し、修正後に成功。Windowsの実採取も成功。
- PR #32/#33/#34/#35 はWindows/Linux/macOSの3件のCIが成功し、マージ・Issueクローズを確認した。#34のmacOSランナー取得失敗によるキャンセルは、同じSHAの再実行で成功した。
- tree-sitter testは実行していない。CMakeのCバインディング検証はUnix CIで実行した。

## CIのmacOS移行

PR #35 の初回CIは、`macos-14` のジョブがテスト開始前に計画停止を理由としてキャンセルされた。
[GitHub公式の告知](https://github.com/actions/runner-images/issues/13518)で、
2026-10-30 14:00 UTCから翌日00:00 UTCの計画停止と、2026-11-02のサポート終了を確認した。
PR #35でOS行列の1項目を `macos-15` へ変更し、テスト工程と権限を維持した。
更新した同一SHA `f3eababf4e4f2c27223b749c3c0fb6a510793cea` の
[CI](https://github.com/owayo/tree-sitter-ruby/actions/runs/41102320033)は3OSすべて成功し、
`8730d72`としてマージした。
[Issue #36](https://github.com/owayo/tree-sitter-ruby/issues/36)と
[ci-runner-migration.json](ci-runner-migration.json)に根拠と実行結果を残す。
文法・scanner・Rust本体は変更しておらず、上の正確性・性能の測定対象ソースと一致する。

## 生データと再現

- 環境・版・入力再照合・ソース/バイナリSHA: [environment.json](environment.json)。実際のC最適化: [build-evidence.json](build-evidence.json)。
- 主比較: final-timings.jsonl / final-summary.json。controlは同じ依存版で作った構文修正前、tsは最終候補。
- 依存更新前: baseline-timings.jsonl / baseline-summary.json。
- 全件検証: *-validation.jsonl.gz と *-validation-summary.json。最終候補とissue28候補の全木は一致する。
- ファイル別: [file-diagnostics.json](file-diagnostics.json) はサイズ層別の中央値/p95。validation内のts_ns/prism_nsは初回の診断用で木の解放を含まず、主比較の時間に使わない。
- 試作の交互測定: paired-body.json / paired-body-2.json / paired-integrated.json。CPU・順序・各組の値を保存している。bootstrapはseed 20261030・5,000回で固定し、environment.jsonにも記録した。
- 入力とハーネスの使い方: [tools/parse-benchmark](../../../tools/parse-benchmark/README.md)。取得済み原本の各SHAはsnapshots.jsonを参照する。

ファイル別診断のキーは上限バイト数（未満）で、`1024`・`4096`・`16384`・`65536`・`larger` は
それぞれ1 KiB未満、1–4 KiB、4–16 KiB、16–64 KiB、64 KiB以上を表す。最大層のp95は
変更前57.787 ms、最終59.866 msだった。単回の解放を含まない診断なので、改善・退行の確定には使わない。
主比較の `control` は37080b4に依存更新後の4つのCargoファイルだけを適用してビルドした版である。

```powershell
mise exec -- cargo build --release --locked --manifest-path tools/parse-benchmark/Cargo.toml
mise exec -- python tools/parse-benchmark/run.py validate --binary tools/parse-benchmark/target/release/ruby-parse-benchmark.exe --source-root <source-root> --output docs/benchmarks/2026-10-31 --label reproduced
mise exec -- python tools/parse-benchmark/run.py bench --binary tools/parse-benchmark/target/release/ruby-parse-benchmark.exe --control-binary <control.exe> --source-root <source-root> --output docs/benchmarks/2026-10-31 --label reproduced
```

## nilデフォルト値の独立回帰

[Issue #31](https://github.com/owayo/tree-sitter-ruby/issues/31) の境界を、[Rustテスト](../../../tests/nil_default_parameters_test.rs) 2件で固定した。通常・特異・endlessメソッド、3個の仮引数、Unicode名、末尾カンマで、名前・nil値・仮引数の範囲を確認する。括弧内の正当な多重代入はデフォルト値の中に残る。変更前の同じテストは1件失敗・1件成功、修正済みの最終統合結果では両方成功する（[記録](nil-default-regression.json)）。本体ソースのハッシュは測定時と一致し、性能に関わる変更は追加していない。
