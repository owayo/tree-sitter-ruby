# tree-sitter-ruby

[![CI][ci]](https://github.com/owayo/tree-sitter-ruby/actions/workflows/ci.yml)

Ruby grammar for [tree-sitter](https://github.com/tree-sitter/tree-sitter) with Ruby 3/4 syntax support.

## Usage (Rust)

Add to your `Cargo.toml`:

```toml
[dependencies]
tree-sitter = "0.26"
tree-sitter-ruby = { git = "https://github.com/owayo/tree-sitter-ruby.git" }
```

```rust
use tree_sitter::Parser;
use tree_sitter_ruby::LANGUAGE;

let mut parser = Parser::new();
parser.set_language(&LANGUAGE.into()).unwrap();

let tree = parser.parse("puts 'hello'", None).unwrap();
println!("{}", tree.root_node().to_sexp());
```

## Development

```bash
# Install dependencies
pnpm install --ignore-scripts

# Generate parser from grammar.js
npx tree-sitter generate

# Run tests
npx tree-sitter test

# Parse a file
npx tree-sitter parse example.rb
```

## References

- [AST Format of the Whitequark parser](https://github.com/whitequark/parser/blob/master/doc/AST_FORMAT.md)

[ci]: https://img.shields.io/github/actions/workflow/status/owayo/tree-sitter-ruby/ci.yml?logo=github&label=CI
