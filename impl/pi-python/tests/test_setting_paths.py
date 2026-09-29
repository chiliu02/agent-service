"""`setting_paths`: what the caller named, and every mistake the agent hides.

**The refusals are the feature, so they are most of this file** (`PI-59`). The
agent accepts all four of the mistakes below and reports none of them -- exit 0,
empty stderr, nothing in the event stream -- which is why they are checked here
instead. The worst is the last: an instructions path that does not exist is
appended to the system prompt AS THE PATH STRING, so the turn runs with a brief
that is the name of the brief.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_service.pi import PiRunner
from agent_service.registry import InvalidSettingPath, resolve_setting_paths

FAKE = (sys.executable, str(Path(__file__).parent / "fake_pi_agent.py"))


class Paths:
    """The shape `RunOptions.setting_paths` arrives in, without the model."""

    def __init__(self, instructions: list[str] | None = None,
                 skills: list[str] | None = None) -> None:
        self.instructions = instructions
        self.skills = skills


def skill(directory: Path, name: str, *, frontmatter: bool = True,
          description: bool = True) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    body = f"---\nname: {name}\n"
    if description:
        body += f"description: What {name} does and when to use it.\n"
    body += "---\n\nbody\n"
    (directory / "SKILL.md").write_text(body if frontmatter else "no frontmatter\n",
                                        encoding="utf-8")
    return directory


# --- what is accepted --------------------------------------------------------


def test_nothing_sent_resolves_to_nothing(tmp_path: Path) -> None:
    assert resolve_setting_paths(None) == ((), ())
    assert resolve_setting_paths(Paths()) == ((), ())


def test_a_named_file_and_a_named_skill_directory_resolve(tmp_path: Path) -> None:
    brief = tmp_path / "brief.md"
    brief.write_text("# brief\n", encoding="utf-8")
    persona = skill(tmp_path / "skills" / "persona", "persona")

    instructions, skills = resolve_setting_paths(
        Paths(instructions=[str(brief)], skills=[str(persona)])
    )
    assert instructions == (brief.resolve(),)
    assert skills == (persona.resolve(),)


def test_a_directory_of_several_skills_is_searched_to_any_depth(tmp_path: Path) -> None:
    """The agent recurses, so a caller may mount one skills root (`PI-59`)."""
    root = tmp_path / "skills"
    skill(root / "alpha", "alpha")
    skill(root / "nested" / "beta", "beta")

    _, skills = resolve_setting_paths(Paths(skills=[str(root)]))
    assert skills == (root.resolve(),)


def test_a_skill_may_be_named_as_the_file_itself(tmp_path: Path) -> None:
    persona = skill(tmp_path / "persona", "persona")
    _, skills = resolve_setting_paths(Paths(skills=[str(persona / "SKILL.md")]))
    assert skills == ((persona / "SKILL.md").resolve(),)


# --- the four silent mistakes ------------------------------------------------


def test_a_missing_instructions_path_is_refused_rather_than_appended(
    tmp_path: Path,
) -> None:
    """**The worst of them** (`PI-59`).

    `--append-system-prompt` reads its argument from disk when the argument
    names an existing file and takes it as LITERAL TEXT when it does not. So a
    mount that failed does not produce a session without a brief; it produces
    one whose brief is the path it was asked to read, as text, and the turn runs.
    """
    with pytest.raises(InvalidSettingPath) as refused:
        resolve_setting_paths(Paths(instructions=[str(tmp_path / "absent.md")]))
    assert "does not exist" in str(refused.value)
    assert "absent.md" in str(refused.value)


def test_a_missing_skill_path_is_refused(tmp_path: Path) -> None:
    """The agent loads nothing, exits zero and says nothing (`PI-59`)."""
    with pytest.raises(InvalidSettingPath) as refused:
        resolve_setting_paths(Paths(skills=[str(tmp_path / "absent")]))
    assert "does not exist" in str(refused.value)


def test_a_skill_directory_holding_no_skill_file_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "skills"
    empty.mkdir()
    with pytest.raises(InvalidSettingPath) as refused:
        resolve_setting_paths(Paths(skills=[str(empty)]))
    assert "no `SKILL.md`" in str(refused.value)


def test_a_skill_without_frontmatter_is_refused(tmp_path: Path) -> None:
    """Dropped by the agent with no diagnostic on any channel (`PI-59`)."""
    broken = skill(tmp_path / "broken", "broken", frontmatter=False)
    with pytest.raises(InvalidSettingPath) as refused:
        resolve_setting_paths(Paths(skills=[str(broken)]))
    assert "frontmatter" in str(refused.value)


def test_a_skill_without_a_description_is_refused(tmp_path: Path) -> None:
    """**Both keys, because the agent silently requires both** (`PI-59`)."""
    nameless = skill(tmp_path / "nameless", "nameless", description=False)
    with pytest.raises(InvalidSettingPath) as refused:
        resolve_setting_paths(Paths(skills=[str(nameless)]))
    assert "description" in str(refused.value)


def test_two_skills_sharing_a_name_are_refused(tmp_path: Path) -> None:
    """The agent keeps the first it reaches and drops the other (`PI-59`)."""
    skill(tmp_path / "one", "persona")
    skill(tmp_path / "two", "persona")
    with pytest.raises(InvalidSettingPath) as refused:
        resolve_setting_paths(
            Paths(skills=[str(tmp_path / "one"), str(tmp_path / "two")])
        )
    assert "'persona'" in str(refused.value)


def test_a_relative_path_is_refused_rather_than_resolved(tmp_path: Path) -> None:
    """**No root it could hang off** (`PI-59`).

    The workspace is the caller's mount and `working_directory` is itself a
    request field, so any base chosen here would silently change meaning when
    that field moved.
    """
    with pytest.raises(InvalidSettingPath) as refused:
        resolve_setting_paths(Paths(instructions=["brief.md"]))
    assert "absolute" in str(refused.value)


def test_a_directory_is_refused_for_instructions(tmp_path: Path) -> None:
    with pytest.raises(InvalidSettingPath) as refused:
        resolve_setting_paths(Paths(instructions=[str(tmp_path)]))
    assert "not a regular file" in str(refused.value)


# --- the command line --------------------------------------------------------


def runner(tmp_path: Path, **kwargs) -> PiRunner:
    return PiRunner(binary=FAKE, workspace=tmp_path, agent_dir=tmp_path / "agent",
                    session_dir=tmp_path / "sessions", **kwargs)


def test_named_paths_become_flags_and_the_suppression_stays(tmp_path: Path) -> None:
    """**Both at once, which is the whole claim** (`PI-59`).

    Suppressing discovery and reading a named path are not alternatives: the
    three flags are unconditional and these add to them. Measured against the
    real agent -- with a path named, the workspace's own `AGENTS.md` was still
    absent from the system prompt.
    """
    argv = runner(
        tmp_path,
        instruction_paths=(Path("/harness/brief.md"),),
        skill_paths=(Path("/harness/skills/persona"),),
    ).argv("hi", sdk_session_id=None, resume=None)

    assert "--no-skills" in argv
    assert "--no-extensions" in argv
    assert "--no-context-files" in argv
    assert argv[argv.index("--skill") + 1] == str(Path("/harness/skills/persona"))
    assert argv[argv.index("--append-system-prompt") + 1] == str(
        Path("/harness/brief.md")
    )


def test_each_named_path_gets_its_own_flag(tmp_path: Path) -> None:
    argv = runner(
        tmp_path,
        instruction_paths=(Path("/a.md"), Path("/b.md")),
        skill_paths=(Path("/one"), Path("/two")),
    ).argv("hi", sdk_session_id=None, resume=None)
    assert argv.count("--skill") == 2
    assert argv.count("--append-system-prompt") == 2


def test_nothing_named_adds_no_flag(tmp_path: Path) -> None:
    """A request that sends nothing behaves exactly as it did before the field."""
    argv = runner(tmp_path).argv("hi", sdk_session_id=None, resume=None)
    assert "--skill" not in argv
    assert "--append-system-prompt" not in argv


def test_the_replacement_framing_and_the_named_brief_coexist(tmp_path: Path) -> None:
    """`PI-20`'s flag and `PI-59`'s are different flags and both are passed.

    Measured on the real agent: with `--system-prompt` replacing the framing,
    the named brief and the named skills are still appended after it.
    """
    argv = runner(
        tmp_path,
        system_prompt="REPLACED",
        instruction_paths=(Path("/harness/brief.md"),),
    ).argv("hi", sdk_session_id=None, resume=None)
    assert argv[argv.index("--system-prompt") + 1] == "REPLACED"
    assert "--append-system-prompt" in argv
