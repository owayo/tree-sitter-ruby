# Ruby parser の新規フルパース比較

通常のライブラリ依存から独立した開発用パッケージ。`ruby-prism` と tree-sitter の
Rust API を使い、入力を読み終えた状態で、ファイルごとのパーサー初期化・
言語設定・木の構築・解放を測る。ASTの構造と提供機能は異なる。
I/O、AST文字列化、クエリ、Ruby VM、CLIの起動時間は含まない。

```powershell
mise exec -- cargo build --release --locked --manifest-path tools/parse-benchmark/Cargo.toml
mise exec -- python tools/parse-benchmark/run.py manifest --source-root C:/temp/source --output docs/benchmarks/<date>
mise exec -- python tools/parse-benchmark/run.py validate --binary tools/parse-benchmark/target/release/ruby-parse-benchmark.exe --source-root C:/temp/source --output docs/benchmarks/<date> --label baseline
mise exec -- python tools/parse-benchmark/run.py bench --binary tools/parse-benchmark/target/release/ruby-parse-benchmark.exe --source-root C:/temp/source --output docs/benchmarks/<date> --label baseline
```

取得先は `ruby_ruby`、`rubocop_rubocop`、`Homebrew_brew`、`rails_rails`、
`mastodon_mastodon` の5ディレクトリ。原本は変更しない。
マニフェストに相対パス・バイト数・SHA256を保存し、`validate` の最初の実行で
両者が受理する `common.jsonl` を固定する。以後の検証で共通集合に新しい失敗が
現れたら終了する。全ノードの種別・フィールド・バイト/行列範囲・named/extra属性の
FNV-1a 64bitハッシュを使って、候補間の木の変化も確認できる。

`bench` は実装ごとに独立したプロセスを起動し、単一スレッドで順番に動かす。
ウォームアップ2回と本測定7回で、実装の順番を反転する。
`--control-binary` に同じコンパイラ・依存で作った変更前の実行ファイルを指定すると、
変更前・候補・Prismの3者を交互に測る。`--reverse 1` で最初の順番を反転できる。
全体は各反復内の5コーパスの合計から中央値を求める。

Windowsでは `GetProcessTimes` のCPU時間、`GetProcessMemoryInfo` のpeak RSSと
peak commitを記録する。commitは仮想アドレス空間のサイズではない。
メモリのpeakは同じ実装の前のコーパス・ウォームアップから累積するため、
コーパス単独のpeakとは解釈しない。プロセスには全入力を読み込む領域も含まれる。
検証は600秒・RSS 6GiBのバッチガード、測定は最初の入力読み込み待ち600秒・以後の応答待ち60秒と
WindowsのRSS/commit 6GiBの監視で終了する。上限超過や異常終了を成功件数に含めない。
Windows以外では現状のCPU値0とmemory値nullは未計測を表す。

正確性は計測区間の外で検証する。Prismは `ruby_prism::parse` の既定オプションで、
Ruby VMの版やshebangの `-n` などの実行時オプションは渡していない。
tree-sitterは入力をUTF-8として読む。版・文字コード・コマンドラインオプションに
依存する受理差は、文法の不具合と区別して記録する。
検証時のファイル別 `ts_ns` / `prism_ns` は初回パースの診断用で、木の解放を含まず、
主比較の所要時間として使わない。

## スキャナーの計測

```powershell
mise exec -- python tools/parse-benchmark/instrument.py C:/temp/new-profile-directory
'0' | & C:/temp/new-profile-directory/harness/target/release/ruby-parse-benchmark.exe serve docs/benchmarks/<date>/common.jsonl C:/temp/source ts
```

Windows/MSVC用。新しいディレクトリへ必要なソースをコピーし、コピーだけに
`scanner_profile.h` の計測を挿入してビルドする。phase 0はscan、1はserialize、
2はdeserialize、3はcreate/destroy。割り当て回数にはmalloc/calloc/reallocを含む。
時計とカウンターの負荷があるため、この実行の時間を性能の最終値に使わない。
`profile` モードでは、manifestとsource-rootに続けて相対パスを渡すと、
tree-sitter loggerのイベント数も計測区間と別に保存できる。

測定結果の例は [2026-10-25の記録](../../docs/benchmarks/2026-10-25/README.md)。

## 関数別の CPU 割合

```powershell
mise exec -- python tools/parse-benchmark/sample_profile.py --binary tools/parse-benchmark/target/release/ruby-parse-benchmark.exe --manifest docs/benchmarks/<date>/common.jsonl --source-root C:/temp/source --rounds 2 --output <profile.json>
```

Windows用。管理者権限の要るWPRを使わず、`serve` の主スレッドを約1ミリ秒ごとに一時停止して
命令位置を読み、隣のPDBで関数名を引く。数えるのは最内の関数だけで、呼び出し先を含む時間ではない。
入力の読み込みと最初の1反復は採取しない。PDBのないntdllなどは最寄りのエクスポート名になるので、
モジュール別の合計で読む。

## reduce の記号別回数

```powershell
& tools/parse-benchmark/target/release/ruby-parse-benchmark.exe reductions <manifest> C:/temp/source
```

ロガー付きで全入力をパースし、reduce の記号別回数（うち子1個の単位reduce）、ロガーのイベント数、
各トークンを処理したときのGLRの版の数を1行のJSONで出す。ロガーの負荷があるので時間の測定には使わない。
`inline` の候補を探すときは、supertype でも `conflicts` の対象でもない隠し規則の単位reduceを見る。

## 揺れのある環境での交互測定

```powershell
mise exec -- python tools/parse-benchmark/paired.py --candidate <候補.exe> --control <対照.exe> --manifest <部分集合.jsonl> --source-root C:/temp/source --pairs 30 --cpu 6 --output <paired.json>
```

デスクトップで他の処理と同居すると、反復ごとの所要時間が数十%揺れ、`bench` の長い反復の
中央値では数%の差を判別できない。候補と対照の `serve` を同じ論理CPUと高い優先度に固定し、
部分集合の1反復ずつを順番を入れ替えながら交互に測る。隣り合う2回の比（候補÷対照）の中央値と、
seedを固定したブートストラップによる中央値の95%区間を保存する。部分集合は共通集合から
一定間隔で抜き出し、5コーパスをすべて含める。Prismとの比較表には `bench` を使う。

## Windows の RSS 監視の比較

変更前の `scripts/corpus_test.py` を別ファイルに保存し、同じ Python・同じ子プロセスで
監視処理だけを交互に11回測る。子プロセスは64 MiBのバッファを保持して待機する。

```powershell
git show 2b400b5:scripts/corpus_test.py | Set-Content -Encoding utf8 $env:TEMP/corpus_baseline.py
mise exec -- python tools/parse-benchmark/rss_benchmark.py --baseline $env:TEMP/corpus_baseline.py --output $env:TEMP/rss-monitor.json
```

1回ずつウォームアップし、wall/CPU時間とRSSの生値、中央値と範囲、取得成功件数を保存する。
旧実装が2秒のコマンド期限で取得不可になった試行も時間の標本に残し、RSSをnullとする。
候補の取得不可は測定失敗にする。さらに候補を200回呼び、測定側のハンドル数を前後で記録する。
これは監視の負荷の比較であり、Rubyのパース速度の測定には含めない。
