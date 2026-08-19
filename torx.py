#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
torx — command line manager for the Tor SOCKS proxy.

Targets Debian based distributions (Kali Linux, Ubuntu, Debian) and relies
only on the Python 3 standard library, so it works on a freshly installed
system with no extra packages.

Run ``torx --help`` for the non interactive interface, or ``torx`` with no
arguments for the menu.
"""

from __future__ import annotations

import argparse
import enum
import logging
import os
import re
import shutil
import socket
import ssl
import stat
import struct
import subprocess
import sys
import tempfile
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

__version__ = "2.0.0"

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
TORRC_PATH = Path("/etc/tor/torrc")
BACKUP_PATH = Path("/etc/tor/torrc.torx.bak")
RENEW_SCRIPT_PATH = Path("/usr/local/sbin/torx-renew")
CRON_FILE_PATH = Path("/etc/cron.d/torx")

DEFAULT_SOCKS_PORT = "9050"

# Endpoints used to look up the exit IP address. The first one also reports
# whether the request really left the network through Tor.
IP_ENDPOINTS = (
    "https://check.torproject.org/api/ip",
    "https://api.ipify.org",
    "http://checkip.amazonaws.com",
)

# Tor matches exit nodes with ISO 3166-1 alpha-2 codes. Note that the United
# Kingdom is "gb", not "uk"; "uk" matches nothing at all.
COUNTRY_NAMES: Dict[str, str] = {
    "at": "Austria", "au": "Australia", "be": "Belgium", "bg": "Bulgaria",
    "br": "Brazil", "ca": "Canada", "ch": "Switzerland", "cl": "Chile",
    "cz": "Czechia", "de": "Germany", "dk": "Denmark", "ee": "Estonia",
    "es": "Spain", "fi": "Finland", "fr": "France", "gb": "United Kingdom",
    "gr": "Greece", "hk": "Hong Kong", "hr": "Croatia", "hu": "Hungary",
    "id": "Indonesia", "ie": "Ireland", "il": "Israel", "in": "India",
    "is": "Iceland", "it": "Italy", "jp": "Japan", "kr": "South Korea",
    "lt": "Lithuania", "lu": "Luxembourg", "lv": "Latvia", "md": "Moldova",
    "mx": "Mexico", "my": "Malaysia", "nl": "Netherlands", "no": "Norway",
    "nz": "New Zealand", "pl": "Poland", "pt": "Portugal", "ro": "Romania",
    "rs": "Serbia", "se": "Sweden", "sg": "Singapore", "si": "Slovenia",
    "sk": "Slovakia", "th": "Thailand", "tr": "Turkey", "tw": "Taiwan",
    "ua": "Ukraine", "us": "United States", "za": "South Africa",
}

# Common mistakes mapped onto the code Tor actually understands.
COUNTRY_ALIASES: Dict[str, str] = {
    "uk": "gb", "en": "gb", "gr8": "gb", "ger": "de", "usa": "us",
    "uae": "ae", "ned": "nl", "hol": "nl", "swe": "se", "sui": "ch",
}

COUNTRY_CODE_RE = re.compile(r"^[a-z]{2}$")

# Cron intervals offered by the menu, in minutes.
CRON_PRESETS: Tuple[Tuple[int, str], ...] = (
    (1, "every minute"),
    (5, "every 5 minutes"),
    (15, "every 15 minutes"),
    (30, "every 30 minutes"),
    (60, "every hour"),
    (240, "every 4 hours"),
    (720, "every 12 hours"),
    (1440, "once a day"),
)

logger = logging.getLogger("torx")


# --------------------------------------------------------------------------
# Terminal helpers
# --------------------------------------------------------------------------
def _colors_enabled() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "") in ("", "dumb"):
        return False
    return sys.stdout.isatty()


class Palette:
    """ANSI escapes, blanked out when the output is not a colour terminal."""

    def __init__(self, enabled: bool) -> None:
        self.reset = "\033[0m" if enabled else ""
        self.bold = "\033[1m" if enabled else ""
        self.dim = "\033[2m" if enabled else ""
        self.red = "\033[31m" if enabled else ""
        self.green = "\033[32m" if enabled else ""
        self.yellow = "\033[33m" if enabled else ""
        self.cyan = "\033[36m" if enabled else ""


C = Palette(_colors_enabled())


class _LevelFormatter(logging.Formatter):
    """Prefix warnings and errors so they stand out, leave info messages bare."""

    PREFIXES = {
        logging.DEBUG: f"{C.dim}[debug]{C.reset} ",
        logging.WARNING: f"{C.yellow}[warn]{C.reset} ",
        logging.ERROR: f"{C.red}[error]{C.reset} ",
        logging.CRITICAL: f"{C.red}[error]{C.reset} ",
    }

    def format(self, record: logging.LogRecord) -> str:
        return self.PREFIXES.get(record.levelno, "") + record.getMessage()


def configure_logging(verbose: bool) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_LevelFormatter())
    logger.handlers[:] = [handler]
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False


def clear_screen() -> None:
    if sys.stdout.isatty():
        # Home the cursor, clear the screen and drop the scrollback buffer.
        sys.stdout.write("\033[H\033[2J\033[3J")
        sys.stdout.flush()


def ask(prompt: str) -> Optional[str]:
    """Read a line, returning None when the user aborts with Ctrl+C/Ctrl+D."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


# --------------------------------------------------------------------------
# SOCKS5 client (standard library only, no PySocks/requests required)
# --------------------------------------------------------------------------
SOCKS5_ERRORS = {
    1: "general SOCKS server failure",
    2: "connection not allowed by ruleset",
    3: "network unreachable",
    4: "host unreachable",
    5: "connection refused",
    6: "TTL expired",
    7: "command not supported",
    8: "address type not supported",
}

MAX_RESPONSE_BYTES = 256 * 1024


class SocksError(Exception):
    """Raised when the SOCKS proxy refuses or fails to relay a connection."""


class SocksTimeout(SocksError):
    """Raised when Tor accepts the request but never opens the circuit.

    This usually means Tor is still bootstrapping or the network is blocking
    it, so trying a different destination will not help.
    """


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise SocksError("proxy closed the connection unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def socks5_connect(proxy_host: str, proxy_port: int, dest_host: str,
                   dest_port: int, timeout: float) -> socket.socket:
    """Open a TCP tunnel to dest_host:dest_port through a SOCKS5 proxy.

    The destination host name is sent to the proxy verbatim so that DNS
    resolution happens inside the Tor network (the socks5h behaviour).
    """
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        # Greeting: version 5, one method, "no authentication".
        sock.sendall(b"\x05\x01\x00")
        version, method = _recv_exact(sock, 2)
        if version != 0x05:
            raise SocksError(f"unexpected SOCKS version {version} from the proxy")
        if method != 0x00:
            raise SocksError("the proxy demands authentication, which is not supported")

        host_bytes = dest_host.encode("idna")
        if len(host_bytes) > 255:
            raise SocksError("destination host name is too long for SOCKS5")
        request = (b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes
                   + struct.pack("!H", dest_port))
        sock.sendall(request)

        try:
            reply = _recv_exact(sock, 4)
        except socket.timeout as exc:
            raise SocksTimeout(
                f"Tor did not open a circuit within {timeout:.0f}s"
            ) from exc
        if reply[1] != 0x00:
            raise SocksError(SOCKS5_ERRORS.get(reply[1], f"SOCKS error {reply[1]}"))

        # Drain the bound address so the stream is positioned at the payload.
        atyp = reply[3]
        if atyp == 0x01:
            _recv_exact(sock, 4)
        elif atyp == 0x03:
            _recv_exact(sock, _recv_exact(sock, 1)[0])
        elif atyp == 0x04:
            _recv_exact(sock, 16)
        else:
            raise SocksError(f"unsupported address type {atyp} in the proxy reply")
        _recv_exact(sock, 2)
        return sock
    except Exception:
        sock.close()
        raise


def _dechunk(body: bytes) -> bytes:
    """Decode a chunked transfer-encoded body."""
    out = bytearray()
    while True:
        line_end = body.find(b"\r\n")
        if line_end == -1:
            break
        size_field = body[:line_end].split(b";", 1)[0].strip()
        try:
            size = int(size_field, 16)
        except ValueError:
            break
        if size == 0:
            break
        start = line_end + 2
        out += body[start:start + size]
        body = body[start + size + 2:]
    return bytes(out)


def http_get_via_socks(url: str, proxy_port: int, timeout: float = 20.0) -> str:
    """Perform a small HTTP(S) GET through the local Tor SOCKS proxy."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        raise SocksError(f"malformed URL: {url}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query

    sock = socks5_connect("127.0.0.1", proxy_port, host, port, timeout)
    try:
        if parts.scheme == "https":
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=host)
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "User-Agent: torx\r\n"
            "Accept: */*\r\n"
            "Connection: close\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))

        chunks: List[bytes] = []
        received = 0
        while received < MAX_RESPONSE_BYTES:
            data = sock.recv(16384)
            if not data:
                break
            chunks.append(data)
            received += len(data)
        raw = b"".join(chunks)
    finally:
        try:
            sock.close()
        except OSError:
            pass

    head, separator, body = raw.partition(b"\r\n\r\n")
    if not separator:
        raise SocksError("truncated HTTP response from the remote host")
    header_lines = head.split(b"\r\n")
    status_parts = header_lines[0].split(None, 2)
    if len(status_parts) < 2 or not status_parts[1].isdigit():
        raise SocksError("malformed HTTP status line")
    status = int(status_parts[1])
    if status != 200:
        raise SocksError(f"remote host answered with HTTP {status}")
    if any(line.lower().startswith(b"transfer-encoding:") and b"chunked" in line.lower()
           for line in header_lines[1:]):
        body = _dechunk(body)
    return body.decode("utf-8", errors="replace").strip()


# --------------------------------------------------------------------------
# torrc parsing helpers
# --------------------------------------------------------------------------
def torrc_directive(line: str) -> Tuple[Optional[str], str]:
    """Return the lower-cased option name and value of a torrc line.

    Blank lines and comments yield (None, ""). The optional ``+``, ``/`` and
    ``\\`` prefixes that torrc allows in front of an option are ignored for
    the purpose of matching.
    """
    text = line.strip()
    if not text or text.startswith("#"):
        return None, ""
    parts = text.split(None, 1)
    name = parts[0].lstrip("+/\\").lower()
    if not name:
        return None, ""
    value = parts[1].strip() if len(parts) > 1 else ""
    # Strip a trailing comment, which torrc allows after a value.
    value = value.split("#", 1)[0].strip()
    return name, value


def normalise_country_codes(raw: str) -> Tuple[List[str], List[str]]:
    """Split user input into (valid codes, rejected tokens)."""
    tokens = [t for t in re.split(r"[\s,;]+", raw.strip().lower()) if t]
    codes: List[str] = []
    invalid: List[str] = []
    for token in tokens:
        code = COUNTRY_ALIASES.get(token, token)
        if not COUNTRY_CODE_RE.match(code):
            invalid.append(token)
            continue
        if code not in codes:
            codes.append(code)
    return codes, invalid


def format_exit_nodes(codes: Sequence[str]) -> str:
    """Build the ExitNodes value. Tor expects a comma separated list."""
    return ",".join("{%s}" % code for code in codes)


class ConfigChange(enum.Enum):
    """Outcome of a torrc edit.

    A plain boolean would blur the difference between "nothing needed
    changing", which is a success, and "the file could not be written",
    which must not be reported as one.
    """

    CHANGED = "changed"
    UNCHANGED = "unchanged"
    FAILED = "failed"


# --------------------------------------------------------------------------
# Manager
# --------------------------------------------------------------------------
class TorManager:
    def __init__(self, auto_restart: bool = True) -> None:
        self._tor_installed_cache: Optional[bool] = None
        self._torrc_cache: Optional[Dict[str, str]] = None
        self._service_backend: Optional[str] = None
        self.auto_restart = auto_restart

    # ---------------- process helpers ----------------
    @staticmethod
    def is_root() -> bool:
        return os.geteuid() == 0

    def _privilege_prefix(self) -> Optional[List[str]]:
        """Return the argv prefix needed for a privileged command.

        ``[]`` when already root, ``["sudo"]`` when sudo is usable and
        ``None`` when the command cannot be elevated at all.
        """
        if self.is_root():
            return []
        sudo = shutil.which("sudo")
        if sudo:
            return [sudo]
        return None

    def _run(self, cmd: Sequence[str], sudo: bool = False,
             timeout: Optional[int] = 600, capture: bool = True,
             env_extra: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
        """Run a command and return (returncode, stdout, stderr).

        Never raises: failures are reported through the return code so that
        callers can decide what to do.
        """
        argv = list(cmd)
        if sudo:
            prefix = self._privilege_prefix()
            if prefix is None:
                return 1, "", ("root privileges are required but sudo is not installed; "
                               "re-run this command as root")
            argv = prefix + argv

        env = None
        if env_extra:
            env = os.environ.copy()
            env.update(env_extra)

        logger.debug("running: %s", " ".join(argv))
        try:
            proc = subprocess.run(
                argv,
                capture_output=capture,
                text=True,
                check=False,
                timeout=timeout,
                env=env,
            )
        except FileNotFoundError:
            return 127, "", f"command not found: {argv[0]}"
        except subprocess.TimeoutExpired:
            return 124, "", f"command timed out after {timeout}s: {' '.join(argv)}"
        except OSError as exc:
            return 1, "", str(exc)

        stdout = (proc.stdout or "").strip() if capture else ""
        stderr = (proc.stderr or "").strip() if capture else ""
        if proc.returncode != 0:
            logger.debug("exit %s: %s", proc.returncode, stderr or stdout)
        return proc.returncode, stdout, stderr

    # ---------------- privileged file helpers ----------------
    def _write_privileged(self, path: Path, content: str,
                          mode: int = 0o644) -> bool:
        """Write a file that normally belongs to root.

        The content is staged in a private temporary file and then moved into
        place with ``install``, so the destination is never left half written
        and the previous ownership and permissions are preserved.
        """
        owner = "root"
        group = "root"
        if path.exists():
            try:
                info = path.stat()
                mode = stat.S_IMODE(info.st_mode)
                owner = str(info.st_uid)
                group = str(info.st_gid)
            except OSError:
                pass

        tmp_name = ""
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                             prefix="torx.", delete=False) as tmp:
                tmp.write(content)
                tmp_name = tmp.name
            os.chmod(tmp_name, 0o644)

            parent = path.parent
            if not parent.is_dir():
                rc, _, err = self._run(["mkdir", "-p", str(parent)], sudo=True)
                if rc != 0:
                    logger.error("Cannot create %s: %s", parent, err)
                    return False

            rc, out, err = self._run(
                ["install", "-m", format(mode, "04o"), "-o", owner, "-g", group,
                 tmp_name, str(path)],
                sudo=True,
            )
            if rc != 0:
                logger.error("Cannot write %s: %s", path, err or out)
                return False
            return True
        except OSError as exc:
            logger.error("Cannot stage %s: %s", path, exc)
            return False
        finally:
            if tmp_name:
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass

    def _remove_privileged(self, path: Path) -> bool:
        if not path.exists():
            return True
        rc, out, err = self._run(["rm", "-f", str(path)], sudo=True)
        if rc != 0:
            logger.error("Cannot remove %s: %s", path, err or out)
            return False
        return True

    def _copy_privileged(self, src: Path, dst: Path) -> bool:
        rc, out, err = self._run(["cp", "-a", str(src), str(dst)], sudo=True)
        if rc != 0:
            logger.error("Cannot copy %s to %s: %s", src, dst, err or out)
            return False
        return True

    # ---------------- detection ----------------
    def is_tor_installed(self, use_cache: bool = True) -> bool:
        if use_cache and self._tor_installed_cache is not None:
            return self._tor_installed_cache
        found = shutil.which("tor") is not None or Path("/usr/sbin/tor").exists()
        self._tor_installed_cache = found
        return found

    def _require_tor(self) -> bool:
        if not self.is_tor_installed():
            logger.error("Tor is not installed. Run 'torx --install' first.")
            return False
        return True

    def _package_manager(self) -> Optional[str]:
        return shutil.which("apt-get")

    def _require_apt(self) -> bool:
        if self._package_manager() is None:
            logger.error(
                "apt-get was not found. Package management is only supported on "
                "Debian based systems such as Debian, Ubuntu and Kali Linux."
            )
            return False
        return True

    def service_backend(self) -> str:
        """Pick how the Tor service is controlled on this system."""
        if self._service_backend is not None:
            return self._service_backend
        if Path("/run/systemd/system").is_dir() and shutil.which("systemctl"):
            backend = "systemctl"
        elif shutil.which("service"):
            backend = "service"
        elif Path("/etc/init.d/tor").exists():
            backend = "initd"
        else:
            backend = "none"
        self._service_backend = backend
        logger.debug("service backend: %s", backend)
        return backend

    # ---------------- torrc ----------------
    def read_torrc(self, use_cache: bool = True) -> Dict[str, str]:
        """Return the torx-relevant directives found in torrc."""
        if use_cache and self._torrc_cache is not None:
            return self._torrc_cache

        values: Dict[str, str] = {}
        if not TORRC_PATH.exists():
            logger.debug("torrc not found at %s", TORRC_PATH)
            self._torrc_cache = values
            return values

        try:
            with TORRC_PATH.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    name, value = torrc_directive(line)
                    if name in ("socksport", "exitnodes", "strictnodes",
                                "entrynodes", "excludenodes"):
                        # The last occurrence is the one Tor keeps for these
                        # options, except SocksPort which accumulates; showing
                        # the first SocksPort matches what clients connect to.
                        if name == "socksport" and "socksport" in values:
                            continue
                        values[name] = value
        except OSError as exc:
            logger.error("Cannot read %s: %s", TORRC_PATH, exc)

        self._torrc_cache = values
        return values

    def invalidate_cache(self) -> None:
        self._torrc_cache = None

    @property
    def socks_port(self) -> str:
        raw = self.read_torrc().get("socksport", "") or DEFAULT_SOCKS_PORT
        # SocksPort can carry flags, e.g. "9050 IsolateDestAddr", and can be
        # written as "127.0.0.1:9050".
        first = raw.split()[0] if raw.split() else DEFAULT_SOCKS_PORT
        if ":" in first:
            first = first.rsplit(":", 1)[1]
        return first if first.isdigit() else DEFAULT_SOCKS_PORT

    def _backup_torrc(self) -> Optional[Path]:
        if not TORRC_PATH.exists():
            return None
        if self._copy_privileged(TORRC_PATH, BACKUP_PATH):
            return BACKUP_PATH
        return None

    def _restore_torrc(self, backup: Path) -> bool:
        if not backup.exists():
            return False
        ok = self._copy_privileged(backup, TORRC_PATH)
        if ok:
            self.invalidate_cache()
        return ok

    def set_torrc_options(self, options: Dict[str, Optional[str]]) -> ConfigChange:
        """Set or remove torrc directives.

        ``options`` maps the canonical directive name to its new value, or to
        None to delete every occurrence of it.
        """
        if not TORRC_PATH.exists():
            logger.error("%s does not exist. Install Tor before changing its "
                         "configuration.", TORRC_PATH)
            return ConfigChange.FAILED

        try:
            original = TORRC_PATH.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.error("Cannot read %s: %s", TORRC_PATH, exc)
            return ConfigChange.FAILED

        wanted = {name.lower(): value for name, value in options.items()}
        seen: set = set()
        new_lines: List[str] = []

        for raw_line in original.splitlines(keepends=True):
            name, _ = torrc_directive(raw_line)
            if name is None or name not in wanted:
                new_lines.append(raw_line)
                continue
            value = wanted[name]
            if value is None:
                # Delete the directive entirely.
                seen.add(name)
                continue
            if name in seen:
                # Drop duplicates so the file keeps exactly one of each.
                continue
            seen.add(name)
            new_lines.append(f"{options_display_name(name)} {value}\n")

        missing = [n for n, v in wanted.items() if v is not None and n not in seen]
        if missing:
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines.append("\n")
            for name in missing:
                new_lines.append(f"{options_display_name(name)} {wanted[name]}\n")

        updated = "".join(new_lines)
        if updated == original:
            logger.info("Configuration already matches the requested values.")
            return ConfigChange.UNCHANGED

        if self._backup_torrc() is None:
            logger.error("Could not back up %s, so it was left untouched.",
                         TORRC_PATH)
            return ConfigChange.FAILED
        if not self._write_privileged(TORRC_PATH, updated):
            return ConfigChange.FAILED
        self.invalidate_cache()
        logger.info("%s updated.", TORRC_PATH)
        return ConfigChange.CHANGED

    def verify_torrc(self) -> bool:
        """Ask Tor itself whether the configuration parses. Advisory only."""
        if not self.is_tor_installed():
            return True
        tor_bin = shutil.which("tor") or "/usr/sbin/tor"
        rc, out, err = self._run([tor_bin, "--verify-config", "-f", str(TORRC_PATH)],
                                 sudo=True, timeout=60)
        if rc == 0:
            logger.debug("tor --verify-config reported a valid configuration")
            return True
        logger.warning("tor reported a problem with the configuration:\n%s",
                       (err or out) or "(no details)")
        return False

    def apply_configuration(self, change: ConfigChange) -> bool:
        """Restart Tor after a configuration change, rolling back on failure."""
        if change is ConfigChange.FAILED:
            return False
        if change is ConfigChange.UNCHANGED:
            return True
        self.verify_torrc()
        if not self.auto_restart:
            logger.info("Restart skipped. Run 'torx --restart' to apply the change.")
            return True
        if not self.is_tor_installed():
            return True
        if self.tor_command("restart"):
            return True
        logger.error("Tor refused to start with the new configuration.")
        if BACKUP_PATH.exists() and self._restore_torrc(BACKUP_PATH):
            logger.warning("Previous configuration restored from %s.", BACKUP_PATH)
            self.tor_command("restart")
        return False

    def show_config(self) -> None:
        values = self.read_torrc(use_cache=False)
        exit_nodes = values.get("exitnodes") or "(any country)"
        strict = values.get("strictnodes") or "0"
        print(f"{C.bold}Configuration file:{C.reset} {TORRC_PATH}"
              f"{'' if TORRC_PATH.exists() else '  (missing)'}")
        print(f"{C.bold}SocksPort:{C.reset}         {self.socks_port}")
        print(f"{C.bold}ExitNodes:{C.reset}         {exit_nodes}")
        print(f"{C.bold}StrictNodes:{C.reset}       {strict}")
        print(f"{C.bold}Service backend:{C.reset}   {self.service_backend()}")

    # ---------------- packages ----------------
    def install_tor(self) -> bool:
        if not self._require_apt():
            return False
        if self.is_tor_installed(use_cache=False):
            logger.info("Tor is already installed; making sure it is up to date.")

        apt_env = {"DEBIAN_FRONTEND": "noninteractive"}
        logger.info("Updating the package lists...")
        rc, out, err = self._run(["apt-get", "update"], sudo=True,
                                 timeout=900, env_extra=apt_env)
        if rc != 0:
            # A stale entry for an unrelated repository should not stop the
            # installation, so this is a warning rather than a hard failure.
            logger.warning("apt-get update finished with errors: %s",
                           (err or out).splitlines()[-1] if (err or out) else rc)

        packages = ["tor", "tor-geoipdb", "ca-certificates"]
        logger.info("Installing: %s", ", ".join(packages))
        rc, out, err = self._run(
            ["apt-get", "install", "-y", "-o", "Dpkg::Options::=--force-confold"] + packages,
            sudo=True, timeout=1800, env_extra=apt_env,
        )
        if rc != 0:
            logger.error("Installation failed: %s", err or out)
            return False

        self._tor_installed_cache = True
        self.invalidate_cache()
        logger.info("%s✓%s Tor installed.", C.green, C.reset)

        # Debian based images do not always enable the service automatically.
        if self.service_backend() == "systemctl":
            self._run(["systemctl", "enable", "tor"], sudo=True, timeout=60)
        self.tor_command("start", quiet=True)
        return True

    def update_tor(self) -> bool:
        if not self._require_apt() or not self._require_tor():
            return False
        apt_env = {"DEBIAN_FRONTEND": "noninteractive"}
        logger.info("Updating the package lists...")
        self._run(["apt-get", "update"], sudo=True, timeout=900, env_extra=apt_env)
        # "apt-get upgrade <package>" does not upgrade a single package;
        # --only-upgrade with install is the supported way to do that.
        rc, out, err = self._run(
            ["apt-get", "install", "-y", "--only-upgrade", "tor", "tor-geoipdb"],
            sudo=True, timeout=1800, env_extra=apt_env,
        )
        if rc != 0:
            logger.error("Update failed: %s", err or out)
            return False
        logger.info("%s✓%s Tor is up to date.", C.green, C.reset)
        return True

    def uninstall_tor(self, purge: bool = False) -> bool:
        if not self._require_apt():
            return False
        if not self.is_tor_installed(use_cache=False):
            logger.info("Tor is not installed; nothing to remove.")
            return True

        self.tor_command("stop", quiet=True)
        self.remove_cron_job(quiet=True)

        apt_env = {"DEBIAN_FRONTEND": "noninteractive"}
        action = "purge" if purge else "remove"
        rc, out, err = self._run(["apt-get", action, "-y", "tor", "tor-geoipdb"],
                                 sudo=True, timeout=1800, env_extra=apt_env)
        if rc != 0:
            logger.error("Removal failed: %s", err or out)
            return False
        self._run(["apt-get", "autoremove", "-y"], sudo=True,
                  timeout=900, env_extra=apt_env)
        self._tor_installed_cache = False
        self.invalidate_cache()
        logger.info("%s✓%s Tor removed.", C.green, C.reset)
        return True

    # ---------------- service control ----------------
    def tor_command(self, action: str, quiet: bool = False) -> bool:
        if action not in {"start", "stop", "restart", "reload", "status"}:
            logger.error("Unknown service action: %s", action)
            return False
        if not self._require_tor():
            return False

        backend = self.service_backend()
        if backend == "systemctl":
            cmd = ["systemctl", "--no-pager", action, "tor"]
        elif backend == "service":
            cmd = ["service", "tor", action]
        elif backend == "initd":
            cmd = ["/etc/init.d/tor", action]
        else:
            logger.error("No service manager was found, so Tor cannot be controlled "
                         "automatically. Start it manually with: tor -f %s", TORRC_PATH)
            return False

        rc, out, err = self._run(cmd, sudo=True, timeout=120)
        if rc == 0:
            if not quiet:
                logger.info("%s✓%s Tor %s.", C.green, C.reset,
                            {"start": "started", "stop": "stopped",
                             "restart": "restarted", "reload": "reloaded",
                             "status": "status queried"}[action])
            return True
        if not quiet:
            logger.error("Tor %s failed: %s", action, err or out or f"exit code {rc}")
        return False

    def is_tor_running(self) -> bool:
        backend = self.service_backend()
        if backend == "systemctl":
            rc, out, _ = self._run(["systemctl", "is-active", "tor"], timeout=30)
            if out == "active":
                return True
            # The tor.service unit is a wrapper around tor@default.service.
            rc, out, _ = self._run(["systemctl", "is-active", "tor@default"], timeout=30)
            return out == "active"
        if shutil.which("pgrep"):
            rc, _, _ = self._run(["pgrep", "-x", "tor"], timeout=30)
            return rc == 0
        # As a last resort, assume it runs when the SOCKS port answers.
        return not self.is_port_available(self.socks_port)

    def show_status(self) -> bool:
        if not self._require_tor():
            return False
        backend = self.service_backend()
        if backend == "systemctl":
            cmd = ["systemctl", "--no-pager", "--full", "status", "tor"]
        elif backend == "service":
            cmd = ["service", "tor", "status"]
        elif backend == "initd":
            cmd = ["/etc/init.d/tor", "status"]
        else:
            print("Running:", "yes" if self.is_tor_running() else "no")
            return True
        # systemctl status exits non-zero when the unit is inactive, which is
        # information rather than an error, so the output is what matters.
        rc, out, err = self._run(cmd, sudo=True, timeout=60)
        text = out or err
        if text:
            print(text)
        else:
            print("Running:", "yes" if self.is_tor_running() else "no")
        return True

    # ---------------- network ----------------
    def is_port_available(self, port: str) -> bool:
        """True when nothing is bound to the port on the loopback interface."""
        try:
            number = int(port)
        except (TypeError, ValueError):
            return False
        if not 1 <= number <= 65535:
            return False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", number))
            except OSError:
                return False
        return True

    def get_tor_ip(self, port: Optional[str] = None,
                   timeout: float = 20.0) -> Optional[Tuple[str, Optional[bool]]]:
        """Return (ip, is_tor) as seen from the outside, or None on failure.

        ``is_tor`` is None when the endpoint that answered cannot confirm it.
        """
        if not self._require_tor():
            return None
        port_str = port or self.socks_port
        try:
            port_number = int(port_str)
        except (TypeError, ValueError):
            logger.error("Invalid SOCKS port: %s", port_str)
            return None

        if self.is_port_available(port_str):
            logger.error("Nothing is listening on 127.0.0.1:%s. Start Tor with "
                         "'torx --start'.", port_str)
            return None

        last_error = ""
        for url in IP_ENDPOINTS:
            try:
                body = http_get_via_socks(url, port_number, timeout=timeout)
            except SocksTimeout as exc:
                # Another destination would stall in the same way, so stop
                # here instead of waiting out every endpoint in the list.
                logger.error(
                    "%s. Tor is probably still bootstrapping, or this network "
                    "is blocking it. Check 'torx --status' and try again in a "
                    "minute.", exc)
                return None
            except (SocksError, OSError, ssl.SSLError, UnicodeError) as exc:
                last_error = str(exc)
                logger.debug("%s failed: %s", url, exc)
                continue

            if url.endswith("/api/ip"):
                # This endpoint answers with JSON. Anything else from it means
                # a captive portal or an error page, so move on rather than
                # mistaking the page itself for an address.
                try:
                    payload = json.loads(body)
                    ip = str(payload.get("IP", "")).strip()
                except (ValueError, AttributeError):
                    ip = ""
                if not ip:
                    logger.debug("Unexpected payload from %s: %.120s", url, body)
                    last_error = "the Tor check service returned an unexpected reply"
                    continue
                return ip, bool(payload.get("IsTor"))

            candidate = body.splitlines()[0].strip() if body else ""
            if candidate and len(candidate) <= 45:
                return candidate, None
            last_error = f"{url} returned an unexpected reply"

        logger.error("Could not determine the exit IP address%s",
                     f": {last_error}" if last_error else ".")
        return None

    def check_connection(self) -> bool:
        """End to end check: installed, running, port open, traffic via Tor."""
        ok = True
        if self.is_tor_installed(use_cache=False):
            print(f"{C.green}✓{C.reset} Tor is installed")
        else:
            print(f"{C.red}✗{C.reset} Tor is not installed")
            return False

        if self.is_tor_running():
            print(f"{C.green}✓{C.reset} the Tor service is running")
        else:
            print(f"{C.red}✗{C.reset} the Tor service is not running")
            ok = False

        port = self.socks_port
        if self.is_port_available(port):
            print(f"{C.red}✗{C.reset} nothing is listening on 127.0.0.1:{port}")
            ok = False
        else:
            print(f"{C.green}✓{C.reset} the SOCKS proxy answers on 127.0.0.1:{port}")

        result = self.get_tor_ip()
        if result is None:
            print(f"{C.red}✗{C.reset} could not reach the internet through Tor")
            return False
        ip, is_tor = result
        if is_tor is False:
            print(f"{C.red}✗{C.reset} the exit IP is {ip} but the traffic did not "
                  f"go through Tor")
            return False
        if is_tor:
            print(f"{C.green}✓{C.reset} exit IP address: {ip} "
                  f"(confirmed by check.torproject.org)")
        else:
            print(f"{C.green}✓{C.reset} exit IP address: {ip} "
                  f"{C.dim}(reached through the proxy; the Tor check service "
                  f"was unreachable, so this is unconfirmed){C.reset}")
        return ok

    # ---------------- configuration actions ----------------
    def set_socks_port(self, port: str) -> bool:
        port = port.strip()
        if not port.isdigit():
            logger.error("A port must be a number between 1 and 65535, got %r.", port)
            return False
        number = int(port)
        if not 1 <= number <= 65535:
            logger.error("Port %s is outside the valid range 1-65535.", port)
            return False
        if number < 1024:
            logger.warning("Port %s is privileged; Tor drops root after start-up "
                           "and may not be able to bind it.", port)

        current = self.socks_port
        if port != current and not self.is_port_available(port):
            logger.error("Port %s is already in use by another program.", port)
            return False

        change = self.set_torrc_options({"socksport": port})
        if not self.apply_configuration(change):
            return False
        if change is ConfigChange.CHANGED:
            logger.info("SOCKS proxy is now on 127.0.0.1:%s", port)
        return True

    def set_countries(self, raw_codes: str) -> bool:
        codes, invalid = normalise_country_codes(raw_codes)
        if invalid:
            logger.error("Not a valid two letter country code: %s", ", ".join(invalid))
            return False
        if not codes:
            logger.error("No country codes were given.")
            return False

        unknown = [c for c in codes if c not in COUNTRY_NAMES]
        if unknown:
            logger.warning("Unrecognised country code(s): %s. They will be written "
                           "as given; check the spelling if Tor cannot build a "
                           "circuit.", ", ".join(unknown))

        # StrictNodes tells Tor to honour the country list instead of treating
        # it as a preference it may silently ignore.
        change = self.set_torrc_options({
            "exitnodes": format_exit_nodes(codes),
            "strictnodes": "1",
        })
        if not self.apply_configuration(change):
            return False
        names = ", ".join(f"{c} ({COUNTRY_NAMES.get(c, 'unknown')})" for c in codes)
        logger.info("Exit nodes restricted to: %s", names)
        logger.info("Note that a restrictive list can leave Tor without a usable "
                    "circuit; use 'torx --clear-countries' to lift it.")
        return True

    def clear_countries(self) -> bool:
        change = self.set_torrc_options({"exitnodes": None, "strictnodes": None})
        if not self.apply_configuration(change):
            return False
        if change is ConfigChange.CHANGED:
            logger.info("Country restriction removed; any exit node may be used.")
        return True

    def new_identity(self) -> bool:
        """Restart Tor so that fresh circuits, and a new exit IP, are used."""
        if not self.tor_command("restart"):
            return False
        return True

    # ---------------- scheduling ----------------
    @staticmethod
    def cron_expression_for_minutes(minutes: int) -> Optional[str]:
        if not 1 <= minutes <= 1440:
            return None
        if minutes == 1:
            return "* * * * *"
        if minutes == 1440:
            return "0 0 * * *"
        if minutes < 60:
            return f"*/{minutes} * * * *"
        if minutes % 60 == 0:
            hours = minutes // 60
            if 24 % hours != 0:
                return None
            return "0 * * * *" if hours == 1 else f"0 */{hours} * * *"
        return None

    def setup_cron_job(self, minutes: int) -> bool:
        """Schedule a periodic Tor restart so the exit IP changes on its own."""
        if not 1 <= minutes <= 1440:
            logger.error("The interval must be between 1 and 1440 minutes "
                         "(one day), got %s.", minutes)
            return False
        expression = self.cron_expression_for_minutes(minutes)
        if expression is None:
            logger.error(
                "%s minutes cannot be expressed as a simple cron schedule. Use a "
                "value below 60, or a whole number of hours that divides 24 "
                "(60, 120, 180, 240, 360, 480, 720, 1440).", minutes)
            return False
        if not self._require_tor():
            return False

        renew_script = (
            "#!/bin/sh\n"
            "# Restart the Tor daemon so that new circuits, and a new exit IP,\n"
            "# are used. Installed by torx.\n"
            "set -e\n"
            "if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then\n"
            "    exec systemctl restart tor\n"
            "fi\n"
            "if command -v service >/dev/null 2>&1; then\n"
            "    exec service tor restart\n"
            "fi\n"
            "exec /etc/init.d/tor restart\n"
        )
        if not self._write_privileged(RENEW_SCRIPT_PATH, renew_script, mode=0o755):
            return False

        # A file in /etc/cron.d runs as the user named in the sixth field, so
        # the restart has the privileges it needs without touching a personal
        # crontab. The file name must not contain a dot or cron ignores it.
        cron_content = (
            "# Periodic Tor restart, installed by torx.\n"
            "# Remove this file, or run 'torx --remove-cron', to stop it.\n"
            "SHELL=/bin/sh\n"
            "PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin\n"
            f"{expression} root {RENEW_SCRIPT_PATH} >/dev/null 2>&1\n"
        )
        if not self._write_privileged(CRON_FILE_PATH, cron_content, mode=0o644):
            return False

        if not shutil.which("crontab") and not Path("/usr/sbin/cron").exists():
            logger.warning("No cron daemon appears to be installed. Install one with "
                           "'sudo apt-get install cron' and enable it, otherwise the "
                           "schedule will never run.")
        logger.info("%s✓%s Scheduled a Tor restart %s (%s).", C.green, C.reset,
                    _describe_minutes(minutes), expression)
        return True

    def remove_cron_job(self, quiet: bool = False) -> bool:
        existed = CRON_FILE_PATH.exists() or RENEW_SCRIPT_PATH.exists()
        ok = self._remove_privileged(CRON_FILE_PATH)
        ok = self._remove_privileged(RENEW_SCRIPT_PATH) and ok
        if ok and not quiet:
            logger.info("Scheduled restart removed." if existed
                        else "No scheduled restart was configured.")
        return ok

    def cron_status(self) -> Optional[str]:
        if not CRON_FILE_PATH.exists():
            return None
        try:
            for line in CRON_FILE_PATH.read_text(encoding="utf-8",
                                                 errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and " root " in line:
                    return " ".join(line.split()[:5])
        except OSError:
            return None
        return None


def options_display_name(canonical: str) -> str:
    """Map an internal directive key back to the spelling used in torrc."""
    return {
        "socksport": "SocksPort",
        "exitnodes": "ExitNodes",
        "strictnodes": "StrictNodes",
        "entrynodes": "EntryNodes",
        "excludenodes": "ExcludeNodes",
    }.get(canonical, canonical)


def _describe_minutes(minutes: int) -> str:
    if minutes == 1:
        return "every minute"
    if minutes < 60:
        return f"every {minutes} minutes"
    if minutes == 60:
        return "every hour"
    if minutes == 1440:
        return "once a day"
    return f"every {minutes // 60} hours"


# --------------------------------------------------------------------------
# Country listing
# --------------------------------------------------------------------------
def print_country_table(columns: int = 3) -> None:
    entries = [f"{code} - {name}" for code, name in sorted(COUNTRY_NAMES.items())]
    width = max(len(entry) for entry in entries) + 2
    for index in range(0, len(entries), columns):
        row = entries[index:index + columns]
        print("  " + "".join(entry.ljust(width) for entry in row).rstrip())


# --------------------------------------------------------------------------
# Interactive menu
# --------------------------------------------------------------------------
MENU_ITEMS: Tuple[Tuple[str, str], ...] = (
    ("1", "Install Tor"),
    ("2", "Update Tor"),
    ("3", "Remove Tor"),
    ("4", "Show the current exit IP"),
    ("5", "Change the exit IP (restart Tor)"),
    ("6", "Change the SOCKS port"),
    ("7", "Change the exit countries"),
    ("8", "Clear the country restriction"),
    ("9", "Schedule an automatic IP change"),
    ("10", "Remove the scheduled IP change"),
    ("11", "Start Tor"),
    ("12", "Stop Tor"),
    ("13", "Restart Tor"),
    ("14", "Reload Tor"),
    ("15", "Show the service status"),
    ("16", "Run a connection check"),
    ("0", "Exit"),
)


class Menu:
    def __init__(self, manager: TorManager) -> None:
        self.mgr = manager

    def _header(self) -> None:
        installed = self.mgr.is_tor_installed(use_cache=False)
        if installed:
            running = self.mgr.is_tor_running()
            state = (f"{C.green}installed and running{C.reset}" if running
                     else f"{C.yellow}installed, not running{C.reset}")
        else:
            state = f"{C.red}not installed{C.reset}"

        values = self.mgr.read_torrc(use_cache=False)
        countries = values.get("exitnodes") or "any"
        schedule = self.mgr.cron_status()

        print(f"{C.bold}{C.cyan}torx{C.reset} {C.dim}v{__version__}{C.reset} "
              f"{C.dim}— Tor proxy manager{C.reset}\n")
        print(f"  Status     : {state}")
        print(f"  SOCKS proxy: 127.0.0.1:{self.mgr.socks_port}")
        print(f"  Exit nodes : {countries}")
        print(f"  Auto change: {schedule if schedule else 'off'}")
        print()

    def _print_menu(self) -> None:
        for key, label in MENU_ITEMS:
            print(f"  {C.bold}{key:>2}{C.reset}) {label}")
        print()

    def run(self) -> int:
        if not sys.stdin.isatty():
            logger.error("The menu needs an interactive terminal. Use the command "
                         "line options instead; run 'torx --help' to see them.")
            return 2

        handlers = {
            "1": self._install,
            "2": self._update,
            "3": self._uninstall,
            "4": self._show_ip,
            "5": self._new_ip,
            "6": self._change_port,
            "7": self._change_countries,
            "8": self._clear_countries,
            "9": self._schedule,
            "10": self._unschedule,
            "11": lambda: self.mgr.tor_command("start"),
            "12": lambda: self.mgr.tor_command("stop"),
            "13": lambda: self.mgr.tor_command("restart"),
            "14": lambda: self.mgr.tor_command("reload"),
            "15": self.mgr.show_status,
            "16": self.mgr.check_connection,
        }

        while True:
            clear_screen()
            self._header()
            self._print_menu()

            choice = ask("Choice: ")
            if choice is None or choice == "0":
                print("Bye.")
                return 0
            handler = handlers.get(choice)
            if handler is None:
                print(f"{C.yellow}'{choice}' is not one of the options.{C.reset}")
            else:
                print()
                try:
                    handler()
                except KeyboardInterrupt:
                    print(f"\n{C.yellow}Interrupted.{C.reset}")
            if ask("\nPress Enter to continue... ") is None:
                return 0

    # -- individual actions -------------------------------------------------
    def _install(self) -> None:
        self.mgr.install_tor()

    def _update(self) -> None:
        self.mgr.update_tor()

    def _uninstall(self) -> None:
        answer = ask("Remove Tor and its configuration? [y/N]: ")
        if answer and answer.lower() in ("y", "yes"):
            purge = ask("Also delete /etc/tor configuration files? [y/N]: ")
            self.mgr.uninstall_tor(purge=bool(purge and purge.lower() in ("y", "yes")))
        else:
            print("Cancelled.")

    def _show_ip(self) -> None:
        result = self.mgr.get_tor_ip()
        if result is None:
            return
        ip, is_tor = result
        if is_tor is True:
            print(f"Exit IP: {C.bold}{ip}{C.reset} {C.green}(via Tor){C.reset}")
        elif is_tor is False:
            print(f"Exit IP: {C.bold}{ip}{C.reset} "
                  f"{C.red}(this traffic did not go through Tor){C.reset}")
        else:
            print(f"Exit IP: {C.bold}{ip}{C.reset}")

    def _new_ip(self) -> None:
        if not self.mgr.new_identity():
            return
        result = self.mgr.get_tor_ip()
        if result:
            print(f"New exit IP: {C.bold}{result[0]}{C.reset}")

    def _change_port(self) -> None:
        print(f"Current SOCKS port: {self.mgr.socks_port}")
        port = ask("New port (Enter to cancel): ")
        if not port:
            print("Cancelled.")
            return
        self.mgr.set_socks_port(port)

    def _change_countries(self) -> None:
        print("Available countries:\n")
        print_country_table()
        print("\nEnter one or more codes separated by spaces or commas, "
              "for example: de nl se")
        raw = ask("Codes (Enter to cancel): ")
        if not raw:
            print("Cancelled.")
            return
        self.mgr.set_countries(raw)

    def _clear_countries(self) -> None:
        self.mgr.clear_countries()

    def _schedule(self) -> None:
        print("How often should the exit IP change?\n")
        for index, (minutes, label) in enumerate(CRON_PRESETS, start=1):
            print(f"  {index}) {label}")
        print(f"  {len(CRON_PRESETS) + 1}) a custom number of minutes")
        pick = ask(f"\nChoice [1-{len(CRON_PRESETS) + 1}]: ")
        if not pick or not pick.isdigit():
            print("Cancelled.")
            return
        index = int(pick)
        if 1 <= index <= len(CRON_PRESETS):
            self.mgr.setup_cron_job(CRON_PRESETS[index - 1][0])
            return
        if index == len(CRON_PRESETS) + 1:
            raw = ask("Minutes between restarts: ")
            if raw and raw.isdigit():
                self.mgr.setup_cron_job(int(raw))
            else:
                print("That is not a number of minutes.")
            return
        print("Cancelled.")

    def _unschedule(self) -> None:
        self.mgr.remove_cron_job()


# --------------------------------------------------------------------------
# Command line interface
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="torx",
        description="Manage the Tor SOCKS proxy on Debian based systems.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  torx                          open the interactive menu\n"
            "  torx --install                install Tor and start the service\n"
            "  torx --set-countries de,nl    only use exit nodes in Germany or "
            "the Netherlands\n"
            "  torx --restart --get-ip       take a new circuit and print the "
            "new exit IP\n"
            "  torx --cron 30                change the exit IP every 30 minutes\n"
        ),
    )
    parser.add_argument("--version", action="version",
                        version=f"torx {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print the commands that are executed")
    parser.add_argument("--non-interactive", action="store_true",
                        help="never open the menu; exit instead")
    parser.add_argument("--no-restart", action="store_true",
                        help="do not restart Tor after a configuration change")

    packages = parser.add_argument_group("packages")
    packages.add_argument("--install", action="store_true",
                          help="install Tor and its GeoIP database")
    packages.add_argument("--update", action="store_true",
                          help="upgrade the installed Tor packages")
    packages.add_argument("--uninstall", action="store_true",
                          help="remove the Tor packages")
    packages.add_argument("--purge", action="store_true",
                          help="with --uninstall, also delete /etc/tor")

    config = parser.add_argument_group("configuration")
    config.add_argument("--set-port", metavar="PORT",
                        help="set the SocksPort in torrc")
    config.add_argument("--set-countries", metavar="CODES",
                        help="restrict exit nodes to these country codes")
    config.add_argument("--clear-countries", action="store_true",
                        help="allow exit nodes in any country")
    config.add_argument("--list-countries", action="store_true",
                        help="list the known country codes")
    config.add_argument("--show-config", action="store_true",
                        help="print the current settings")

    service = parser.add_argument_group("service")
    service.add_argument("--start", action="store_true", help="start Tor")
    service.add_argument("--stop", action="store_true", help="stop Tor")
    service.add_argument("--restart", action="store_true",
                         help="restart Tor, which also changes the exit IP")
    service.add_argument("--reload", action="store_true",
                         help="reload the Tor configuration")
    service.add_argument("--status", action="store_true",
                         help="show the service status")

    network = parser.add_argument_group("network")
    network.add_argument("--get-ip", action="store_true",
                         help="print the current exit IP address")
    network.add_argument("--check", action="store_true",
                         help="verify that traffic really goes through Tor")

    schedule = parser.add_argument_group("scheduling")
    schedule.add_argument("--cron", type=int, metavar="MINUTES",
                          help="restart Tor every MINUTES minutes (1-1440)")
    schedule.add_argument("--remove-cron", action="store_true",
                          help="remove the scheduled restart")

    return parser


def run_cli(args: argparse.Namespace) -> int:
    mgr = TorManager(auto_restart=not args.no_restart)
    ok = True
    acted = False

    # Read-only actions first, so they can be combined with anything else.
    if args.list_countries:
        acted = True
        print_country_table()

    if args.install:
        acted = True
        ok = mgr.install_tor() and ok
    if args.update:
        acted = True
        ok = mgr.update_tor() and ok

    if args.set_port:
        acted = True
        ok = mgr.set_socks_port(args.set_port) and ok
    if args.set_countries:
        acted = True
        ok = mgr.set_countries(args.set_countries) and ok
    if args.clear_countries:
        acted = True
        ok = mgr.clear_countries() and ok

    if args.cron is not None:
        acted = True
        ok = mgr.setup_cron_job(args.cron) and ok
    if args.remove_cron:
        acted = True
        ok = mgr.remove_cron_job() and ok

    for flag, action in (("start", "start"), ("stop", "stop"),
                         ("restart", "restart"), ("reload", "reload")):
        if getattr(args, flag):
            acted = True
            ok = mgr.tor_command(action) and ok

    if args.show_config:
        acted = True
        mgr.show_config()
    if args.status:
        acted = True
        ok = mgr.show_status() and ok

    if args.get_ip:
        acted = True
        result = mgr.get_tor_ip()
        if result is None:
            ok = False
        else:
            print(result[0])
    if args.check:
        acted = True
        ok = mgr.check_connection() and ok

    if args.uninstall:
        acted = True
        ok = mgr.uninstall_tor(purge=args.purge) and ok

    if not acted:
        if args.non_interactive or not sys.stdin.isatty():
            build_parser().print_help()
            return 0
        return Menu(mgr).run()

    return 0 if ok else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    if sys.platform != "linux":
        logger.error("torx manages a system service and only runs on Linux.")
        return 2
    if args.purge and not args.uninstall:
        parser.error("--purge only makes sense together with --uninstall")

    try:
        return run_cli(args)
    except KeyboardInterrupt:
        print()
        logger.warning("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
