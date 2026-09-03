<!--
Keep the description short. This repository's reasoning lives in commit
messages and in the code, not in tracking documents — write it where it will
still be found in a year.
-->

## What changed, and why

<!-- One or two sentences. The "why" is the half that cannot be recovered from
the diff. -->

## Checks

- [ ] `uv run --no-project python .ci/ci.py --fast` is green
- [ ] `uv run --no-project python .ci/ci.py` is green — **required if this
      touches anything container-shaped** (Dockerfile, compose, boot gates,
      the published document)
- [ ] Tests added or updated. Behaviour a client can observe belongs in
      `spec/conformance/`, where all three builds are held to it; anything
      else goes in that build's own suite

## If this touches the published surface

- [ ] All three OpenAPI documents regenerated, and the computed core checked
- [ ] [`docs/capability-divergence.md`](../docs/capability-divergence.md)
      updated **in this same change** — it is the only place the three builds
      are shown side by side, and it is the thing that goes stale silently
- [ ] Widening or breaking change stated explicitly in the commit message
- [ ] No version was cut. Snapshots are free; moving `spec/VERSION` to a bare
      number, bumping a `pyproject.toml` version, or tagging an image are
      maintainer decisions — see [`docs/versioning.md`](../docs/versioning.md)

## If this adds a code comment that cites something

- [ ] It cites an ID in that build's own references file (`CP-nnn` / `CX-nn` /
      `GP-nn`) and nothing else — no paths, no other build's documents
- [ ] `impl/common/` and `spec/conformance/` cite nothing at all
- [ ] The referenced entry exists and is self-contained
