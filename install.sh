#!/usr/bin/env bash
#
# Installer for torx, the Tor proxy manager.
#
# One command installs torx, installs Tor itself and opens the menu:
#
#   curl -fsSL https://raw.githubusercontent.com/meran77777/tor/main/install.sh | sudo bash
#
# Works on Debian based systems such as Debian, Ubuntu and Kali Linux.

set -euo pipefail

REPO_RAW_URL="https://raw.githubusercontent.com/meran77777/tor/main/torx.py"
BIN_DIR="${BIN_DIR:-/usr/local/bin}"
TARGET="${BIN_DIR}/torx"
RENEW_SCRIPT="/usr/local/sbin/torx-renew"
CRON_FILE="/etc/cron.d/torx"

# Whether to install the Tor package and open the menu once torx is in place.
WITH_TOR=1
START_AFTER_INSTALL=1

# Older copies of this project installed into these paths. They are cleaned up
# so that a stale executable earlier in PATH cannot shadow the new one.
LEGACY_PATHS=("/usr/bin/torx" "/usr/share/torx" "/usr/bin/restart_tor.sh")

WORK_DIR=""

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
else
    C_RESET=''; C_BOLD=''; C_RED=''; C_GREEN=''; C_YELLOW=''
fi

info()  { printf '%s\n' "${C_BOLD}::${C_RESET} $*"; }
ok()    { printf '%s\n' "${C_GREEN}✓${C_RESET} $*"; }
warn()  { printf '%s\n' "${C_YELLOW}!${C_RESET} $*" >&2; }
die()   { printf '%s\n' "${C_RED}✗${C_RESET} $*" >&2; exit 1; }

cleanup() {
    if [ -n "${WORK_DIR}" ] && [ -d "${WORK_DIR}" ]; then
        rm -rf -- "${WORK_DIR}"
    fi
}
trap cleanup EXIT

usage() {
    cat <<'EOF'
Installer for torx, the Tor proxy manager.

Usage:
  ./install.sh                install torx and Tor, then open the menu
  ./install.sh --no-start     install everything but do not open the menu
  ./install.sh --no-tor       install torx only, leave the Tor package alone
  ./install.sh --uninstall    remove torx and everything it installed
  ./install.sh --prefix DIR   install into DIR instead of /usr/local/bin
  ./install.sh --help         show this text

Remote install, all in one command:
  curl -fsSL https://raw.githubusercontent.com/meran77777/tor/main/install.sh | sudo bash

Works on Debian based systems such as Debian, Ubuntu and Kali Linux.
EOF
}

# True when the script was run from a file rather than piped into a shell.
# When piped, "$0" is the shell itself, so paths relative to it are meaningless.
running_from_file() {
    [ -f "$0" ]
}

# True when a controlling terminal can be reached, even if stdin is a pipe.
have_terminal() {
    { : >/dev/tty; } 2>/dev/null
}

require_root() {
    if [ "$(id -u)" -eq 0 ]; then
        return
    fi
    if ! running_from_file; then
        die "Root privileges are required. Re-run it as:
  curl -fsSL ${REPO_RAW_URL%/torx.py}/install.sh | sudo bash"
    fi
    if command -v sudo >/dev/null 2>&1; then
        info "Root privileges are required; re-running through sudo."
        exec sudo -- "$0" "$@"
    fi
    die "Run this installer as root, or install sudo first."
}

detect_os() {
    if [ ! -r /etc/os-release ]; then
        warn "/etc/os-release is missing; continuing without a distribution check."
        return
    fi
    # shellcheck disable=SC1091
    . /etc/os-release
    local family="${ID:-unknown} ${ID_LIKE:-}"
    case "${family}" in
        *debian*|*ubuntu*|*kali*)
            info "Detected ${PRETTY_NAME:-${ID:-unknown}}."
            ;;
        *)
            warn "${PRETTY_NAME:-${ID:-this system}} is not a Debian based distribution."
            warn "torx will install, but its package management needs apt-get."
            ;;
    esac
}

ensure_python() {
    if command -v python3 >/dev/null 2>&1; then
        return
    fi
    info "Python 3 is missing; installing it."
    command -v apt-get >/dev/null 2>&1 || die "python3 is required but apt-get is not available to install it."
    DEBIAN_FRONTEND=noninteractive apt-get update -qq || warn "apt-get update reported errors."
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 \
        || die "Could not install python3."
}

fetch_source() {
    # Prefer the copy next to this script so that a git clone installs itself
    # instead of silently pulling a different revision from the network.
    local script_dir
    if running_from_file; then
        script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
        if [ -f "${script_dir}/torx.py" ]; then
            info "Using ${script_dir}/torx.py"
            cp -- "${script_dir}/torx.py" "${WORK_DIR}/torx.py"
            return
        fi
    fi

    info "Downloading torx.py"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 --retry-delay 2 -o "${WORK_DIR}/torx.py" "${REPO_RAW_URL}" \
            || die "Download failed. Check the network connection and try again."
    elif command -v wget >/dev/null 2>&1; then
        wget -q --tries=3 -O "${WORK_DIR}/torx.py" "${REPO_RAW_URL}" \
            || die "Download failed. Check the network connection and try again."
    else
        die "Neither curl nor wget is available to download torx.py."
    fi
    [ -s "${WORK_DIR}/torx.py" ] || die "The downloaded file is empty."
}

verify_source() {
    local error
    # Report only the syntax error itself, not the interpreter traceback.
    if ! error="$(python3 - "${WORK_DIR}/torx.py" 2>&1 <<'PY'
import sys
path = sys.argv[1]
try:
    with open(path, "rb") as handle:
        compile(handle.read(), path, "exec")
except SyntaxError as exc:
    sys.exit(f"line {exc.lineno}: {exc.msg}")
except OSError as exc:
    sys.exit(str(exc))
PY
    )"; then
        warn "${error}"
        die "torx.py does not compile; refusing to install a broken script."
    fi
    ok "Source verified."
}

remove_legacy() {
    local path
    for path in "${LEGACY_PATHS[@]}"; do
        if [ -e "${path}" ]; then
            info "Removing the previous installation at ${path}"
            rm -rf -- "${path}"
        fi
    done
}

install_tor_package() {
    [ "${WITH_TOR}" -eq 1 ] || return 0
    printf '\n'
    info "Installing the Tor package..."
    # A failure here is not fatal: torx is installed and can retry on its own.
    if ! "${TARGET}" --install; then
        warn "Tor could not be installed automatically. Run 'sudo torx --install'"
        warn "once the problem is fixed."
        return 0
    fi
}

start_torx() {
    [ "${START_AFTER_INSTALL}" -eq 1 ] || return 0
    if ! have_terminal; then
        info "No terminal is attached, so the menu was not opened."
        info "Run 'torx' from a terminal to use it."
        return 0
    fi
    printf '\n'
    # stdin is the download when the installer is piped into a shell, so the
    # controlling terminal is reattached before handing over to the menu.
    "${TARGET}" </dev/tty || true
}

print_hints() {
    printf '\n'
    printf '%s\n' "  ${C_BOLD}torx${C_RESET}              open the menu"
    printf '%s\n' "  ${C_BOLD}torx --check${C_RESET}      verify that traffic goes through Tor"
    printf '%s\n' "  ${C_BOLD}torx --get-ip${C_RESET}     print the current exit IP"
    printf '%s\n' "  ${C_BOLD}torx --help${C_RESET}       list every option"
    printf '\n'
}

do_install() {
    detect_os
    ensure_python

    WORK_DIR="$(mktemp -d)"
    fetch_source
    verify_source
    remove_legacy

    install -d -m 0755 "${BIN_DIR}"
    # 0755, never 0777: a world writable file run as root is a way in for
    # anybody with a local account.
    install -m 0755 -o root -g root "${WORK_DIR}/torx.py" "${TARGET}"
    ok "Installed ${TARGET}"

    if ! command -v torx >/dev/null 2>&1; then
        warn "${BIN_DIR} is not in your PATH. Run it as ${TARGET}, or add:"
        warn "  export PATH=\"${BIN_DIR}:\$PATH\""
    fi

    install_tor_package

    printf '\n'
    ok "Installation finished."
    print_hints
    start_torx
}

do_uninstall() {
    local removed=0
    local path
    for path in "${TARGET}" "${RENEW_SCRIPT}" "${CRON_FILE}" "${LEGACY_PATHS[@]}"; do
        if [ -e "${path}" ]; then
            rm -rf -- "${path}"
            ok "Removed ${path}"
            removed=1
        fi
    done
    if [ "${removed}" -eq 0 ]; then
        info "Nothing to remove; torx is not installed."
    else
        ok "torx removed. The Tor package itself was left untouched;"
        info "remove it with: sudo apt-get remove tor"
    fi
}

main() {
    # Keep the original arguments so that re-running through sudo does not
    # drop them.
    local original_args=("$@")
    local action="install"

    while [ "$#" -gt 0 ]; do
        case "$1" in
            -h|--help)      usage; exit 0 ;;
            -u|--uninstall) action="uninstall" ;;
            --no-tor)       WITH_TOR=0 ;;
            --no-start)     START_AFTER_INSTALL=0 ;;
            --prefix)
                [ "$#" -ge 2 ] || die "--prefix needs a directory."
                BIN_DIR="$2"; TARGET="${BIN_DIR}/torx"; shift ;;
            *) die "Unknown option: $1 (try --help)" ;;
        esac
        shift
    done

    require_root ${original_args[@]+"${original_args[@]}"}

    if [ "${action}" = "uninstall" ]; then
        do_uninstall
    else
        do_install
    fi
}

main "$@"
