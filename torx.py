import os
import subprocess
import socket
import shutil

# Path to the torrc configuration file
torrc_path = '/etc/tor/torrc'

# Valid country codes for Tor exit nodes
valid_country_codes = {
    'tr': 'Turkey', 'de': 'Germany', 'us': 'United States', 'fr': 'France', 
    'uk': 'United Kingdom', 'at': 'Austria', 'be': 'Belgium', 'ro': 'Romania', 
    'ca': 'Canada', 'sg': 'Singapore', 'jp': 'Japan', 'ie': 'Ireland', 
    'fi': 'Finland', 'es': 'Spain', 'pl': 'Poland'
}

# Clear screen function for a clean user interface
def clear_screen():
    os.system("clear")

# Banner for program branding
def display_banner():
    print('''\033[1;36m
         King M3hran Tor Management Tool
    \033[0m''')

# Install Tor and necessary packages
def install_tor():
    try:
        print("Installing Tor ...")
        subprocess.run(['sudo', 'apt', 'update'], check=True)
        subprocess.run(['sudo', 'apt', 'install', '-y', 'tor', 'tor-geoipdb', 'python3-pip'], check=True)
        subprocess.run(['pip3', 'install', 'requests[socks]'], check=True)
        print("[+] Tor, geoipdb, and requests installed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error during installation: {e}")

# Uninstall Tor
def uninstall_tor():
    try:
        print("Uninstalling Tor ...")
        subprocess.run(['sudo', 'apt', 'remove', '-y', 'tor'], check=True)
        print("[+] Tor has been uninstalled successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error during uninstallation: {e}")

# Update Tor
def update_tor():
    if not check_tor():
        install_tor()
    else:
        try:
            print("Updating Tor ...")
            subprocess.run(['sudo', 'apt', 'update'], check=True)
            subprocess.run(['sudo', 'apt', 'upgrade', '-y', 'tor'], check=True)
            print("[+] Tor has been updated successfully.")
        except subprocess.CalledProcessError as e:
            print(f"Error during update: {e}")

# Display the main menu options
def display_menu():
    print(" \033[1;32mM3hran Tor Management Tool\033[0m\n")
    print("\033[0;33m═════════════════════════════════════════════\033[0m")
    print(" 1 - Install Tor (Current status: \033[0;36m{}\033[0m)".format("Installed" if check_tor() else "Not installed"))
    print(" 2 - Update Tor")
    print(" 3 - Uninstall Tor")
    print(" -----------------")
    print(" 4 - Get Tor IP")
    print(" 5 - Set Tor IP change interval (Cronjob)")
    print(" -----------------")
    print(" 6 - Change Tor IP")
    print(" 7 - Change Tor Port")
    print(" 8 - Change Tor Countries")
    print(" -----------------")
    print(" 9  - Start Tor")
    print(" 10 - Stop Tor")
    print(" 11 - Restart Tor")
    print(" 12 - Reload Tor")
    print(" 13 - Show Tor Status")
    print(" -----------------")
    print(" 0 - Exit\n")

# Check if Tor is installed
def check_tor():
    result = subprocess.run(['which', 'tor'], capture_output=True, text=True)
    return bool(result.stdout)

# Modify torrc settings
def modify_torrc(file_path, new_socks_port=None, new_exit_nodes=None):
    try:
        with open(file_path, 'r') as file:
            lines = file.readlines()

        modified_lines = []
        for line in lines:
            if line.startswith('SocksPort') and new_socks_port:
                modified_lines.append(f"SocksPort {new_socks_port}\n")
            elif line.startswith('ExitNodes') and new_exit_nodes:
                modified_lines.append(f"ExitNodes {new_exit_nodes}\n")
            else:
                modified_lines.append(line)

        with open(file_path, 'w') as file:
            file.writelines(modified_lines)
        print("The torrc file has been modified successfully.")
    except Exception as e:
        print(f"Error modifying torrc file: {e}")

# Read current Tor settings from torrc
def read_torrc(file_path):
    if not os.path.exists(file_path):
        return None, None
    with open(file_path, 'r') as file:
        lines = file.readlines()

    socks_port, exit_nodes = None, None
    for line in lines:
        if line.startswith('SocksPort'):
            socks_port = line.split()[1]
        elif line.startswith('ExitNodes'):
            exit_nodes = line.split()[1]
    return socks_port, exit_nodes

# Get Tor IP
def get_tor_ip():
    try:
        result = subprocess.run(['curl', '--socks5', '127.0.0.1:9050', 'https://check.torproject.org/api/ip'], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else None
    except Exception as e:
        print(f"Error retrieving Tor IP: {e}")

# Main function with a while loop for menu
def main():
    while True:
        clear_screen()
        display_banner()
        display_menu()

        choice = input("Enter Your Choice [0-13]: ")
        match choice:
            case "0":
                break
            case "1":
                install_tor()
            case "2":
                update_tor()
            case "3":
                uninstall_tor()
            case "4":
                print(f"Tor IP: {get_tor_ip()}")
            case "5":
                # create_cron_job()  # Placeholder for cron job function
                pass
            case "6":
                print("Reloading Tor IP ...")
            case "7":
                port = input("Enter new Tor Port: ")
                modify_torrc(torrc_path, new_socks_port=port)
            case "8":
                country_code = input("Enter country code (e.g., us for USA): ")
                modify_torrc(torrc_path, new_exit_nodes=country_code)
            case "9":
                subprocess.run(['sudo', 'service', 'tor', 'start'])
            case "10":
                subprocess.run(['sudo', 'service', 'tor', 'stop'])
            case "11":
                subprocess.run(['sudo', 'service', 'tor', 'restart'])
            case "12":
                subprocess.run(['sudo', 'service', 'tor', 'reload'])
            case "13":
                subprocess.run(['sudo', 'service', 'tor', 'status'])
            case _:
                print("Invalid choice. Please select from the menu.")
        input("\nPress Enter to continue...")

if __name__ == "__main__":
    main()
