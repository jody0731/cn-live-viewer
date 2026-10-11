#!/bin/sh
# Install cn-live-viewer for the current user on Linux or macOS (Windows: install.ps1).
#   ./install.sh          from a clone of the repository
#   ./install.sh --yes    the same, without asking before installing system packages
#   curl -fsSL https://raw.githubusercontent.com/jody0731/cn-live-viewer/main/install.sh | sh
# First it installs what the system is missing: mpv, a Chinese font for the chat, Python 3.10+ and its venv module,
# with apt, dnf, pacman, zypper or Homebrew, asking first. Then it installs cn-live-viewer with pipx when that is
# there, otherwise into a private virtual environment linked into ~/.local/bin, and adds the app launcher.
set -eu

yes=0
for arg in "$@"; do
    case $arg in -y|--yes) yes=1 ;; esac
done

# from this folder when it is a clone, otherwise the latest version from GitHub (a zip, so git isn't needed)
here=$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo /nonexistent)
if [ -f "$here/pyproject.toml" ] && [ -d "$here/src/cn_live_viewer" ]; then
    src=$here
else
    src=https://github.com/jody0731/cn-live-viewer/archive/refs/heads/main.zip
fi

# ask "question": yes with --yes; otherwise ask on the terminal, and with no terminal to ask, no
ask() {
    [ "$yes" = 1 ] && return 0
    if [ -r /dev/tty ] && printf '%s [Y/n] ' "$1" > /dev/tty 2>/dev/null; then
        answer=n
        read -r answer < /dev/tty || true
        case $answer in [nN]*) return 1 ;; *) return 0 ;; esac
    fi
    return 1
}

python_ok() {
    command -v "$1" >/dev/null 2>&1 && "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null
}

# ---------------------------------------------------------------- system packages

missing=""
command -v mpv >/dev/null 2>&1 || missing="$missing mpv"
python_ok python3 || missing="$missing python"
if [ "$(uname -s)" = Linux ]; then
    # a font with Simplified Chinese, for the chat (macOS has one built in)
    if command -v fc-list >/dev/null 2>&1 && [ -z "$(fc-list :lang=zh-cn family 2>/dev/null)" ]; then
        missing="$missing font"
    fi
    python3 -c 'import ensurepip, venv' 2>/dev/null || missing="$missing venv"
fi

if [ -n "$missing" ]; then
    # package names for each missing piece, per package manager
    pm="" update="" names=""
    if command -v apt-get >/dev/null 2>&1; then
        pm="sudo apt-get install -y"; update="sudo apt-get update"
        names="mpv:mpv font:fonts-noto-cjk venv:python3-venv python:python3"
    elif command -v dnf >/dev/null 2>&1; then
        pm="sudo dnf install -y"; update=""
        names="mpv:mpv font:google-noto-sans-cjk-fonts venv:python3 python:python3"
    elif command -v pacman >/dev/null 2>&1; then
        pm="sudo pacman -S --needed --noconfirm"; update=""
        names="mpv:mpv font:noto-fonts-cjk venv:python python:python"
    elif command -v zypper >/dev/null 2>&1; then
        pm="sudo zypper install -y"; update=""
        names="mpv:mpv font:noto-sans-sc-fonts venv:python3 python:python3"
    elif command -v brew >/dev/null 2>&1; then
        pm="brew install"; update=""
        names="mpv:mpv python:python"
    fi
    pkgs=""
    for m in $missing; do
        for pair in $names; do
            if [ "${pair%%:*}" = "$m" ]; then
                p=${pair#*:}
                case " $pkgs " in *" $p "*) ;; *) pkgs="$pkgs $p" ;; esac
            fi
        done
    done

    if [ -z "$pm" ]; then
        echo "Missing:$missing. Install them with your system's package manager (macOS: Homebrew, https://brew.sh)." >&2
    elif [ -n "$pkgs" ] && ask "Missing:$missing. Install them now with: $pm$pkgs ?"; then
        if [ -n "$update" ]; then $update || true; fi
        # shellcheck disable=SC2086  # $pm and $pkgs are word lists on purpose
        $pm $pkgs || echo "Installing$pkgs failed; install them yourself and run this again." >&2
    elif [ -n "$pkgs" ]; then
        echo "Not installed:$pkgs. cn-live-viewer needs mpv and Python 3.10+ to work." >&2
    fi
fi

# ---------------------------------------------------------------- cn-live-viewer

python=python3
if ! python_ok "$python"; then
    echo "Python 3.10 or newer is needed (python3 is missing or older). Install it and run this again." >&2
    exit 1
fi

if command -v pipx >/dev/null 2>&1; then
    pipx install --force "$src"
else
    venv=${XDG_DATA_HOME:-$HOME/.local/share}/cn-live-viewer/venv
    if ! "$python" -m venv --clear "$venv"; then
        echo "Could not create a Python environment (Debian/Ubuntu: sudo apt install python3-venv)" >&2
        exit 1
    fi
    "$venv/bin/python" -m pip install --quiet --upgrade pip
    "$venv/bin/python" -m pip install --quiet "$src"
    mkdir -p "$HOME/.local/bin"
    ln -sf "$venv/bin/cn-live-viewer" "$HOME/.local/bin/cn-live-viewer"
    echo "Installed: $HOME/.local/bin/cn-live-viewer"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) echo "Add ~/.local/bin to your PATH to run it by name." ;;
    esac
fi

# the app launcher: the app menu on Linux, ~/Applications (Launchpad, Spotlight) on macOS
exe=$(command -v cn-live-viewer || echo "$HOME/.local/bin/cn-live-viewer")
"$exe" desktop || echo "Could not add the app launcher; it is added when cn-live-viewer first starts." >&2
command -v mpv >/dev/null 2>&1 || echo "Note: mpv is still missing; install it before watching." >&2
echo "Start \"CN Live Viewer\" from your apps, or run: cn-live-viewer 333003"
