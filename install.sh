#!/bin/sh
# otaku's one-line install:
#
#     curl -LsSf https://otaku.sh/install.sh | sh
#
# This file's canonical home is the otaku repository itself —
# github.com/enclavum/otaku — and otaku.sh serves it from there by
# redirect, so what you audit here is exactly what the pipe runs.
#
# All it does is make sure uv is on the machine and then run
# `uv tool install otaku`. uv is the reason this stays short: it brings
# its own CPython when the system's is too old, which on a stock Mac it
# always is — macOS still ships 3.9.6 as /usr/bin/python3, and otaku
# needs 3.11+. Homebrew would work too, but a third-party tap gets no
# bottles, so it builds otaku from source; uv installs wheels in seconds.
#
# It takes no options, because it is the newcomer's path and nothing
# else: a particular release, or anything else worth choosing, is
# `uv tool install otaku==0.2.2` and its own flags.
#
# It never uses sudo and never writes outside $HOME. An otaku that uv,
# Homebrew or pipx already put on the machine is reported, not replaced —
# updating one is `otaku update`'s job, and it knows which installer to
# ask. Only an otaku of unknown origin is installed alongside, with a
# warning: the new shim comes first on PATH, so it wins until the old
# one is removed.
set -eu

UV_INSTALLER_URL="https://astral.sh/uv/install.sh"
ISSUES_URL="https://github.com/enclavum/otaku/issues"

# The interpreter to fall back on when uv finds nothing it can use. Only
# ever downloaded in that case — a machine with any 3.11+ keeps it.
PYTHON_FALLBACK="3.13"

# ---------------------------------------------------------------- output

setup_colors() {
    if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
        BOLD=$(printf '\033[1m')  DIM=$(printf '\033[2m')
        RED=$(printf '\033[31m')  YELLOW=$(printf '\033[33m')
        RESET=$(printf '\033[0m')
    else
        BOLD=''  DIM=''  RED=''  YELLOW=''  RESET=''
    fi
}

say()  { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*"; }
note() { printf '    %s%s%s\n' "$DIM" "$*" "$RESET"; }
warn() { printf '%swarning:%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%serror:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

# What the owner of an already-installed otaku needs: how to run it, and
# how to bring it to the newest release.
hints() {
    say "  otaku            start playing"
    say "  otaku update     update to the newest version"
}

# ------------------------------------------------------------- utilities

# `readlink -f` is GNU; BSD only grew it recently and this has to run on
# whatever macOS the reader has, so walk the chain by hand.
resolve() {
    _path="$1" _hops=0
    while [ -L "$_path" ] && [ "$_hops" -lt 32 ]; do
        _target=$(readlink "$_path")
        case "$_target" in
            /*) _path="$_target" ;;
            *)  _path="$(dirname "$_path")/$_target" ;;
        esac
        _hops=$((_hops + 1))
    done
    printf '%s\n' "$_path"
}

# `command -v`, minus Windows. WSL appends the Windows PATH to its own,
# so a uv.exe installed on the Windows side answers here — and would
# install otaku into Windows, where the Linux shell cannot run it.
find_tool() {
    _found=$(command -v "$1" 2>/dev/null) || return 1
    case "$_found" in
        /mnt/*|*.exe) return 1 ;;
    esac
    printf '%s\n' "$_found"
}

# A path as the reader would write it themselves.
pretty() {
    case "$1" in
        "$HOME"/*) printf '~%s\n' "${1#"$HOME"}" ;;
        *) printf '%s\n' "$1" ;;
    esac
}

fetch() {  # url, destination
    if [ -n "$CURL" ]; then
        "$CURL" -LsSf "$1" -o "$2"
    else
        "$WGET" -q "$1" -O "$2"
    fi
}

# ------------------------------------------------------------ the checks

# curl first. The advertised one-liner is curl's, so in the common path
# it is already proven present; beyond that it is the more dependable of
# the two — macOS ships it in the base system and ships no wget at all,
# and the Red Hat family installs curl by default while leaving wget out.
# wget is here for whoever fetched this script some other way, and it
# comes second because "wget" is two programs — GNU's and busybox's —
# agreeing on little beyond -q and -O.
check_tools() {
    CURL=$(find_tool curl || true)
    WGET=''
    [ -n "$CURL" ] || WGET=$(find_tool wget || true)
    [ -n "$CURL" ] || [ -n "$WGET" ] || die "this needs curl or wget, and finds neither. Install one:
       Debian, Ubuntu   sudo apt install curl
       Fedora, RHEL     sudo dnf install curl
       Arch             sudo pacman -S curl
       Alpine           apk add curl"
}

check_platform() {
    OS=$(uname -s)
    case "$OS" in
        Darwin|Linux) ;;
        MINGW*|MSYS*|CYGWIN*)
            die "otaku is a Unix program — Git Bash and MSYS cannot run it.
       On Windows it runs under WSL: install it with \`wsl --install\`,
       open your Linux shell, and run this same line there." ;;
        *) die "unsupported system: $OS — otaku runs on macOS and Linux" ;;
    esac

    # WSL is just Linux to everything above, and needs no special path;
    # what it needs is the /mnt guard in find_tool, and this warning.
    if [ "$OS" = Linux ] && [ -r /proc/sys/kernel/osrelease ]; then
        case "$(cat /proc/sys/kernel/osrelease)" in
            *icrosoft*|*WSL*)
                case "$HOME" in
                    /mnt/*) warn "your home is on the Windows drive ($HOME).
         otaku will install and run, but every database read crosses the
         filesystem boundary and is slow. A home inside WSL is the better
         place for it." ;;
                esac ;;
        esac
    fi
}

# An otaku already on the machine: whoever owns it should keep owning it.
# Installing a second copy leaves two otakus with one name, and whichever
# PATH happens to prefer wins — including for `otaku update`, which reads
# the running install to decide how to upgrade it.
check_existing() {
    _otaku=$(find_tool otaku) || return 0
    _real=$(resolve "$_otaku")

    # The name with its version when the binary answers — "otaku 0.2.2 is
    # already installed" says what they have and sets up the update row
    # below. A binary that will not answer still gets the plain report.
    _name=$("$_otaku" --version 2>/dev/null) || _name=''
    case "$_name" in
        otaku*) _name=$(printf '%s\n' "$_name" | sed 's/, version / /') ;;
        *)      _name='otaku' ;;
    esac

    case "$_real" in
        */Cellar/*)
            say "$_name is already installed, and Homebrew owns it:"
            note "$_real"
            say ""
            hints
            exit 0 ;;
        */pipx/*)
            say "$_name is already installed, and pipx owns it:"
            note "$_real"
            say ""
            hints
            exit 0 ;;
        */uv/tools/*)
            say "$_name is already installed in:"
            note "$_real"
            say ""
            hints
            exit 0 ;;
        *)
            warn "another otaku is already on your PATH:
         $_real
         This installs uv's own copy alongside it, first on PATH — the
         new one wins in new shells until the old one is removed." ;;
    esac
}

# ------------------------------------------------------------------ work

ensure_uv() {
    if UV=$(find_tool uv); then
        step "uv is already here"
        note "$UV"
        return 0
    fi

    step "installing uv — otaku's installer (python package and project manager)"
    note "$UV_INSTALLER_URL, about 35 MB, into $BIN_DIR"

    # To a file rather than straight into a pipe: POSIX sh has no
    # pipefail, so `fetch ... | sh` would run an empty or half-downloaded
    # installer as a success.
    TMP=$(mktemp "${TMPDIR:-/tmp}/otaku-install.XXXXXX") || die "cannot write a temporary file"
    fetch "$UV_INSTALLER_URL" "$TMP" || die "could not download uv's installer from $UV_INSTALLER_URL"
    [ -s "$TMP" ] || die "uv's installer came back empty — a network or proxy problem"

    # INSTALLER_NO_MODIFY_PATH: this script owns the PATH edit below, and
    # two installers appending to one rc file is how you get it twice.
    UV_INSTALL_DIR="$BIN_DIR" INSTALLER_NO_MODIFY_PATH=1 sh "$TMP" >/dev/null \
        || die "uv's installer failed"
    rm -f "$TMP"; TMP=''

    UV="$BIN_DIR/uv"
    [ -x "$UV" ] || die "uv installed but is not at $UV — please report this at $ISSUES_URL"
}

# uv puts otaku's shim in the same directory it puts itself, so one check
# covers both. The rc edit is the one thing here that changes a file the
# user owns, so it is announced and idempotent.
#
# This runs before the install, not after: exporting the directory first
# means uv finds it on PATH and keeps its own "not on your PATH" advice
# to itself, leaving one account of the matter instead of two.
ensure_path() {
    case ":$PATH:" in
        *":$BIN_DIR:"*) return 0 ;;
    esac
    PATH="$BIN_DIR:$PATH"; export PATH  # so this run can verify what it installed

    _line="export PATH=\"$BIN_DIR:\$PATH\""
    _rc=''
    case "$(basename "${SHELL:-sh}")" in
        zsh)  _rc="${ZDOTDIR:-$HOME}/.zshrc" ;;
        bash) # macOS terminals open login shells, which read .bash_profile
              # and never .bashrc — chosen even when absent (and created),
              # or the "open a new shell" advice below would not come true.
              if [ "$OS" = Darwin ]; then
                  _rc="$HOME/.bash_profile"
              else
                  _rc="$HOME/.bashrc"
              fi ;;
        fish) _rc="$HOME/.config/fish/conf.d/otaku.fish"
              _line="fish_add_path \"$BIN_DIR\"" ;;
    esac

    # An unrecognized shell: nowhere to write that would be right, so the
    # reader has to do it — the one case worth raising your voice about.
    if [ -z "$_rc" ]; then
        PATH_ACTION=manual
        PATH_NOTE="$BIN_DIR is not on your PATH. Add it:
         $_line"
        return 0
    fi

    if [ -f "$_rc" ] && grep -qF "$BIN_DIR" "$_rc"; then
        PATH_ACTION=pending
        PATH_NOTE="$(pretty "$_rc") already has it — open a new shell to pick it up,
    or run this once in the current one:
        $_line"
        return 0
    fi

    mkdir -p "$(dirname "$_rc")"
    printf '\n# added by the otaku installer (https://otaku.sh/install.sh)\n%s\n' "$_line" >> "$_rc"
    PATH_ACTION=added
    PATH_NOTE="added to your PATH in $(pretty "$_rc") — open a new shell to pick it up,
    or run this once in the current one:
        $_line"
}

install_otaku() {
    step "installing otaku"

    # --force because the check above only sees an otaku that is on PATH:
    # one uv installed into a directory the shell never picked up is
    # invisible there, and a plain install would stop at "already
    # installed" rather than making the shim this run promises.
    if "$UV" tool install --force otaku; then
        return 0
    fi

    # The likeliest reason for that failure is the interpreter: otaku
    # needs 3.11+ and uv reached for something older. Ask for a version
    # by name and uv downloads a managed CPython rather than searching.
    step "retrying with a managed CPython $PYTHON_FALLBACK — the usual cause is no Python 3.11+"
    "$UV" tool install --force --python "$PYTHON_FALLBACK" otaku \
        || die "the install failed. The output above says why; if it is not
       something you can fix, please report it at $ISSUES_URL"
}

verify() {
    VERSION=$("$BIN_DIR/otaku" --version 2>/dev/null) \
        || die "otaku installed but will not run — please report this at $ISSUES_URL"
}

finish() {
    say ""
    step "$VERSION"
    say ""
    say "  otaku            start playing"
    say ""
    say "Your stories and settings are in ~/.otaku"

    case "$PATH_ACTION" in
        # Something the script did, not something the reader must fix.
        added|pending) say ""; note "$PATH_NOTE" ;;
        manual)        say ""; warn "$PATH_NOTE" ;;
    esac
}

# ------------------------------------------------------------------ main
#
# Everything runs from here, called on the last line of the file. `curl |
# sh` hands the shell a stream: if the connection drops halfway, sh runs
# the bytes that arrived. A body that only executes once that final line
# is parsed turns a truncated download into a no-op instead of half an
# install.

main() {
    setup_colors

    TMP=''
    PATH_NOTE=''
    PATH_ACTION=''
    VERSION=''

    trap 'rm -f "$TMP" 2>/dev/null || true' EXIT INT TERM

    # Where uv installs itself and its tools' shims, by its own rules.
    BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"

    check_tools
    check_platform
    check_existing
    ensure_uv

    # uv knows better than the guess above where its shims go; ask it
    # once it exists, and only trust an answer that looks like a path.
    if _bin=$("$UV" tool dir --bin 2>/dev/null); then
        case "$_bin" in /*) BIN_DIR="$_bin" ;; esac
    fi

    ensure_path
    install_otaku
    verify
    finish
}

main
