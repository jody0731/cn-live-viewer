#!/bin/sh
# Install cn-live-viewer for the current user on Linux or macOS (Windows: install.ps1).
#   curl -fsSL https://raw.githubusercontent.com/jody0731/cn-live-viewer/main/install.sh | sh
#   ./install.sh          from a clone of the repository
#   ./install.sh --yes    the same, without asking before installing system packages
# First it installs what the system is missing: mpv, a Chinese font for the chat, Python 3.10+ and its venv module,
# with apt, dnf, pacman, zypper or Homebrew (on a Mac without Homebrew, it offers to install Homebrew first), asking
# once. Then it installs cn-live-viewer with pipx when that is there, otherwise into a private virtual environment
# linked into ~/.local/bin, adds the app launcher, and has the installed copy check itself.
set -eu

yes=0
for arg in "$@"; do
    case $arg in -y|--yes) yes=1 ;; esac
done
os=$(uname -s)

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

# The newest Python 3.10+ here: python3, or a versioned one (an older system's python3 may be 3.9 with python3.12
# beside it), or Homebrew's before it is on PATH. Never macOS's own /usr/bin/python3: it is 3.9, and without Apple's
# developer tools, running it opens a dialog to install them.
find_python() {
    for p in python3 python3.14 python3.13 python3.12 python3.11 python3.10 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
        exe=$(command -v "$p" 2>/dev/null) || continue
        if [ "$os" = Darwin ] && [ "$exe" = /usr/bin/python3 ]; then continue; fi
        if "$exe" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
            echo "$exe"
            return 0
        fi
    done
    return 1
}

# mpv on PATH, or where Homebrew and the mpv.app download put it (cn-live-viewer looks there too)
find_mpv() {
    for m in mpv /opt/homebrew/bin/mpv /usr/local/bin/mpv /Applications/mpv.app/Contents/MacOS/mpv; do
        command -v "$m" >/dev/null 2>&1 && return 0
    done
    return 1
}

# Homebrew installed but not on this shell's PATH yet: add it
brew_env() {
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [ -x "$b" ]; then eval "$("$b" shellenv)"; return 0; fi
    done
    return 1
}

# ---------------------------------------------------------------- system packages

if [ "$os" = Darwin ] && ! command -v brew >/dev/null 2>&1; then brew_env || true; fi

missing=""
find_mpv || missing="$missing mpv"
python=$(find_python || true)
[ -n "$python" ] || missing="$missing python"
if [ "$os" = Linux ]; then
    # a font with Simplified Chinese, for the chat (macOS has one built in)
    if command -v fc-list >/dev/null 2>&1 && [ -z "$(fc-list :lang=zh-cn family 2>/dev/null)" ]; then
        missing="$missing font"
    fi
    # Debian and Ubuntu split venv off Python; a Python about to be installed needs it too
    if [ -z "$python" ] || ! "$python" -c 'import ensurepip, venv' 2>/dev/null; then missing="$missing venv"; fi
fi
if [ -n "$python" ]; then echo "Python: $python"; fi

if [ -n "$missing" ] && [ "$os" = Darwin ] && ! command -v brew >/dev/null 2>&1; then
    if ask "Missing:$missing. These come from Homebrew (https://brew.sh), which isn't installed. Install Homebrew first? (It asks for your password.)"; then
        installer=$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh) || installer=""
        if [ -z "$installer" ]; then
            echo "Could not download Homebrew's installer." >&2
        elif (exec < /dev/tty) 2>/dev/null; then
            /bin/bash -c "$installer" < /dev/tty || true      # on the terminal, so it can ask for the password
        else
            NONINTERACTIVE=1 /bin/bash -c "$installer" || true
        fi
        brew_env || true
    fi
fi

if [ -n "$missing" ]; then
    # package names for each missing piece, per package manager. Where the system's own python3 may be older than
    # 3.10 (RHEL and its rebuilds, openSUSE Leap), a newer Python is its own package.
    pm="" update="" names=""
    if command -v apt-get >/dev/null 2>&1; then
        pm="sudo apt-get install -y"; update="sudo apt-get update"
        names="mpv:mpv font:fonts-noto-cjk venv:python3-venv python:python3"
    elif command -v dnf >/dev/null 2>&1; then
        pm="sudo dnf install -y"
        names="mpv:mpv font:google-noto-sans-cjk-fonts venv:python3 python:python3.12"
    elif command -v pacman >/dev/null 2>&1; then
        pm="sudo pacman -S --needed --noconfirm"
        names="mpv:mpv font:noto-fonts-cjk venv:python python:python"
    elif command -v zypper >/dev/null 2>&1; then
        pm="sudo zypper install -y"
        names="mpv:mpv font:noto-sans-sc-fonts venv:python3 python:python311"
    elif command -v brew >/dev/null 2>&1; then
        pm="brew install"
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

python=$(find_python || true)
if [ -z "$python" ]; then
    echo "Python 3.10 or newer is needed and wasn't found. Install it (https://www.python.org/downloads/) and run this again." >&2
    exit 1
fi
echo "Installing cn-live-viewer with $python ..."

if command -v pipx >/dev/null 2>&1; then
    pipx install --force --python "$python" "$src"
    exe="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo "$HOME/.local/bin")/cn-live-viewer"
else
    venv=${XDG_DATA_HOME:-$HOME/.local/share}/cn-live-viewer/venv
    if ! "$python" -m venv --clear "$venv"; then
        echo "Could not create a Python environment (Debian/Ubuntu: sudo apt install python3-venv)" >&2
        exit 1
    fi
    "$venv/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip
    "$venv/bin/python" -m pip install --quiet --disable-pip-version-check "$src"
    mkdir -p "$HOME/.local/bin"
    ln -sf "$venv/bin/cn-live-viewer" "$HOME/.local/bin/cn-live-viewer"
    exe=$venv/bin/cn-live-viewer
    echo "Installed: $HOME/.local/bin/cn-live-viewer"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) echo "Add ~/.local/bin to your PATH to run it by name." ;;
    esac
fi

# the app launcher: the app menu on Linux, ~/Applications (Launchpad, Spotlight) on macOS. Run the copy just
# installed, not another one earlier on PATH.
"$exe" desktop || echo "Could not add the app launcher; it is added when cn-live-viewer first starts." >&2
echo
if "$exe" check; then                     # what's in place: Python, the libraries, mpv, the font
    echo
    echo "Installed. Start \"CN Live Viewer\" from your apps, or run: cn-live-viewer 333003"
else
    echo
    echo "Installed, but not ready to play yet (see above). Install what's missing and run this again." >&2
fi
