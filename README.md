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

## Queries

This grammar ships with the following query files in `queries/`:

| File | Description |
|------|-------------|
| `highlights.scm` | Syntax highlighting (keywords, literals, operators, etc.) |
| `tags.scm` | Code navigation tags (definitions and references for methods, classes, modules, constants) |
| `locals.scm` | Local variable scoping |

## Prerequisites

```bash
cargo install tree-sitter-cli
```

## Development

```bash
# Install dependencies
pnpm install --ignore-scripts

# Generate parser from grammar.js
tree-sitter generate

# Lint grammar.js
pnpm run lint

# Parse a file
tree-sitter parse example.rb
```

### Testing

> **Warning:** `tree-sitter test` consumes excessive memory (RSS 8GB+, VSIZE 400GB+) with this parser due to the large parser table size (parser.c ~15MB, STATE_COUNT 5989). The `test` subcommand internally converts the entire parse tree to an S-expression string for diff comparison, which triggers massive memory allocation with large grammars. `tree-sitter parse` is unaffected (~10MB RSS). This is not tracked as a specific upstream issue, but related memory problems have been reported in [tree-sitter#1890](https://github.com/tree-sitter/tree-sitter/issues/1890), [tree-sitter#1185](https://github.com/tree-sitter/tree-sitter/issues/1185), and [zed#47880](https://github.com/zed-industries/zed/issues/47880). Use the alternative test runner instead.

```bash
# Recommended: corpus tests via tree-sitter parse (low memory)
pnpm run test

# Unit tests for scripts/corpus_test.py
# - malformed corpus extraction (empty files, whitespace-only code, :error tags)
# - tree-sitter CLI setup / generic failure / PermissionError propagation
# - expected ERROR / TIMEOUT / non-.txt branches in the runner
# - mixed pass/fail result aggregation, multi-file corpus aggregation
# - boundary values for separator detection and command failure summaries
# - edge cases: empty AST sections, consecutive tests without AST, empty corpus
# - additional coverage: empty test names, no trailing newline, MISSING-only detection,
#   bool/float/empty-string failure details, meaningful lines after noise
# - :error tag behavior without ERROR in AST, separator-like lines in code,
#   multiple ERROR/MISSING node counting, PermissionError during parse
# - __main__ guard invocation, expected ERROR but parsed OK,
#   non-zero exit without error nodes
# - dash separator in code, file ending with header separator,
#   indented Error: lines, stderr-only errors, very long separators,
#   multiple error tag tests, expected ERROR matched by MISSING
pnpm run test:unit

# Pre-compile parser library (required for parse-based testing)
mkdir -p /tmp/ts-lib
cc -shared -fPIC -O0 -o /tmp/ts-lib/ruby.dylib -I src src/parser.c src/scanner.c

# If pnpm blocked tree-sitter-cli's install script, download the local CLI binary
node node_modules/tree-sitter-cli/install.js
```

`pnpm run test` verifies `tree-sitter --version` before executing corpus cases and exits with a setup error if the CLI is missing or does not start within 10 seconds. The corresponding setup and failure branches are covered by `pnpm run test:unit`.

### Scanner

The external scanner (`src/scanner.c`) handles context-sensitive tokens that cannot be expressed in `grammar.js` alone: heredocs, delimited literals (strings, regexes, subshells, symbol/string arrays), line breaks, whitespace-sensitive operators, and the serialized scanner state needed to resume those constructs correctly. Unlike the rest of `src/`, this file is manually maintained and should be edited directly when adding new token types.

Long heredoc terminators are covered by a dedicated regression case in `test/corpus/literals.txt`, so changes to scanner serialization should be validated with `pnpm run test`. The `deserialize()` function includes bounds checking to safely handle truncated or corrupted buffers.

## References

- [AST Format of the Whitequark parser](https://github.com/whitequark/parser/blob/master/doc/AST_FORMAT.md)

[ci]: https://img.shields.io/github/actions/workflow/status/owayo/tree-sitter-ruby/ci.yml?logo=github&label=CI
