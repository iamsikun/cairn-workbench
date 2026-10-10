# Automatic updates

Cairn keeps itself and its knowledge-base skills current the same way Finch and Quill
do: a release is the `stable` branch of the repository, identified by its version
number. The owner authorizes automatic updates once. After that, a new release is
adopted without a per-release review, and every knowledge base keeps an exact,
recorded binding to the release it runs.

## What updates, and how

| Component | Source | Check | What changes |
|---|---|---|---|
| Cairn runtime | `stable` branch, when its version increases | hourly job and each `cairn` start, at most every 24 h | a new verified runtime; each registered knowledge base is rebound to it |
| Knowledge-base Quill | Quill's `stable` branch | same run | the Cairn-managed copy in `<kb>/.claude/skills/quill` |
| Finch | Finch's own installer | Finch's daily job; also invoked by each run | Finch's machine-wide clone |

The schedule and the launch-time check only start `cairn update run --if-due`. No
model, worker or packet takes part in updating, and paper processing never installs
software.

## Releasing

Development happens on `main`. Managed installs track `stable` and adopt it only when
its version is higher than the installed one. A release follows the same steps as
Quill's:

1. Run `bash scripts/check.sh`.
2. Bump the version in both places, which must agree: `version` in `pyproject.toml`
   and `__version__` in `src/cairn/__init__.py`. Use semantic versioning as defined in
   `CHANGELOG.md`.
3. Add an entry to `CHANGELOG.md`.
4. Commit, tag, and publish:

   ```sh
   git tag vX.Y.Z
   git push origin main vX.Y.Z
   git push origin main:stable      # this is the release; it fast-forwards stable
   ```

Commits on `stable` without a version bump are not adopted. Never force-push `stable`:
an update must build on the installed commit, so rewritten history stops updates with
a "stable must only fast-forward" error. Updates never move to a lower or equal version.

## One-time setup

Requirements: `git`, `uv`, and a local Docker engine (the worker image is built from
each release). The paths below are synthetic examples.

1. Bootstrap the managed runtime from a checkout of `stable`:

   ```sh
   git clone --branch stable https://github.com/iamsikun/cairn-workbench.git
   cd cairn-workbench && uv run cairn update setup
   ```

   `setup` writes `CAIRN_HOME/updater.json` (default `~/.local/share/cairn`). It builds
   and installs the current `stable` release and adds `~/.local/bin/cairn`, which always
   runs `CAIRN_HOME/current`. It also installs the job (`launchd` on macOS, `cron`
   elsewhere; `--no-schedule` skips it). `--repository` and `--ref` select another
   channel; re-running `setup` changes them.

2. Create the knowledge base with the managed runtime and opt in:

   ```sh
   cairn init --workspace /srv/cairn --code-root /srv/cairn-workbench \
     --statement "I reviewed this release, continuity trial, and recovery procedure." \
     --acknowledge release_review --acknowledge manual_continuity \
     --acknowledge backup_restore --auto-update
   ```

   From a managed runtime, `--release`/`--release-sha256` default to the bundle it was
   installed from. The first activation still requires the three owner
   acknowledgements and a fresh isolation probe. `--auto-update` (or later
   `cairn update enable --workspace PATH`) records an `UpdateAuthorization` in the
   knowledge base, naming the repository, the branch and the owner statement. It also
   registers the knowledge base for updates.

## What one update run does

1. Fetches the channel branch into a bare mirror (`CAIRN_HOME/source.git`).
2. Reads the version from the branch head. It continues only if the version is higher
   than the current runtime's and the head builds on the current commit. It then
   exports that exact tree.
3. Builds the worker image (`docker build --target base`) and a release bundle for this
   machine (`scripts/build_release.py`), and checks that the manifest's revision and
   source hash match the exported tree.
4. Installs the bundle offline, with hashes, into `CAIRN_HOME/runtimes/<sha256>/`. Then
   runs the new runtime's `release check-runtime`, `release check-worker` and a synthetic
   `init`. Any failure removes the new runtime and keeps the current one.
5. For each registered knowledge base, the **new** runtime runs `update rebind`. Under the
   writer lock it verifies itself. It confirms that the release commit is on the branch
   named in that knowledge base's own authorization and declares the expected version,
   and that the version is higher than the previous binding's. It recomputes the source
   hash, runs a fresh 13-check worker probe, and writes a backup to
   `CAIRN_HOME/backups/<workspace>/`. Then it writes an `upgrade` runtime approval that
   names the previous approval, the authorization, the version and the backup digest.
   Replacing `workspace.json` is the commit point. Supported schema migrations then run
   automatically, each with its own backup; they invalidate pending proposals, which are
   regenerated from preserved sources.
6. Switches `CAIRN_HOME/current`, keeps the previous runtime and any runtime a knowledge
   base is still bound to, and removes older ones.
7. Fast-forwards the managed skill clones and refreshes the managed copies.

The next `cairn` command prints a one-line notice such as `Cairn updated to v0.3.0
(was v0.2.0).` A rebind failure is reported in `cairn update status`. That knowledge
base keeps its previous, valid binding, and `cairn` automatically runs it with the
runtime it is bound to. The next run retries the rebind.

Every open re-checks the approval chain: each `upgrade` approval must name an
authorization of this workspace and lead back to an owner-acknowledged `init` or
`restore`.

## Commands

```text
cairn update status                         channel, current/running runtime, knowledge bases, skills
cairn update run [--if-due] [--quiet]       check now
cairn update enable  --workspace PATH       opt a knowledge base in (records an authorization)
cairn update disable --workspace PATH       opt out (records a revocation; binding stays valid)
cairn update schedule [--off]               install or remove the periodic job
cairn update setup                          install or reconfigure the managed runtime
```

Set `CAIRN_NO_AUTO_UPDATE=1` to suppress the launch-time check for one shell.

## Managed Quill

On a private `init`/`restore`, Quill (unless already machine-wide) is installed into the
knowledge base as a Cairn-managed copy. It is generated from a pristine clone of Quill's
`stable` branch (`CAIRN_HOME/skills/quill`), plus Cairn's writing handoff
(`references/cairn-workflow.md` and a short section in `SKILL.md`). The clone is never
edited, so it always fast-forwards. A copy is replaced only while it still matches the
bytes Cairn recorded in its `.cairn-managed.json`. Owner edits are reported as
`locally_modified` and kept. A Quill directory Cairn did not create is left alone and
only receives the handoff, as before. If Quill cannot be fetched at setup, the bundled
snapshot is installed and the next successful run moves it to the channel. Synthetic
setups install the bundled snapshot and are not registered.

## Restore and rollback

A pre-upgrade backup is bound to the release it was taken under. Restore it with that
runtime (`CAIRN_HOME/runtimes/<old sha256>/venv/bin/python -I -B -m cairn restore ...`),
which is kept while it is the previous runtime or still bound. Restoring an upgraded
archive works with the release it names. There is no automatic downgrade. To stop
updates, use `cairn update disable` and `cairn update schedule --off`.

## Trust and limits

- Authority comes from the owner's standing authorization and the channel branch.
  Anyone who can push to `stable` in the configured repository can ship code that runs
  on the knowledge base within a day. Restrict who can push to `stable`, block force
  pushes and deletions, and protect the GitHub account with two-factor authentication.
- The updater builds the wheel and worker image locally from the exported tree. The
  manifest is bound to that tree's source hash, and the build's dependencies come from
  its locked hashes. This does not detect a compromised repository, host, Docker
  engine, uv or Python.
- Skill updates follow each skill's upstream `stable` branch over HTTPS, like Finch's
  and Quill's own updaters. They change agent guidance, not Cairn's runtime or
  canonical records; every handoff is still validated and staged as a proposal for
  the owner.
- Development and tests use a synthetic `CAIRN_HOME` and local synthetic remotes.
  Contributor code never runs `setup`, `run` or the scheduler against a real home.
