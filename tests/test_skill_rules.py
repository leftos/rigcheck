"""The skill and command frontmatter rules: placement, parse, keys, description and reachability."""

import json
import os
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import Layer
from rigcheck.report.budget import LISTING_DETAIL_CHARS
from rigcheck.rules import REGISTRY
from support import Workspace, git_add, symlink_or_skip, write

SKILL = Path(".claude") / "skills" / "demo" / "SKILL.md"
COMMAND = Path(".claude") / "commands" / "x.md"
PLUGIN = "tools@market"


def _file(frontmatter: str) -> str:
    return f"---\n{frontmatter}---\n\nBody.\n"


def _run(workspace: Workspace, rule_id: str) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home), REGISTRY.values())
    return [(finding.message, finding.line) for finding in findings if finding.rule_id == rule_id]


def _findings(workspace: Workspace, rule_id: str, text: str, path: Path = SKILL) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / path, text)
    return _run(workspace, rule_id)


def _misplaced(line: int) -> str:
    return f"the frontmatter starts on line {line}, so Claude Code reads the whole file as content and no field is set"


def test_misplaced_after_a_blank_line_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-misplaced", "\n---\nname: a\n---\n") == [(_misplaced(2), 2)]


def _not_exact(opening: str) -> str:
    return f'the opening line is "{opening}", not exactly ---, so Claude Code reads the whole file as content and no field is set'


def test_misplaced_indented_fence_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-misplaced", " ---\nname: a\n---\n") == [(_not_exact(" ---"), 1)]


def test_misplaced_fence_with_a_trailing_space_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-misplaced", "--- \nname: a\n---\n") == [(_not_exact("--- "), 1)]


def test_misplaced_after_a_heading_is_not_frontmatter(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-misplaced", "# Title\n\n---\n") == []


def test_misplaced_rule_without_a_closing_fence_is_a_horizontal_rule(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-misplaced", "\n---\n\n# Notes\n") == []


def test_misplaced_on_line_one_passes(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-misplaced", "---\nname: a\n---\n") == []


def _rejected(reason: str) -> str:
    return f"Claude Code rejects the frontmatter ({reason}), so the skill loads with no fields set"


def test_invalid_crlf_colon_fires(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    skill = repo / SKILL
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_bytes(b"---\r\nname: demo\r\ndescription: use when: x\r\n---\r\n\r\nBody.\r\n")
    assert _run(workspace, "skill-frontmatter-invalid") == [(_rejected("mapping values are not allowed here"), 3)]


def test_invalid_lf_colon_loads_through_the_retry(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-invalid", _file("name: demo\ndescription: use when: x\n")) == []


def test_invalid_unclosed_fires_on_line_one(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-invalid", "---\nname: a\n") == [(_rejected("unclosed frontmatter"), 1)]


def _unknown(key: str, known: str | None, line: int) -> tuple[str, int]:
    hint = f' (did you mean "{known}"?)' if known else ""
    return f'unknown key "{key}"{hint}; Claude Code ignores it', line


def _unknown_findings(workspace: Workspace, frontmatter: str, path: Path = SKILL) -> list[tuple[str, int | None]]:
    return _findings(workspace, "skill-key-unknown", _file(frontmatter), path)


def test_unknown_snake_case_suggests_the_hyphenated_key(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "name: a\nallowed_tools: Read\n") == [_unknown("allowed_tools", "allowed-tools", 3)]


def test_unknown_camel_case_suggests_the_hyphenated_key(workspace: Workspace) -> None:
    expected = [_unknown("disableModelInvocation", "disable-model-invocation", 2)]
    assert _unknown_findings(workspace, "disableModelInvocation: true\n") == expected


def test_unknown_hyphenated_when_to_use_suggests_the_underscore_key(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "when-to-use: x\n") == [_unknown("when-to-use", "when_to_use", 2)]


def test_unknown_key_without_a_near_match_has_no_suggestion(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "tags: x\n") == [_unknown("tags", None, 2)]


def test_unknown_capitalised_key_suggests_the_lower_case_key(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "Description: x\n") == [_unknown("Description", "description", 2)]


def test_unknown_non_string_key_is_reported_as_text(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "1: x\n") == [_unknown("1", None, 2)]


def test_unknown_skips_name_and_paths_in_a_command(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "name: x\npaths: src/**\n", COMMAND) == []


def test_unknown_key_in_a_command_fires(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "allowed_tools: Read\n", COMMAND) == [_unknown("allowed_tools", "allowed-tools", 2)]


def test_unknown_key_in_a_plugin_skill_fires(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    install = workspace.home / "plugin-cache" / "tools"
    write(install / "skills" / "lint" / "SKILL.md", _file("name: lint\ndescription: Lint.\ntags: x\n"))
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "tools"}))
    installed = {"version": 2, "plugins": {PLUGIN: [{"scope": "user", "installPath": str(install)}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))
    findings = engine.run(discover(repo, workspace.home), REGISTRY.values())
    fired = [finding for finding in findings if finding.rule_id == "skill-key-unknown"]
    assert [(finding.layer, finding.message, finding.line) for finding in fired] == [(Layer.PLUGIN, _unknown("tags", None, 4)[0], 4)]


MISSING = [("no description, so Claude Code lists the first line of content instead", 1)]


def test_description_missing_without_frontmatter_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", "# Demo\n\nBody.\n") == MISSING


def test_description_missing_key_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", _file("name: demo\n")) == MISSING


def test_description_not_a_string_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", _file("description: 5\n")) == MISSING


def test_description_blank_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", _file('description: "  "\n')) == MISSING


def test_description_missing_skips_rejected_frontmatter(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", "---\nname: a\n") == []


def test_description_present_passes(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", _file("description: Demo.\n")) == []


def test_description_missing_in_a_command_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", "Run the thing.\n", COMMAND) == MISSING


def _truncated(total: int) -> list[tuple[str, int | None]]:
    message = f"description and when_to_use run to {total} characters; the skill listing cuts them at {LISTING_DETAIL_CHARS}"
    return [(message, 2)]


def test_description_at_the_limit_passes(workspace: Workspace) -> None:
    text = _file(f"description: {'a' * 1536}\n")
    assert _findings(workspace, "skill-description-truncated", text) == []


def test_description_past_the_limit_fires(workspace: Workspace) -> None:
    text = _file(f"description: {'a' * 1537}\n")
    assert _findings(workspace, "skill-description-truncated", text) == _truncated(1537)


def test_description_and_when_to_use_count_the_joining_space(workspace: Workspace) -> None:
    text = _file(f"description: {'a' * 1000}\nwhen_to_use: {'b' * 536}\n")
    assert _findings(workspace, "skill-description-truncated", text) == _truncated(1537)


UNREACHABLE = "user-invocable is false and disable-model-invocation is true, so neither you nor Claude can invoke it"


def test_unreachable_booleans_fire(workspace: Workspace) -> None:
    text = _file("user-invocable: false\ndisable-model-invocation: true\n")
    assert _findings(workspace, "skill-unreachable", text) == [(UNREACHABLE, 3)]


def test_unreachable_yes_no_fire(workspace: Workspace) -> None:
    text = _file("disable-model-invocation: yes\nuser-invocable: no\n")
    assert _findings(workspace, "skill-unreachable", text) == [(UNREACHABLE, 2)]


def test_unreachable_string_and_number_fire(workspace: Workspace) -> None:
    text = _file('user-invocable: "false"\ndisable-model-invocation: 1\n')
    assert _findings(workspace, "skill-unreachable", text) == [(UNREACHABLE, 3)]


def test_unreachable_needs_both_settings(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-unreachable", _file("user-invocable: false\n")) == []


def test_unreachable_disable_alone_passes(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-unreachable", _file("disable-model-invocation: true\n")) == []


def test_unreachable_command_fires(workspace: Workspace) -> None:
    text = _file("user-invocable: false\ndisable-model-invocation: true\n")
    assert _findings(workspace, "skill-unreachable", text, COMMAND) == [(UNREACHABLE, 3)]


LINK_RULES = ("skill-link-broken", "skill-link-too-deep", "skill-link-outside", "skill-file-unreferenced")
SKILL_HEAD = "---\nname: demo\ndescription: Demo.\n---\n\n"
"""Frontmatter and a blank line; a link appended to it sits on line 6."""


def _bundle(workspace: Workspace, files: dict[str, str]) -> list[tuple[str, str, str, int | None]]:
    """Write a CLAUDE.md and ``files`` under the demo skill folder; return the SK11 findings as (rule, file, message, line)."""
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    folder = repo / SKILL.parent
    for relative, text in files.items():
        write(folder / relative, text)
    findings = engine.run(discover(repo, workspace.home), REGISTRY.values())
    return [
        (finding.rule_id, os.path.relpath(finding.path, folder).replace("\\", "/"), finding.message, finding.line)
        for finding in findings
        if finding.rule_id in LINK_RULES and finding.path is not None
    ]


def test_skill_link_to_a_bundled_file_passes(workspace: Workspace) -> None:
    assert _bundle(workspace, {"SKILL.md": SKILL_HEAD + "[ref](reference.md)\n", "reference.md": "# Ref\n"}) == []


def test_skill_link_to_a_missing_file_is_broken(workspace: Workspace) -> None:
    found = _bundle(workspace, {"SKILL.md": SKILL_HEAD + "[ref](missing.md)\n"})
    assert found == [("skill-link-broken", "SKILL.md", "the link missing.md points at no file", 6)]


def test_skill_link_to_an_existing_file_outside_the_skill_fires(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "[x](../other/SKILL.md)\n", "../other/SKILL.md": SKILL_HEAD}
    found = _bundle(workspace, files)
    assert found == [("skill-link-outside", "SKILL.md", "the link ../other/SKILL.md points outside the skill folder", 6)]


def test_skill_link_to_a_missing_file_outside_the_skill_is_only_broken(workspace: Workspace) -> None:
    found = _bundle(workspace, {"SKILL.md": SKILL_HEAD + "[x](../other/SKILL.md)\n"})
    assert found == [("skill-link-broken", "SKILL.md", "the link ../other/SKILL.md points at no file", 6)]


def test_skill_link_home_link_is_outside(workspace: Workspace) -> None:
    write(workspace.home / "notes.md", "# Notes\n")
    found = _bundle(workspace, {"SKILL.md": SKILL_HEAD + "[n](~/notes.md)\n"})
    assert found == [("skill-link-outside", "SKILL.md", "the link ~/notes.md points outside the skill folder", 6)]


def test_skill_link_web_and_anchor_links_are_skipped(workspace: Workspace) -> None:
    assert _bundle(workspace, {"SKILL.md": SKILL_HEAD + "[t](https://x.dev/a) and [a](#usage)\n"}) == []


def _deep(workspace: Workspace, skill_links: str) -> list[tuple[str, str, str, int | None]]:
    files = {
        "SKILL.md": SKILL_HEAD + skill_links,
        "reference.md": "# Ref\n\nSee [details](details.md).\n",
        "details.md": "# Details\n",
    }
    return _bundle(workspace, files)


def test_skill_link_file_linked_only_from_a_linked_file_is_too_deep(workspace: Workspace) -> None:
    message = "reference.md links details.md, which SKILL.md does not link, so details.md sits two levels deep"
    assert _deep(workspace, "[ref](reference.md)\n") == [("skill-link-too-deep", "reference.md", message, 3)]


def test_skill_link_file_linked_from_skill_md_too_is_not_too_deep(workspace: Workspace) -> None:
    assert _deep(workspace, "[ref](reference.md) [d](details.md)\n") == []


def test_skill_link_linked_file_linking_back_to_skill_md_passes(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "[ref](reference.md)\n", "reference.md": "# Ref\n\nBack to [the skill](SKILL.md).\n"}
    assert _bundle(workspace, files) == []


def test_skill_link_nested_linked_file_linking_up_to_skill_md_passes(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "[guide](docs/guide.md)\n", "docs/guide.md": "# Guide\n\nBack to [the skill](../SKILL.md).\n"}
    assert _bundle(workspace, files) == []


def test_skill_link_linked_file_linking_a_script_is_not_too_deep(workspace: Workspace) -> None:
    files = {
        "SKILL.md": SKILL_HEAD + "[ref](reference.md)\n",
        "reference.md": "# Ref\n\nRun [the script](scripts/run.py).\n",
        "scripts/run.py": "print(1)\n",
    }
    assert _bundle(workspace, files) == []


def test_skill_link_broken_link_in_a_linked_file_sits_in_that_file(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "[ref](reference.md)\n", "reference.md": "# Ref\n\nSee [gone](gone.md).\n"}
    assert _bundle(workspace, files) == [("skill-link-broken", "reference.md", "the link gone.md points at no file", 3)]


def _script(workspace: Workspace, body: str) -> list[tuple[str, str, str, int | None]]:
    return _bundle(workspace, {"SKILL.md": SKILL_HEAD + body, "scripts/run.py": "print(1)\n"})


def test_skill_file_script_named_in_a_fence_is_referenced(workspace: Workspace) -> None:
    assert _script(workspace, "```bash\npython scripts/run.py --fast\n```\n") == []


def test_skill_file_script_named_in_a_code_span_is_referenced(workspace: Workspace) -> None:
    assert _script(workspace, "Use `scripts/run.py` to run it.\n") == []


def test_skill_file_script_folder_linked_is_referenced(workspace: Workspace) -> None:
    assert _script(workspace, "See [scripts](scripts/).\n") == []


def test_skill_file_script_named_from_a_linked_file_is_referenced(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "[ref](reference.md)\n", "reference.md": "Run `scripts/run.py`.\n", "scripts/run.py": "print(1)\n"}
    assert _bundle(workspace, files) == []


def test_skill_file_script_named_nowhere_is_unreferenced(workspace: Workspace) -> None:
    message = "scripts/run.py is not named by SKILL.md or a file it links, so Claude has no pointer to it"
    assert _script(workspace, "Body.\n") == [("skill-file-unreferenced", "scripts/run.py", message, None)]


def test_skill_file_license_dotfiles_and_bytecode_are_not_unreferenced(workspace: Workspace) -> None:
    files = {
        "SKILL.md": SKILL_HEAD,
        "LICENSE.txt": "MIT\n",
        ".gitignore": "*.pyc\n",
        "__pycache__/x.pyc": "x",
        "cache.pyc": "x",
        "agents/openai.yaml": "interface: {}\n",
        "agents/notes.txt": "x\n",
        "UPSTREAM.md": "# Upstream\n",
        "README.md": "# Readme\n",
        "NOTICE": "Notice\n",
        "node_modules/pkg/index.js": "x\n",
        "env/pyvenv.cfg": "home = x\n",
        "env/lib/site.py": "x\n",
        "CHANGELOG.md": "# Changelog\n",
        "nested/SKILL.md": SKILL_HEAD,
        "nested/extra.md": "# Extra\n",
    }
    assert _bundle(workspace, files) == []


@pytest.mark.parametrize("prefix", ["${CLAUDE_SKILL_DIR}/", "$CLAUDE_SKILL_DIR/", "{baseDir}/"])
def test_skill_link_placeholder_resolves_against_the_skill_folder(workspace: Workspace, prefix: str) -> None:
    files = {"SKILL.md": SKILL_HEAD + f"[r]({prefix}references/a.md)\n", "references/a.md": "# A\n"}
    assert _bundle(workspace, files) == []


@pytest.mark.parametrize("prefix", ["${CLAUDE_SKILL_DIR}/", "{baseDir}/"])
def test_skill_link_placeholder_to_a_missing_file_is_broken(workspace: Workspace, prefix: str) -> None:
    found = _bundle(workspace, {"SKILL.md": SKILL_HEAD + f"[r]({prefix}references/a.md)\n"})
    assert found == [("skill-link-broken", "SKILL.md", f"the link {prefix}references/a.md points at no file", 6)]


def test_skill_file_placeholder_code_span_is_referenced(workspace: Workspace) -> None:
    assert _script(workspace, "Run `${CLAUDE_SKILL_DIR}/scripts/run.py`.\n") == []


def test_skill_link_in_a_linked_file_falls_back_to_the_skill_folder(workspace: Workspace) -> None:
    files = {
        "SKILL.md": SKILL_HEAD + "[a](references/a.md)\n",
        "references/a.md": "# A\n\nSee [b](references/b.md).\n",
        "references/b.md": "# B\n",
    }
    message = "references/a.md links references/b.md, which SKILL.md does not link, so references/b.md sits two levels deep"
    assert _bundle(workspace, files) == [("skill-link-too-deep", "references/a.md", message, 3)]


def test_skill_file_named_in_a_command_span_is_referenced(workspace: Workspace) -> None:
    assert _script(workspace, "Run `python scripts/run.py --x` first.\n") == []


def test_skill_file_named_from_a_span_named_file_is_referenced(workspace: Workspace) -> None:
    files = {
        "SKILL.md": SKILL_HEAD + "Read `references/a.md` first.\n",
        "references/a.md": "# A\n\nRun [the script](../scripts/run.py).\n",
        "scripts/run.py": "print(1)\n",
    }
    assert _bundle(workspace, files) == []


@pytest.mark.parametrize("line", ["@role.md", "Follow @${CLAUDE_SKILL_DIR}/role.md now.", "@./role.md"])
def test_skill_file_named_by_an_import_is_referenced(workspace: Workspace, line: str) -> None:
    assert _bundle(workspace, {"SKILL.md": SKILL_HEAD + line + "\n", "role.md": "# Role\n"}) == []


def test_skill_file_named_by_an_import_in_a_linked_file_is_referenced(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "[ref](reference.md)\n", "reference.md": "See @scripts/run.py\n", "scripts/run.py": "print(1)\n"}
    assert _bundle(workspace, files) == []


def test_skill_file_named_by_agent_metadata_is_referenced(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD, "agents/openai.yaml": "icon: ./assets/mark.svg\n", "assets/mark.svg": "<svg/>\n"}
    assert _bundle(workspace, files) == []


def test_skill_file_named_nowhere_beside_agent_metadata_is_unreferenced(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD, "agents/openai.yaml": "icon: none\n", "assets/mark.svg": "<svg/>\n"}
    message = "assets/mark.svg is not named by SKILL.md or a file it links, so Claude has no pointer to it"
    assert _bundle(workspace, files) == [("skill-file-unreferenced", "assets/mark.svg", message, None)]


def test_skill_link_network_path_never_reaches_the_filesystem(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    touched: list[str] = []
    real_exists, real_is_file = Path.exists, Path.is_file

    def exists(self: Path, *, follow_symlinks: bool = True) -> bool:
        if "nohost" in str(self):
            touched.append(str(self))
        return real_exists(self, follow_symlinks=follow_symlinks)

    def is_file(self: Path, *, follow_symlinks: bool = True) -> bool:
        if "nohost" in str(self):
            touched.append(str(self))
        return real_is_file(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setattr(Path, "is_file", is_file)
    body = "[x](//nohost/share/x.md) `\\\\nohost\\share\\y.md` [z](/nohost/z.md)\n"
    assert _bundle(workspace, {"SKILL.md": SKILL_HEAD + body}) == []
    assert touched == []


def _unreferenced(name: str) -> tuple[str, str, str, None]:
    message = f"{name} is not named by SKILL.md or a file it links, so Claude has no pointer to it"
    return ("skill-file-unreferenced", name, message, None)


def test_skill_file_name_inside_a_longer_name_is_not_a_mention(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "```bash\ncat data.md\n```\n", "a.md": "# A\n", "data.md": "# Data\n"}
    assert _bundle(workspace, files) == [_unreferenced("a.md")]


def test_skill_file_folder_inside_a_longer_folder_is_not_a_mention(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "```bash\npython metadata/x.py\n```\n", "data/y.py": "x\n"}
    assert _bundle(workspace, files) == [_unreferenced("data/y.py")]


def test_skill_file_path_under_a_folder_does_not_mention_the_top_file(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "```bash\npython scripts/run.py\n```\n", "scripts/run.py": "x\n", "run.py": "x\n"}
    assert _bundle(workspace, files) == [_unreferenced("run.py")]


def test_skill_file_code_mention_after_a_placeholder_or_dot_slash_counts(workspace: Workspace) -> None:
    body = "```bash\npython ./scripts/a.py && python ${CLAUDE_SKILL_DIR}/scripts/b.py\n```\n"
    files = {"SKILL.md": SKILL_HEAD + body, "scripts/a.py": "x\n", "scripts/b.py": "x\n"}
    assert _bundle(workspace, files) == []


def test_skill_file_code_path_through_the_skill_folder_counts(workspace: Workspace) -> None:
    body = "```bash\nuv run --project ~/.claude/skills/demo/scripts/tool/ tool && python ~/.claude/skills/demo/run.py\n```\n"
    files = {"SKILL.md": SKILL_HEAD + body, "scripts/tool/cli.py": "x\n", "run.py": "x\n"}
    assert _bundle(workspace, files) == []


def test_skill_file_backslash_paths_in_code_count(workspace: Workspace) -> None:
    body = "```powershell\npython scripts\\a.py\n```\n\nThen `${CLAUDE_SKILL_DIR}\\scripts\\b.py`.\n"
    files = {"SKILL.md": SKILL_HEAD + body, "scripts/a.py": "x\n", "scripts/b.py": "x\n"}
    assert _bundle(workspace, files) == []


def test_skill_file_image_is_a_reference(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "![logo](assets/logo.png)\n", "assets/logo.png": "png\n"}
    assert _bundle(workspace, files) == []


def test_skill_link_broken_image_is_broken(workspace: Workspace) -> None:
    found = _bundle(workspace, {"SKILL.md": SKILL_HEAD + "![logo](assets/logo.png)\n"})
    assert found == [("skill-link-broken", "SKILL.md", "the link assets/logo.png points at no file", 6)]


def test_skill_file_symlinked_folder_is_not_walked(workspace: Workspace) -> None:
    elsewhere = write(workspace.home / "elsewhere" / "x.txt", "x\n").parent
    repo = workspace.rig()
    link = repo / SKILL.parent / "shared"
    link.parent.mkdir(parents=True, exist_ok=True)
    symlink_or_skip(link, str(elsewhere))
    assert _bundle(workspace, {"SKILL.md": SKILL_HEAD}) == []


def test_skill_file_resolved_link_names_only_its_target(workspace: Workspace) -> None:
    files = {
        "SKILL.md": SKILL_HEAD + "[guide](docs/guide.md)\n",
        "docs/guide.md": "# Guide\n\nSee [b](b.md).\n",
        "docs/b.md": "# B\n",
        "b.md": "# Top B\n",
    }
    too_deep = "docs/guide.md links b.md, which SKILL.md does not link, so docs/b.md sits two levels deep"
    assert sorted(_bundle(workspace, files)) == sorted([("skill-link-too-deep", "docs/guide.md", too_deep, 3), _unreferenced("b.md")])


def test_skill_link_placeholder_link_is_decoded(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "[r](${CLAUDE_SKILL_DIR}/a%20b.md)\n", "a b.md": "# A\n"}
    assert _bundle(workspace, files) == []


def test_skill_link_placeholder_link_is_decoded_only_once(workspace: Workspace) -> None:
    """``%2520`` decodes once to ``%20``, a name with a placeholder character, so it never reaches ``a b.md``."""
    files = {"SKILL.md": SKILL_HEAD + "[r](${CLAUDE_SKILL_DIR}/a%2520b.md)\n", "a b.md": "# A\n"}
    assert _bundle(workspace, files) == [_unreferenced("a b.md")]


def test_skill_link_url_encoded_placeholder_resolves(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "[r](%7BbaseDir%7D/references/a.md)\n", "references/a.md": "# A\n"}
    assert _bundle(workspace, files) == []


def test_skill_link_nested_skill_md_is_not_too_deep(workspace: Workspace) -> None:
    files = {"SKILL.md": SKILL_HEAD + "[ref](reference.md)\n", "reference.md": "See [sub](sub/SKILL.md).\n", "sub/SKILL.md": SKILL_HEAD}
    assert _bundle(workspace, files) == []


def test_skill_link_repeated_broken_link_on_one_line_fires_once(workspace: Workspace) -> None:
    found = _bundle(workspace, {"SKILL.md": SKILL_HEAD + "[a](missing.md) and [b](missing.md)\n"})
    assert found == [("skill-link-broken", "SKILL.md", "the link missing.md points at no file", 6)]


def test_skill_link_outside_from_a_linked_file_sits_in_that_file(workspace: Workspace) -> None:
    files = {
        "SKILL.md": SKILL_HEAD + "[ref](reference.md)\n",
        "reference.md": "See [other](../other/SKILL.md).\n",
        "../other/SKILL.md": SKILL_HEAD,
    }
    found = _bundle(workspace, files)
    assert found == [("skill-link-outside", "reference.md", "the link ../other/SKILL.md points outside the skill folder", 1)]


def test_skill_file_binary_linked_markdown_does_not_crash(workspace: Workspace) -> None:
    repo = workspace.rig()
    binary = repo / SKILL.parent / "reference.md"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"\x00\xff\xfe[x](gone.md)\x00\x89PNG\r\n")
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / SKILL, SKILL_HEAD + "[ref](reference.md)\n")
    findings = engine.run(discover(repo, workspace.home), REGISTRY.values())
    assert [finding.message for finding in findings if finding.rule_id == "internal-error"] == []


def test_skill_file_git_ignored_files_are_skipped(workspace: Workspace) -> None:
    repo = workspace.rig()
    folder = repo / SKILL.parent
    write(repo / ".gitignore", "*.log\n")
    write(folder / "debug.log", "x\n")
    write(folder / "notes.txt", "x\n")
    write(folder / "SKILL.md", SKILL_HEAD)
    git_add(repo, [".gitignore"])
    assert _bundle(workspace, {}) == [_unreferenced("notes.txt")]


def test_skill_link_broken_link_in_a_plugin_skill_fires(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    install = workspace.home / "plugin-cache" / "tools"
    write(install / "skills" / "lint" / "SKILL.md", SKILL_HEAD + "[ref](missing.md)\n")
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "tools"}))
    installed = {"version": 2, "plugins": {PLUGIN: [{"scope": "user", "installPath": str(install)}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))
    findings = engine.run(discover(repo, workspace.home), REGISTRY.values())
    fired = [finding for finding in findings if finding.rule_id in LINK_RULES]
    assert [(finding.rule_id, finding.layer, finding.message, finding.line) for finding in fired] == [
        ("skill-link-broken", Layer.PLUGIN, "the link missing.md points at no file", 6)
    ]
