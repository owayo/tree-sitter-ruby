use serde::Deserialize;
use serde_json::json;
use std::{
    env, fs,
    hint::black_box,
    io::{self, BufRead, Write},
    path::Path,
    time::Instant,
};
use tree_sitter::{Parser, Tree};

#[derive(Deserialize)]
struct Entry {
    corpus: String,
    path: String,
    bytes: usize,
}

struct Input {
    entry: Entry,
    source: Vec<u8>,
}

fn load(manifest: &str, root: &str) -> Vec<Input> {
    fs::read_to_string(manifest)
        .unwrap()
        .lines()
        .map(|line| {
            let entry: Entry = serde_json::from_str(line).unwrap();
            let source = fs::read(Path::new(root).join(&entry.corpus).join(&entry.path)).unwrap();
            assert_eq!(source.len(), entry.bytes);
            Input { entry, source }
        })
        .collect()
}

fn parser() -> Parser {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_ruby::LANGUAGE.into())
        .unwrap();
    parser
}

// 匿名ノード、フィールド、バイトと行列の範囲も含め、全木の差を検出する。
fn inspect(tree: &Tree) -> (u64, usize, usize) {
    let mut hash = 14695981039346656037_u64;
    let mut errors = 0;
    let mut missing = 0;
    let mut cursor = tree.walk();
    loop {
        let node = cursor.node();
        errors += usize::from(node.is_error());
        missing += usize::from(node.is_missing());
        let record = format!(
            "{}|{:?}|{}|{}|{:?}|{:?}|{}|{};",
            node.kind(),
            cursor.field_name(),
            node.start_byte(),
            node.end_byte(),
            node.start_position(),
            node.end_position(),
            node.is_named(),
            node.is_extra()
        );
        for byte in record.bytes() {
            hash = (hash ^ u64::from(byte)).wrapping_mul(1099511628211);
        }
        if cursor.goto_first_child() {
            continue;
        }
        loop {
            hash = (hash ^ 255).wrapping_mul(1099511628211);
            if cursor.goto_next_sibling() {
                break;
            }
            if !cursor.goto_parent() {
                return (hash, errors, missing);
            }
        }
    }
}

fn validate(inputs: &[Input]) {
    // 既知の負例も検出できることを、入力の検証前に確認する。
    assert!(parser()
        .parse("def (", None)
        .unwrap()
        .root_node()
        .has_error());
    assert!(ruby_prism::parse(b"def (").errors().next().is_some());
    for input in inputs {
        let start = Instant::now();
        let tree = parser()
            .parse(&input.source, None)
            .expect("parse interrupted");
        let ts_ns = start.elapsed().as_nanos();
        let (hash, errors, missing) = inspect(&tree);
        let start = Instant::now();
        let result = ruby_prism::parse(&input.source);
        let prism_ns = start.elapsed().as_nanos();
        let diagnostics: Vec<_> = result
            .errors()
            .map(|e| String::from_utf8_lossy(e.message()).into_owned())
            .collect();
        println!(
            "{}",
            json!({"corpus":input.entry.corpus,"path":input.entry.path,"bytes":input.source.len(),"ts_errors":errors,"ts_missing":missing,"tree_hash":format!("{hash:016x}"),"prism_errors":diagnostics,"ts_ns":ts_ns,"prism_ns":prism_ns})
        );
    }
}

#[cfg(windows)]
mod process {
    use std::ffi::c_void;
    #[repr(C)]
    #[derive(Default)]
    struct Counters {
        cb: u32,
        faults: u32,
        peak_rss: usize,
        rss: usize,
        peak_paged: usize,
        paged: usize,
        peak_nonpaged: usize,
        nonpaged: usize,
        pagefile: usize,
        peak_pagefile: usize,
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentProcess() -> *mut c_void;
        fn GetProcessTimes(
            process: *mut c_void,
            creation: *mut u64,
            exit: *mut u64,
            kernel: *mut u64,
            user: *mut u64,
        ) -> i32;
    }
    #[link(name = "psapi")]
    extern "system" {
        fn GetProcessMemoryInfo(process: *mut c_void, counters: *mut Counters, size: u32) -> i32;
    }
    pub fn cpu_ns() -> u64 {
        let (mut c, mut e, mut k, mut u) = (0, 0, 0, 0);
        assert_ne!(
            unsafe { GetProcessTimes(GetCurrentProcess(), &mut c, &mut e, &mut k, &mut u) },
            0
        );
        (k + u) * 100
    }
    pub fn memory() -> serde_json::Value {
        let mut counters = Counters {
            cb: std::mem::size_of::<Counters>() as u32,
            ..Default::default()
        };
        assert_ne!(
            unsafe { GetProcessMemoryInfo(GetCurrentProcess(), &mut counters, counters.cb) },
            0
        );
        serde_json::json!({"peak_rss_bytes":counters.peak_rss,"peak_commit_bytes":counters.peak_pagefile})
    }
}

#[cfg(not(windows))]
mod process {
    pub fn cpu_ns() -> u64 {
        0
    }
    pub fn memory() -> serde_json::Value {
        serde_json::Value::Null
    }
}

fn bench(inputs: &[Input], engine: &str, round: usize) {
    for corpus in [
        "rails_rails",
        "ruby_ruby",
        "rubocop_rubocop",
        "Homebrew_brew",
        "mastodon_mastodon",
    ] {
        let selected: Vec<_> = inputs.iter().filter(|i| i.entry.corpus == corpus).collect();
        assert!(!selected.is_empty());
        let cpu = process::cpu_ns();
        let start = Instant::now();
        for input in &selected {
            match engine {
                "ts" => {
                    let tree = parser()
                        .parse(black_box(&input.source), None)
                        .expect("parse interrupted");
                    black_box(tree.root_node().kind_id());
                    drop(tree);
                }
                "prism" => {
                    let tree = ruby_prism::parse(black_box(&input.source));
                    black_box(tree.node());
                    drop(tree);
                }
                _ => panic!("unknown engine"),
            }
        }
        let elapsed = start.elapsed().as_nanos();
        let cpu = process::cpu_ns() - cpu;
        println!(
            "{}",
            json!({"engine":engine,"round":round,"corpus":corpus,"files":selected.len(),"bytes":selected.iter().map(|i|i.source.len()).sum::<usize>(),"wall_ns":elapsed,"cpu_ns":cpu,"memory":process::memory()})
        );
    }
    io::stdout().flush().unwrap();
}

fn profile(inputs: &[Input], path: &str) {
    let input = inputs.iter().find(|i| i.entry.path == path).unwrap();
    let mut parser = parser();
    let counts = std::sync::Arc::new(std::sync::Mutex::new(std::collections::BTreeMap::new()));
    let logged_counts = counts.clone();
    parser.set_logger(Some(Box::new(move |kind, message| {
        let key = format!(
            "{kind:?}:{}",
            message.split_whitespace().next().unwrap_or("")
        );
        *logged_counts.lock().unwrap().entry(key).or_insert(0_u64) += 1;
    })));
    let tree = parser.parse(&input.source, None).unwrap();
    black_box(tree.root_node());
    drop(parser);
    println!("{}", json!({"path":path,"events":*counts.lock().unwrap()}));
}

fn main() {
    let args: Vec<_> = env::args().collect();
    assert!(
        args.len() >= 4,
        "MODE MANIFEST SOURCE_ROOT [ENGINE|PROFILE_PATH]"
    );
    let inputs = load(&args[2], &args[3]);
    assert!(!inputs.is_empty());
    match args[1].as_str() {
        "validate" => validate(&inputs),
        "profile" => profile(&inputs, &args[4]),
        // 別プロセスを起動したまま反復指示を待ち、実装の測定順を交互にできる。
        "serve" => {
            for line in io::stdin().lock().lines() {
                let line = line.unwrap();
                let round: usize = line.parse().unwrap();
                bench(&inputs, &args[4], round);
                println!("DONE");
                io::stdout().flush().unwrap();
            }
        }
        _ => panic!("unknown mode"),
    }
}
