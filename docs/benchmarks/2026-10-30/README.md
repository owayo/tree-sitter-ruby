# 定期点検と新規フルパースの測定（2026-10-30）

新規フルパースで最新安定版Prismを上回る目標は未達。今回は関数別のCPU割合を初めて測り、
その結果から、実行時に作る見えない部分木を文法の `inline` で減らした。見える木と
`src/node-types.json` は変えていない。同じ論理CPUで交互に測った比では、変更前より約3〜4%速い。
最終候補は scanner とランナーの整理、`inline`、[#24](https://github.com/owayo/tree-sitter-ruby/issues/24) の
修正（保存できない長さの heredoc 終端語。実ソースに該当する入力はない）を含む。

## 主比較

Windows 11 / Ryzen 7 5700X / Rust 1.99.1 / MSVC 19.51.36260 / tree-sitter 0.27.1 /
ruby-prism 2.0.0（[environment.json](environment.json)）。ruby-prism 2.1.0 は2026-10-28公開で、
depupの公開から1週間の条件を満たさないため使っていない。
単一スレッドで入力読込後に、新しいParserの作成・言語設定・parse(None)・木とParserの解放を測る。
Prismは公開Rust APIのparseとParseResultの解放。I/O、AST出力、クエリ、VM起動は除く。
ウォームアップ2回、本測定7回。実装ごとの独立プロセスを交互に動かし、中央値［最小–最大］を示す。
全体は同じ反復内の5コーパスの合計から中央値を求める。

| コーパス | 件数 | バイト数 | Prism ms（範囲） | tree-sitter ms（範囲） | Prism/TS |
|---|---:|---:|---:|---:|---:|
| Rails | 3,481 | 20,011,502 | 204.393 [174.603–405.264] | 3126.046 [2845.781–6228.623] | 0.0654 |
| Ruby | 7,480 | 36,165,003 | 406.229 [388.464–800.066] | 7243.782 [6324.487–13260.486] | 0.0561 |
| RuboCop | 1,791 | 11,624,842 | 97.200 [85.682–174.849] | 1159.100 [1045.517–1618.507] | 0.0839 |
| Homebrew | 2,407 | 13,575,237 | 151.381 [138.107–228.735] | 2234.169 [2088.687–3140.624] | 0.0678 |
| Mastodon | 3,355 | 6,069,022 | 71.402 [63.656–115.726] | 1010.398 [948.143–1483.045] | 0.0707 |
| 合計 | 18,514 | 87,445,606 | 913.301 [870.940–1713.570] | 14731.034 [13358.444–25466.858] | 0.0620 |

倍率はPrism中央値÷TS中央値で、1超がTS優位。全体0.0620、全体のTSスループットは5.661 MiB/s。
この実行でも他の処理との同居で反復全体の時間が揺れた（TSの合計13.4〜25.5秒）。反復ごとの
Prism/TSは0.059〜0.074で、両者は同じように遅くなっている。同じ実行で交互に測った変更前（`control`）の
全体中央値は18755.487 ms［13710.479–23061.546］だが、同じ反復どうしの比が0.77〜1.10とばらつくため、
中央値の比0.785を改善率には使わない。改善率は次の交互測定で求めた。

## 交互測定

`bench` の1回目（[inline-run1-summary.json](inline-run1-summary.json)）では、同じ実装でも
反復ごとの5コーパスの合計が13.6〜20.6秒と揺れ、CPU時間も同じだけ増えた。デスクトップで
他の処理と同居したためで、長い反復の中央値では数%の差を判別できなかった。
そこで [paired.py](../../../tools/parse-benchmark/paired.py) で、候補と対照の `serve` を同じ論理CPUと
高い優先度に固定し、共通集合の4件に1件（約4,630件、5コーパスを含む）を1反復ずつ順番を
入れ替えながら交互に測った。比は候補÷対照で、1未満が候補の高速を表す。

| 比較 | 論理CPU | 部分集合 | 組 | 比の中央値 | 95%区間（ブートストラップ） | 候補が速い組 |
|---|---:|---|---:|---:|---|---:|
| `inline` 追加 ÷ 整理のみ | 6 | 0行目から4行ごと（4,629件） | 30 | 0.9684 | 0.9533–0.9861 | 25 |
| `inline` 追加 ÷ 整理のみ（独立した再測定） | 10 | 2行目から4行ごと（4,628件） | 30 | 0.9643 | 0.9519–0.9689 | 27 |
| 最終候補 ÷ 変更前 | 6 | 0行目から4行ごと（4,629件） | 30 | 0.9592 | 0.9379–0.9763 | 22 |

2回の独立した測定で区間が1を含まず、`inline` による高速化を採用した。
最終候補と変更前の比は外乱が大きく（0.85〜1.28）、区間も広い。
生データは [paired-inline-1.json](paired-inline-1.json)、[paired-inline-2.json](paired-inline-2.json)、
[paired-final.json](paired-final.json)。

## CPUの内訳

[sample_profile.py](../../../tools/parse-benchmark/sample_profile.py) で、管理者権限の要るWPRを使わずに
`serve` の主スレッドを約1ミリ秒ごとに止め、命令位置を関数名に引いた。共通集合の2反復分で、
数えるのは最内の関数だけである。変更前の採取は、このスクリプトにまとめる前の同じ方法の試作で行い、
上位80関数を保存した（変更後は上位100関数）。

| 関数 | 変更前 | 最終候補 |
|---|---:|---:|
| `stack_node_new` | 9.19% | 9.29% |
| `ts_subtree_new_node` | 7.41% | 7.30% |
| `stack__iter` | 7.08% | 6.64% |
| `ts_language_lookup` | 6.56% | 6.42% |
| ntdll（`RtlSizeHeap` の位置、ヒープ） | 6.38% | 6.78% |
| `ts_subtree_release` | 5.54% | 5.54% |
| `ts_subtree_summarize_children` | 5.09% | 5.16% |
| `ts_parser__advance` | 4.38% | 4.52% |
| `ts_lexer__advance` | 3.61% | 4.07% |
| `ts_parser__lex` | 3.59% | 3.66% |
| `ts_parser__reduce` | 3.31% | 3.30% |
| `ts_parser__balance_subtree` | 3.31% | 3.00% |
| `ts_stack__add_version` | 2.46% | 2.00% |
| 外部scannerの関数の合計 | 4.07% | 4.17% |
| 標本数（2反復） | 20,228 | 19,019 |

変更前は scanner とランナーの整理だけを入れた候補で、文法は変更前と同じである。
reduce の減少は割り当てとスタック操作をほぼ同じ割合で減らすため、関数ごとの比率はほとんど変わらない。

モジュール別では、変更前の実行ファイルが84.71%、ntdll（ヒープ）が12.55%、VCRUNTIME140が1.58%、
ucrtbaseが1.16%だった。外部scannerの関数は合計4.07%で、scannerを速くしても全体は数%しか縮まない。
大半はtree-sitter実行系のGLRスタック、部分木の生成・解放、パーステーブルの参照、ヒープ操作にある。
ntdllはPDBがなく、関数名は最寄りのエクスポート名になるため、モジュールの合計で読む。
生データは [profile-before.json](profile-before.json)、[profile-after.json](profile-after.json)。

## reduceの内訳と `inline`

ハーネスの `reductions` モードで、共通集合18,514件のreduceを記号別に数えた。
トークン1つあたり約2.4回のreduceがあり、その74%は子1個の単位reduceである。
supertypeの隠しノード（`_primary` 12.33%、`_arg` 10.51%、`_expression` 9.59% など）は
クエリのsupertype照合に使うため残す。supertypeでも `conflicts` の対象でもない隠し規則6つを
`inline` にし、その単位reduceを無くした。

| 記号 | 変更前 | 最終候補 |
|---|---:|---:|
| `_terminator` | 1,525,276 | 0 |
| `_literal` | 594,233 | 0 |
| `_numeric` | 384,416 | 0 |
| `_simple_formal_parameter` | 124,657 | 0 |
| `_formal_parameter` | 122,974 | 0 |
| `_function_identifier` | 102,806 | 0 |
| reduce 合計 | 35,811,103 | 32,956,741（−7.97%） |
| shift | 14,704,730 | 14,704,730 |
| 複数のGLRの版で処理した割合 | 10.42% | 10.42% |

他の記号のreduce回数は1回も変わっていない。状態数は9,135から9,337、大きい表の状態は3,462から3,552、
記号は380から374、parser.cは25,654,077から26,163,506バイトになった。
生データは [reductions-before.json](reductions-before.json)、[reductions-after.json](reductions-after.json)。

## 試した候補と採否

1. `inline` の6規則: 採用。全18,520件の木のハッシュ、`node-types.json`、テストが変わらず、
   2回の交互測定で約3%速い。
2. 他の隠し規則: `_argument`・`_bare_call_method`・`_assignment_lhs`・`_index_assignment_argument` は
   `conflicts` の対象で inline にできない。`_literal_contents` は `bare_string` / `bare_symbol` の別名で
   見えるノードを作る。優先順位を持つ `_call` などと、`_statements` などの繰り返しは対象外とした。
3. GLR: トークンの約10%を複数の版で処理する。変数と裸の呼び出し、代入の左辺などの宣言済みの
   衝突によるもので、ローカル変数の束縛を解決しない文法では減らせない。
4. scanner: 外部scannerは合計4.07%で律速ではない。2026-10-25に不採用とした状態復元の配列再利用は
   再試行していない。
5. 残る差: Prismとの差は、tree-sitter実行系の汎用的なGLR・部分木の割り当て・パーステーブルの
   線形探索によるもので、文法側で縮められる余地は小さい。実行系の変更や割り当て器の差し替えは
   利用側の選択であり、この比較では行っていない。

## 正確性

5リポジトリ（[snapshots.json](snapshots.json)、SHAは2026-10-29と同じ）の全18,520件を、変更前・
scannerとランナーの整理後・`inline` 追加後・最終候補で検証した。匿名ノードを含む種別・フィールド・
バイト/行列範囲・named/extra属性のハッシュ、ERROR/MISSINGの件数、Prismの診断はすべて一致した。
tree-sitterの失敗は既知の5件、Prismの診断は3件で、共通集合は18,514件（[common.jsonl](common.jsonl)）。
入力の相対パス・サイズ・SHA256は [manifest.jsonl](manifest.jsonl)、検証の生データは
`*-validation.jsonl.gz`、集計は `*-validation-summary.json`。

## 生データ

- 主比較: `final-timings.jsonl`、`final-summary.json`（`control` は変更前、`ts` は最終候補）。
- 揺れの記録: `inline-run1-timings.jsonl`、`inline-run1-summary.json`（判定に使っていない）。
- 交互測定・CPUの内訳・reduceの内訳: 上の各節に記載。
- 部分集合は共通集合から上表の規則で作り直せるため保存していない。
