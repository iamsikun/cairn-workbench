#!/usr/bin/env bash
# Finch installer: one install that stays current.
#
#   curl -fsSL https://raw.githubusercontent.com/iamsikun/finch/stable/install.sh | bash
#
# After installing, the same script is available as the `finch` command:
#   finch status                              show installed version, links, and last update
#   finch update                              fast-forward to the latest stable release (also run daily)
#   finch uninstall                           remove links, the command, scheduled job, and the clone
#   finch install [--no-auto-update]          (re)install: clone, link into every detected agent, schedule updates
#
# Environment overrides:
#   FINCH_HOME  where the clone lives            (default: ~/.local/share/finch)
#   FINCH_REF   branch or tag to track           (default: stable)
#   FINCH_REPO  git URL to clone from            (default: https://github.com/iamsikun/finch.git)
#   FINCH_BIN   directory for the finch command  (default: ~/.local/bin)

set -euo pipefail

FINCH_HOME="${FINCH_HOME:-$HOME/.local/share/finch}"
FINCH_REF="${FINCH_REF:-stable}"
FINCH_REPO="${FINCH_REPO:-https://github.com/iamsikun/finch.git}"
FINCH_BIN="${FINCH_BIN:-$HOME/.local/bin}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/finch"
LOG_FILE="$STATE_DIR/update.log"
LAUNCHD_LABEL="io.github.iamsikun.finch.update"
LAUNCHD_PLIST="$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist"
CRON_MARKER="# finch-auto-update"

say() { printf 'finch: %s\n' "$*"; }
die() { printf 'finch: error: %s\n' "$*" >&2; exit 1; }

skill_src() { printf '%s/skills/finch' "$FINCH_HOME"; }

# Skill directories of agents that appear to be installed. ~/.agents/skills is the
# shared location read by Codex, Gemini CLI, and Cursor.
agent_skill_dirs() {
  [ -d "$HOME/.claude" ] && printf '%s\n' "$HOME/.claude/skills"
  if [ -d "$HOME/.agents" ] || [ -d "$HOME/.codex" ] || [ -d "$HOME/.gemini" ] || [ -d "$HOME/.cursor" ]; then
    printf '%s\n' "$HOME/.agents/skills"
  fi
  [ -d "$HOME/.copilot" ] && printf '%s\n' "$HOME/.copilot/skills"
  [ -d "$HOME/.config/opencode" ] && printf '%s\n' "$HOME/.config/opencode/skills"
  return 0
}

installed_version() {
  sed -n 's/^  version: "\(.*\)"$/\1/p' "$(skill_src)/SKILL.md" 2>/dev/null | head -n1
}

link_skill() {
  local found=0 dir target
  while IFS= read -r dir; do
    [ -n "$dir" ] || continue
    found=1
    target="$dir/finch"
    mkdir -p "$dir"
    if [ -L "$target" ]; then
      ln -sfn "$(skill_src)" "$target"
      say "linked $target"
    elif [ -e "$target" ]; then
      say "skipped $target (already exists and is not a symlink; remove it to let Finch manage it)"
    else
      ln -s "$(skill_src)" "$target"
      say "linked $target"
    fi
  done < <(agent_skill_dirs)
  if [ "$found" -eq 0 ]; then
    say "no supported agent detected; link manually, e.g.:"
    say "  ln -s $(skill_src) ~/.claude/skills/finch"
  fi
}

unlink_skill() {
  local dir target
  for dir in "$HOME/.claude/skills" "$HOME/.agents/skills" "$HOME/.copilot/skills" "$HOME/.config/opencode/skills"; do
    target="$dir/finch"
    if [ -L "$target" ] && [ "$(readlink "$target")" = "$(skill_src)" ]; then
      rm "$target"
      say "removed $target"
    fi
  done
}

# Expose the installed copy of this script as `finch`, so it updates along with the skill.
link_command() {
  local target="$FINCH_BIN/finch"
  mkdir -p "$FINCH_BIN"
  if [ -L "$target" ]; then
    ln -sfn "$FINCH_HOME/install.sh" "$target"
  elif [ -e "$target" ]; then
    say "skipped $target (already exists and is not a symlink); use $FINCH_HOME/install.sh instead"
    return 0
  else
    ln -s "$FINCH_HOME/install.sh" "$target"
  fi
  say "command: $target"
  case ":$PATH:" in
    *":$FINCH_BIN:"*) ;;
    *) say "note: $FINCH_BIN is not on your PATH; add this to your shell profile:"
       say "  export PATH=\"$FINCH_BIN:\$PATH\"" ;;
  esac
}

unlink_command() {
  local target="$FINCH_BIN/finch"
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$FINCH_HOME/install.sh" ]; then
    rm "$target"
    say "removed $target"
  fi
}

schedule_updates() {
  local script="$FINCH_HOME/install.sh"
  mkdir -p "$STATE_DIR"
  case "$(uname -s)" in
    Darwin)
      mkdir -p "$(dirname "$LAUNCHD_PLIST")"
      cat > "$LAUNCHD_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LAUNCHD_LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$script</string><string>update</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>FINCH_HOME</key><string>$FINCH_HOME</string>
    <key>FINCH_REF</key><string>$FINCH_REF</string>
  </dict>
  <key>StartInterval</key><integer>86400</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG_FILE</string>
  <key>StandardErrorPath</key><string>$LOG_FILE</string>
</dict>
</plist>
EOF
      launchctl bootout "gui/$(id -u)/$LAUNCHD_LABEL" 2>/dev/null || true
      launchctl bootstrap "gui/$(id -u)" "$LAUNCHD_PLIST"
      say "daily updates scheduled (launchd: $LAUNCHD_LABEL)"
      ;;
    Linux)
      command -v crontab >/dev/null || { say "crontab not found; run '$script update' to update manually"; return 0; }
      local line="17 9 * * * FINCH_HOME='$FINCH_HOME' FINCH_REF='$FINCH_REF' /bin/bash '$script' update >>'$LOG_FILE' 2>&1 $CRON_MARKER"
      { crontab -l 2>/dev/null | grep -v "$CRON_MARKER" || true; printf '%s\n' "$line"; } | crontab -
      say "daily updates scheduled (cron)"
      ;;
    *)
      say "automatic updates not supported on this OS; run '$script update' to update manually"
      ;;
  esac
}

unschedule_updates() {
  if [ -f "$LAUNCHD_PLIST" ]; then
    launchctl bootout "gui/$(id -u)/$LAUNCHD_LABEL" 2>/dev/null || true
    rm -f "$LAUNCHD_PLIST"
    say "removed launchd job"
  fi
  if command -v crontab >/dev/null && crontab -l 2>/dev/null | grep -q "$CRON_MARKER"; then
    crontab -l 2>/dev/null | grep -v "$CRON_MARKER" | crontab -
    say "removed cron job"
  fi
}

cmd_install() {
  local auto=1
  for arg in "$@"; do
    case "$arg" in
      --no-auto-update) auto=0 ;;
      *) die "unknown option: $arg" ;;
    esac
  done
  command -v git >/dev/null || die "git is required"

  if [ -d "$FINCH_HOME/.git" ]; then
    say "existing install found at $FINCH_HOME; updating"
    cmd_update
  else
    mkdir -p "$(dirname "$FINCH_HOME")"
    git clone --quiet --branch "$FINCH_REF" "$FINCH_REPO" "$FINCH_HOME"
    say "installed Finch $(installed_version) ($FINCH_REF) to $FINCH_HOME"
  fi

  link_skill
  link_command
  if [ "$auto" -eq 1 ]; then
    schedule_updates
  else
    say "automatic updates off; run 'finch update' to update"
  fi
  say "done. Restart your agent to pick up the skill. Run 'finch status' to check it."
}

# Fast-forward only: never discards local edits, never moves to unreleased work.
cmd_update() {
  [ -d "$FINCH_HOME/.git" ] || die "Finch is not installed at $FINCH_HOME"
  local before after
  before="$(installed_version)"
  if [ -n "$(git -C "$FINCH_HOME" status --porcelain --untracked-files=all)" ]; then
    say "$(date '+%F %T') local edits in $FINCH_HOME; skipping update ($before)"
    return 0
  fi
  if ! git -C "$FINCH_HOME" fetch --quiet --tags origin "$FINCH_REF" 2>/dev/null; then
    say "$(date '+%F %T') offline or fetch failed; keeping $before"
    return 0
  fi
  if ! git -C "$FINCH_HOME" merge --quiet --ff-only FETCH_HEAD 2>/dev/null; then
    say "$(date '+%F %T') local changes in $FINCH_HOME prevent a fast-forward; keeping $before"
    return 0
  fi
  after="$(installed_version)"
  mkdir -p "$STATE_DIR"
  date '+%F %T' > "$STATE_DIR/last-update"
  if [ "$before" = "$after" ]; then
    say "$(date '+%F %T') up to date ($after)"
  else
    say "$(date '+%F %T') updated $before -> $after (see $FINCH_HOME/CHANGELOG.md)"
  fi
}

cmd_status() {
  [ -d "$FINCH_HOME/.git" ] || { say "not installed at $FINCH_HOME"; return 0; }
  say "version:     $(installed_version)"
  say "tracking:    $FINCH_REF ($(git -C "$FINCH_HOME" rev-parse --short HEAD))"
  say "location:    $FINCH_HOME"
  say "last update: $(cat "$STATE_DIR/last-update" 2>/dev/null || echo never)"
  local dir
  for dir in "$HOME/.claude/skills" "$HOME/.agents/skills" "$HOME/.copilot/skills" "$HOME/.config/opencode/skills"; do
    [ -L "$dir/finch" ] && say "linked:      $dir/finch"
  done
  [ -L "$FINCH_BIN/finch" ] && say "command:     $FINCH_BIN/finch"
  if [ -f "$LAUNCHD_PLIST" ] || { command -v crontab >/dev/null && crontab -l 2>/dev/null | grep -q "$CRON_MARKER"; }; then
    say "auto-update: on (daily)"
  else
    say "auto-update: off"
  fi
}

cmd_uninstall() {
  unschedule_updates
  unlink_skill
  unlink_command
  if [ -d "$FINCH_HOME/.git" ]; then
    if [ -n "$(git -C "$FINCH_HOME" status --porcelain 2>/dev/null)" ]; then
      say "kept $FINCH_HOME because it has local edits; delete it yourself when done"
    else
      rm -rf "$FINCH_HOME"
      say "removed $FINCH_HOME"
    fi
  fi
  rm -rf "$STATE_DIR"
  say "Finch uninstalled"
}

main() {
  # Run as `finch`, the default is status; run as install.sh or piped to bash, it installs.
  local default=install
  [ "$(basename "$0")" = finch ] && default=status
  local cmd="${1:-$default}"
  case "$cmd" in
    install) shift || true; cmd_install "$@" ;;
    --no-auto-update) cmd_install "$@" ;;
    update) cmd_update ;;
    status) cmd_status ;;
    uninstall) cmd_uninstall ;;
    -h|--help|help) sed -n '2,17p' "$0" 2>/dev/null || true ;;
    *) die "unknown command: $cmd (try: install, update, status, uninstall)" ;;
  esac
}

main "$@"
