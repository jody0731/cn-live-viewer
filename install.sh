#!/bin/sh
# Install cn-live-viewer for the current user on Linux or macOS (Windows: install.ps1).
#   ./install.sh            from a clone of the repository
#   sh install.sh           the same
# Uses pipx when it is installed, otherwise a private virtual environment linked into ~/.local/bin.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
if [ -f "$here/pyproject.toml" ]; then
    src=$here
else
    src=git+https://github.com/jody0731/cn-live-viewer
fi

if ! command -v mpv >/dev/null 2>&1; then
    echo "Note: mpv is not installed. It is needed to watch:" >&2
    echo "  Debian/Ubuntu: sudo apt install mpv    Fedora: sudo dnf install mpv (RPM Fusion)" >&2
    echo "  Arch: sudo pacman -S mpv               macOS: brew install mpv" >&2
fi

if command -v pipx >/dev/null 2>&1; then
    pipx install --force "$src"
else
    venv=${XDG_DATA_HOME:-$HOME/.local/share}/cn-live-viewer/venv
    if ! python3 -m venv --clear "$venv"; then
        echo "Could not create a Python environment. Debian/Ubuntu: sudo apt install python3-venv (or pipx)" >&2
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
"$exe" desktop || echo "Could not add the app launcher; run 'cn-live-viewer desktop' later." >&2
echo "Run: cn-live-viewer 333003   (any Huya or Douyin room number or link)"
