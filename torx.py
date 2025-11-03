import os
import subprocess
import socket
import sys
from pathlib import Path
from typing import Optional, Tuple
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

TORRC_PATH = '/etc/tor/torrc'
SCRIPT_PATH = '/usr/bin/restart_tor.sh'

VALID_COUNTRY_CODES = {
    'tr': 'Turkey', 'de': 'Germany', 'us': 'United States', 'fr': 'France',
    'uk': 'United Kingdom', 'at': 'Austria', 'be': 'Belgium', 'ro': 'Romania',
    'ca': 'Canada', 'sg': 'Singapore', 'jp': 'Japan', 'ie': 'Ireland',
    'fi': 'Finland', 'es': 'Spain', 'pl': 'Poland'
}

class TorManager:
    def __init__(self):
        self._tor_installed_cache = None
        self._torrc_cache = None
    
    def _run_command(self, cmd: list, sudo: bool = False, check: bool = True) -> Tuple[bool, str, str]:
        """Execute command and return (success, stdout, stderr)"""
        try:
            if sudo:
                cmd = ['sudo'] + cmd
            result = subprocess.run(cmd, capture_output=True, text=True, check=check)
            return True, result.stdout.strip(), result.stderr.strip()
        except subprocess.CalledProcessError as e:
            return False, e.stdout.strip(), e.stderr.strip()
        except Exception as e:
            return False, '', str(e)
    
    def is_tor_installed(self, use_cache: bool = True) -> bool:
        """Check if Tor is installed"""
        if use_cache and self._tor_installed_cache is not None:
            return self._tor_installed_cache
        
        success, _, _ = self._run_command(['which', 'tor'], check=False)
        self._tor_installed_cache = success
        return success
    
    def _invalidate_cache(self):
        """Clear cached values"""
        self._torrc_cache = None
    
    def _require_tor(self) -> bool:
        """Check if Tor is installed and show error if not"""
        if not self.is_tor_installed():
            print("\033[31mTor is not installed.\033[0m\nPlease install it first.")
            return False
        return True
    
    def read_torrc(self, silent: bool = False) -> Tuple[Optional[str], Optional[str]]:
        """Read SocksPort and ExitNodes from torrc (cached)"""
        if self._torrc_cache is not None:
            return self._torrc_cache
        
        if not self.is_tor_installed():
            if not silent:
                print("\033[31mTor is not installed.\033[0m")
            return None, None
        
        try:
            if not os.path.exists(TORRC_PATH):
                if not silent:
                    print("Torrc file not found.")
                return None, None
            
            with open(TORRC_PATH, 'r') as f:
                lines = f.readlines()
            
            socks_port, exit_nodes = None, None
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('SocksPort'):
                    parts = stripped.split()
                    socks_port = parts[1] if len(parts) > 1 else None
                elif stripped.startswith('ExitNodes'):
                    parts = stripped.split(maxsplit=1)
                    exit_nodes = parts[1] if len(parts) > 1 else None
            
            self._torrc_cache = (socks_port, exit_nodes)
            return socks_port, exit_nodes
        except Exception as e:
            if not silent:
                logger.error(f"Error reading torrc: {e}")
            return None, None
    
    def modify_torrc(self, new_socks_port: Optional[str] = None, new_exit_nodes: Optional[str] = None):
        """Modify torrc file (only if changes needed)"""
        if not self.is_tor_installed():
            print("\033[31mTor is not installed.\033[0m\nPlease install it first.")
            return
        
        try:
            with open(TORRC_PATH, 'r') as f:
                lines = f.readlines()
            
            modified = False
            socks_found, exit_found = False, False
            new_lines = []
            
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('SocksPort'):
                    socks_found = True
                    if new_socks_port:
                        new_lines.append(f"SocksPort {new_socks_port}\n")
                        modified = True
                    else:
                        new_lines.append(line)
                elif stripped.startswith('ExitNodes'):
                    exit_found = True
                    if new_exit_nodes:
                        new_lines.append(f"ExitNodes {new_exit_nodes}\n")
                        modified = True
                    else:
                        new_lines.append(line)
                else:
                    new_lines.append(line)
            
            if new_socks_port and not socks_found:
                new_lines.append(f"SocksPort {new_socks_port}\n")
                modified = True
            
            if new_exit_nodes and not exit_found:
                new_lines.append(f"ExitNodes {new_exit_nodes}\n")
                modified = True
            
            if modified:
                with open(TORRC_PATH, 'w') as f:
                    f.writelines(new_lines)
                self._invalidate_cache()
                print("Torrc file updated successfully.")
            else:
                print("No changes needed.")
        
        except Exception as e:
            logger.error(f"Error modifying torrc: {e}")
    
    def install_tor(self):
        """Install Tor and dependencies"""
        print("Installing Tor...\n")
        commands = [
            (['sudo', 'apt', 'update'], "Updating packages"),
            (['sudo', 'apt', 'install', '-y', 'tor'], "Installing Tor"),
            (['sudo', 'apt-get', 'install', '-y', 'tor-geoipdb'], "Installing tor-geoipdb"),
            (['sudo', 'apt', 'install', '-y', 'python3-pip'], "Installing python3-pip"),
            (['pip3', 'install', 'requests', 'requests[socks]'], "Installing Python requests"),
        ]
        
        for cmd, desc in commands:
            print(f"{desc}...\n")
            success, _, stderr = self._run_command(cmd)
            if not success:
                print(f"✗ {desc} failed: {stderr}")
                return
            print(f"✓ {desc} completed.")
        
        self._tor_installed_cache = True
        print("[+] Tor installation completed successfully.")
        input("Press Enter to continue")
    
    def uninstall_tor(self):
        """Uninstall Tor"""
        print("Uninstalling Tor...\n")
        success, _, stderr = self._run_command(['sudo', 'apt', 'remove', '-y', 'tor'])
        if success:
            self._tor_installed_cache = False
            print("✓ Tor uninstalled successfully.")
        else:
            print(f"✗ Uninstall failed: {stderr}")
        input("Press Enter to continue")
    
    def update_tor(self):
        """Update Tor"""
        if not self.is_tor_installed():
            print("Tor is not installed.")
            if input("Do you want to install Tor? [Y/n]: ").lower() in ['y', '']:
                self.install_tor()
            return
        
        print("Updating Tor...\n")
        success, _, stderr = self._run_command(['sudo', 'apt', 'upgrade', '-y', 'tor'])
        if success:
            print("✓ Tor updated successfully.")
        else:
            print(f"✗ Update failed: {stderr}")
        input("Press Enter to continue")
    
    def get_tor_ip(self, port: Optional[str] = None) -> Optional[str]:
        """Get current Tor exit node IP"""
        if not self._require_tor():
            return None
        
        if port is None:
            port, _ = self.read_torrc()
            port = port or '9050'
        
        try:
            import requests
            response = requests.get(
                'http://checkip.amazonaws.com',
                proxies={'http': f'socks5://127.0.0.1:{port}', 'https': f'socks5://127.0.0.1:{port}'},
                timeout=10
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"Error getting Tor IP: {e}")
            return None
    
    def is_port_available(self, port: str) -> bool:
        """Check if port is available"""
        try:
            port_num = int(port)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                return s.connect_ex(('127.0.0.1', port_num)) != 0
        except ValueError:
            return False
    
    def change_port(self):
        """Change Tor SOCKS port"""
        while True:
            port = input("Enter Tor port: ").strip()
            if not port.isdigit():
                print("Invalid input. Enter a number.")
                continue
            if not self.is_port_available(port):
                print(f"Port {port} is busy.")
                continue
            break
        
        self.modify_torrc(new_socks_port=port)
        self.tor_command('restart')
        print(f"✓ Port changed to {port}\n")
        input("Press Enter to continue")
    
    def change_countries(self):
        """Change Tor exit node countries"""
        print("Available countries:")
        for code, name in sorted(VALID_COUNTRY_CODES.items()):
            print(f"  {name:20} -> \033[0;32m{code}\033[0m")
        
        while True:
            codes_input = input("\nEnter country codes (comma/space separated): ").strip()
            codes = [c.strip().lower() for c in codes_input.replace(',', ' ').split() if c.strip()]
            
            if not codes:
                print("Please enter at least one country code.")
                continue
            
            invalid = [c for c in codes if c not in VALID_COUNTRY_CODES]
            if invalid:
                print(f"Invalid codes: {', '.join(invalid)}")
                continue
            
            exit_nodes = ''.join(f"{{{code}}}" for code in codes)
            self.modify_torrc(new_exit_nodes=exit_nodes)
            self.tor_command('restart')
            print(f"✓ Countries updated to: {exit_nodes}\n")
            break
        
        input("Press Enter to continue")
    
    def setup_cron_job(self):
        """Setup automatic IP rotation via cron"""
        delays = {
            '1': 1, '2': 30, '3': 60, '4': 240, '5': 720, '6': 1440
        }
        
        print("Select IP rotation interval:")
        print("  1 - 1 minute\n  2 - 30 minutes\n  3 - 1 hour\n  4 - 4 hours")
        print("  5 - 12 hours\n  6 - 24 hours\n  0 - Exit\n")
        
        choice = input("Enter choice [0-6]: ").strip()
        if choice == '0':
            return
        
        if choice not in delays:
            print("Invalid choice.")
            input("Press Enter to continue")
            return
        
        delay = delays[choice]
        
        # Create script
        script_content = "#!/bin/bash\nservice tor reload\nsystemctl restart tor\n"
        try:
            with open(SCRIPT_PATH, 'w') as f:
                f.write(script_content)
            self._run_command(['chmod', '+x', SCRIPT_PATH])
        except Exception as e:
            logger.error(f"Error creating script: {e}")
            input("Press Enter to continue")
            return
        
        # Setup cron
        cron_entry = f"*/{delay} * * * * {SCRIPT_PATH}\n"
        try:
            result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
            crontab = [line for line in result.stdout.split('\n') if SCRIPT_PATH not in line and line.strip()]
            crontab.append(cron_entry.strip())
            
            with open('/tmp/cron_temp', 'w') as f:
                f.write('\n'.join(crontab) + '\n')
            
            self._run_command(['crontab', '/tmp/cron_temp'])
            os.remove('/tmp/cron_temp')
            print(f"✓ Cron job set to rotate IP every {delay} minutes.\n")
        except Exception as e:
            logger.error(f"Cron setup error: {e}")
        
        input("Press Enter to continue")
    
    def tor_command(self, action: str):
        """Execute tor systemctl commands"""
        if not self._require_tor():
            return
        
        actions = {
            'start': 'Starting', 'stop': 'Stopping', 'restart': 'Restarting', 
            'reload': 'Reloading', 'status': 'Status'
        }
        
        print(f"\n{actions.get(action, action).capitalize()} Tor...\n")
        success, stdout, stderr = self._run_command(['sudo', 'systemctl', action, 'tor'], check=False)
        
        if action == 'status':
            print("Tor Status:")
            print(stdout if stdout else stderr)
        elif success:
            print(f"✓ Tor {action}ed successfully.")
        else:
            print(f"✗ Error: {stderr}")
    
    def show_menu(self):
        """Display main menu"""
        os.system('clear')
        print('''\033[1;36m
  _________.__                     .__                
 /   _____/|__| ____ _____    _____|__| _____   ______
 \_____  \ |  |/    \\__  \  /  ___/  |/     \ /  ___/
 /        \|  |   |  \/ __ \_\___ \|  |  Y Y  \\___ \ 
/_______  /|__|___|  (____  /____  >__|__|_|  /____  >
        \/         \/     \/     \/         \/     \/ 
\033[0m''')
        
        tor_status = "✓ Installed" if self.is_tor_installed() else "✗ Not installed"
        socks_port, countries = self.read_torrc(silent=True)
        socks_port = socks_port or '9050'
        countries = countries or 'Default'
        
        print(f"\033[1;32mTor Management\033[0m")
        print(f"  Status: {tor_status}")
        print(f"  Server: 127.0.0.1:{socks_port}")
        print(f"  Countries: {countries}")
        print("\033[0;33m═════════════════════════════════════════════\033[0m")
        print("  1 - Install Tor     | 2 - Update Tor    | 3 - Uninstall Tor")
        print("  4 - Get Tor IP      | 5 - Setup Cron Job")
        print("  6 - Change IP       | 7 - Change Port   | 8 - Change Countries")
        print("  9 - Start Tor       | 10 - Stop Tor     | 11 - Restart Tor")
        print("  12 - Reload Tor     | 13 - Show Status  | 0 - Exit")
        print("\033[0;33m═════════════════════════════════════════════\033[0m\n")

def main():
    manager = TorManager()
    
    while True:
        manager.show_menu()
        choice = input("Enter choice [0-13]: ").strip()
        
        # Use if-elif instead of match for Python 3.9 compatibility
        if choice == '0':
            os.system('clear')
            print("Exiting...")
            sys.exit(0)
        elif choice == '1':
            manager.install_tor()
        elif choice == '2':
            manager.update_tor()
        elif choice == '3':
            manager.uninstall_tor()
        elif choice == '4':
            ip = manager.get_tor_ip()
            if ip:
                print(f"\nTor IP: {ip}\n")
            else:
                print("\n✗ Could not get IP\n")
            input("Press Enter to continue")
        elif choice == '5':
            manager.setup_cron_job()
        elif choice == '6':
            manager.tor_command('reload')
            manager.tor_command('restart')
            print("✓ Tor IP changed.")
            input("Press Enter to continue")
        elif choice == '7':
            manager.change_port()
        elif choice == '8':
            manager.change_countries()
        elif choice == '9':
            manager.tor_command('start')
            input("Press Enter to continue")
        elif choice == '10':
            manager.tor_command('stop')
            input("Press Enter to continue")
        elif choice == '11':
            manager.tor_command('restart')
            input("Press Enter to continue")
        elif choice == '12':
            manager.tor_command('reload')
            input("Press Enter to continue")
        elif choice == '13':
            manager.tor_command('status')
            input("\nPress Enter to continue")
        else:
            print("Invalid choice.")
            input("Press Enter to continue")

if __name__ == "__main__":
    main()