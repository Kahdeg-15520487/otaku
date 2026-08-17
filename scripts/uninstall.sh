#!/bin/sh
# The reverse of install.sh, for testing installs on a machine made clean
# again. Dev tooling: lives in scripts/, never served, never advertised.
#
# Removes only what uv owns. An otaku installed by Homebrew or pipx is
# reported with its owner's own uninstall command instead. Stories and
# settings in ~/.otaku are never touched, and the PATH line install.sh
# may have added to a shell rc is left alone — shared config, harmless,
# and rc surgery is not worth the risk in a test helper.
#
#   scripts/uninstall.sh         remove otaku
#   scripts/uninstall.sh --uv    also remove uv itself: binaries, managed
#                                pythons, tools, cache — any OTHER uv
#                                tools on the machine go with it

set -eu

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

REMOVE_UV=0
for arg in "$@"; do
    case "$arg" in
        --uv) REMOVE_UV=1 ;;
        *) die "unknown option: $arg (the only one is --uv)" ;;
    esac
done

# Foreign owners keep their otaku: removing it is their command's job.
if _otaku=$(command -v otaku 2>/dev/null); then
    _real=$(readlink -f "$_otaku" 2>/dev/null || echo "$_otaku")
    case "$_real" in
        */Cellar/*) die "Homebrew owns this otaku — remove it with: brew uninstall otaku" ;;
        */pipx/*)   die "pipx owns this otaku — remove it with: pipx uninstall otaku" ;;
    esac
fi

if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q '^otaku '; then
    uv tool uninstall otaku
    say "otaku removed"
else
    say "no uv-installed otaku found"
fi

if [ "$REMOVE_UV" = 1 ]; then
    if UV=$(command -v uv 2>/dev/null); then
        # The order uv's own docs give: cache, managed pythons, tools,
        # then the binaries.
        uv cache clean >/dev/null 2>&1 || true
        _dir=$(uv python dir 2>/dev/null) && [ -n "$_dir" ] && rm -rf "$_dir"
        _dir=$(uv tool dir 2>/dev/null) && [ -n "$_dir" ] && rm -rf "$_dir"
        rm -f "$UV" "$(dirname "$UV")/uvx"
        say "uv removed"
    else
        say "no uv found"
    fi
fi

say "Stories and settings in ~/.otaku are untouched."
