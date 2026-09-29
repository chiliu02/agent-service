"""The agent-service specification, rendered as pydantic models.

**These models ARE the published document.** `openapi-<version>.json` is
generated from them, AS-24 freezes it once published, and
`test_the_published_spec_file_matches_this_version_of_the_app` fails the build
if a running service serves anything else.

That is why they are here rather than copied into each implementation: **two
hand-maintained copies of 1,000 lines of field descriptions cannot stay
byte-identical**, and any drift is a specification violation that ships rather
than a duplication that annoys.

The version above tracks `spec/VERSION`, not any implementation's build number.
"""
