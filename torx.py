import os
import subprocess
import requests

# Path to the torrc configuration file
torrc_path = '/etc/tor/torrc'

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

# Display the main menu options
def display_menu():
    print(" \033[1;32mM3hran Tor Management Tool\033[0m\n")
    print("\033[1;32m═════════════════════════════════════════════\033[0m")
    print(" 1 - Install Tor")
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

# Get Tor IP using Python requests through the Tor SOCKS5 proxy
def get_tor_ip():
    try:
        proxies = {
            'http': 'socks5h://127.0.0.1:9050',
            'https': 'socks5h://127.0.0.1:9050'
        }
        response = requests.get("https://check.torproject.org/api/ip", proxies=proxies)
        if response.status_code == 200:
            ip_data = response.json()
            return f"Tor IP: {ip_data.get('IP', 'Not found')}"
        else:
            return "Could not retrieve IP."
    except Exception as e:
        return f"Error retrieving Tor IP: {e}"

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
            case "3":
                uninstall_tor()
            case "4":
                print(get_tor_ip())
            case _:
                print("Invalid choice. Please select from the menu.")
        input("\nPress Enter to continue...")

if __name__ == "__main__":
    main()
