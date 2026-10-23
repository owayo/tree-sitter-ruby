use tree_sitter::{Parser, Tree};

fn parse(source: &str) -> Tree {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_ruby::LANGUAGE.into())
        .unwrap();
    parser.parse(source, None).unwrap()
}

/// 利用側は演算子の直前の空白 1 文字を改ページに置き換えて、直前の識別子がローカル変数だと伝える。
/// Ruby はローカル変数の後 (EXPR_END) の演算子を引数の始まりではなく二項演算として読むので、
/// 手がかりのある木は空白付きの二項演算と同じ構造になり、演算子はもとのバイト位置に残る。
#[test]
fn form_feed_before_an_operator_reads_it_as_binary() {
    for (hinted, binary) in [
        ("i\x0c+1", "i + 1"),
        ("i\x0c+1.5", "i + 1.5"),
        ("i\x0c+'1'", "i + '1'"),
        ("i\x0c+%q(1)", "i + %q(1)"),
        ("i\x0c+(x)", "i + (x)"),
        ("i\x0c+x.y", "i + x.y"),
        ("i\x0c-1", "i - 1"),
        ("i\x0c-x", "i - x"),
        ("i\x0c+-x", "i + -x"),
        ("i\x0c-x - y", "i - x - y"),
        ("i\x0c+x * y", "i + x * y"),
        ("i\x0c*x", "i * x"),
        ("i\x0c**x", "i ** x"),
        ("i\x0c&x", "i & x"),
        ("i\x0c<<x", "i << x"),
        ("i\x0c/x", "i / x"),
        ("i\x0c%x", "i % x"),
        ("i\x0c[0]", "i[0]"),
        ("[1].map { |i| i\x0c+1 }", "[1].map { |i| i + 1 }"),
        ("x = i\x0c-1 if i\x0c+1", "x = i - 1 if i + 1"),
        // 行継続は改行を消すだけなので、その前の手がかりは改行を越えて残る。
        ("i\x0c\\\n+1", "i \\\n+ 1"),
        ("i\x0c\\\r\n+1", "i \\\r\n+ 1"),
        ("i\x0c\\\n\\\n-1", "i \\\n\\\n- 1"),
    ] {
        let tree = parse(hinted);
        let root = tree.root_node();
        assert!(!root.has_error(), "{hinted:?}: {}", root.to_sexp());
        assert_eq!(
            root.to_sexp(),
            parse(binary).root_node().to_sexp(),
            "{hinted:?}"
        );
        for (index, _) in hinted.match_indices('\x0c') {
            let mut start = index + 1;
            while let Some(continuation) = ["\\\n", "\\\r\n"]
                .into_iter()
                .find(|continuation| hinted[start..].starts_with(continuation))
            {
                start += continuation.len();
            }
            let operator = root.descendant_for_byte_range(start, start + 1).unwrap();
            assert!(
                !operator.is_named(),
                "{hinted:?}: {} at {}",
                operator.kind(),
                start
            );
            assert_eq!(operator.start_byte(), start, "{hinted:?}");
        }
    }
}

/// 二項演算が成立しない位置の改ページと、演算子の直前ではない改ページは、空白と同じに読む。
#[test]
fn form_feed_outside_a_binary_position_reads_as_whitespace() {
    for (with_form_feed, with_space) in [
        ("x =\x0c-1", "x = -1"),
        ("foo(\x0c+1)", "foo( +1)"),
        ("return\x0c-1", "return -1"),
        ("[\x0c*a]", "[ *a]"),
        ("i\x0c +1", "i  +1"),
        ("i\x0c\n+1", "i \n+1"),
        ("i\x0c \\\n+1", "i  \\\n+1"),
        ("foo\x0cbar", "foo bar"),
    ] {
        let tree = parse(with_form_feed);
        let root = tree.root_node();
        assert!(!root.has_error(), "{with_form_feed:?}: {}", root.to_sexp());
        assert_eq!(
            root.to_sexp(),
            parse(with_space).root_node().to_sexp(),
            "{with_form_feed:?}"
        );
    }
}

/// 手がかりが無ければ、未知の識別子の後の符号や区切り文字は従来どおりコマンド引数の始まり。
#[test]
fn without_a_hint_an_operator_after_an_identifier_starts_an_argument() {
    for source in [
        "i +1",
        "i -1",
        "i *x",
        "i **x",
        "i &x",
        "i [0]",
        "i <<X\nX\n",
        "i /x/",
        "i %w(a)",
    ] {
        let tree = parse(source);
        let root = tree.root_node();
        assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
        let statement = root.named_child(0).unwrap();
        assert_eq!(statement.kind(), "call", "{source:?}: {}", root.to_sexp());
        assert!(
            statement.child_by_field_name("arguments").is_some(),
            "{source:?}: {}",
            root.to_sexp()
        );
    }
}
