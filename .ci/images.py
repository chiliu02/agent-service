"""Build, verify and publish the three implementation images.

    uv run --no-project python .ci/images.py                 # build + verify
    uv run --no-project python .ci/images.py --push          # ... and publish
    uv run --no-project python .ci/images.py --only gemini-python

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
    if build == "gemini-python":
        out = _run("docker", "run", "--rm", "--entrypoint", "gemini", image,
                   "--version", check=False, quiet=True)
        return out.strip().splitlines()[-1] if out.strip() else "unknown"
    package = "claude-agent-sdk" if build == "claude-python" else "openai-codex"
    return _run("docker", "run", "--rm", "--entrypoint", "python", image, "-c",
                f"from importlib.metadata import version; print(version('{package}'))",
                check=False, quiet=True).strip() or "unknown"


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
    args = parser.parse_args()

    builds = [b for b in BUILDS if args.only in (None, b[0])]
    if not builds:
        raise SystemExit(f"no such build: {args.only}")

    summary: list[dict[str, str]] = []
    for build, extra in builds:
        image = build_image(build, force=args.force)
        if not args.skip_verify:
            verify(build, image, extra)
        digest = push(image) if args.push else ""
        summary.append({"image": image, "digest": digest,
                        "agent": agent_version(build, image)})

    print("\n  --- for the availability note " + "-" * 40)
    for row in summary:
        print(f"  {row['image']:<44} agent {row['agent']:<10} {row['digest']}")
    if args.push:
        print("\n  The note names the image BARE. The registry address belongs to")
        print("  the reader -- see versioning.md §5.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
