# Automatic updates

Cairn can keep itself and its knowledge-base skills current, like a self-updating
terminal application. The owner authorizes this once. Each later release is adopted
without a per-release review, but only if it carries a tag signed by a key the owner
listed. Every knowledge base keeps an exact, recorded binding to the release it runs.

## What updates, and how

| Component | Source | Check | What changes |
|---|---|---|---|
| Cairn runtime | signed `vX.Y.Z` tags on the `stable` branch | hourly job and each `cairn` start, at most every 24 h | a new verified runtime; each registered knowledge base is rebound to it |
| Knowledge-base Quill | Quill's `stable` branch | same run | the Cairn-managed copy in `<kb>/.claude/skills/quill` |
| Finch | Finch's own installer | Finch's daily job; also invoked by each run | Finch's machine-wide clone |

The schedule and the launch-time check only start `cairn update run --if-due`. No
model, worker or packet takes part in updating, and paper processing never installs
software.

## One-time setup

Requirements: `git`, `ssh-keygen`, `uv`, and a local Docker engine (the worker image is
built from each release). The paths below are synthetic examples.

1. Release signing (on the machine that publishes Cairn). Configure SSH tag signing
   and keep the public key in an allowed-signers file:

   ```sh
   git config gpg.format ssh
   git config user.signingkey ~/.ssh/cairn_release_ed25519.pub
   printf 'owner@example.invalid namespaces="git" %s\n' \
     "$(cat ~/.ssh/cairn_release_ed25519.pub)" > ~/.config/cairn/allowed_signers
   ```

   Publish a release by moving `stable` and pushing a signed tag:

   ```sh
   git switch stable && git merge --ff-only main
   git tag -s v0.2.0 -m "Cairn 0.2.0" && git push origin stable v0.2.0
   ```

   Only annotated tags named `vMAJOR.MINOR.PATCH`, with exactly one SSH signature by an
   allowed key, whose embedded tag name matches the ref, and whose commit is on `stable`
   are accepted. Tags are tried newest first; an unverifiable tag is skipped and reported.
   Updates never move to an older or equal version.

2. Bootstrap the managed runtime from a checkout of a signed tag:

   ```sh
   git clone https://github.com/iamsikun/cairn-workbench.git && cd cairn-workbench
   git -c gpg.ssh.allowedSignersFile=$HOME/.config/cairn/allowed_signers verify-tag v0.2.0
   git checkout v0.2.0
   uv run cairn update setup --signers ~/.config/cairn/allowed_signers
   ```

   `setup` writes `CAIRN_HOME/updater.json` (default `~/.local/share/cairn`). It builds
   and installs the newest signed release and adds `~/.local/bin/cairn`, which always
   runs `CAIRN_HOME/current`. It also installs the job (`launchd` on macOS, `cron`
   elsewhere; `--no-schedule` skips it). Re-running `setup` changes the channel or keys.

3. Create the knowledge base with the managed runtime and opt in:

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
   knowledge base: the channel, the signer keys and the owner statement. It also
   registers the knowledge base for updates.

## What one update run does

1. Fetches the channel branch and tags into a bare mirror (`CAIRN_HOME/source.git`).
2. Picks the newest signed tag above the current runtime and exports that exact tree.
3. Builds the worker image (`docker build --target base`) and a release bundle for this
   machine (`scripts/build_release.py`), and checks that the manifest's revision and
   source hash match the signed tree.
4. Installs the bundle offline, with hashes, into `CAIRN_HOME/runtimes/<sha256>/`. Then
   runs the new runtime's `release check-runtime`, `release check-worker` and a synthetic
   `init`. Any failure removes the new runtime and keeps the current one.
5. For each registered knowledge base, the **new** runtime runs `update rebind`. Under the
   writer lock it verifies itself and re-verifies the tag against the signer list
   stored *in that knowledge base*, not the machine configuration. It recomputes the
   source hash from the signed tree, runs a fresh 13-check worker probe, and writes a
   backup to `CAIRN_HOME/backups/<workspace>/`. Then it writes an `upgrade` runtime
   approval that names the previous approval, the authorization, the tag, the signer
   and the backup digest. Replacing `workspace.json` is the commit point. Supported
   schema migrations then run automatically, each with its own backup; they invalidate
   pending proposals, which are regenerated from preserved sources.
6. Switches `CAIRN_HOME/current`, keeps the previous runtime and any runtime a knowledge
   base is still bound to, and removes older ones.
7. Fast-forwards the managed skill clones and refreshes the managed copies.

The next `cairn` command prints a one-line notice such as `Cairn updated to v0.3.0
(was v0.2.0).` A rebind failure is reported in `cairn update status`. That knowledge
base keeps its previous, valid binding, and `cairn` automatically runs it with the
runtime it is bound to. The next run retries the rebind.

Every open re-checks the approval chain: each `upgrade` approval must name an
authorization of this workspace whose key list contains the recorded signer, and lead
back to an owner-acknowledged `init` or `restore`.

## Commands

```text
cairn update status                         channel, current/running runtime, knowledge bases, skills
cairn update run [--if-due] [--quiet]       check now
cairn update enable  --workspace PATH       opt a knowledge base in (records an authorization)
cairn update disable --workspace PATH       opt out (records a revocation; binding stays valid)
cairn update schedule [--off]               install or remove the periodic job
cairn update setup --signers FILE           install or reconfigure the managed runtime
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

- Authority comes from the owner's standing authorization and the release signature.
  Anyone holding an allowed signing key can ship code that runs on the knowledge base.
  Keep the key offline or on a hardware token.
- The updater builds the wheel and worker image locally from the signed tree. The
  manifest is bound to that tree's source hash, and the build's dependencies come from
  its locked hashes. This does not detect a compromised host, Docker engine, uv or
  Python.
- Skill updates follow each skill's upstream `stable` branch over HTTPS without
  signatures, like Finch's own updater. They change agent guidance, not Cairn's
  runtime or canonical records; every handoff is still validated and staged as a
  proposal for the owner.
- Development and tests use a synthetic `CAIRN_HOME`, local synthetic remotes and
  throwaway keys. Contributor code never runs `setup`, `run` or the scheduler against
  a real home.
