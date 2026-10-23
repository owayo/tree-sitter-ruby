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

// 木のすべてのノードの種類・範囲・extra かどうかを先行順で並べる。
fn node_ranges(tree: &tree_sitter::Tree) -> Vec<(String, std::ops::Range<usize>, bool)> {
    let mut nodes = Vec::new();
    let mut cursor = tree.walk();
    loop {
        let node = cursor.node();
        nodes.push((node.kind().to_string(), node.byte_range(), node.is_extra()));
        if cursor.goto_first_child() {
            continue;
        }
        while !cursor.goto_next_sibling() {
            if !cursor.goto_parent() {
                return nodes;
            }
        }
    }
}

// heredoc 本文ごとに、終端語・終端行・本文の開始位置・外側の本文の中にあるかを集める。
fn heredoc_bodies(
    tree: &tree_sitter::Tree,
    source: &str,
) -> Vec<(String, usize, tree_sitter::Point, bool)> {
    let mut bodies = Vec::new();
    let mut stack = vec![tree.root_node()];
    while let Some(node) = stack.pop() {
        if node.kind() == "heredoc_body" {
            let mut cursor = node.walk();
            let end = node.named_children(&mut cursor).last().unwrap();
            assert_eq!(end.kind(), "heredoc_end");
            bodies.push((
                end.utf8_text(source.as_bytes()).unwrap().to_string(),
                end.start_position().row,
                node.start_position(),
                node.parent().unwrap().kind() == "heredoc_body",
            ));
        }
        let mut cursor = node.walk();
        stack.extend(node.named_children(&mut cursor));
    }
    bodies.sort_by_key(|body| body.1);
    bodies
}

#[test]
fn nested_heredoc_bodies_follow_their_opening_line() {
    // 本文の補間で開いた heredoc は、その行の次から外側の本文や後続の heredoc より先に読む。
    // CRLF でも LF と同じく、入れ子の本文は開いた行の行末 ('\r') から始まる。
    let source = "def example\n  foo(<<~A, <<~B, value)\n    #{<<~C}\n      #{value = fetch}\n    C\n  A\n    #{value}\n  B\nend\n";
    for source in [source.to_string(), source.replace('\n', "\r\n")] {
        let tree = parse(&source);
        let root = tree.root_node();
        assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
        let method = root.named_child(0).unwrap();
        assert_eq!(method.kind(), "method");
        assert_eq!(
            method.end_position(),
            tree_sitter::Point::new(8, 3),
            "{source:?}"
        );
        assert_eq!(
            heredoc_bodies(&tree, &source),
            [
                ("C".to_string(), 4, tree_sitter::Point::new(2, 11), true),
                ("A".to_string(), 5, tree_sitter::Point::new(1, 24), false),
                ("B".to_string(), 7, tree_sitter::Point::new(5, 3), false),
            ],
            "{source:?}: {}",
            root.to_sexp()
        );
    }
}

#[test]
fn lone_cr_after_nested_heredoc_start_stays_in_outer_content() {
    // 単独 CR は行末ではないので、入れ子の本文は次の LF から始まる。
    let source = "x = <<~A\n  #{<<~C}\rX\n    c\n  C\nA\n";
    let tree = parse(source);
    let root = tree.root_node();
    assert!(!root.has_error(), "{}", root.to_sexp());
    let bodies = heredoc_bodies(&tree, source);
    assert_eq!(
        bodies[0],
        ("C".to_string(), 3, tree_sitter::Point::new(1, 11), true)
    );
    let outer = root.named_child(1).unwrap();
    let content = outer.named_child(2).unwrap();
    assert_eq!(content.kind(), "heredoc_content");
    assert_eq!(content.utf8_text(source.as_bytes()).unwrap(), "\rX");
}

#[test]
fn line_continuation_does_not_delay_nested_heredoc_body() {
    // 行継続 (`\` + 行末) の行で開いた heredoc も、次の行から本文を読む。
    // `\` は外側の本文に残り、行末は escape_sequence に飲まれない。
    let source = "x = <<-A\n#{<<-C}\\\n\ncc\nC\nzz\nA\n";
    for source in [source.to_string(), source.replace('\n', "\r\n")] {
        let tree = parse(&source);
        let root = tree.root_node();
        assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
        let bodies = heredoc_bodies(&tree, &source);
        assert_eq!(
            bodies,
            [
                ("C".to_string(), 4, tree_sitter::Point::new(1, 8), true),
                ("A".to_string(), 6, tree_sitter::Point::new(0, 8), false),
            ],
            "{source:?}: {}",
            root.to_sexp()
        );
        let outer = root.named_child(1).unwrap();
        let backslash = outer.named_child(2).unwrap();
        assert_eq!(backslash.kind(), "heredoc_content");
        assert_eq!(backslash.utf8_text(source.as_bytes()).unwrap(), "\\");
        let nested = outer.named_child(3).unwrap();
        assert!(nested.utf8_text(source.as_bytes()).unwrap().starts_with(
            if source.contains('\r') {
                "\r\n\r\ncc"
            } else {
                "\n\ncc"
            }
        ));
    }
}

#[test]
fn line_continuation_after_heredoc_start_reads_the_body_first() {
    // 行継続の行で開いた heredoc も次の行から本文を読み、行継続は本文の終端の次の行へつながる。
    // 段の最後の終端行の改行は heredoc_body に含まれ、heredoc_end は終端語だけになる。
    for (source, statement) in [
        ("x = <<~A \\\n  a\nA\n+ \"b\"\n", "assignment"),
        ("y = <<~A \\\n  a\nA\nif c\n", "if_modifier"),
    ] {
        for source in [source.to_string(), source.replace('\n', "\r\n")] {
            let tree = parse(&source);
            let root = tree.root_node();
            assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
            assert_eq!(
                root.named_child_count(),
                1,
                "{source:?}: {}",
                root.to_sexp()
            );
            assert_eq!(root.named_child(0).unwrap().kind(), statement);
            assert_eq!(
                heredoc_bodies(&tree, &source),
                [("A".to_string(), 2, tree_sitter::Point::new(0, 10), false)],
                "{source:?}"
            );
            let mut stack = vec![root];
            while let Some(node) = stack.pop() {
                if node.kind() == "heredoc_body" {
                    assert_eq!(node.end_position(), tree_sitter::Point::new(3, 0));
                }
                let mut cursor = node.walk();
                stack.extend(node.named_children(&mut cursor));
            }
        }
    }

    // 同じ行で開いた複数の heredoc では、最後の本文の後だけを行継続につなぐ。
    let source = "foo(<<~A, <<~B, \\\n  a\nA\n  b\nB\n\n1)\n";
    let tree = parse(source);
    let root = tree.root_node();
    assert!(!root.has_error(), "{}", root.to_sexp());
    assert_eq!(
        heredoc_bodies(&tree, source),
        [
            ("A".to_string(), 2, tree_sitter::Point::new(0, 17), false),
            ("B".to_string(), 4, tree_sitter::Point::new(2, 1), false),
        ]
    );
}

#[test]
fn lone_cr_in_code_is_whitespace_before_heredoc_body() {
    // コード中の単独 CR は Ruby と同じく空白で、heredoc の本文は次の改行から始まる。
    // 単独 CR の後に外部スキャナーのトークンが続いても、範囲は CR の後から始まる。
    for argument in ["1", "\"x\"", ":s", "-1", "*a"] {
        for line_end in ["\n", "\r\n"] {
            let source = format!("p foo(<<~C,\r{argument}){line_end}  c{line_end}C{line_end}");
            let tree = parse(&source);
            let root = tree.root_node();
            assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
            let line = format!("p foo(<<~C,\r{argument})");
            let bodies = heredoc_bodies(&tree, &source);
            assert_eq!(
                bodies,
                [(
                    "C".to_string(),
                    2,
                    tree_sitter::Point::new(0, line.len()),
                    false
                )],
                "{source:?}: {}",
                root.to_sexp()
            );
            let node = root
                .descendant_for_byte_range(12, 12 + argument.len())
                .unwrap();
            assert_eq!(node.start_byte(), 12, "{source:?}: {}", root.to_sexp());
        }
    }
}

#[test]
fn literal_line_breaks_start_pending_heredoc_bodies() {
    // heredoc の開始の後で改行をまたぐリテラルでも、本文はその改行から始まる。
    for (source, literal) in [
        ("x = [<<~A, \"x\n  a\nA\ny\"]\n", "string"),
        ("x = [<<~A, 'x\n  a\nA\ny']\n", "string"),
        ("x = [<<~A, /x\n  a\nA\ny/]\n", "regex"),
        ("x = [<<~A, :\"x\n  a\nA\ny\"]\n", "delimited_symbol"),
        ("x = [<<~A, `x\n  a\nA\n`]\n", "subshell"),
        ("x = [<<~A, %w[a  \n  a\nA\nb]]\n", "string_array"),
        ("x = [<<~A, %i[a\r \x0c\n  a\nA\nb]]\n", "symbol_array"),
        // `\` でエスケープした改行は語の一部なので、本文の後も同じ語が続く。
        ("x = [<<~A, %w[x\\\n  a\nA\ny]]\n", "bare_string"),
        ("x = [<<~A, %W[x\\\n  a\nA\ny]]\n", "bare_string"),
        ("x = [<<~A, \"x\\\n  a\nA\ny\"]\n", "string"),
    ] {
        for source in [source.to_string(), source.replace('\n', "\r\n")] {
            let tree = parse(&source);
            let root = tree.root_node();
            assert!(!root.has_error(), "{source:?}: {}", root.to_sexp());
            let mut bodies = Vec::new();
            let mut stack = vec![root];
            while let Some(node) = stack.pop() {
                if node.kind() == "heredoc_body" {
                    bodies.push(node);
                }
                let mut cursor = node.walk();
                stack.extend(node.named_children(&mut cursor));
            }
            assert_eq!(bodies.len(), 1, "{source:?}: {}", root.to_sexp());
            let parent = bodies[0].parent().unwrap();
            assert_eq!(parent.kind(), literal, "{source:?}: {}", root.to_sexp());
            if literal == "bare_string" {
                assert_eq!(parent.parent().unwrap().named_child_count(), 1);
            }
        }
    }

    // `\` でエスケープした単独 CR は、heredoc が開始待ちでも配列の語を分けない。
    let source = "p foo(<<A, %w[x\\\ry])\nbody\nA\n";
    let tree = parse(source);
    let root = tree.root_node();
    assert!(!root.has_error(), "{}", root.to_sexp());
    let start = source.find("%w").unwrap();
    let array = root
        .descendant_for_byte_range(start, start + 2)
        .unwrap()
        .parent()
        .unwrap();
    assert_eq!(array.kind(), "string_array", "{}", root.to_sexp());
    assert_eq!(array.named_child_count(), 1, "{}", root.to_sexp());
}

#[test]
fn incremental_parsing_matches_fresh_trees() {
    for (source, old_text, new_text) in [
        ("x = <<EOS\n#{1}EOS\nEOS\n", "#{1}", "#{2 + 3}"),
        ("x = <<EOS\nE\\t\nEOS\n", "E\\t", "EOS\\n"),
        ("x = <<~EOS\n  #{1}EOS\n  EOS\n", "  EOS\n", "    EOS\n"),
        ("x = <<\"\"\nbody\n\n", "body", "#{1}\nmore"),
        // 入れ子の本文の編集、入れ子の heredoc の追加と削除で、保存した段の状態を再利用する。
        (
            "x = <<~A\n  #{<<~C} tail\n    c\n  C\nA\n",
            "    c\n",
            "    #{<<~D}\n      d\n    D\n",
        ),
        ("x = <<~A\n  #{1}\n    c\n  C\nA\n", "#{1}", "#{<<~C}"),
        ("x = <<~A\n  #{<<~C}\n    c\n  C\nA\n", "<<~C", "1"),
        // 行継続で終わる行の入れ子の本文の編集と、行継続の追加。
        ("x = <<-A\n#{<<-C}\\\ncc\nC\nzz\nA\n", "cc", "#{1}"),
        (
            "x = <<-A\n#{<<-C}\ncc\nC\nzz\nA\n",
            "#{<<-C}\n",
            "#{<<-C}\\\n",
        ),
        // コードの行継続の追加と、行継続の行で開いた本文・改行をまたぐリテラル・単独 CR の後の編集。
        ("x = <<~A\n  a\nA\n+ \"b\"\n", "x = <<~A\n", "x = <<~A \\\n"),
        ("foo(<<~A, \\\n  a\nA\n1)\n", "  a\n", "  #{2}\n"),
        ("x = [<<~A, \"x\n  a\nA\ny\"]\n", "  a\n", "  b\n  c\n"),
        ("p foo(<<~C,\r\"x\")\n  c\nC\n", "\"x\"", "1"),
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
        // 本文の所属先も比べるため、extra を含む全ノードの範囲を突き合わせる。
        assert_eq!(
            node_ranges(&incremental),
            node_ranges(&fresh),
            "{changed:?}"
        );
    }
}
