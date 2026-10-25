#!/usr/bin/env bash
#
# Install the OCPP skill for Claude Code and/or OpenCode.
#
# Usage:
#   ./install.sh                     # personal Claude Code install (also visible to OpenCode)
#   ./install.sh --claude            # personal Claude Code
#   ./install.sh --opencode          # personal OpenCode
#   ./install.sh --both              # both personal locations
#   ./install.sh --project           # ./.claude/skills/ocpp
#   ./install.sh --project-opencode  # ./.opencode/skills/ocpp
#   ./install.sh --dir PATH          # install under PATH/ocpp
#   ./install.sh --force             # replace an existing install
#
set -euo pipefail

SKILL_NAME="ocpp"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Install the OCPP skill for Claude Code and/or OpenCode.

Usage:
  ./install.sh                     personal Claude Code install (also visible to OpenCode)
  ./install.sh --claude            personal Claude Code
  ./install.sh --opencode          personal OpenCode
  ./install.sh --both              both personal locations
  ./install.sh --project           ./.claude/skills/ocpp
  ./install.sh --project-opencode  ./.opencode/skills/ocpp
  ./install.sh --dir PATH          install under PATH/ocpp
  ./install.sh --force             replace an existing install
  ./install.sh --help              show this help

Default:
  ~/.claude/skills/ocpp

OpenCode also discovers ~/.claude/skills, so the default install serves both tools.
Use --opencode if you want the native ~/.config/opencode/skills path.
EOF
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

mode="claude"
force="false"
custom_dir=""

while (($# > 0)); do
  case "$1" in
    --claude) mode="claude" ;;
    --opencode) mode="opencode" ;;
    --both) mode="both" ;;
    --project) mode="project" ;;
    --project-opencode) mode="project-opencode" ;;
    --dir)
      (($# >= 2)) || fail "--dir needs a path"
      custom_dir="${2%/}"
      [[ -n "$custom_dir" ]] || fail "--dir needs a non-empty path"
      mode="custom"
      shift
      ;;
    --force) force="true" ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "unknown option: $1"
      ;;
  esac
  shift
done

[[ -f "$SCRIPT_DIR/SKILL.md" ]] || fail "SKILL.md not found next to this script"

config_home="${XDG_CONFIG_HOME:-$HOME/.config}"

targets=()
case "$mode" in
  claude)
    targets+=("$HOME/.claude/skills/$SKILL_NAME")
    ;;
  opencode)
    targets+=("$config_home/opencode/skills/$SKILL_NAME")
    ;;
  both)
    targets+=("$HOME/.claude/skills/$SKILL_NAME")
    targets+=("$config_home/opencode/skills/$SKILL_NAME")
    ;;
  project)
    targets+=("$PWD/.claude/skills/$SKILL_NAME")
    ;;
  project-opencode)
    targets+=("$PWD/.opencode/skills/$SKILL_NAME")
    ;;
  custom)
    targets+=("$custom_dir/$SKILL_NAME")
    ;;
  *)
    fail "unknown install mode: $mode"
    ;;
esac

for target in "${targets[@]}"; do
  case "$target" in
    ""|"/"|"$HOME")
      fail "refusing to install into unsafe path: '$target'"
      ;;
  esac
done

if [[ "$force" != "true" ]]; then
  for target in "${targets[@]}"; do
    if [[ -e "$target" ]]; then
      fail "'$target' already exists; re-run with --force to replace it"
    fi
  done
fi

for target in "${targets[@]}"; do
  if [[ -e "$target" ]]; then
    rm -rf -- "$target"
  fi
  mkdir -p -- "$target"

  cp -- "$SCRIPT_DIR/SKILL.md" "$target/SKILL.md"
  cp -R -- "$SCRIPT_DIR/references" "$target/references"
  cp -R -- "$SCRIPT_DIR/scripts" "$target/scripts"

  for extra in LICENSE README.md CHANGELOG.md; do
    if [[ -f "$SCRIPT_DIR/$extra" ]]; then
      cp -- "$SCRIPT_DIR/$extra" "$target/$extra"
    fi
  done

  printf 'installed %s → %s\n' "$SKILL_NAME" "$target"
done

printf '\n'
printf 'Verify with:\n'
printf '  python3 "%s/scripts/validate_skill.py"\n' "${targets[0]}"
printf '\n'
printf 'Invoke in Claude Code with /ocpp, or let the description trigger it.\n'
printf 'Invoke in OpenCode by mentioning @ocpp or letting the description trigger it.\n'
