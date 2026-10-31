# 2026-10-31 通常リテラルの部分木構築を減らす

通常の文字列・正規表現・区切りシンボル・サブシェルで、先頭の内容を親へ直接展開した。
全18,532件のノード種別・フィールド・範囲・named/extra属性と診断を維持し、同条件の新規フルパースは
全体で **1.96%** 短くなった。Prismを上回る目標は未達である。
[Issue #39](https://github.com/owayo/tree-sitter-ruby/issues/39)として対応する。

## 最終候補と最新安定版Prism

Windows 11 Home 10.0.26300、Ryzen 7 5700X、Rust 1.99.1、MSVC 19.51.36260。
tree-sitter 0.27.1とruby-prism / ruby-prism-sys / Prism C 2.1.0を使用する。
2026-10-31に[crates.io](https://crates.io/crates/ruby-prism)と
[公式リリース](https://github.com/ruby/prism/releases/tag/v2.1.0)で最新安定版を確認した。

単一スレッドのRust公開APIで、入力を読み込んでからファイルごとに新しいパーサーを作る。
初期化・言語設定・木の構築と解放を含み、I/O・AST出力・クエリ・Ruby VM起動を除く。
両者のASTと提供機能は異なる。両C実装は-O2で、生成器の最適化無効化pragmaはOUT_DIRのコピーだけから外す。
実際の引数とコピーを[build-evidence.json](build-evidence.json)で検証した。
独自allocator、LTO、CPU固有の追加フラグは使っていない。

2回のウォームアップ後、候補・Prism・変更前対照の順を反転しながら7回測定した。中央値 [最小–最大]。
全体は各反復の5コーパスの合計から中央値を求める。倍率はPrism/TSで、1超がTSの高速を表す。

| Corpus   |  Files |      Bytes |          Prism ms (range) |          tree-sitter ms (range) | Prism/TS |
| -------- | -----: | ---------: | ------------------------: | ------------------------------: | -------: |
| Rails    |  3,481 | 20,022,696 | 170.851 [169.695–174.829] |    2530.314 [2474.366–2579.083] |   0.0675 |
| Ruby     |  7,480 | 36,175,846 | 359.221 [347.777–368.527] |    5916.550 [5781.003–6151.738] |   0.0607 |
| RuboCop  |  1,791 | 11,643,866 |    81.142 [79.074–82.147] |      996.910 [980.813–1015.842] |   0.0814 |
| Homebrew |  2,419 | 13,716,704 | 133.361 [131.814–134.281] |    1903.197 [1883.248–1955.418] |   0.0701 |
| Mastodon |  3,355 |  6,072,014 |    61.210 [59.023–62.172] |       860.751 [853.153–874.765] |   0.0711 |
| Total    | 18,526 | 87,631,126 | 807.844 [788.222–817.093] | 12151.275 [12015.206–12496.597] |   0.0665 |

全体の倍率は0.0665で、目標は未達。最終候補の処理速度は
6.878 MiB/s、
Prismは103.450 MiB/sだった。
再利用・増分パース・I/O込みの速度は測定していない。増分パースは正確性のテストで検証した。

## 変更前との比較と独立した再測定

| Corpus   | Control ms |   Final ms | Time reduction |
| -------- | ---------: | ---------: | -------------: |
| Rails    |   2518.139 |  2530.314  |         -0.48% |
| Ruby     |   6008.761 |  5916.550  |          1.53% |
| RuboCop  |   1004.532 |   996.910  |          0.76% |
| Homebrew |   1943.201 |  1903.197  |          2.06% |
| Mastodon |    864.252 |   860.751  |          0.41% |
| Total    |  12394.237 | 12151.275  |          1.96% |

最終全件測定のRailsは約0.5%長く、範囲が重なる。全コーパスで一律に速いとは扱わない。
初回の全件測定は全体12.629→12.296秒（2.64%短縮）で、trial-full-*.jsonに保存した。
最終表には再ビルド後の独立した測定を使い、異なる測定の最速値を混ぜていない。

デスクトップの外乱を減らすため、同じ論理CPUと高い優先度で候補と対照を短く交互に測った。
共通集合の0行目/2行目から4行ごとに選んだ別の部分集合で、各30組、順序を反転した。
比は候補/対照。中央値のbootstrap 95%区間はseed 20261030、5,000回。

| CPU |  件数 | 比の中央値 | 95%区間           | 候補が速い組 |
| --: | ----: | ---------: | ----------------- | -----------: |
|   6 | 4,632 |   0.974183 | 0.956051–0.988619 |        24/30 |
|  10 | 4,631 |   0.976320 | 0.970226–0.980577 |        26/30 |

2回とも区間が1を含まず、2.58%・2.37%の短縮を再現した。生データはpaired-first-tail*.json、入力はsample*.jsonl。
初回試作と最終exeはSHA256が異なるが、差はビルド時刻とCodeView情報の24バイトだけで、
命令・データ・巻き戻し情報・再配置の各セクションは一致する
（[binary-equivalence.json](binary-equivalence.json)、[pe-sections.json](pe-sections.json)）。
最終exeでも全件を検証・再測定した。計測中に本作業のビルド・テスト・プロファイラーは動かしていない。

| 実装        |    CPU ms | peak RSS MiB | peak commit MiB |
| ----------- | --------: | -----------: | --------------: |
| 最終候補    | 12140.625 |      232.895 |         236.559 |
| 変更前      | 12296.875 |      239.887 |         243.609 |
| Prism 2.1.0 |   812.500 |      108.164 |         113.320 |

CPU時間は各反復の合計の中央値。メモリは実装別の独立プロセスで取得した累積peakで、入力保持・ウォームアップ・
以前のコーパスを含む。commitは仮想アドレス空間の大きさではない。入力読込待ち600秒、以後の応答待ち60秒、
RSS/commit 6 GiBの上限を設け、中断・超過・異常終了はなかった。各値はfinal-timings.jsonlを参照する。

## 律速・仮説・採否

変更前のCPUプロファイルでは、GLRスタック、部分木の割当・解放、parse table参照、ヒープ操作が主負荷だった。
通常リテラルが1つのstring_contentだけの場合にも、\_literal_contentsの単位reduceで中間の部分木を作っていた。
単にrepeat1をinline化する案と、別名用/通常用を分けてもrepeat1を維持する案は、生成器が同じ繰り返しを再構成し、
579件のreduceは840,255のままだったため不採用とした。

採用案は通常用だけをseq(最初の要素, repeat(残りの要素))としてinline化する。1要素だけなら中間部分木が要らない。
%w/%iのbare_string/bare_symbolは既存の別名付き規則を維持する。supertype、conflict対象、優先順位付きの規則はinlineにしない。

全18,526件のロガー付き集計（時間の測定には使わない）:

| 指標                   |     変更前 |   最終候補 |
| ---------------------- | ---------: | ---------: |
| reduce合計             | 33,051,713 | 32,159,934 |
| shift                  | 14,770,394 | 14,770,394 |
| _literal_contents      |  1,216,331 |     26,485 |
| 通常用の残りの繰り返し |          0 |    298,067 |

reduce合計は2.70%減った。
579件の最小試行でも840,255→818,358で、削減する操作と実測の改善が対応した。
優先順位や意味を変える整理は行わず、重複した大きなリファクタリングも加えていない。

| 関数（最内の命令位置）        | 変更前 | 最終候補 |
| ----------------------------- | -----: | -------: |
| stack_node_new                | 10.63% |    9.20% |
| ts_subtree_new_node           |  7.48% |    7.35% |
| stack__iter                   |  6.84% |    7.03% |
| ts_language_lookup            |  6.36% |    6.65% |
| ts_subtree_release            |  4.89% |    5.18% |
| ts_subtree_summarize_children |  4.69% |    5.47% |

profile-before.json / profile-after.jsonはウォームアップ後の2反復の命令位置を約1msごとに採取した。
最内の関数だけで、PDBのないntdllの関数名は最寄りのexportになる。採取用の時間は主比較に使わない。
残る主負荷は汎用のGLR・部分木管理・table参照にある。Prismの参照ソース37d2d0dのarenaによる割当と一括解放を確認したが、
計測するcrateは公開タグca15cb3由来で同一HEADとは扱わない。増分パースで共有する部分木の管理を持つTS runtimeの変更や、
allocatorの差し替えまで作業範囲を広げていない。

生成物は手編集していない。状態数9,361→9,415、large stateは3,556のまま、記号377→378、production ID 161→164。
parser.cは26,191,107→26,238,906バイト（0.18%増）、exeは4,474,880→4,487,680バイト。
サイズの変化を速度の根拠には使わない。node-types.jsonは1バイトも変わっていない。

## 入力と正確性・構文確認

取得済み5リポジトリの全18,532件を使用し、原本を変更・再取得していない。HEADと.source_shaは一致、全作業ツリーがclean。
各SHAはsnapshots.json、相対パス・バイト数・SHA256はmanifest.jsonl、共通集合18,526件はcommon.jsonlに固定した。
最終確認でも全ファイルの列挙・サイズ・ハッシュ・リポジトリ状態が一致した（inputs-rehashed.json）。

| Corpus   |  全.rb | TS失敗 | Prism診断あり | 共通集合 | 新しい失敗 |
| -------- | -----: | -----: | ------------: | -------: | ---------: |
| Rails    |  3,481 |      0 |             0 |    3,481 |          0 |
| Ruby     |  7,486 |      5 |             3 |    7,480 |          0 |
| RuboCop  |  1,791 |      0 |             0 |    1,791 |          0 |
| Homebrew |  2,419 |      0 |             0 |    2,419 |          0 |
| Mastodon |  3,355 |      0 |             0 |    3,355 |          0 |
| 合計     | 18,532 |      5 |             3 |   18,526 |          0 |

変更前/試作/最終候補で、匿名ノードを含む全ノードの種別・フィールド・バイト/行列範囲・named/extra属性のFNVハッシュと、
ERROR/MISSING・Prism診断が全件一致した。構文を削ったり、新しい失敗を比較集合から外したりしていない。
既知の除外6件は意図的な負例2件、UTF-16入力2件、束縛依存のsample/trick2018/04-colin/entry.rb、
shebangの-nが必要なtool/fetch-bundled_gems.rb。詳細はacceptance-differences.json。
TSはUTF-8、Prismは既定APIで、Ruby VMの実行オプションは渡していない。

[Ruby 4.1の公式NEWS](https://docs.ruby-lang.org/en/master/NEWS_md.html)とPrismの最新リリースを確認した。
今回追加の構文修正は必要なく、Ruby 3.4のit/index assignment、4.0の*nil・行頭論理演算子、4.1の仮引数末尾カンマ等は
既存コーパス・Rustテスト・全実ソースで回帰確認した。Sonicopに由来する構文不具合や木/captureの差はなく、追加の差分計測は行っていない。

## 検証と依存・Issue対応

- コーパス432件、Rust debug/release各109件（doctestを含む）、Python165件（既定の1件skip）が成功。
- リテラルの直接の子・範囲、%W/%Iの別名、Unicode/CRLFを含む8回の置換×6種の増分編集を3件のRustテストに追加。
- 既存のクエリcapture、heredoc、scanner保存状態、境界と増分パースの検証も成功。scannerと保存形式は変更していない。
- lint、Ruff check/format、cargo fmt、git diff --check、astro-sight review/impactが成功。API変更・未解決の呼出し影響はない。
- tree-sitter testは実行していない。構文用DLLはMSVC /Odで新しく作り、絶対パスでCLIへ指定した。
- Cバインディングは未変更。CMakeがないためローカル再実行は省略し、Unix CIの既存検査で確認する。

mise install / pnpm install後、depup --install --include-pinnedは更新0・skip14。
Prism 2.1.0がすでにlock済みだがageフィルターより新しいため終了1となり、後退させずに最新安定版を維持した。
コンパイラ・runtime・依存版は高速化の前後で同じである。

リリース後に2つのCargo.lockの自パッケージ版が旧版のままになる不具合も再現し、
[Issue #38](https://github.com/owayo/tree-sitter-ruby/issues/38)・[PR #40](https://github.com/owayo/tree-sitter-ruby/pull/40)で先に修正した。
依存版を動かさずに同期し、Release workflowへ組み込み、将来のリリースコミットにも日本語のConventional Commits件名と詳細本文を付ける。
回帰テストは変更前に両lockで失敗し、修正後に成功。Windows/Linux/macOSのCI成功とマージ・クローズを確認した（756a95a）。

## 生データと再現

final-*.json/jsonlとbaseline/final-validation.jsonl.gzが最終候補の記録。試作の全件値はtrial-full-*で分けた。
environment.jsonにソース・依存・バイナリSHA、build-evidence.jsonにC最適化の実体、verification.jsonに検証件数を記録した。
file-diagnostics.jsonはサイズ層別の単回の中央値/p95で、木の解放を含まない診断用。主比較の速度の根拠には使わない。
[ハーネス](../../../tools/parse-benchmark/README.md)をReleaseでビルドし、保存したmanifest/commonを使う。

```powershell
mise exec -- cargo build --release --locked --manifest-path tools/parse-benchmark/Cargo.toml
mise exec -- python tools/parse-benchmark/run.py validate --binary <candidate.exe> --source-root <source-root> --output <record-directory> --label reproduced
mise exec -- python tools/parse-benchmark/run.py bench --binary <candidate.exe> --control-binary <control.exe> --source-root <source-root> --output <record-directory> --label reproduced
```
