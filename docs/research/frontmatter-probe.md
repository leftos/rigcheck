# Claude Code frontmatter probe

Measured 2026-09-27 with `claude plugin validate --json <dir>` (Claude Code 2.1.283) on a directory holding `skills/<variant>/SKILL.md` and `agents/<variant>.md`, one variant each, every file starting with `name: <variant>` (the probe script was a throwaway and is not kept). Every frontmatter below is synthetic. "Claude Code: rejects" is its error "YAML frontmatter failed to parse: YAML Parse error: …", after which a skill loads with empty metadata and an agent with its name taken from the filename. Strict YAML is PyYAML `safe_load`.

## Inferred rule

Claude Code parses the block as YAML; when that fails, it rewrites the block line by line and parses it once more:

- R0: a block strict YAML loads, Claude Code loads the same way (no probed variant separated them).
- R1: a line that fully matches `([a-zA-Z_-]+):\s+(.+)` (JavaScript `.`, so no CR) whose value contains `: ` or one of `` {}[]*&#!|>%@` `` becomes `key: "value"`, with `\` and `"` escaped.
- R2: a CRLF file's lines keep their CR, which `.` does not match, so no line is rewritten: this is what separates `friction-review` (CRLF) from `debugger` and `debug-live` (LF), which share its unquoted `: ` in `description`.
- R3: an indented line, a list item and a key containing a digit are never rewritten.
- R4: a value that starts and ends with the same quote character is left alone.
- R5: a value with neither `: ` nor a special character is left alone (a trailing `:`, a quoted start that continues after its closing quote).
- R6: tab indentation, which strict YAML rejects, loads; rigcheck models this by expanding leading tabs to spaces in the retry.
- R7: a rewritten value is a closed quoted scalar, so an indented continuation line after it stays an error.
- R8: a column-0 line that is not `key:` stays an error.

The model (R0 to R8) predicts Claude Code's result for all 66 variants; where the probe cannot say what Claude Code loads as the value (R6), rigcheck leans to "loads".

## Results

| Variant | Kind | Frontmatter (between the fences) | Strict YAML (PyYAML) | Claude Code | Rule |
|---|---|---|---|---|---|
| plain | skill | `name: plain\ndescription: simple text` | loads: "simple text" | loads | R0 strict YAML loads it |
| colon | skill | `name: colon\ndescription: use when: it breaks` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| colon-trailing | skill | `name: colon-trailing\ndescription: use when:` | rejects: mapping values are not allowed here | rejects: Unexpected token | R5 no `: ` or special character in the value, so it is not re-quoted |
| colon-dq-inside | skill | `name: colon-dq-inside\ndescription: say "a b" then: c` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| colon-sq-inside | skill | `name: colon-sq-inside\ndescription: it's here: now` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| colon-dq-apostrophe | skill | `name: colon-dq-apostrophe\ndescription: phrases "don't do x", "y z": more` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| dq-start-continues | skill | `name: dq-start-continues\ndescription: "quoted" then more` | rejects: while parsing a block mapping | rejects: Unexpected token | R5 no `: ` or special character in the value, so it is not re-quoted |
| dq-start-continues-colon | skill | `name: dq-start-continues-colon\ndescription: "quoted" then: more` | rejects: while parsing a block mapping | loads | R1 fallback re-quotes the key line's value |
| sq-start-continues | skill | `name: sq-start-continues\ndescription: 'quoted' then more` | rejects: while parsing a block mapping | rejects: Unexpected token | R5 no `: ` or special character in the value, so it is not re-quoted |
| dq-start-unclosed | skill | `name: dq-start-unclosed\ndescription: "never closed` | rejects: while scanning a quoted scalar | rejects: Unexpected EOF | R5 no `: ` or special character in the value, so it is not re-quoted |
| hash | skill | `name: hash\ndescription: a # comment` | loads: "a" | loads | R0 strict YAML loads it |
| hash-colon | skill | `name: hash-colon\ndescription: a: b # c` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| hash-nospace | skill | `name: hash-nospace\ndescription: a#b: c` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| emdash | skill | `name: emdash\ndescription: a — b` | loads: "a — b" | loads | R0 strict YAML loads it |
| emdash-colon | skill | `name: emdash-colon\ndescription: a — b: c` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| multiline | skill | `name: multiline\ndescription: first line\n  second line` | loads: "first line second line" | loads | R0 strict YAML loads it |
| multiline-colon-first | skill | `name: multiline-colon-first\ndescription: first: line\n  second line` | rejects: mapping values are not allowed here | rejects: Unexpected token | R7 a re-quoted value is a closed quoted scalar, so an indented continuation line after it is an error |
| multiline-colon-second | skill | `name: multiline-colon-second\ndescription: first line\n  second: line` | rejects: mapping values are not allowed here | rejects: Unexpected token | R3 only a column-0 `key: value` line with a key of letters, `_`, `-` is re-quoted |
| block-literal-colon | skill | `name: block-literal-colon\ndescription: \|\n  first: line\n  second` | loads: "first: line\nsecond" | loads | R0 strict YAML loads it |
| list | skill | `name: list\ndescription: d\nallowed-tools:\n  - Read\n  - Grep` | loads: "d" | loads | R0 strict YAML loads it |
| list-colon | skill | `name: list-colon\ndescription: use when: x\nallowed-tools:\n  - Read\n  - Grep` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| flow-list-colon | skill | `name: flow-list-colon\ndescription: use when: x\nallowed-tools: [Read, Grep]` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| bom | skill | `<BOM>name: bom\ndescription: simple text` | loads: "simple text" | loads | R0 strict YAML loads it |
| bom-colon | skill | `<BOM>name: bom-colon\ndescription: use when: x` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| crlf | skill | `name: crlf\r\ndescription: simple text` | loads: "simple text" | loads | R0 strict YAML loads it |
| crlf-colon | skill | `name: crlf-colon\r\ndescription: use when: x` | rejects: mapping values are not allowed here | rejects: Unexpected token | R2 CRLF: the trailing CR stops the key line matching, so nothing is re-quoted |
| crlf-colon-dq-apostrophe-emdash | skill | `name: crlf-colon-dq-apostrophe-emdash\r\ndescription: phrases "don't do x", "y z": more — end` | rejects: mapping values are not allowed here | rejects: Unexpected token | R2 CRLF: the trailing CR stops the key line matching, so nothing is re-quoted |
| crlf-list-colon | skill | `name: crlf-list-colon\r\ndescription: use when: x\r\nallowed-tools:\r\n  - Read` | rejects: mapping values are not allowed here | rejects: Unexpected token | R2 CRLF: the trailing CR stops the key line matching, so nothing is re-quoted |
| tab-continuation | skill | `name: tab-continuation\ndescription: first\n\tsecond` | rejects: while scanning for the next token | loads | R6 tab indentation is accepted |
| tab-list | skill | `name: tab-list\ndescription: d\nallowed-tools:\n\t- Read` | rejects: while scanning for the next token | loads | R6 tab indentation is accepted |
| flow-start-colon | skill | `name: flow-start-colon\ndescription: [a: b` | rejects: while parsing a flow sequence | loads | R1 fallback re-quotes the key line's value |
| brace-start-colon | skill | `name: brace-start-colon\ndescription: {a: b` | rejects: while parsing a flow mapping | loads | R1 fallback re-quotes the key line's value |
| at-start-colon | skill | `name: at-start-colon\ndescription: @a: b` | rejects: while scanning for the next token | loads | R1 fallback re-quotes the key line's value |
| backtick-start-colon | skill | `` name: backtick-start-colon\ndescription: `a`: b `` | rejects: while scanning for the next token | loads | R1 fallback re-quotes the key line's value |
| star-start-colon | skill | `name: star-start-colon\ndescription: *a: b` | rejects: found undefined alias 'a' | loads | R1 fallback re-quotes the key line's value |
| amp-start-colon | skill | `name: amp-start-colon\ndescription: &a: b` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| backslash-colon | skill | `name: backslash-colon\ndescription: a\b: c` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| colon-then-key | skill | `name: colon-then-key\ndescription: a: b\nmodel: sonnet` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| dup-key | skill | `name: dup-key\ndescription: a\ndescription: b` | loads: "b" | loads | R0 strict YAML loads it |
| key-colon-only-junk | skill | `name: key-colon-only-junk\ndescription: a\nnot a key line` | rejects: while scanning a simple key | rejects: Unexpected token | R8 a column-0 line that is not `key:` stays invalid |
| indented-key-colon | skill | `name: indented-key-colon\ndescription: a\n  nested: b: c` | rejects: mapping values are not allowed here | rejects: Unexpected token | R3 only a column-0 `key: value` line with a key of letters, `_`, `-` is re-quoted |
| hyphen-key-colon | skill | `name: hyphen-key-colon\ndescription: d\nargument-hint: a: b` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| underscore-key-colon | skill | `name: underscore-key-colon\ndescription: d\nmy_key: a: b` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| digit-key-colon | skill | `name: digit-key-colon\ndescription: d\nkey2: a: b` | rejects: mapping values are not allowed here | rejects: Unexpected token | R3 only a column-0 `key: value` line with a key of letters, `_`, `-` is re-quoted |
| at-start | skill | `name: at-start\ndescription: @a b` | rejects: while scanning for the next token | loads | R1 fallback re-quotes the key line's value |
| backtick-start | skill | `` name: backtick-start\ndescription: `a` b `` | rejects: while scanning for the next token | loads | R1 fallback re-quotes the key line's value |
| star-start | skill | `name: star-start\ndescription: *a b` | rejects: found undefined alias 'a' | loads | R1 fallback re-quotes the key line's value |
| brace-start | skill | `name: brace-start\ndescription: {a b` | rejects: while parsing a flow mapping | loads | R1 fallback re-quotes the key line's value |
| bracket-start | skill | `name: bracket-start\ndescription: [a b` | rejects: while parsing a flow sequence | loads | R1 fallback re-quotes the key line's value |
| bracket-inside | skill | `name: bracket-inside\ndescription: a [b` | loads: "a [b" | loads | R0 strict YAML loads it |
| pipe-start | skill | `name: pipe-start\ndescription: \|a b` | rejects: while scanning a block scalar | loads | R1 fallback re-quotes the key line's value |
| gt-start | skill | `name: gt-start\ndescription: >a b` | rejects: while scanning a block scalar | loads | R1 fallback re-quotes the key line's value |
| percent-start | skill | `name: percent-start\ndescription: %a b` | rejects: while scanning for the next token | loads | R1 fallback re-quotes the key line's value |
| bang-start-junk | skill | `name: bang-start-junk\ndescription: !a !b c` | rejects: while parsing a block mapping | loads | R1 fallback re-quotes the key line's value |
| quoted-both-ends-colon | skill | `name: quoted-both-ends-colon\ndescription: "a" b: "c"` | rejects: while parsing a block mapping | rejects: Unexpected token | R4 a value that starts and ends with a quote is left alone |
| sq-both-ends-colon | skill | `name: sq-both-ends-colon\ndescription: 'a' b: 'c'` | rejects: while parsing a block mapping | rejects: Unexpected token | R4 a value that starts and ends with a quote is left alone |
| backslash-bad-escape-colon | skill | `name: backslash-bad-escape-colon\ndescription: a\q: c` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| upper-key-colon | skill | `name: upper-key-colon\ndescription: d\nFoo: a: b` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| two-space-colon | skill | `name: two-space-colon\ndescription:  a: b` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| tab-after-key-colon | skill | `name: tab-after-key-colon\ndescription:\ta: b` | rejects: while scanning for the next token | loads | R1 fallback re-quotes the key line's value |
| trailing-space-colon | skill | `name: trailing-space-colon\ndescription: a: b   ` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| colon-in-list-item | skill | `name: colon-in-list-item\ndescription: d\nallowed-tools:\n  - a: b: c` | rejects: mapping values are not allowed here | rejects: Unexpected token | R3 only a column-0 `key: value` line with a key of letters, `_`, `-` is re-quoted |
| agent-colon | agent | `name: agent-colon\ndescription: use when: it breaks\ntools: Read, Grep` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| agent-dq-inside-colon | agent | `name: agent-dq-inside-colon\ndescription: Use it. "a b, c d" then e: f\ntools: Read, mcp__s__t` | rejects: mapping values are not allowed here | loads | R1 fallback re-quotes the key line's value |
| agent-crlf-colon | agent | `name: agent-crlf-colon\r\ndescription: use when: it breaks` | rejects: mapping values are not allowed here | rejects: Unexpected token | R2 CRLF: the trailing CR stops the key line matching, so nothing is re-quoted |
| agent-crlf-plain | agent | `name: agent-crlf-plain\r\ndescription: plain` | loads: "plain" | loads | R0 strict YAML loads it |
