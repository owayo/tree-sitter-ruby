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
