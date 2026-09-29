"""Build, verify and publish the three implementation images.

    uv run --no-project python .ci/images.py                 # build + verify
    uv run --no-project python .ci/images.py --push          # ... and publish
    uv run --no-project python .ci/images.py --only gemini-python
    uv run --no-project python .ci/images.py --prune        # what ages out
    uv run --no-project python .ci/images.py --prune --yes  # ... delete it

**This exists because the procedure was prose and the prose was followed by
hand** (user, 2026-08-19). `versioning.md` §5 has always said to build, verify
against the tag, push, and name the image bare in the note; every one of those
steps was a shell line somebody retyped. The step that was actually forgotten was
the one added last: **removing the `host.docker.internal:5000/` alias after the
push.**

**The alias is an address, not part of the image's identity.** A push needs the
registry hostname inside the tag because there is no `docker push --to`, and once
the push has happened the alias has done its job. Left behind, it reads as a
second image per build in any tool that lists by tag -- which is exactly how it
was noticed.

**The untag runs in a `finally`**, so a push that fails does not leave the alias
behind either. That is the whole reason this is code rather than three lines in a
document: the failure path is where a hand-run procedure stops early.

**Nothing here is authorised by running it.** Building is free; `--push` writes to
the registry, and `versioning.md` §3 makes that the user's call, not a flag's.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The registry, spelled the one way that works from the host AND from inside a
#: container on the consumer's network. `localhost:5000` reaches it from the host
#: only, which is why it is never the spelling used here.
REGISTRY = "host.docker.internal:5000"

#: Each build, and the one container flag that is not shared. Codex confines its
#: agent with bubblewrap, which needs a user namespace that Docker's default
#: seccomp profile refuses -- so its image cannot run a shell command without it.
BUILDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claude-python", ()),
    ("codex-python", ("--security-opt", "seccomp=unconfined")),
    ("gemini-python", ()),
    # **Added after 0.22.0 was tagged, which is how the gap was found.** The
    # fourth build was in `ci.py`'s CONTAINER_IMPLS and not here, so a full CI
    # run exercised its image on every commit while the release tooling could
    # not produce one. Two lists naming the same set is the shape that drifts,
    # and it drifted at the only moment it mattered.
    ("pi-python", ()),
)


def _run(*args: str, check: bool = True, quiet: bool = False) -> str:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(f"FAILED: {' '.join(args)}")
    if not quiet and result.stdout.strip():
        print("   ", result.stdout.strip().splitlines()[-1])
    return result.stdout.strip()


def implementation_version(build: str) -> str:
    """The image tag, read from that build's `pyproject.toml`.

    **Never passed in.** A version typed on a command line is a version that can
    disagree with what the image reports at `capabilities.impl.version`, and the
    two are meant to be the same number.
    """
    pyproject = ROOT / "impl" / build / "pyproject.toml"
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]


def published_digest(build: str, version: str) -> str:
    """What the registry already holds for this tag, or `""` if it holds nothing.

    Read over HTTP rather than by pulling: the question is what the registry
    says, and a pull would answer it by changing the local daemon.
    """
    import urllib.error
    import urllib.request

    url = f"http://localhost:5000/v2/agent-service-{build}/manifests/{version}"
    request = urllib.request.Request(url, method="HEAD")
    request.add_header(
        "Accept", "application/vnd.docker.distribution.manifest.v2+json"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.headers.get("Docker-Content-Digest", "")
    except (urllib.error.URLError, OSError):
        return ""


def registry_tags(build: str) -> list[str]:
    """Every tag the registry holds for one build.

    **An unreachable registry raises; only a 404 returns `[]`.** The difference
    is the whole safety of `prune`: "the repository holds nothing" and "I could
    not ask" produce the same empty list, and one of them would make the prune
    below decide that everything outside the window is already gone.
    """
    import json
    import urllib.error
    import urllib.request

    url = f"http://localhost:5000/v2/agent-service-{build}/tags/list"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return sorted(json.load(response).get("tags") or [], key=_semver)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise SystemExit(f"registry refused {url}: {exc}")
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit(
            f"could not reach the registry at localhost:5000 ({exc}).\n"
            "  Refusing to prune: not knowing what is there is not the same as\n"
            "  knowing it is empty."
        )


def _semver(version: str) -> tuple[int, ...]:
    """Sort key for tags, with anything non-numeric sorting last."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (9999,)


def delete_tag(build: str, version: str) -> bool:
    """Remove one tag from the registry by digest. `False` if it was not there.

    **Deleting a manifest removes every tag that points at it**, which is why
    `prune` checks for a shared digest first. Two releases that built byte
    identical images share one manifest, and deleting the older would take the
    newer with it.
    """
    import urllib.error
    import urllib.request

    digest = published_digest(build, version)
    if not digest:
        return False
    url = f"http://localhost:5000/v2/agent-service-{build}/manifests/{digest}"
    request = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(request, timeout=30):
            return True
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"could not delete agent-service-{build}:{version}: {exc}")


#: The registry runs as this container. Deleting a manifest only unlinks it; the
#: blobs are reclaimed by the registry's own collector, which has to run INSIDE
#: it. Nothing else in this file needs a container name -- a push addresses the
#: registry over HTTP -- so this is the one place the deployment leaks in.
REGISTRY_CONTAINER = "agent-harness-registry"


def garbage_collect() -> None:
    """Reclaim the blobs the deleted manifests referenced.

    **Failure here is reported, not fatal.** The tags are already gone, which is
    what the policy asked for; collection is only how the disk follows. It also
    wants no concurrent push -- the registry cannot notice one arriving mid
    sweep -- so a prune is a quiet-moment operation.
    """
    print(f"\n  collect {REGISTRY_CONTAINER}")
    done = subprocess.run(
        ["docker", "exec", REGISTRY_CONTAINER, "registry", "garbage-collect",
         "--delete-untagged", "/etc/distribution/config.yml"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()
        print("    garbage collection did not run; the tags are still deleted.")
        print(f"    {tail[-1] if tail else 'no output'}")
        return
    freed = [line for line in done.stdout.splitlines() if "eligible for deletion" in line]
    print(f"    {len(freed)} blob(s) collected")


def prune(*, execute: bool) -> int:
    """Delete every image outside the retention window (user, 2026-09-18).

    **The window is imported from `ci.py`, never restated here.** It is defined
    once, as `IMAGE_RETENTION` released versions, and both the audit stage and
    this function ask the same code for it. Two lists naming the same set is the
    shape that drifts, and `BUILDS` above records what that cost last time.

    **A dry run is the default and `--yes` is the gate**, for the same reason
    `--push` is a flag: running this file authorises nothing. A prune is the one
    operation here that destroys rather than creates, and undoing one means
    checking out a release tag and building it again.
    """
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ci

    retained = ci.retained_image_versions()
    if not retained:
        raise SystemExit("the release manifest named no images; refusing to prune")

    print(f"  window  the newest {ci.IMAGE_RETENTION} released versions")
    for build, versions in sorted(retained.items()):
        print(f"    keep  agent-service-{build}: "
              + ", ".join(sorted(versions, key=_semver)))

    present: dict[str, list[str]] = {b: registry_tags(b) for b, _ in BUILDS}
    doomed = [(build, version)
              for build, _extra in BUILDS
              for version in present[build]
              if version not in retained.get(build, set())]

    if not doomed:
        print("\n  nothing to prune: the registry already matches the window")
        return 0

    # A shared manifest would make one DELETE remove a tag the window keeps.
    for build, version in doomed:
        digest = published_digest(build, version)
        sharing = [other for other in present[build]
                   if other != version
                   and other in retained.get(build, set())
                   and published_digest(build, other) == digest]
        if sharing:
            raise SystemExit(
                f"REFUSING to prune agent-service-{build}:{version}: it shares a\n"
                f"  manifest with {', '.join(sharing)}, which the window keeps.\n"
                "  Deleting by digest would remove both."
            )

    print(f"\n  {'delete' if execute else 'would delete'}  {len(doomed)} tag(s)")
    for build, version in doomed:
        print(f"    agent-service-{build}:{version}")

    if not execute:
        print("\n  Dry run. Add --yes to delete. Rebuilding a pruned image means")
        print("  checking out its release tag -- see versioning.md.")
        return 0

    gone = 0
    for build, version in doomed:
        if delete_tag(build, version):
            gone += 1
            print(f"    deleted agent-service-{build}:{version}")
        else:
            print(f"    absent  agent-service-{build}:{version}")
    print(f"\n  {gone} manifest(s) deleted. Blobs stay until collection.")
    garbage_collect()
    return 0


def build_image(build: str, *, force: bool = False) -> str:
    """`docker build`, returning `<image>:<version>`.

    **Refuses to rebuild a version the registry already holds**, unless forced.
    A published tag is never moved -- the rule the whole release process rests on
    -- and a rebuild after a push breaks it quietly at the local end: the tag
    resolves to a new image while the registry still serves the old one, so every
    later `docker run` of that tag exercises something nobody published.

    **Measured, immediately.** Rebuilding `gemini-python:0.0.9` minutes after
    pushing it produced a different image id, because two docstrings had changed
    in between. Nothing warned, and the local tag had to be restored by pulling
    the pushed copy back.
    """
    version = implementation_version(build)
    image = f"agent-service-{build}:{version}"
    existing = published_digest(build, version)
    if existing and not force:
        raise SystemExit(
            f"REFUSING to rebuild {image}: the registry already holds that tag\n"
            f"  at {existing}.\n"
            f"  A published tag is never moved. Bump the version in\n"
            f"  impl/{build}/pyproject.toml and versions.py, or pass --force if\n"
            f"  you mean to replace an image nobody has pulled."
        )
    print(f"\n  build  {image}")
    _run("docker", "build", "-q", "-f", f"impl/{build}/Dockerfile",
         "-t", image, "impl")
    return image


def verify(build: str, image: str, extra: tuple[str, ...]) -> None:
    """Boot gates and the full HTTP suite, **against this tag**.

    `versioning.md` §5 step 2 says to verify the tag rather than a CI image that
    happens to share a commit, and the distinction is not pedantic: the CI images
    are built by a different stage with a different name, so a tag that was never
    built would pass a check that read them.
    """
    print(f"  gates  {image}")
    gates = subprocess.run(
        ["uv", "run", "pytest", "test_boot_gates.py", "-q"],
        cwd=ROOT / "spec" / "conformance", capture_output=True, text=True,
        env={**_env(), "AGENT_SERVICE_TEST_IMAGE": image}, check=False,
    )
    if gates.returncode != 0:
        sys.stdout.write(gates.stdout)
        raise SystemExit(f"FAILED: boot gates against {image}")
    print("   ", gates.stdout.strip().splitlines()[-1])

    workspace = ROOT / "temp" / "image-verify"
    workspace.mkdir(parents=True, exist_ok=True)
    name = f"verify-{build}"
    _run("docker", "rm", "-f", name, check=False, quiet=True)
    print(f"  suite  {image}")
    _run("docker", "run", "-d", "--name", name, *extra, "--cap-drop", "ALL",
         "-p", "127.0.0.1:8797:8000",
         "-e", "AGENT_SERVICE_REQUIRE_CREDENTIALS=false",
         "-v", f"{workspace.as_posix()}:/workspace", image, quiet=True)
    try:
        _wait_for_health()
        suite = subprocess.run(
            ["uv", "run", "pytest", "-q"],
            cwd=ROOT / "spec" / "conformance", capture_output=True, text=True,
            env={**_env(), "AGENT_SERVICE_TEST_BASE_URL": "http://127.0.0.1:8797"},
            check=False,
        )
        if suite.returncode != 0:
            sys.stdout.write(suite.stdout)
            raise SystemExit(f"FAILED: conformance suite against {image}")
        print("   ", suite.stdout.strip().splitlines()[-1])
    finally:
        _run("docker", "rm", "-f", name, check=False, quiet=True)


def push(image: str) -> str:
    """Tag with the registry address, push, **and untag whatever happens.**

    The `finally` is the point of this function. A push that fails part way
    leaves the alias behind exactly as a successful one does, and a procedure
    followed by hand stops at the error -- which is how three of these survived
    long enough to be mistaken for extra images.

    Removing the alias removes a NAME. The image is still referenced by its bare
    tag and the copy in the registry is a separate object that is not touched.
    """
    alias = f"{REGISTRY}/{image}"
    _run("docker", "tag", image, alias, quiet=True)
    try:
        print(f"  push   {alias}")
        out = _run("docker", "push", alias, quiet=True)
        digest = next(
            (part for line in out.splitlines() for part in line.split()
             if part.startswith("sha256:")), "")
        print(f"    {digest or 'pushed'}")
        return digest
    finally:
        _run("docker", "rmi", alias, check=False, quiet=True)
        print(f"  untag  {alias}")


def _env() -> dict[str, str]:
    import os
    return dict(os.environ)


def _wait_for_health(timeout_s: float = 45.0) -> None:
    """Poll `/healthz` rather than sleeping a guessed number of seconds."""
    import time
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8797/healthz", timeout=3):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(1.0)
    raise SystemExit("the container never became healthy on 127.0.0.1:8797")


def agent_version(build: str, image: str) -> str:
    """The bundled agent's version, **read out of the built image**.

    Two of the three are floors rather than pins, so a rebuild can move them with
    nothing in the tree changing. The availability note carries this row because
    the consumer's gateway reads the model vendor's response shape, which no
    document here describes.
    """
    # The two Node agents answer a binary rather than a Python package.
    entrypoint = {"gemini-python": "gemini", "pi-python": "pi"}.get(build)
    if entrypoint:
        out = _run("docker", "run", "--rm", "--entrypoint", entrypoint, image,
                   "--version", check=False, quiet=True)
        return out.strip().splitlines()[-1] if out.strip() else "unknown"
    package = "claude-agent-sdk" if build == "claude-python" else "openai-codex"
    return _run("docker", "run", "--rm", "--entrypoint", "python", image, "-c",
                f"from importlib.metadata import version; print(version('{package}'))",
                check=False, quiet=True).strip() or "unknown"


def _report_partial(summary: list[dict[str, str]], remaining: list[str],
                    *, pushed: bool) -> None:
    """What got done and what did not, printed on the way out of a failed run.

    **Named per mode rather than always saying "pushed".** Without `--push`
    nothing was published and calling the completed ones pushed would be a
    second wrong answer stacked on the first.

    **The not-done list includes the build that just failed**, which is the row
    a reader most needs and the one a summary built from successes alone would
    leave out.
    """
    verb = "PUSHED" if pushed else "BUILT"
    done = [row["image"] for row in summary]
    # **Both lists spelled the same way**, so they can be read against each
    # other. `summary` carries full `<image>:<version>` refs and `remaining`
    # carries bare build names, and a reader comparing two columns that name
    # the same thing differently has to do the translation themselves --
    # at the moment they are least inclined to.
    not_done = []
    for build in remaining:
        try:
            not_done.append(f"agent-service-{build}:{implementation_version(build)}")
        except (OSError, KeyError):
            not_done.append(build)
    print("\n  --- stopped part way " + "-" * 48)
    print(f"  {verb}:     {', '.join(done) if done else '(none)'}")
    print(f"  NOT {verb}: {', '.join(not_done)}")
    if pushed and done:
        print("\n  The registry now holds part of this release. Ask it rather than")
        print("  reading this list back: ci.py --stages artifacts is what checks it.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--push", action="store_true",
                        help="publish to the registry. ASK FIRST")
    parser.add_argument("--only", default=None,
                        help="one build, e.g. gemini-python")
    parser.add_argument("--force", action="store_true",
                        help="rebuild a version the registry already holds. It "
                             "moves a published tag locally; ASK FIRST")
    parser.add_argument("--skip-verify", action="store_true",
                        help="build and push without verifying. For a rebuild "
                             "whose tag was already verified, and nothing else")
    parser.add_argument("--prune", action="store_true",
                        help="delete images outside the retention window. Shows "
                             "the plan; add --yes to carry it out")
    parser.add_argument("--yes", action="store_true",
                        help="with --prune, actually delete. ASK FIRST")
    args = parser.parse_args()

    if args.prune:
        return prune(execute=args.yes)

    builds = [b for b in BUILDS if args.only in (None, b[0])]
    if not builds:
        raise SystemExit(f"no such build: {args.only}")

    summary: list[dict[str, str]] = []
    #: **What has NOT been done yet, so a failure can say so.**
    #:
    #: This loop stops at the first bad build, verify or push, which is right --
    #: but `docker push` is chatty enough that a reader looking at the tail of
    #: the output sees the failure and none of the partial state. A run that
    #: pushed two of four images and stopped looked, from the last thirty lines,
    #: exactly like a run that pushed nothing.
    #:
    #: The exit code was never the problem: `_run` raises `SystemExit` and the
    #: process exits 1. What was missing is the SHAPE of the damage, in the one
    #: place a reader is already looking.
    remaining = [build for build, _ in builds]
    try:
        for build, extra in builds:
            image = build_image(build, force=args.force)
            if not args.skip_verify:
                verify(build, image, extra)
            digest = push(image) if args.push else ""
            summary.append({"image": image, "digest": digest,
                            "agent": agent_version(build, image)})
            remaining.remove(build)
    except BaseException as stopped:
        # **BaseException, because SystemExit is not an Exception.** That is how
        # every failure in here is raised, so catching `Exception` would print
        # nothing for the case this exists for. Ctrl-C lands here too, and a
        # partial state is exactly as worth printing when a human stopped it.
        #
        # **The cause is printed HERE rather than left to the interpreter**, so
        # it lands above the summary instead of below it. Re-raising the original
        # would put the reason after the shape of the damage, which reads
        # backwards and buries the one line naming what went wrong.
        if str(stopped):
            print(f"\n{stopped}")
        _report_partial(summary, remaining, pushed=args.push)
        raise SystemExit(1) from stopped

    print("\n  --- for the availability note " + "-" * 40)
    for row in summary:
        print(f"  {row['image']:<44} agent {row['agent']:<10} {row['digest']}")
    if args.push:
        print("\n  The note names the image BARE. The registry address belongs to")
        print("  the reader -- see versioning.md §5.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
