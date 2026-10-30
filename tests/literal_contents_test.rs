use tree_sitter::{InputEdit, Parser, Point, Tree};

fn parser() -> Parser {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_ruby::LANGUAGE.into())
        .unwrap();
    parser
}

fn snapshot(tree: &Tree) -> Vec<String> {
    let mut result = Vec::new();
    let mut cursor = tree.walk();
    loop {
        let node = cursor.node();
        result.push(format!(
            "{}|{:?}|{:?}|{}|{}|{}",
            node.kind(),
            cursor.field_name(),
            node.range(),
            node.is_named(),
            node.is_extra(),
            node.child_count()
        ));
        if cursor.goto_first_child() {
            continue;
        }
        loop {
            if cursor.goto_next_sibling() {
                break;
            }
            if !cursor.goto_parent() {
                return result;
            }
        }
    }
}

#[test]
fn literal_parts_remain_direct_children_with_original_ranges() {
    let cases: &[(&str, &[(&str, &str)])] = &[
        ("", &[]),
        ("文字", &[("string_content", "文字")]),
        ("\\n", &[("escape_sequence", "\\n")]),
        ("#{value}", &[("interpolation", "#{value}")]),
        (
            "before\\n#{value}after",
            &[
                ("string_content", "before"),
                ("escape_sequence", "\\n"),
                ("interpolation", "#{value}"),
                ("string_content", "after"),
            ],
        ),
    ];
    for (prefix, suffix, kind) in [
        ("%Q[", "]", "string"),
        ("%r[", "]im", "regex"),
        (":\"", "\"", "delimited_symbol"),
        ("%x[", "]", "subshell"),
    ] {
        for (body, parts) in cases {
            let source = format!("{prefix}{body}{suffix}");
            let tree = parser().parse(&source, None).unwrap();
            let root = tree.root_node();
            assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
            let literal = root.named_child(0).unwrap();
            assert_eq!(literal.kind(), kind, "{source:?}");
            assert_eq!(literal.byte_range(), 0..source.len());
            assert_eq!(literal.named_child_count() as usize, parts.len());
            let mut offset = prefix.len();
            for (index, (part_kind, text)) in parts.iter().enumerate() {
                let part = literal.named_child(index as u32).unwrap();
                assert_eq!(part.kind(), *part_kind, "{source:?}");
                assert_eq!(part.byte_range(), offset..offset + text.len());
                assert_eq!(part.utf8_text(source.as_bytes()).unwrap(), *text);
                offset += text.len();
            }
        }
    }
}

#[test]
fn word_arrays_preserve_aliased_words_and_their_content() {
    for (prefix, word_kind) in [("%W[", "bare_string"), ("%I[", "bare_symbol")] {
        let source = format!("{prefix}one two\\ three #{{value}}]");
        let tree = parser().parse(&source, None).unwrap();
        let root = tree.root_node();
        assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
        let array = root.named_child(0).unwrap();
        assert_eq!(array.named_child_count(), 3);
        let mut offset = prefix.len();
        for (index, (text, expected_parts)) in [
            ("one", vec!["string_content"]),
            (
                "two\\ three",
                vec!["string_content", "escape_sequence", "string_content"],
            ),
            ("#{value}", vec!["interpolation"]),
        ]
        .into_iter()
        .enumerate()
        {
            let word = array.named_child(index as u32).unwrap();
            assert_eq!(word.kind(), word_kind);
            assert_eq!(word.byte_range(), offset..offset + text.len());
            assert_eq!(word.utf8_text(source.as_bytes()).unwrap(), text);
            let mut cursor = word.walk();
            assert_eq!(
                word.named_children(&mut cursor)
                    .map(|child| child.kind())
                    .collect::<Vec<_>>(),
                expected_parts
            );
            offset += text.len() + 1;
        }
    }
}

fn point_at(source: &str, byte: usize) -> Point {
    let before = &source.as_bytes()[..byte];
    Point::new(
        before.iter().filter(|&&b| b == b'\n').count(),
        before
            .iter()
            .rposition(|&b| b == b'\n')
            .map_or(byte, |last| byte - last - 1),
    )
}

#[test]
fn edits_between_literal_part_shapes_match_fresh_trees() {
    for (prefix, suffix) in [
        ("%Q[", "]"),
        ("%r[", "]im"),
        (":\"", "\""),
        ("%x[", "]"),
        ("%W[", "]"),
        ("%I[", "]"),
    ] {
        let mut parser = parser();
        let mut body = "";
        let mut source = format!("value = {prefix}{body}{suffix}\r\nnext_call\r\n");
        let mut tree = parser.parse(&source, None).unwrap();
        for replacement in [
            "plain",
            "\\n",
            "#{value}",
            "before\\n#{[\"中\", %W[a b]].first}after",
            "first\r\n#{value}\\nlast",
            "plain",
            "",
            "終わり",
        ] {
            let start = "value = ".len() + prefix.len();
            let end = start + body.len();
            let mut edited_source = source.clone();
            edited_source.replace_range(start..end, replacement);
            tree.edit(&InputEdit {
                start_byte: start,
                old_end_byte: end,
                new_end_byte: start + replacement.len(),
                start_position: point_at(&source, start),
                old_end_position: point_at(&source, end),
                new_end_position: point_at(&edited_source, start + replacement.len()),
            });
            let incremental = parser.parse(&edited_source, Some(&tree)).unwrap();
            let fresh = parser.parse(&edited_source, None).unwrap();
            assert!(
                !fresh.root_node().has_error(),
                "{edited_source:?}: {}",
                fresh.root_node().to_sexp()
            );
            assert_eq!(
                snapshot(&incremental),
                snapshot(&fresh),
                "{edited_source:?}"
            );
            tree = incremental;
            source = edited_source;
            body = replacement;
        }
    }
}
