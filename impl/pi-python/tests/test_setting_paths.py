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

from agent_service.pi import PiError, PiRunner, compose_project_context
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
    # **The named directory resolves to the skill file inside it** (`PI-60`).
    assert skills == ((persona / "SKILL.md").resolve(),)


def test_a_directory_of_several_skills_is_searched_to_any_depth(tmp_path: Path) -> None:
    """The agent recurses, so a caller may mount one skills root (`PI-59`).

    **Resolved to the files, not the directory** (`PI-60`): one walk, ours,
    decides both what was validated and what the agent is handed.
    """
    root = tmp_path / "skills"
    skill(root / "alpha", "alpha")
    skill(root / "nested" / "beta", "beta")

    _, skills = resolve_setting_paths(Paths(skills=[str(root)]))
    assert skills == (
        (root / "alpha" / "SKILL.md").resolve(),
        (root / "nested" / "beta" / "SKILL.md").resolve(),
    )


def test_a_skill_may_be_named_as_the_file_itself(tmp_path: Path) -> None:
    persona = skill(tmp_path / "persona", "persona")
    _, skills = resolve_setting_paths(Paths(skills=[str(persona / "SKILL.md")]))
    assert skills == ((persona / "SKILL.md").resolve(),)


# --- layering (`PI-60`) ------------------------------------------------------


def test_a_later_entry_shadows_an_earlier_one_declaring_the_same_name(
    tmp_path: Path,
) -> None:
    """**The case the old refusal broke** (`PI-60`).

    User scope mounted outside the workspace, project scope inside it, both
    declaring `review`. That is layered configuration, not a mistake, and the
    caller's own order says which wins.
    """
    user = tmp_path / "user"
    project = tmp_path / "project"
    skill(user / "review", "review")
    skill(user / "only-user", "only-user")
    skill(project / "review", "review")

    _, skills = resolve_setting_paths(
        Paths(skills=[str(user), str(project)])
    )
    assert (project / "review" / "SKILL.md").resolve() in skills
    assert (user / "review" / "SKILL.md").resolve() not in skills
    # The unshadowed one survives, so shadowing is per NAME and not per entry.
    assert (user / "only-user" / "SKILL.md").resolve() in skills


def test_the_winner_takes_the_later_position(tmp_path: Path) -> None:
    """Announced where the entry that supplied it sits (`PI-60`)."""
    user = tmp_path / "user"
    project = tmp_path / "project"
    skill(user / "review", "review")
    skill(user / "zzz", "zzz")
    skill(project / "review", "review")

    _, skills = resolve_setting_paths(Paths(skills=[str(user), str(project)]))
    assert skills == (
        (user / "zzz" / "SKILL.md").resolve(),
        (project / "review" / "SKILL.md").resolve(),
    )


def test_a_duplicate_name_under_ONE_entry_is_still_refused(tmp_path: Path) -> None:
    """**Where the order runs out** (`PI-60`).

    There is nothing inside a single named path to decide it with, so keeping
    either would be traversal order deciding -- the thing `PI-59` refuses.
    """
    root = tmp_path / "skills"
    skill(root / "one", "persona")
    skill(root / "two", "persona")
    with pytest.raises(InvalidSettingPath) as refused:
        resolve_setting_paths(Paths(skills=[str(root)]))
    assert "'persona'" in str(refused.value)
    assert "declared twice" in str(refused.value)


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
        tmp_path / "agent" / "instructions.md"
    )


def test_every_named_skill_gets_its_own_flag_and_the_briefs_get_one(
    tmp_path: Path,
) -> None:
    """`PI-60` for skills, `PI-63` for instructions -- and they differ on purpose.

    A skill is a file the agent loads by path, so one flag each. Instructions
    are one labelled BLOCK with a single header, so they are composed into one
    file and named once.
    """
    argv = runner(
        tmp_path,
        instruction_paths=(Path("/a.md"), Path("/b.md")),
        skill_paths=(Path("/one"), Path("/two")),
    ).argv("hi", sdk_session_id=None, resume=None)
    assert argv.count("--skill") == 2
    assert argv.count("--append-system-prompt") == 1


def test_the_composed_block_labels_each_file_the_way_the_agent_does(
    tmp_path: Path,
) -> None:
    """`PI-63`: the wrapper is the agent's own, reproduced byte for byte.

    Text reaching `--append-system-prompt` is wrapped in nothing, so before this
    a caller's two named files arrived as one anonymous run of prose -- while
    the agent's own loader labels every context file with its path.
    """
    user = tmp_path / "user.md"
    user.write_text("# User\nUSER-MARKER\n", encoding="utf-8")
    project = tmp_path / "project.md"
    project.write_text("# Project\nPROJECT-MARKER\n", encoding="utf-8")

    composed = compose_project_context((user, project))

    assert composed.startswith(
        "<project_context>\n\nProject-specific instructions and guidelines:\n\n"
    )
    assert composed.endswith("</project_context>\n")
    assert f'<project_instructions path="{user}">\n# User\nUSER-MARKER\n\n' \
           "</project_instructions>" in composed
    # Order is the caller's, broad tree first, and it survives the wrapping.
    assert composed.index("USER-MARKER") < composed.index("PROJECT-MARKER")


def test_the_composed_file_is_written_beside_models_json(tmp_path: Path) -> None:
    """`PI-63`: `argv` names it and `write_config` writes it; one path, one place."""
    brief = tmp_path / "brief.md"
    brief.write_text("BRIEF-MARKER\n", encoding="utf-8")
    run = runner(tmp_path, instruction_paths=(brief,))
    run.write_config()
    written = (tmp_path / "agent" / "instructions.md").read_text(encoding="utf-8")
    assert "BRIEF-MARKER" in written
    assert f'<project_instructions path="{brief}">' in written
    argv = run.argv("hi", sdk_session_id=None, resume=None)
    assert argv[argv.index("--append-system-prompt") + 1] == str(
        tmp_path / "agent" / "instructions.md"
    )


def test_nothing_named_composes_nothing(tmp_path: Path) -> None:
    """A deployment that names no brief gets an agent dir without the file."""
    run = runner(tmp_path)
    run.write_config()
    assert not (tmp_path / "agent" / "instructions.md").exists()


def test_a_mount_that_vanishes_under_the_session_is_named(tmp_path: Path) -> None:
    """`PI-63`: `PI-59` stats at creation, and a turn is later. Say so, do not guess."""
    gone = tmp_path / "gone.md"
    gone.write_text("x", encoding="utf-8")
    run = runner(tmp_path, instruction_paths=(gone,))
    gone.unlink()
    with pytest.raises(PiError, match="went away under the session"):
        run.write_config()


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


def test_the_composed_file_is_written_with_lf_only(tmp_path: Path) -> None:
    """`PI-63`: `write_text` translates newlines, and the agent's own does not.

    Without `newline=""` this build put a carriage return on every line of the
    wrapper on a Windows host and none in the image -- a difference no test that
    reads the file back as text can see, because the read translates them again.
    """
    brief = tmp_path / "brief.md"
    brief.write_text("one\ntwo\n", encoding="utf-8", newline="")
    run = runner(tmp_path, instruction_paths=(brief,))
    run.write_config()
    raw = (tmp_path / "agent" / "instructions.md").read_bytes()
    assert b"\r\n" not in raw
    assert raw.count(b"\n") > 5
