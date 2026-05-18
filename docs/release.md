# Releasing imail to PyPI

The release pipeline lives in [`.github/workflows/release.yml`](../.github/workflows/release.yml).
It triggers on a `v*` tag push, builds sdist + wheel, publishes to PyPI via
Trusted Publishing (no API token in repo secrets), and attaches the artefacts
to a GitHub release.

## One-time setup (already done — record kept here for the next maintainer)

PyPI **Trusted Publisher** binding ties the GitHub workflow file to a PyPI
project, so the workflow can mint a short-lived OIDC token at publish time
instead of carrying a long-lived API token.

1. Sign in at <https://pypi.org/manage/account/publishing/>
2. Click **Add a new pending publisher**.
3. Fill in:

   | Field          | Value                          |
   |----------------|--------------------------------|
   | PyPI project   | `imail`                        |
   | Owner          | `jessecu2024`                  |
   | Repository     | `imail`                        |
   | Workflow       | `release.yml`                  |
   | Environment    | `pypi`                         |

4. After the first successful publish, the project will exist and the
   "pending" publisher converts to a regular one. Subsequent releases need
   no further PyPI-side action.

If PyPI rejects the name `imail` as already taken, fall back to
`imail-cli` (update `pyproject.toml [project] name` and the `url:` in
release.yml — environment URL would become `https://pypi.org/p/imail-cli`).
The CLI entry point and the import name `imail` can stay regardless of the
distribution name.

## Cutting a release

1. Bump `version` in `pyproject.toml`. Follow semver:
   - `feat:` PR(s) since last tag → bump minor.
   - `fix:` or `chore:` only → bump patch.
   - Anything that changes a public API or breaks an existing flow →
     bump major (still allowed pre-1.0 for tightening).
2. Commit the bump:
   ```bash
   git commit -am "chore: bump to v1.3.0"
   git push
   ```
3. Tag it (must match `vMAJOR.MINOR.PATCH`, leading `v`):
   ```bash
   git tag v1.3.0
   git push origin v1.3.0
   ```
4. Watch the release workflow at
   <https://github.com/jessecu2024/imail/actions/workflows/release.yml>.
   It will:
   - re-run the test suite (acts as the final pre-publish gate)
   - build the wheel + sdist
   - upload them to PyPI
   - create a GitHub release with auto-generated notes + the artefacts.
5. Verify: `pipx install imail==1.3.0` on a clean machine, run `imail`.

## What gets shipped

The hatchling build pulls in the entire `src/imail/` tree, including the
`static/` assets (icon, wordmark, CSS, JS, HTML). End users get a single
`pip install imail` and the bundled web UI runs out of the box. The
`uv.lock` file is **not** shipped — runtime resolution is governed by
`pyproject.toml` deps so users can pick up newer transitive patch
versions.
