use std::ffi::{c_char, c_void};

extern "C" {
    fn tree_sitter_ruby_external_scanner_create() -> *mut c_void;
    fn tree_sitter_ruby_external_scanner_destroy(scanner: *mut c_void);
    fn tree_sitter_ruby_external_scanner_serialize(
        scanner: *mut c_void,
        buffer: *mut c_char,
    ) -> u32;
    fn tree_sitter_ruby_external_scanner_deserialize(
        scanner: *mut c_void,
        buffer: *const c_char,
        length: u32,
    );
}

struct Scanner(*mut c_void);

impl Scanner {
    fn new() -> Self {
        // 文法クレートをリンクし、外部スキャナーの C シンボルを利用可能にする。
        let _: tree_sitter::Language = tree_sitter_ruby::LANGUAGE.into();
        Self(unsafe { tree_sitter_ruby_external_scanner_create() })
    }

    fn restore(&mut self, bytes: &[u8]) {
        // C 側には、指定した長さ以上の読み取り可能なバッファを渡す。
        unsafe {
            tree_sitter_ruby_external_scanner_deserialize(
                self.0,
                bytes.as_ptr().cast(),
                bytes.len() as u32,
            );
        }
    }

    fn save(&self) -> Vec<u8> {
        let mut bytes = [0u8; 1024];
        let length = unsafe {
            tree_sitter_ruby_external_scanner_serialize(self.0, bytes.as_mut_ptr().cast())
        } as usize;
        assert!(length <= bytes.len());
        bytes[..length].to_vec()
    }
}

impl Drop for Scanner {
    fn drop(&mut self) {
        unsafe { tree_sitter_ruby_external_scanner_destroy(self.0) };
    }
}

fn heredoc_state(word: &[u8], flags: u8) -> Vec<u8> {
    heredocs_state(&[(word, flags)])
}

fn heredocs_state(heredocs: &[(&[u8], u8)]) -> Vec<u8> {
    let mut bytes = vec![0, heredocs.len() as u8];
    for (word, flags) in heredocs {
        bytes.extend_from_slice(&[1, 1, *flags]);
        bytes.extend_from_slice(&(word.len() as u32).to_ne_bytes());
        bytes.extend_from_slice(word);
    }
    bytes
}

#[test]
fn round_trip_preserves_empty_unicode_and_pending_terminators() {
    let mut scanner = Scanner::new();
    let mut literal_state = vec![1, 3, b'"', b'"'];
    literal_state.extend_from_slice(&1u32.to_ne_bytes());
    literal_state.extend_from_slice(&[1, 0]);
    for state in [
        vec![0, 0],
        literal_state,
        heredoc_state(b"", 1),
        heredoc_state("終端".as_bytes(), 3),
        heredoc_state(&vec![b'A'; 1015], 3),
        // 開始済みの本文の行で開いた段 (bit 2) と、その中の開始済みの段を保つ。
        heredocs_state(&[(b"A", 1), (b"B", 0), (b"C", 5), (b"D", 0), (b"E", 4)]),
        // 行継続で終わる行で開いた段の先頭の印 (bit 3) は、開始前の段の先頭にも付く。
        heredocs_state(&[(b"A", 9), (b"B", 0)]),
        heredocs_state(&[(b"B", 8)]),
        heredocs_state(&[(b"A", 1), (b"C", 13)]),
    ] {
        scanner.restore(&state);
        assert_eq!(scanner.save(), state);
    }
}

#[test]
fn truncated_and_trailing_buffers_discard_partial_state() {
    let state = heredoc_state(b"EOS", 3);
    let mut scanner = Scanner::new();
    for length in 0..state.len() {
        scanner.restore(&state);
        scanner.restore(&state[..length]);
        assert_eq!(scanner.save(), [0, 0], "prefix length: {length}");
    }
    let mut trailing = state.clone();
    trailing.push(0);
    scanner.restore(&trailing);
    assert_eq!(scanner.save(), [0, 0]);
    scanner.restore(&[0, 0, 1]);
    assert_eq!(scanner.save(), [0, 0]);

    // 完全な 1 件目を復元した後に 2 件目が途切れても、1 件目を残さない。
    let mut partial_second = state;
    partial_second[1] = 2;
    scanner.restore(&partial_second);
    assert_eq!(scanner.save(), [0, 0]);
}

#[test]
fn invalid_heredoc_frames_discard_state() {
    let mut scanner = Scanner::new();
    for state in [
        // 未使用のフラグ、index 0 の段の印、未開始の本文の終端行の保留
        heredoc_state(b"A", 16),
        heredoc_state(b"A", 128),
        heredoc_state(b"A", 4),
        heredoc_state(b"A", 2),
        // 段の先頭でない開始済みの heredoc と、段の先頭でない行継続の印
        heredocs_state(&[(b"A", 1), (b"B", 1)]),
        heredocs_state(&[(b"A", 9), (b"B", 8)]),
        // 未開始の本文の中で開いた段
        heredocs_state(&[(b"A", 0), (b"C", 4)]),
        heredocs_state(&[(b"A", 1), (b"C", 4), (b"E", 4)]),
    ] {
        scanner.restore(&heredoc_state(b"EOS", 3));
        scanner.restore(&state);
        assert_eq!(scanner.save(), [0, 0], "{state:?}");
    }
}

#[test]
fn oversized_word_length_does_not_overflow_bounds_check() {
    let mut bytes = vec![0, 1, 0, 1, 1];
    bytes.extend_from_slice(&u32::MAX.to_ne_bytes());
    let mut scanner = Scanner::new();
    scanner.restore(&bytes);
    assert_eq!(scanner.save(), [0, 0]);
}

#[test]
fn repeated_restore_discards_old_words_and_partial_literals() {
    let mut scanner = Scanner::new();
    let mut literals = vec![2];
    for _ in 0..2 {
        literals.extend_from_slice(&[3, b'"', b'"']);
        literals.extend_from_slice(&1u32.to_ne_bytes());
        literals.push(1);
    }
    literals.push(0);
    let long_word = vec![b'A'; 1015];
    let states = [
        literals.clone(),
        heredoc_state(&long_word, 1),
        heredocs_state(&[("終端".as_bytes(), 1), (b"B", 0), (b"C", 5)]),
        heredoc_state(b"", 1),
        vec![0, 0],
    ];
    // 以前の長い終端語や復元途中のリテラルを、次の状態に残さない。
    for _ in 0..100 {
        for state in &states {
            scanner.restore(state);
            assert_eq!(scanner.save(), *state);
            scanner.restore(&literals[..literals.len() - 2]);
            assert_eq!(scanner.save(), [0, 0]);
            scanner.restore(state);
            assert_eq!(scanner.save(), *state);
        }
    }
}
