/// 既知の生成器が挿入する最適化の無効化指定だけをビルド用コピーから外す。
pub fn optimized_parser_source(source: &str) -> String {
    source
        .split_inclusive('\n')
        .filter(|line| {
            !matches!(
                line.trim(),
                "#pragma optimize(\"\", off)"
                    | "#pragma clang optimize off"
                    | "#pragma GCC optimize (\"O0\")"
                    | "#pragma GCC optimize (\"O0\", \"jump-tables\")"
            )
        })
        .collect()
}
