import json
from pathlib import Path

from rigcheck.discover import MEMORY_INDEX_BYTES, discover, memory_dir
from rigcheck.model import LoadClass
from rigcheck.parse.markdown import strip_html_comments
from rigcheck.parse.tokens import DESCRIPTION_CHARS_PER_TOKEN, INSTRUCTION_CHARS_PER_TOKEN, estimate
from rigcheck.report import budget
from support import Workspace, write

PLUGIN = "tools@market"


def _instructions(text: str) -> int:
    return estimate(text, INSTRUCTION_CHARS_PER_TOKEN)


def _description(text: str) -> int:
    return estimate(text, DESCRIPTION_CHARS_PER_TOKEN)


def _skill(home: Path, name: str, frontmatter: str) -> Path:
    return write(home / ".claude" / "skills" / name / "SKILL.md", f"---\n{frontmatter}---\n\nBody.\n")


def _install_plugin(workspace: Workspace) -> None:
    install = workspace.home / "plugin-cache" / "tools"
    write(install / "skills" / "lint" / "SKILL.md", "---\nname: lint\ndescription: Lint.\n---\n")
    write(install / "agents" / "reviewer.md", "---\nname: reviewer\ndescription: Reviews.\n---\n")
    write(install / "commands" / "go.md", "Go.\n")
    write(install / ".claude-plugin" / "plugin.json", '{"name": "tools"}\n')
    installed = {"version": 2, "plugins": {PLUGIN: [{"scope": "user", "installPath": str(install)}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))


def test_every_turn_rows_are_the_every_turn_artifacts(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n\n" + "Use uv.\n" * 40)
    write(workspace.home / ".claude" / "CLAUDE.md", "# Me\n")
    _skill(workspace.home, "lint", "name: lint\ndescription: Lint.\n")
    rig = discover(repo, workspace.home)
    result = budget.compute(rig, 200_000)
    every_turn = {artifact.path for artifact in rig.artifacts if artifact.load_class is LoadClass.EVERY_TURN}
    assert {source.path for source in result.every_turn.sources} == every_turn
    assert [source.path for source in result.every_turn.sources] == [repo / "CLAUDE.md", workspace.home / ".claude" / "CLAUDE.md"]
    assert result.every_turn.sources[0].tokens_est == _instructions((repo / "CLAUDE.md").read_text(encoding="utf-8"))
    assert result.every_turn.total_est == sum(source.tokens_est for source in result.every_turn.sources)


def test_memory_index_counts_only_its_loaded_head(workspace: Workspace) -> None:
    repo = workspace.rig()
    lines = [f"- [Entry {index:03d}](entry-{index:03d}.md) - a remembered fact\n" for index in range(250)]
    index_path = write(memory_dir(repo, workspace.home) / "MEMORY.md", "".join(lines))
    result = budget.compute(discover(repo, workspace.home), 200_000)
    row = next(source for source in result.every_turn.sources if source.path == index_path)
    assert row.tokens_est == _instructions("".join(lines[:200]))


def test_memory_index_cuts_at_25000_bytes(workspace: Workspace) -> None:
    repo = workspace.rig()
    text = ("- " + "é" * 200 + "\n") * 100
    index_path = write(memory_dir(repo, workspace.home) / "MEMORY.md", text)
    result = budget.compute(discover(repo, workspace.home), 200_000)
    row = next(source for source in result.every_turn.sources if source.path == index_path)
    head = text.encode("utf-8")[:MEMORY_INDEX_BYTES].decode("utf-8", errors="ignore")
    assert len(text) < MEMORY_INDEX_BYTES < len(text.encode("utf-8"))
    assert row.tokens_est == _instructions(head)


def test_html_comments_do_not_count(workspace: Workspace) -> None:
    repo = workspace.rig()
    text = "# Project\n\n<!-- " + "maintainer note " * 50 + "-->\n\nUse uv.\n"
    write(repo / "CLAUDE.md", text)
    result = budget.compute(discover(repo, workspace.home), 200_000)
    assert result.every_turn.total_est == _instructions(strip_html_comments(text))
    assert result.every_turn.total_est < _instructions(text)


def test_skill_listing_counts_name_description_and_when_to_use(workspace: Workspace) -> None:
    _skill(workspace.home, "lint", "name: lint\ndescription: Lints the code.\nwhen_to_use: Before every commit.\n")
    result = budget.compute(discover(workspace.rig(), workspace.home), 200_000)
    assert result.skill_listing.entries == 1
    assert result.skill_listing.tokens_est == _description("lint: Lints the code. Before every commit.")


def test_skill_listing_cuts_description_at_1536_characters(workspace: Workspace) -> None:
    _skill(workspace.home, "big", "description: " + "x" * 1400 + "\nwhen_to_use: " + "y" * 600 + "\n")
    result = budget.compute(discover(workspace.rig(), workspace.home), 200_000)
    assert result.skill_listing.tokens_est == _description("big: " + ("x" * 1400 + " " + "y" * 600)[:1536])


def test_disabled_model_invocation_is_not_listed(workspace: Workspace) -> None:
    _skill(workspace.home, "deploy", "name: deploy\ndescription: Deploys.\ndisable-model-invocation: true\n")
    _skill(workspace.home, "lint", "name: lint\ndescription: Lints.\n")
    result = budget.compute(discover(workspace.rig(), workspace.home), 200_000)
    assert result.skill_listing.entries == 1
    assert result.skill_listing.tokens_est == _description("lint: Lints.")


def test_commands_count_as_listing_entries(workspace: Workspace) -> None:
    write(workspace.home / ".claude" / "commands" / "ship.md", "---\ndescription: Ship it.\n---\n\nShip.\n")
    write(workspace.home / ".claude" / "commands" / "plain.md", "Plain command body.\n")
    result = budget.compute(discover(workspace.rig(), workspace.home), 200_000)
    assert result.skill_listing.entries == 2
    assert result.skill_listing.tokens_est == _description("ship: Ship it.") + _description("plain")


def test_plugin_entries_have_their_own_subtotal(workspace: Workspace) -> None:
    _install_plugin(workspace)
    _skill(workspace.home, "fmt", "name: fmt\ndescription: Formats.\n")
    result = budget.compute(discover(workspace.rig(), workspace.home), 200_000)
    plugin_listing = _description("lint: Lint.") + _description("go")
    assert result.skill_listing.by_layer == {"user": _description("fmt: Formats."), "plugin": plugin_listing}
    assert result.skill_listing.entries == 3
    assert result.agent_descriptions.by_layer == {"plugin": _description("reviewer: Reviews.")}


def test_agent_frontmatter_strict_yaml_rejects_still_counts(workspace: Workspace) -> None:
    agents = workspace.home / ".claude" / "agents"
    write(agents / "fixer.md", "---\nname: fixer\ndescription: Use when: a thing: breaks\n---\n\nFix it.\n")
    write(agents / "unclosed.md", "---\nname: never\n\ndescription: Not frontmatter.\n")
    result = budget.compute(discover(workspace.rig(), workspace.home), 200_000)
    assert result.agent_descriptions.entries == 2
    assert result.agent_descriptions.tokens_est == _description("fixer: Use when: a thing: breaks") + _description("unclosed")
    assert result.agent_descriptions.budget == 15_000


def test_listing_budget_is_one_percent_of_the_window(workspace: Workspace) -> None:
    rig = discover(workspace.rig(), workspace.home)
    assert budget.compute(rig, 200_000).skill_listing.budget == 2_000
    assert budget.compute(rig, 1_000_000).skill_listing.budget == 10_000
