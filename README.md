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

> **Warning:** `tree-sitter test` consumes excessive memory (RSS 8GB+, VSIZE 400GB+) with this parser due to the large parser table size (parser.c ~15MB, STATE_COUNT 6013). The `test` subcommand internally converts the entire parse tree to an S-expression string for diff comparison, which triggers massive memory allocation with large grammars. `tree-sitter parse` is unaffected (~10MB RSS). This is not tracked as a specific upstream issue, but related memory problems have been reported in [tree-sitter#1890](https://github.com/tree-sitter/tree-sitter/issues/1890), [tree-sitter#1185](https://github.com/tree-sitter/tree-sitter/issues/1185), and [zed#47880](https://github.com/zed-industries/zed/issues/47880). Use the alternative test runner instead.

```bash
# Recommended: corpus tests via tree-sitter parse (low memory)
# - covers recent Ruby syntax regressions such as anonymous *, **, & forwarding
# - covers Ruby 4.0 `*nil` splat parsing
# - covers Ruby 3.4 index assignment rejecting keyword/block arguments
# - covers scanner regressions for `%=` strings, empty heredoc delimiters,
#   invalid regexp options, and invalid `..` method/operator names
# - covers Ruby 4.0 leading logical-operator continuations in expressions and if conditions,
#   including keyword operators (`and` / `or`)
# - covers scanner line-continuation boundaries (leading `and`/`or` keywords vs identifiers,
#   leading `||`/`&&` operators, non-continuing single `&`, leading `..`)
# - covers scanner.c `is_iden_char` regression for non-ASCII Unicode identifier symbols
#   (e.g. `:Ĩ` U+0128 and `:漢字`) so char truncation cannot collide with NON_IDENTIFIER_CHARS
# - covers scanner short-interpolation handling so `$` immediately before EOF is not
#   mistaken for a one-character special global variable
# - covers Ruby 3.4 `it` implicit block parameter
# - covers expression-based scope resolution used by Ruby Box examples (`box::Foo`)
# - compares normalized AST output from `tree-sitter parse --no-ranges`
# - preserves single CR characters in corpus source sections
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
# - CLI timeout direct test, multi-blank-line name sections,
#   KeyboardInterrupt propagation, Emitted 'error' event only output,
#   code trailing whitespace trimming, empty code test skipping
# - missing corpus directory setup error,
#   OSError propagation on temp file creation failure (UnboundLocalError prevention)
# - tree-sitter CLI resolution (TREE_SITTER_CLI override, local native binary,
#   local shim, PATH fallback), AST normalization, and single-CR preservation
# - hidden .txt / .txt directory skipping, and OSError suppression during temp file cleanup
# - summarize_command_failure returning exit code only for empty / fully-filtered output
# - _resolve_memory_limit_mb parsing of TS_MEMORY_LIMIT_MB (unset / blank / non-numeric /
#   zero-or-negative / valid / os.environ fallback) boundary cases
# - run_with_memory_guard normal completion, large pipe output without deadlock,
#   child-process RSS kill, and timeout-triggered kill (kill_reason set)
pnpm run test:unit

# Pre-compile parser library (required for parse-based testing)
mkdir -p /tmp/ts-lib
cc -shared -fPIC -O0 -o /tmp/ts-lib/ruby.dylib -I src src/parser.c src/scanner.c

# Rust binding tests (grammar loading, parsing, query validation,
# locals query captures for singleton_method/for/as_pattern/block/do_block/lambda,
# locals query captures for keyword/optional/splat/hash_splat/block/destructured
# parameter identifiers, pattern-match bindings, and rescue exception variables,
# highlights query captures keywords, operators, and global variables,
# tags query regression for nested definitions, method/alias definitions,
# builtin pseudo-method filtering, and pseudo-constant filtering for
# __FILE__/__LINE__/__ENCODING__ in reference.call captures;
# scanner regression for special global-variable symbols like
# :$", :$;, :$$ and friends;
# corpus regression for Ruby 4.0 `*nil` splat parsing;
# scanner regression for heredoc EOF/quote/empty-delimiter boundaries,
# deep literal nesting serialization, oversized heredoc delimiters,
# symbol setter suffix validation, regexp option validation, and `%=` strings;
# scanner backslash continuation across CRLF line endings (\\\r\n);
# leading `&.` safe navigation treated as line continuation by the scanner;
# scanner.c `is_iden_char` accepting non-ASCII Unicode identifier symbols
# without colliding with NON_IDENTIFIER_CHARS via char truncation;
# Ruby 3.4 `it` implicit block parameter parsing;
# Ruby 3.4 index assignment rejecting keyword/block arguments;
# Ruby 4.0 `*nil` splat argument parsing;
# Ruby 4.0 leading logical-operator (`||`, `&&`, `and`, `or`) continuations,
# including keyword operators in if conditions;
# regex option scanning (imxouesn) not hanging on a regex ending at EOF without a
# trailing newline such as `a = /x/`, where strchr would otherwise match the terminating NUL)
cargo test

# If pnpm blocked tree-sitter-cli's install script, download the local CLI binary.
# Run from the package directory; install.js writes tree-sitter into the current directory.
(cd node_modules/tree-sitter-cli && node install.js)
```

`pnpm run test` verifies `tree-sitter --version` before executing corpus cases and exits with a setup error if the CLI is missing or does not start within 10 seconds. The corresponding setup and failure branches are covered by `pnpm run test:unit`.

When `scripts/corpus_test.py` is run directly, it resolves the CLI in this order:
`TREE_SITTER_CLI`, `node_modules/tree-sitter-cli/tree-sitter`, `node_modules/.bin/tree-sitter`,
then `tree-sitter` from `PATH`. This keeps direct `python3 scripts/corpus_test.py` runs aligned
with the project-pinned CLI when dependencies are installed.

### Scanner

The external scanner (`src/scanner.c`) handles context-sensitive tokens that cannot be expressed in `grammar.js` alone: heredocs, delimited literals (strings, regexes, subshells, symbol/string arrays), line breaks, whitespace-sensitive operators, and the serialized scanner state needed to resume those constructs correctly. Unlike the rest of `src/`, this file is manually maintained and should be edited directly when adding new token types.

Long heredoc terminators over 255 characters are covered by a dedicated regression case in `test/corpus/literals.txt`; terminators that cannot fit in tree-sitter's scanner serialization buffer are rejected instead of being silently misparsed. Changes to scanner serialization should be validated with `pnpm run test`. The `deserialize()` function includes bounds checking to safely handle truncated or corrupted buffers, and uses subtraction (`word_length > length - size`) instead of addition for the word-length boundary check so that an attacker-controlled `word_length` cannot wrap around via unsigned integer overflow. Regex option scanning (`imxouesn`) and short interpolation scanning for special global variables both guard against `lexer->lookahead == 0`, so EOF cannot be mistaken for the terminating NUL matched by `strchr`.

## References

- [AST Format of the Whitequark parser](https://github.com/whitequark/parser/blob/master/doc/AST_FORMAT.md)

[ci]: https://img.shields.io/github/actions/workflow/status/owayo/tree-sitter-ruby/ci.yml?logo=github&label=CI
