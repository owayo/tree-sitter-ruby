mod build_support;

fn main() {
    let src_dir = std::path::Path::new("src");

    let mut c_config = cc::Build::new();
    c_config
        .std("c11")
        .include(src_dir)
        .flag_if_supported("-Wno-unused-value");

    #[cfg(target_env = "msvc")]
    c_config.flag("-utf-8");

    if std::env::var("TARGET").unwrap() == "wasm32-unknown-unknown" {
        let Ok(wasm_headers) = std::env::var("DEP_TREE_SITTER_LANGUAGE_WASM_HEADERS") else {
            panic!("Environment variable DEP_TREE_SITTER_LANGUAGE_WASM_HEADERS must be set by the language crate");
        };
        let Ok(wasm_src) =
            std::env::var("DEP_TREE_SITTER_LANGUAGE_WASM_SRC").map(std::path::PathBuf::from)
        else {
            panic!("Environment variable DEP_TREE_SITTER_LANGUAGE_WASM_SRC must be set by the language crate");
        };

        c_config.include(&wasm_headers);
        c_config.files([
            wasm_src.join("stdio.c"),
            wasm_src.join("stdlib.c"),
            wasm_src.join("string.c"),
            wasm_src.join("wctype.c"),
        ]);
    }

    let parser_source_path = src_dir.join("parser.c");
    println!(
        "cargo:rerun-if-changed={}",
        parser_source_path.to_str().unwrap()
    );
    println!("cargo:rerun-if-changed=bindings/rust/build_support.rs");

    let parser_path = if std::env::var("OPT_LEVEL").expect("OPT_LEVEL must be set by Cargo") == "0"
    {
        parser_source_path
    } else {
        // 生成器が挿入する最適化の無効化指定は、Cargo の最適化フラグより優先される。
        // 原本は変更せず、ビルド用コピーで既知の無効化指定だけを外す。
        let source = std::fs::read_to_string(&parser_source_path)
            .expect("Failed to read the generated parser source");
        let output_path = std::path::PathBuf::from(
            std::env::var_os("OUT_DIR").expect("OUT_DIR must be set by Cargo"),
        )
        .join("parser-optimized.c");
        std::fs::write(
            &output_path,
            build_support::optimized_parser_source(&source),
        )
        .expect("Failed to write the optimized parser source");
        output_path
    };
    c_config.file(&parser_path);

    let scanner_path = src_dir.join("scanner.c");
    c_config.file(&scanner_path);
    println!("cargo:rerun-if-changed={}", scanner_path.to_str().unwrap());

    c_config.compile("tree-sitter-ruby");
}
