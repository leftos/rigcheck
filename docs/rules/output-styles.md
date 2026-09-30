# Output styles

Output styles (`output-styles/*.md` in the repo, user and plugin layers) are checked for unknown frontmatter keys and for a missing `keep-coding-instructions`, which decides whether the style keeps Claude Code's built-in coding instructions. The rules are in `src/rigcheck/rules/output_styles.py`; the recognised keys (`name`, `description`, `keep-coding-instructions`, `force-for-plugin`) are `OUTPUT_STYLE_KEYS` in `src/rigcheck/rules/components.py`. How frontmatter is read is in [`frontmatter-and-rules-dir.md`](frontmatter-and-rules-dir.md).

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `output-style-key-unknown` | warn | `official:OS1` |
| `output-style-drops-coding` | warn | `official:OS2` |

Both rules run on every layer.

## Design

- `output-style-key-unknown` reports every string key outside the four recognised keys, with a "did you mean" for a case or `-`/`_` variant.
- `force-for-plugin` works only in a plugin's output style, so outside a plugin it is itself reported under `output-style-key-unknown`, and a misspelling of it outside a plugin gets no "did you mean".
- `output-style-drops-coding` fires when `keep-coding-instructions` is absent, including a style with no frontmatter and one whose frontmatter Claude Code rejects, because then the style drops the built-in coding instructions. It is silent when the key has any value, `false` included, since that states the choice, and when a case or `-`/`_` variant of the key is present, which `output-style-key-unknown` reports instead.
