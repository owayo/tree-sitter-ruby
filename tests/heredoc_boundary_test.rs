use tree_sitter::Parser;

fn parse(source: &str) -> tree_sitter::Tree {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_ruby::LANGUAGE.into())
        .unwrap();
    parser.parse(source, None).unwrap()
}

#[test]
fn terminator_must_begin_a_physical_line() {
    // 行途中の終端語を本文に残し、最後の終端行まで heredoc を維持する。
    for source in [
        "x = <<EOS\n#{1}EOS\nEOS\n",
        "x = <<EOS\na\\tEOS\nEOS\n",
        "x = <<~EOS\n  #{1}EOS\n  EOS\n",
        "x = <<EOS\na\rEOS\nEOS\n",
        "x = <<EOS\nEOS\rfoo\nEOS\n",
        "x = <<EOS\nEOS \nputs 1\nEOS\n",
        "x = <<-EOS\n  EOS\t\nputs 1\n  EOS\n",
        "x = <<'EOS'\nEOS \nEOS\n",
        "x = <<EOS\n#$!EOS\nEOS\n",
        "x = <<EOS\na\\\nEOS\nEOS\n",
    ] {
        let tree = parse(source);
        let root = tree.root_node();
        assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
        assert_eq!(root.named_child_count(), 2, "{source:?}");
        let body = root.named_child(1).unwrap();
        assert_eq!(body.kind(), "heredoc_body");
        let mut cursor = body.walk();
        let end = body.named_children(&mut cursor).last().unwrap();
        assert_eq!(end.kind(), "heredoc_end");
        assert_eq!(end.start_position().row, source.lines().count() - 1);
    }
}

#[test]
fn partial_terminator_before_escape_is_content() {
    for source in [
        "x = <<EOS\nE\\t\nEOS\n",
        "x = <<~EOS\n  E\\t\n  EOS\n",
        "x = <<EOS\nEOS\\t\nEOS\n",
        "x = <<EOS\nE#{1}\nEOS\n",
    ] {
        let tree = parse(source);
        assert!(
            !tree.root_node().has_error(),
            "{source:?}: {}",
            tree.root_node().to_sexp()
        );
        let body = tree.root_node().named_child(1).unwrap();
        let content = body.named_child(0).unwrap();
        assert_eq!(content.kind(), "heredoc_content");
        assert!(content.utf8_text(source.as_bytes()).unwrap().contains('E'));
    }
}

#[test]
fn terminator_line_endings_and_empty_delimiters() {
    for source in [
        "x = <<EOS\nbody\nEOS",
        "x = <<EOS\r\nbody\r\nEOS\r\n",
        "x = <<-EOS\nbody\n  EOS\n",
        "x = <<\"\"\nbody\n\n",
        "x = <<-\"\"\nbody\n  \n",
        "x = <<-\"\"\nbody\n  ",
    ] {
        assert!(!parse(source).root_node().has_error(), "{source:?}");
    }
    for source in [
        "x = <<EOS\nbody\nEOS \n",
        "x = <<EOS\nbody\nEOS\t\n",
        "x = <<EOS\nbody\nEOS\r",
        "x = <<\"\"\nbody\n \n",
        "x = <<\"\"\nbody\n",
    ] {
        assert!(parse(source).root_node().has_error(), "{source:?}");
    }
}

#[test]
fn literal_capacity_overflow_preserves_pending_heredoc() {
    let delimiter = "A".repeat(1000);
    // 2 重目のリテラルだけが保存容量を超える。heredoc 本文をコードにしない。
    let source = format!("x = <<{delimiter} + \"#{{\"#{{1}}\"}}\"\nbody\n{delimiter}\ny = 1\n");
    let tree = parse(&source);
    let root = tree.root_node();
    assert!(root.has_error(), "{}", root.to_sexp());
    // エラー回復で本文が式の内側へ移っても、実際の本文範囲が保たれることを見る。
    let start_byte = source.find("\nbody").unwrap() + 1;
    let end_byte = source.rfind(&delimiter).unwrap() + delimiter.len();
    let body = root
        .descendant_for_byte_range(start_byte, end_byte)
        .unwrap();
    assert_eq!(body.kind(), "heredoc_body", "{}", root.to_sexp());
    let mut cursor = body.walk();
    let end = body.named_children(&mut cursor).last().unwrap();
    assert_eq!(end.kind(), "heredoc_end");
    assert_eq!(end.utf8_text(source.as_bytes()).unwrap(), delimiter);
}

#[test]
fn incremental_parsing_matches_fresh_trees() {
    for (source, old_text, new_text) in [
        ("x = <<EOS\n#{1}EOS\nEOS\n", "#{1}", "#{2 + 3}"),
        ("x = <<EOS\nE\\t\nEOS\n", "E\\t", "EOS\\n"),
        ("x = <<~EOS\n  #{1}EOS\n  EOS\n", "  EOS\n", "    EOS\n"),
        ("x = <<\"\"\nbody\n\n", "body", "#{1}\nmore"),
    ] {
        let mut parser = Parser::new();
        parser
            .set_language(&tree_sitter_ruby::LANGUAGE.into())
            .unwrap();
        let mut old_tree = parser.parse(source, None).unwrap();
        let start_byte = source.find(old_text).unwrap();
        let changed = source.replacen(old_text, new_text, 1);
        let point = |text: &str, byte: usize| {
            let prefix = &text[..byte];
            tree_sitter::Point::new(
                prefix.bytes().filter(|&c| c == b'\n').count(),
                prefix.rsplit('\n').next().unwrap().len(),
            )
        };
        // interpolation・エスケープ・終端行の編集後に保存状態を再利用する。
        old_tree.edit(&tree_sitter::InputEdit {
            start_byte,
            old_end_byte: start_byte + old_text.len(),
            new_end_byte: start_byte + new_text.len(),
            start_position: point(source, start_byte),
            old_end_position: point(source, start_byte + old_text.len()),
            new_end_position: point(&changed, start_byte + new_text.len()),
        });
        let incremental = parser.parse(&changed, Some(&old_tree)).unwrap();
        let fresh = parser.parse(&changed, None).unwrap();
        let root = incremental.root_node();
        assert!(!root.has_error(), "{changed:?}: {}", root.to_sexp());
        assert_eq!(root.to_sexp(), fresh.root_node().to_sexp(), "{changed:?}");
        let body = root.named_child(1).unwrap();
        assert_eq!(
            body.byte_range(),
            fresh.root_node().named_child(1).unwrap().byte_range()
        );
    }
}
