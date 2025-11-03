#!/usr/bin/env python3
"""
tor_manager.py — safer, cleaner rewrite of your Tor manager.
Works on Python 3.8+.
"""

from __future__ import annotations
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple, List
import logging
import argparse

# Config
TORRC_PATH = Path("/etc/tor/torrc")
SCRIPT_PATH = Path("/usr/bin/restart_tor.sh")
VALID_COUNTRY_CODES = {
    "tr": "Turkey", "de": "Germany", "us": "United States", "fr": "France",
    "uk": "United Kingdom", "at": "Austria", "be": "Belgium", "ro": "Romania",
    "ca": "Canada", "sg": "Singapore", "jp": "Japan", "ie": "Ireland",
    "fi": "Finland", "es": "Spain", "pl": "Poland"
}

# Logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("tor_manager")


class TorManager:
    def __init__(self):
        self._tor_installed_cache: Optional[bool] = None
        self._torrc_cache: Optional[Tuple[Optional[str], Optional[str]]] = None

    # ---------- helpers ----------
    def _run_command(self, cmd: List[str], check: bool = True, sudo: bool = False,
                     timeout: Optional[int] = None) -> Tuple[int, str, str]:
        """Run command and return (returncode, stdout, stderr). Do not raise."""
        if sudo and os.geteuid() != 0:
            cmd = ["sudo"] + cmd
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            if check and proc.returncode != 0:
                logger.debug("Command failed: %s -> %s", " ".join(cmd), stderr.strip())
            return proc.returncode, stdout.strip(), stderr.strip()
        except Exception as e:
            return 1, "", str(e)

    def is_tor_installed(self, use_cache: bool = True) -> bool:
        """Detect tor using shutil.which — reliable and simple."""
        if use_cache and self._tor_installed_cache is not None:
            return self._tor_installed_cache
        found = shutil.which("tor") is not None
        self._tor_installed_cache = found
        return found

    def _invalidate_cache(self) -> None:
        self._torrc_cache = None

    def _require_tor(self) -> bool:
        if not self.is_tor_installed():
            logger.error("Tor is not installed. Install it first.")
            return False
        return True

    # ---------- torrc reading/writing ----------
    def read_torrc(self) -> Tuple[Optional[str], Optional[str]]:
        """Return (SocksPort, ExitNodes). Uses cache."""
        if self._torrc_cache is not None:
            return self._torrc_cache

        if not TORRC_PATH.exists():
            logger.warning("torrc not found at %s", TORRC_PATH)
            self._torrc_cache = (None, None)
            return (None, None)

        socks_port = None
        exit_nodes = None
        try:
            with TORRC_PATH.open("r", encoding="utf-8", errors="ignore") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("SocksPort"):
                        parts = line.split()
                        socks_port = parts[1] if len(parts) > 1 else None
                    elif line.startswith("ExitNodes"):
                        # keep everything after directive
                        exit_nodes = line.split(maxsplit=1)[1] if len(line.split(maxsplit=1)) > 1 else None
            self._torrc_cache = (socks_port, exit_nodes)
            return self._torrc_cache
        except Exception as e:
            logger.error("Failed to read torrc: %s", e)
            return (None, None)

    def modify_torrc(self, new_socks_port: Optional[str] = None, new_exit_nodes: Optional[str] = None) -> bool:
        """Modify torrc only if required. Returns True if file changed."""
        if not TORRC_PATH.exists():
            logger.error("torrc not found at %s — cannot modify", TORRC_PATH)
            return False

        try:
            with TORRC_PATH.open("r", encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()
        except Exception as e:
            logger.error("Cannot read torrc: %s", e)
            return False

        socks_found = False
        exit_found = False
        new_lines: List[str] = []
        modified = False

        for raw in lines:
            stripped = raw.strip()
            if stripped.startswith("SocksPort"):
                socks_found = True
                if new_socks_port:
                    new_lines.append(f"SocksPort {new_socks_port}\n")
                    modified = modified or (raw.strip() != f"SocksPort {new_socks_port}")
                else:
                    new_lines.append(raw)
            elif stripped.startswith("ExitNodes"):
                exit_found = True
                if new_exit_nodes:
                    new_lines.append(f"ExitNodes {new_exit_nodes}\n")
                    modified = modified or (raw.strip() != f"ExitNodes {new_exit_nodes}")
                else:
                    new_lines.append(raw)
            else:
                new_lines.append(raw)

        if new_socks_port and not socks_found:
            new_lines.append(f"SocksPort {new_socks_port}\n")
            modified = True
        if new_exit_nodes and not exit_found:
            new_lines.append(f"ExitNodes {new_exit_nodes}\n")
            modified = True

        if not modified:
            logger.info("No changes needed in torrc.")
            return False

        # safe write (atomic-ish)
        try:
            tmp = TORRC_PATH.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                fh.writelines(new_lines)
            tmp.replace(TORRC_PATH)
            self._invalidate_cache()
            logger.info("torrc updated successfully.")
            return True
        except Exception as e:
            logger.error("Failed to write torrc: %s", e)
            return False

    # ---------- package management ----------
    def install_tor(self) -> bool:
        """Install tor and dependencies (apt). Return success boolean."""
        logger.info("Installing Tor and dependencies...")
        steps = [
            (["apt", "update"], "update packages"),
            (["apt", "install", "-y", "tor"], "install tor"),
            (["apt", "install", "-y", "tor-geoipdb"], "install tor-geoipdb"),
            (["apt", "install", "-y", "python3-pip"], "install python3-pip"),
        ]
        for cmd, desc in steps:
            rc, out, err = self._run_command(cmd, check=True, sudo=True)
            if rc != 0:
                logger.error("Failed: %s — %s", desc, err or out)
                return False
            logger.info("✓ %s", desc)
        # install requests (pip) — non-fatal if fails
        rc, out, err = self._run_command(["pip3", "install", "requests", "requests[socks]"], check=False, sudo=False)
        if rc != 0:
            logger.warning("pip install returned non-zero: %s", err or out)
        self._tor_installed_cache = True
        logger.info("Tor installation completed.")
        return True

    def uninstall_tor(self) -> bool:
        rc, out, err = self._run_command(["apt", "remove", "-y", "tor"], check=False, sudo=True)
        if rc == 0:
            self._tor_installed_cache = False
            logger.info("Tor uninstalled.")
            return True
        logger.error("Uninstall failed: %s", err or out)
        return False

    def update_tor(self) -> bool:
        if not self.is_tor_installed():
            logger.error("Tor is not installed.")
            return False
        rc, out, err = self._run_command(["apt", "upgrade", "-y", "tor"], check=False, sudo=True)
        if rc == 0:
            logger.info("Tor updated.")
            return True
        logger.error("Update failed: %s", err or out)
        return False

    # ---------- runtime / network ----------
    def get_tor_ip(self, port: Optional[str] = None) -> Optional[str]:
        """Return external IP via Tor SOCKS proxy (requires requests and a running tor)."""
        if not self._require_tor():
            return None
        socks_port, _ = self.read_torrc()
        port = (port or socks_port or "9050")
        try:
            import requests  # type: ignore
            proxies = {"http": f"socks5h://127.0.0.1:{port}", "https": f"socks5h://127.0.0.1:{port}"}
            r = requests.get("http://checkip.amazonaws.com", proxies=proxies, timeout=10)
            if r.ok:
                return r.text.strip()
            logger.error("Failed to fetch IP — status %s", r.status_code)
            return None
        except Exception as e:
            logger.error("Error getting Tor IP: %s", e)
            return None

    def is_port_available(self, port: str) -> bool:
        """Return True if port is free on localhost."""
        try:
            p = int(port)
        except ValueError:
            return False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", p)) != 0

    # ---------- tor control ----------
    def tor_command(self, action: str) -> bool:
        """start/stop/restart/reload via systemctl"""
        if not self._require_tor():
            return False
        if action not in {"start", "stop", "restart", "reload", "status"}:
            logger.error("Unknown action: %s", action)
            return False
        rc, out, err = self._run_command(["systemctl", action, "tor"], check=False, sudo=True)
        if rc == 0:
            logger.info("Tor %s OK", action)
            return True
        logger.error("Tor %s failed: %s", action, err or out)
        return False

    def show_status(self) -> None:
        rc, out, err = self._run_command(["systemctl", "status", "tor"], check=False, sudo=True)
        print(out or err)

    # ---------- cron helpers ----------
    def _cron_expression_for_minutes(self, minutes: int) -> Optional[str]:
        """Translate minutes to a safe cron expression (minute hour day month dow)."""
        # handle common presets only
        if minutes == 1:
            return "* * * * *"  # every minute
        if minutes == 30:
            return "*/30 * * * *"
        if minutes == 60:
            return "0 * * * *"  # every hour at minute 0
        if minutes == 240:
            return "0 */4 * * *"  # every 4 hours
        if minutes == 720:
            return "0 */12 * * *"  # every 12 hours
        if minutes == 1440:
            return "0 0 * * *"  # daily at midnight
        return None

    def setup_cron_job(self, minutes: int) -> bool:
        """Create a cron entry that runs SCRIPT_PATH at the specified frequency (minutes)."""
        expr = self._cron_expression_for_minutes(minutes)
        if expr is None:
            logger.error("Unsupported minutes value: %s", minutes)
            return False

        script_content = "#!/bin/bash\nsystemctl restart tor || service tor restart\n"
        try:
            SCRIPT_PATH.write_text(script_content)
            SCRIPT_PATH.chmod(0o755)
        except Exception as e:
            logger.error("Failed to create %s: %s", SCRIPT_PATH, e)
            return False

        # Read current crontab safely
        rc, out, err = self._run_command(["crontab", "-l"], check=False, sudo=False)
        existing = []
        if rc == 0 and out:
            existing = [l for l in out.splitlines() if SCRIPT_PATH.as_posix() not in l and l.strip()]
        existing.append(f"{expr} {SCRIPT_PATH.as_posix()}")
        with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
            tmp.write("\n".join(existing) + "\n")
            tmp_name = tmp.name
        rc, out, err = self._run_command(["crontab", tmp_name], check=False, sudo=False)
        try:
            os.remove(tmp_name)
        except Exception:
            pass
        if rc == 0:
            logger.info("Cron job installed: every %s minutes (expr: %s)", minutes, expr)
            return True
        logger.error("Failed to install crontab: %s", err or out)
        return False

    # ---------- interactive menu ----------
    def interactive_menu(self) -> None:
        """Simple interactive menu loop. Uses if/elif to stay compatible."""
        is_tty = sys.stdin.isatty()
        while True:
            os.system("clear")
            print("\033[1;36mTor Manager\033[0m\n")
            tor_status = "✓ Installed" if self.is_tor_installed() else "✗ Not installed"
            socks_port, countries = self.read_torrc()
            socks_port = socks_port or "9050"
            countries = countries or "Default"
            print(f"Status: {tor_status}")
            print(f"Server: 127.0.0.1:{socks_port}")
            print(f"Countries: {countries}")
            print("\n1) Install Tor\n2) Update Tor\n3) Uninstall Tor\n4) Get Tor IP\n5) Setup Cron Job\n6) Change IP (reload/restart)\n7) Change Port\n8) Change Countries\n9) Start Tor\n10) Stop Tor\n11) Restart Tor\n12) Reload Tor\n13) Show Status\n0) Exit\n")

            choice = input("Choice: ").strip() if is_tty else "0"
            # classic if/elif
            if choice == "0":
                print("Exiting.")
                return
            elif choice == "1":
                self.install_tor()
            elif choice == "2":
                self.update_tor()
            elif choice == "3":
                self.uninstall_tor()
            elif choice == "4":
                ip = self.get_tor_ip()
                print(f"Tor IP: {ip}" if ip else "Could not get IP.")
            elif choice == "5":
                print("Choose interval:\n 1) 1 min\n 2) 30 min\n 3) 1 hour\n 4) 4 hours\n 5) 12 hours\n 6) 24 hours")
                pick = input("Pick [1-6]: ").strip()
                mapping = {"1": 1, "2": 30, "3": 60, "4": 240, "5": 720, "6": 1440}
                if pick in mapping:
                    self.setup_cron_job(mapping[pick])
                else:
                    print("Invalid")
            elif choice == "6":
                self.tor_command("reload")
                self.tor_command("restart")
                print("Tor reloaded & restarted.")
            elif choice == "7":
                port = input("Enter new SocksPort: ").strip()
                if port.isdigit() and self.is_port_available(port):
                    self.modify_torrc(new_socks_port=port)
                    self.tor_command("restart")
                    print("Port changed.")
                else:
                    print("Invalid or busy port.")
            elif choice == "8":
                print("Available countries:")
                for code, name in sorted(VALID_COUNTRY_CODES.items()):
                    print(f"  {code} - {name}")
                codes_raw = input("Enter codes (comma/space sep): ").strip()
                codes = [c.strip().lower() for c in codes_raw.replace(",", " ").split() if c.strip()]
                invalid = [c for c in codes if c not in VALID_COUNTRY_CODES]
                if invalid:
                    print("Invalid codes:", ", ".join(invalid))
                else:
                    exit_nodes = "".join(f"{{{c}}}" for c in codes)
                    self.modify_torrc(new_exit_nodes=exit_nodes)
                    self.tor_command("restart")
                    print("Countries updated.")
            elif choice == "9":
                self.tor_command("start")
            elif choice == "10":
                self.tor_command("stop")
            elif choice == "11":
                self.tor_command("restart")
            elif choice == "12":
                self.tor_command("reload")
            elif choice == "13":
                self.show_status()
            else:
                print("Invalid choice.")

            if is_tty:
                input("Press Enter to continue...")

# ---------- CLI ----------
def parse_args():
    p = argparse.ArgumentParser(description="Tor Manager (safe rewrite)")
    p.add_argument("--install", action="store_true", help="Install Tor")
    p.add_argument("--uninstall", action="store_true", help="Uninstall Tor")
    p.add_argument("--update", action="store_true", help="Update Tor package")
    p.add_argument("--get-ip", action="store_true", help="Get current Tor exit IP")
    p.add_argument("--restart", action="store_true", help="Restart Tor")
    p.add_argument("--reload", action="store_true", help="Reload Tor")
    p.add_argument("--status", action="store_true", help="Show systemctl status")
    p.add_argument("--set-port", type=str, help="Set SocksPort (modify torrc)")
    p.add_argument("--set-countries", type=str, help="Set ExitNodes (comma separated codes)")
    p.add_argument("--cron", type=int, choices=[1,30,60,240,720,1440], help="Install cron job interval (minutes)")
    p.add_argument("--non-interactive", action="store_true", help="Do not run interactive menu")
    return p.parse_args()

def main():
    args = parse_args()
    mgr = TorManager()

    if args.install:
        mgr.install_tor()
    elif args.uninstall:
        mgr.uninstall_tor()
    elif args.update:
        mgr.update_tor()
    elif args.get_ip:
        ip = mgr.get_tor_ip()
        print(ip or "Could not retrieve IP.")
    elif args.restart:
        mgr.tor_command("restart")
    elif args.reload:
        mgr.tor_command("reload")
    elif args.status:
        mgr.show_status()
    elif args.set_port:
        p = args.set_port.strip()
        if p.isdigit() and mgr.is_port_available(p):
            mgr.modify_torrc(new_socks_port=p)
            mgr.tor_command("restart")
            print("Port set to", p)
        else:
            print("Invalid or busy port:", p)
    elif args.set_countries:
        codes = [c.strip().lower() for c in args.set_countries.replace(",", " ").split() if c.strip()]
        invalid = [c for c in codes if c not in VALID_COUNTRY_CODES]
        if invalid:
            print("Invalid country codes:", ", ".join(invalid))
        else:
            exit_nodes = "".join(f"{{{c}}}" for c in codes)
            mgr.modify_torrc(new_exit_nodes=exit_nodes)
            mgr.tor_command("restart")
            print("ExitNodes set to", exit_nodes)
    elif args.cron is not None:
        mgr.setup_cron_job(args.cron)
    else:
        if args.non_interactive:
            print("No action specified and running non-interactive — exiting.")
            return
        mgr.interactive_menu()


if __name__ == "__main__":
    main()
