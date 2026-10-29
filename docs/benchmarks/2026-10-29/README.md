# 定期点検（2026-10-29）

`origin/master` と `upstream` を取得し、master は同期済みだった。
今回の変更は依存更新とコーパスランナーの監視・終了処理に限る。
文法、scanner、生成パーサー、クエリは変更していない。

## 依存更新

`mise exec -- depup --install --include-pinned` と `biome migrate --write` を実行した。

| 対象 | 変更前 | 変更後 |
|---|---|---|
| Biome | 2.5.15 | 2.6.2 |
| cc | 1.8.0 | 1.9.0 |
| find-msvc-tools（間接依存） | 0.1.14 | 0.1.15 |
| Node.js | 26.12.0 | 26.12.1 |
| pnpm | 12.14.0 | 12.15.0 |
| Python | 3.14.7 | 3.15.1 |

独立した計測ハーネスの Cargo.lock も cc の更新に追従した。
Python の[公式移行ガイド](https://docs.python.org/3.15/whatsnew/3.15.html)を確認し、
ランナーは引き続き Python 3.7 の構文・標準ライブラリ API で実装した。
Python 3.7 実行系でのテストは行っていない。

## 終了処理の修正と共通化

[Issue #23](https://github.com/owayo/tree-sitter-ruby/issues/23)。
`run_with_memory_guard()` はタイムアウト・メモリ超過時しか子を終了せず、
監視中の KeyboardInterrupt や例外では子プロセスとパイプを回収していなかった。
中断時に終了処理が呼ばれる回帰テストが変更前に失敗することを確認した。

`_terminate_and_collect()` にプロセスツリーの終了とパイプの回収を共通化し、
監視中の例外でも実行してから元の例外を伝播する。
回収は10秒、その後の再試行は5秒に制限する。終了処理の OSError などで
元の監視エラーを置き換えないことも検証した。

## Windows の RSS 監視

旧実装は観測ごとに tasklist を起動して CSV を解析していた。
Windows 11 / Python 3.15.1 / MSVC 19.51 の環境で、初回の9標本の中央値は985.981ms。
その後の同じ子プロセスを対象とした比較では、2秒のコマンド期限で取得不可になる試行もあった。

候補は K32GetProcessMemoryInfo を直接呼び、現在の WorkingSetSize を MiB へ変換する。
DWORD と SIZE_T、HANDLE の幅を明示し、成功・失敗時とも開いたハンドルを解放する。
APIの契約は[Microsoftの仕様](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-getprocessmemoryinfo)と
[構造体の定義](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters)で確認した。
POSIXは従来どおりプロセスグループ合計、Windowsは対象PIDのみを監視する。

64 MiB のバッファを保持して待機する同一の子プロセスに対し、各実装を1回ウォームアップしてから
順番を反転して11回ずつ測定した。通常テストには時間制限による性能判定を追加していない。

| 実行 | 旧実装 ms 中央値［最小–最大］ | 候補 ms 中央値［最小–最大］ | 取得成功（旧／候補） |
|---|---:|---:|---:|
| 1 | 2133.225 [2080.241–2310.949] | 0.1405 [0.0647–0.1823] | 0/11 ／ 11/11 |
| 2 | 2173.523 [1247.340–2328.899] | 0.1492 [0.0710–0.2356] | 2/11 ／ 11/11 |

観測処理の待ち時間は両実行とも99.99%以上減った。ただし旧実装の中央値は取得失敗も含む。
正常取得だけを比較したパース速度の改善率ではない。デスクトップ上の他の処理と同居する環境であり、
絶対時間はその負荷も含む。候補を追加で200回呼んだ前後のハンドル数は両実行とも167→167で、
ハンドルの増加はなかった。

[1回目の生データ](rss-monitor.json)、[独立再測定](rss-monitor-repeat.json)、
[再現コマンド](../../../tools/parse-benchmark/README.md#windows-の-rss-監視の比較)。

## 構造・正確性・検証

astro-sight の symbols / calls / refs / sequence / ast と差分を使い、文法の補助関数、
scanner の scan・deserialize、Rust ビルド処理、ランナーの監視・例外・終了経路を確認した。
scanner の長い分岐は状態とトークンの有効性に結び付いており、今回の変更と独立している。
既存の割り当て再利用の不採用記録も踏まえ、追加のパーサー最適化を裏付ける新しい測定はない。
今回採用した性能改善は監視の外部コマンド起動の除去であり、新規フルパースの高速化は主張しない。

- 変更前: Python 143件（1 skip）、Rust Debug 98件成功。
- 変更後: Python 150件（1 skip）、Rust Debug/Release 各98件成功。
- UTF-8指定でMSVCの共有ライブラリを作り、コーパス427件成功。
- Biome、Ruff lint/format、Rust fmt を確認。
- Windows の実API、無効PID、取得失敗時のハンドル解放、現在値とピーク値の区別、
  中断・監視失敗時の終了、期限付き回収の再試行を追加検証した。

5リポジトリの取得元は[snapshots.json](snapshots.json)に保存した。
全実ソース検証は入力作成中の先行起動で不一致となった試行を成功に含めず、
再試行も入力読込中に終了したため未完了。新しい入力集合での全件受理差・Prism性能比較は未確認。
通常のコーパス・Rustの構文、範囲、クエリ、保存状態と増分パースの回帰は上記テストで確認した。
Cバインディングは未変更で、CMake検証は省略した。

ドキュメント工程の指定スクリプト `/Users/owa/GitHub/mac-shell/shell/link_agent.md.sh` は存在せず、
確認できる同等のスクリプトもなかったため実行していない。
CLAUDE.md は `AGENTS.md` という内容の通常ファイルだったため、そのまま保持した。
README の英語版・日本語版と AGENTS.md に監視処理と追加テストを反映した。
