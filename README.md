# tree-sitter-ruby

[![CI][ci]](https://github.com/owayo/tree-sitter-ruby/actions/workflows/ci.yml)

Ruby grammar for [tree-sitter](https://github.com/tree-sitter/tree-sitter) with Ruby 3/4 syntax support.

## Usage (Rust)

Add to your `Cargo.toml`:

```toml
[dependencies]
tree-sitter = "0.27"
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
mise install
```

The versions of Node.js, pnpm, Python, Ruff, and Rust are defined in `mise.toml`. The project-local tree-sitter CLI is installed by pnpm.

## Development

```bash
# Install dependencies (also fetches the tree-sitter CLI binary)
mise exec -- pnpm install

# Generate parser from grammar.js
mise exec -- pnpm exec tree-sitter generate

# Lint grammar.js
mise exec -- pnpm run lint

# Parse a file
mise exec -- pnpm exec tree-sitter parse example.rb
```

### Testing

> **Warning:** `tree-sitter test` consumes excessive memory (RSS 8GB+, VSIZE 400GB+) with this parser due to the large parser table size (currently parser.c ~21MB, STATE_COUNT 8235). The `test` subcommand internally converts the entire parse tree to an S-expression string for diff comparison, which triggers massive memory allocation with large grammars. `tree-sitter parse` is unaffected (~10MB RSS). This is not tracked as a specific upstream issue, but related memory problems have been reported in [tree-sitter#1890](https://github.com/tree-sitter/tree-sitter/issues/1890), [tree-sitter#1185](https://github.com/tree-sitter/tree-sitter/issues/1185), and [zed#47880](https://github.com/zed-industries/zed/issues/47880). Use the alternative test runner instead.

```bash
# Recommended: corpus tests via tree-sitter parse (low memory)
# - covers recent Ruby syntax regressions such as anonymous *, **, & forwarding
# - covers Ruby 4.0 `*nil` splat parsing
# - covers Ruby 3.4 index assignment rejecting keyword/block arguments
# - covers spaced index assignment with newlines and comments inside the brackets,
#   while keeping multiline array arguments as method-call arguments
# - covers scanner regressions for `%=` strings, empty heredoc delimiters,
#   invalid regexp options, and invalid `..` method/operator names
# - covers Ruby 4.0 leading logical-operator continuations in expressions and if conditions,
#   including keyword operators (`and` / `or`)
# - covers scanner line-continuation boundaries (leading `and`/`or` keywords vs identifiers,
#   leading `||`/`&&` operators, non-continuing single `&`, leading `..`)
# - covers scanner.c `is_iden_char` regression for non-ASCII Unicode identifier symbols
#   (e.g. `:Ĩ` U+0128 and `:漢字`) so char truncation cannot collide with NON_IDENTIFIER_CHARS
# - covers valid Ruby identifiers containing `ſ` (U+017F) and `K` (U+212A),
#   which tree-sitter-cli 0.26.11 removed from generic character sets during generation
#   (0.27.0 no longer strips them, but the explicit allowance is kept as a safety net)
# - covers endless method definitions with parenthesis-less command calls
#   (`def m = foo 1`), including their rescue modifier and splat / block arguments
# - covers regex option scanning so non-ASCII characters whose low 8 bits collide with
#   an option letter (`ど` U+3069, `ũ` U+0169 -> 0x69 = 'i') are not consumed
# - covers scanner short-interpolation handling so `$` immediately before EOF is not
#   mistaken for a one-character special global variable
# - covers scanner short-interpolation handling so non-ASCII Unicode characters
#   (e.g. `Ĥ` U+0124, `Ŀ` U+0140) are not misclassified as `@`/`$` interpolation
#   starts via char truncation
# - covers unquoted and quoted Unicode heredoc terminators, including a code point
#   whose low 8 bits collide with an ASCII delimiter
# - covers Unicode global variables such as `$名前` and `$-名`, including short interpolation
# - covers Ruby 3.4 `it` implicit block parameter
# - covers expression-based scope resolution used by Ruby Box examples (`box::Foo`)
# - compares normalized AST output from `tree-sitter parse --no-ranges`
# - preserves single CR characters in corpus source sections
python3 scripts/corpus_test.py

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
#   non-finite / zero-or-negative / valid / os.environ fallback) boundary cases
# - OS-specific RSS parsing, including quoted thousands separators in Windows tasklist CSV
#   and POSIX process-group aggregation
# - run_with_memory_guard normal completion, large pipe output without deadlock,
#   child-process RSS kill, and timeout-triggered kill (kill_reason set)
# - direct-process kill fallback when Windows taskkill or POSIX process-group kill fails
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
# scanner.c `scan_short_interpolation` not misclassifying non-ASCII Unicode characters
# whose low 8 bits collide with `@` (0x40) or `$` (0x24) as interpolation starts;
# Unicode heredoc terminators retained and compared as UTF-8 byte sequences;
# Unicode global variables, including `$名前` and `$-名` short interpolation;
# Ruby 3.4 `it` implicit block parameter parsing;
# Ruby 3.4 index assignment rejecting keyword/block arguments;
# Ruby 4.0 `*nil` splat argument parsing;
# Ruby 4.0 leading logical-operator (`||`, `&&`, `and`, `or`) continuations,
# including keyword operators in if conditions;
# regex option scanning (imxouesn) not hanging on a regex ending at EOF without a
# trailing newline such as `a = /x/`, where strchr would otherwise match the terminating NUL;
# endless method definitions with parenthesis-less command calls, and `def m = foo 1 rescue 2`
# binding the rescue modifier to the method body;
# block-call chains such as `1.upto 0 do end.foo(1)` as a regression guard;
# regex option scanning rejecting non-ASCII characters that collide with an option letter
# after char truncation, while still accepting valid options and EOF)
cargo test

# tree-sitter-cli's install script is allow-listed in `pnpm-workspace.yaml`, so this is
# normally unnecessary. Run it only if the script was skipped for some reason.
# Run from the package directory; install.js writes tree-sitter into the current directory
# (running it from the repository root drops an 18MB binary into the work tree; gitignored).
(cd node_modules/tree-sitter-cli && node install.js)
```

`pnpm run test` verifies `tree-sitter --version` before executing corpus cases and exits with a setup error if the CLI is missing or does not start within 10 seconds. The corresponding setup and failure branches are covered by `pnpm run test:unit`.

When `scripts/corpus_test.py` is run directly, it resolves the CLI in this order:
`TREE_SITTER_CLI`, `node_modules/tree-sitter-cli/tree-sitter`, `node_modules/.bin/tree-sitter`,
then `tree-sitter` from `PATH`. This keeps direct `python3 scripts/corpus_test.py` runs aligned
with the project-pinned CLI when dependencies are installed.

### Scanner

The external scanner (`src/scanner.c`) handles context-sensitive tokens that cannot be expressed in `grammar.js` alone: heredocs, delimited literals (strings, regexes, subshells, symbol/string arrays), line breaks, whitespace-sensitive operators, and the serialized scanner state needed to resume those constructs correctly. Unlike the rest of `src/`, this file is manually maintained and should be edited directly when adding new token types.

Long heredoc terminators over 255 characters are covered by a dedicated regression case in `test/corpus/literals.txt`; terminators that cannot fit in tree-sitter's scanner serialization buffer are rejected instead of being silently misparsed, while a state that exactly fills the 1024-byte buffer remains valid. Unicode terminators are stored and compared as UTF-8 byte sequences, preserving the existing one-byte representation and capacity for ASCII terminators. Changes to scanner serialization should be validated with `pnpm run test`. The `deserialize()` function includes bounds checking to safely handle truncated or corrupted buffers, and uses subtraction (`word_length > length - size`) instead of addition for the word-length boundary check so that an attacker-controlled `word_length` cannot wrap around via unsigned integer overflow. Regex option scanning (`imxouesn`) and short interpolation scanning for special global variables avoid calling `strchr` on `lexer->lookahead` directly: `strchr` converts its second argument to `char`, so EOF (`0`) would match the terminating NUL and non-ASCII code points whose low 8 bits collide with an option letter (`ど` U+3069 and `ũ` U+0169 both end in 0x69 = `'i'`) would be consumed as options. The former compares against `int32_t` values directly; the latter narrows to `c > 0 && c < 0x80` before matching. Short-interpolation entry points (`@`/`$` after `#`) compare against `lexer->lookahead` (`int32_t`) directly instead of truncating to `char`, so Unicode characters whose low 8 bits collide with `'@'` (0x40) or `'$'` (0x24) — such as `Ĥ` (U+0124) or `Ŀ` (U+0140) — are not misclassified as interpolation starts.

### Unicode identifiers

tree-sitter-cli 0.26.11 stripped `ſ` (U+017F, simple-folded to `s`) and `K`
(U+212A, simple-folded to `k`) from generic lexer character sets to make
case-insensitive keyword extraction correct. Ruby accepts both characters in
identifiers, so `grammar.js` explicitly adds them back to the initial and
continuation character rules. Since 0.27.0 the CLI no longer strips them and the
explicit allowance is a no-op (`src/parser.c` is byte-identical either way), but it
is kept so the grammar does not break silently if the CLI regresses. Keep this
exception synchronized with `test/corpus/identifiers.txt` when changing identifier
token rules.
Named global variables reuse these Unicode identifier rules, including the
single-character option form (`$-名`) and short interpolation (`"#$名前"`).

### Endless method definitions

Since Ruby 3.1 the body of an endless method definition may be a parenthesis-less
command call (`endless_command : command` in `parse.y`), for example
`def greet(person) = "Hi, ".dup.concat person`. Reusing the existing `command_call`
rule for that position is not viable: its argument list loops back into
`_expression`, which drags pattern matching (`x in [1] | [2]`) and block binding
into the endless-body context and produces a cascade of LR conflicts. The grammar
therefore defines a narrowed `_endless_command_call` / `_endless_command_argument_list`
/ `_endless_command_argument` trio that reuses `_arg` only as a leaf.

`pair` (`def m = foo a: 1`) is deliberately excluded from the endless argument list:
the `_arg => _arg` form competes with `match_pattern` and doubles the LR state count
in this context alone, growing `src/parser.c` from 21MB to 32MB. Splat, double-splat
and block arguments cost almost nothing by comparison and are supported. Parenthesized
calls such as `def m = foo(a: 1)` are unaffected.

Do not add `_chained_command_call` to the receiver of `call` or
`command_call_with_block`. It improves the AST for `1.upto 0 do end.foo(1)`, but it
also makes whole files fail to parse across Rails, Homebrew and ruby itself, and
doubles `src/parser.c` to 37MB.

## References

- [AST Format of the Whitequark parser](https://github.com/whitequark/parser/blob/master/doc/AST_FORMAT.md)

[ci]: https://img.shields.io/github/actions/workflow/status/owayo/tree-sitter-ruby/ci.yml?logo=github&label=CI
