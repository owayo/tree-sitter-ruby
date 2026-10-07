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
    let mut bytes = vec![0, 1, 1, 1, flags];
    bytes.extend_from_slice(&(word.len() as u32).to_ne_bytes());
    bytes.extend_from_slice(word);
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
fn oversized_word_length_does_not_overflow_bounds_check() {
    let mut bytes = vec![0, 1, 0, 1, 1];
    bytes.extend_from_slice(&u32::MAX.to_ne_bytes());
    let mut scanner = Scanner::new();
    scanner.restore(&bytes);
    assert_eq!(scanner.save(), [0, 0]);
}
