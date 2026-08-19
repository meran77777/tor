# torx

A command line manager for the Tor SOCKS proxy on Debian based systems.

It installs Tor, keeps the service running, changes the exit IP on demand or on
a schedule, restricts exit nodes to chosen countries, and verifies that traffic
really leaves through the Tor network — from an interactive menu or from
scriptable flags.

```
torx v2.0.0 — Tor proxy manager

  Status     : installed and running
  SOCKS proxy: 127.0.0.1:9050
  Exit nodes : {de},{nl}
  Auto change: */30 * * * *
```

---

## Install

One command installs torx, installs Tor itself, starts the service and opens
the menu:

```bash
curl -fsSL https://raw.githubusercontent.com/meran77777/tor/main/install.sh | sudo bash
```

Prefer `wget`:

```bash
wget -qO- https://raw.githubusercontent.com/meran77777/tor/main/install.sh | sudo bash
```

Or from a clone:

```bash
git clone https://github.com/meran77777/tor.git
cd tor
sudo ./install.sh
```

The installer verifies that the source compiles before putting anything in
place, and migrates any previous installation out of `/usr/bin`.

### Installer options

| Option | Effect |
| --- | --- |
| *(none)* | install torx and Tor, then open the menu |
| `--no-start` | install everything, do not open the menu |
| `--no-tor` | install torx only, leave the Tor package alone |
| `--prefix DIR` | install into `DIR` instead of `/usr/local/bin` |
| `--uninstall` | remove torx and everything it installed |
| `--help` | show usage |

For an unattended install — a Dockerfile, a provisioning script, CI — use
`--no-start`. Without a terminal the menu is skipped automatically rather than
hanging, so a piped install never blocks.

---

## Usage

Run `torx` with no arguments for the menu, or use the flags directly:

```bash
torx --check                    # is traffic really going through Tor?
torx --get-ip                   # print the current exit IP
torx --restart                  # new circuits, new exit IP
torx --set-countries de,nl,se   # only exit in Germany, the Netherlands or Sweden
torx --clear-countries          # allow any country again
torx --set-port 9150            # move the SOCKS proxy
torx --cron 30                  # change the exit IP every 30 minutes
torx --remove-cron              # stop doing that
```

Flags can be combined; they run in a sensible order and the exit status is
non-zero if any step fails:

```bash
torx --restart --get-ip
```

Point a program at the proxy with `socks5h://127.0.0.1:9050` — the `h` makes
DNS resolve inside the Tor network instead of leaking to the local resolver:

```bash
curl --proxy socks5h://127.0.0.1:9050 https://check.torproject.org/api/ip
```

### All options

| Group | Options |
| --- | --- |
| Packages | `--install` `--update` `--uninstall` `--purge` |
| Configuration | `--set-port` `--set-countries` `--clear-countries` `--list-countries` `--show-config` |
| Service | `--start` `--stop` `--restart` `--reload` `--status` |
| Network | `--get-ip` `--check` |
| Scheduling | `--cron MINUTES` `--remove-cron` |
| Other | `--no-restart` `--non-interactive` `--verbose` `--version` `--help` |

`torx --help` prints the full list with descriptions.

---

## The source

The whole project is two files. There is nothing to build and nothing to
package.

| Path | Purpose |
| --- | --- |
| `torx.py` | the entire program — CLI, menu, Tor management, SOCKS client |
| `install.sh` | installer and uninstaller |

### Inside `torx.py`

A single file, standard library only, laid out in sections:

- **Configuration** — paths, the country table, the endpoints used for IP
  lookups.
- **Terminal helpers** — colour handling that respects `NO_COLOR` and
  non-terminal output, and input that survives `Ctrl+C` and `Ctrl+D`.
- **SOCKS5 client** — `socks5_connect()` and `http_get_via_socks()` speak
  SOCKS5 and HTTP(S) directly over `socket` and `ssl`. This is why torx has no
  dependency on `requests` or `PySocks`, which recent Debian, Ubuntu and Kali
  releases refuse to install with `pip` under
  [PEP 668](https://peps.python.org/pep-0668/).
- **torrc parsing** — `torrc_directive()` tokenises a configuration line;
  `set_torrc_options()` rewrites directives while preserving comments,
  formatting and unrelated settings.
- **`TorManager`** — everything that touches the system: package management
  through `apt-get`, service control, privileged writes, the network checks
  and the scheduler.
- **`Menu`** — the interactive interface.
- **CLI** — `build_parser()`, `run_cli()` and `main()`.

Two design points worth knowing:

*Privileged writes.* `torx` is meant to be run as a normal user. Every write to
a root owned file is staged in a private temporary file and moved into place
with `install` under `sudo`, preserving the destination's original owner and
mode. A write that is refused is reported as a failure — never as success.

*Configuration rollback.* Before `torrc` is modified it is copied to
`/etc/tor/torrc.torx.bak`. The new file is checked with `tor --verify-config`,
and if Tor still refuses to start, the previous configuration is restored and
the service is brought back up. A bad edit cannot leave the daemon dead.

### What lands on the system

| Path | Created by | Purpose |
| --- | --- | --- |
| `/usr/local/bin/torx` | installer | the program |
| `/etc/tor/torrc` | Tor package, edited by torx | Tor configuration |
| `/etc/tor/torrc.torx.bak` | torx | rollback copy of the last good configuration |
| `/etc/cron.d/torx` | `--cron` | the schedule |
| `/usr/local/sbin/torx-renew` | `--cron` | the script the schedule runs |

---

## Requirements

- Debian, Ubuntu or Kali Linux — anything with `apt-get`.
- Python 3.8 or newer, which every supported release already ships. No `pip`
  packages, no virtualenv.
- `sudo`, or run as root.

systemd is used when present; `service` and `/etc/init.d/tor` are used as
fallbacks, so torx also works in containers and on WSL.

---

## Notes on anonymity

`--set-countries` writes `ExitNodes` together with `StrictNodes 1`, because
without `StrictNodes` Tor treats the country list as a preference and silently
ignores it. Be aware of the trade-off the Tor Project itself points out:
restricting exit nodes shrinks the set of relays you use and can make you
easier to distinguish, and an over-narrow list can leave Tor unable to build a
circuit at all. `torx --clear-countries` lifts the restriction.

`torx --check` confirms the answer with `check.torproject.org`, which reports
whether the request actually arrived over Tor rather than merely through the
proxy.

torx sends nothing anywhere. The only outbound requests it makes are the exit
IP lookups, and those go through Tor.

---

## Uninstall

```bash
sudo ./install.sh --uninstall     # remove torx, keep Tor
sudo torx --uninstall             # remove the Tor package too
sudo torx --uninstall --purge     # and delete /etc/tor
```

---

## Troubleshooting

**`torx --get-ip` reports that no circuit opened.** Tor had not finished
bootstrapping, or the network is blocking it. Check `torx --status`, wait a
moment and try again.

**The schedule never runs.** A cron daemon has to be installed and enabled:
`sudo apt-get install cron && sudo systemctl enable --now cron`. torx warns
about this when it writes the schedule.

**Tor will not start after a country change.** The list was too restrictive.
Run `torx --clear-countries`, or restore `/etc/tor/torrc.torx.bak`.

Add `--verbose` to any command to see exactly which system commands are run.
