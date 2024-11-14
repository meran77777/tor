import os
import subprocess
import socket
import shutil

torrc_path = '/etc/tor/torrc'
valid_country_codes = {
        'tr': 'Turkey', 
        'de': 'Germany', 
        'us': 'United States', 
        'fr': 'France', 
        'uk': 'United Kingdom',
        'at': 'Austria', 
        'be': 'Belgium', 
        'ro': 'Romania', 
        'ca': 'Canada', 
        'sg': 'Singapore',
        'jp': 'Japan', 
        'ie': 'Ireland', 
        'fi': 'Finland', 
        'es': 'Spain', 
        'pl': 'Poland'
    }


def clear_screen():
    os.system("clear")

def m3hran():
    print('''\033[1;36m
                                                                    
 King M3hran
                                                      
          
    \033[0m''')

def install_tor():
    try:
        print("Installing Tor ...\n")
        subprocess.run(['sudo', 'apt', 'update'], check=True)
        subprocess.run(['sudo', 'apt', 'install', '-y', 'tor'], check=True)
        print("[+] Tor has been installed successfully.")
        print("Installing Tor-geoipdb ...\n")
        subprocess.run(['sudo', 'apt-get', 'install', '-y', 'tor-geoipdb'], check=True)
        print("[+] Tor-geoipdb has been installed successfully.")
        print("Installing python3-pip ...\n")
        subprocess.run(['sudo', 'apt', 'install', '-y', 'python3-pip'], check=True)
        print("[+] python3-pip has been installed successfully.")
        print("Installing requests ...\n")
        subprocess.run(['pip3', 'install', 'requests'], check=True)
        subprocess.run(['pip3', 'install', 'requests[socks]'], check=True)
        print('[+] python3 requests is installed.')
        print(".")
        print(".")
        print(".")
        print("[+] Tor has been installed successfully.")
        input("Press Enter to continue")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while installing Tor: {e}")
        input("Press Enter to continue")

def uninstall_tor():
    print("Uninstalling Tor ...\n")
    try:
        subprocess.run(['sudo', 'apt', 'remove', '-y', 'tor'], check=True)
        print("Tor has been uninsalled successfully.")
        input("Press Enter to continue")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while uninsalling Tor: {e}")
        input("Press Enter to continue")

def update_tor():
    try:
        # Check if Tor is installed
        result = subprocess.run(['which', 'tor'], capture_output=True, text=True)
        
        if result.stdout:
            print("Updating Tor...\n")
            subprocess.run(['sudo', 'apt', 'update'], check=True)
            subprocess.run(['sudo', 'apt', 'upgrade', 'tor'], check=True)
            print("Tor has been updated successfully.")
        else:
            print("Tor is not installed. Please install Tor first.")
            _X = input("Do you want to install Tor? [Y/n]: ")
            if _X.lower() in ['y', '']:

                install_tor()

        
        input("Press Enter to continue")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred: {e}")

def show_numbers():
    tor_status = check_tor()
    if(tor_status):
        tor = True
    else:
        tor = False
    print(" \033[1;32mM3hran tor management:\033[0m\n")
    print(" \033[0;32mversion: \033[0;33mv1.0\033[0m")
    print(" \033[0;32mgithub: \033[0;33mgithub.com/m3hran/torx")
    print(" \033[0;32mTelegram ID: \033[0;33mt.me/m3hran")
    print("\033[0;33m═════════════════════════════════════════════\033[0m")
    if tor:
        print(" \033[0;36mTor: \033[0;32mInstalled")
    else:
        print(" \033[0;36mTor: \033[0;31mNot installed")

    
    socks_port, countries = read_torrc(torrc_path)
    if(socks_port == None):
        socks_port = 9050
    print(f" \033[0;36mYour Tor Server: \033[0;33m127.0.0.1:{socks_port}\033[0m")
    print(f" \033[0;36mYour Tor Countries: \033[0;33m{countries}\033[0m")
    # if get_server_location() != None:
    #     country, ip = get_server_location()
    #     print(f" \033[0;36mServer Location: \033[0m{country}")
    #     print(f" \033[0;36mServer IP: \033[0m{ip}")

    print("\033[0;33m═════════════════════════════════════════════\033[0m\n")

    
    if tor:
        print(" \033[1;32m1 -\033[0m install tor (" + "\033[1;32minstalled\033[0m)")

    else:
        print(" \033[1;32m1 -\033[0m install tor (" + "\033[1;31mnot installed\033[0m)")

    print(" \033[1;32m2 -\033[0m update tor")
    print(" \033[1;32m3 -\033[0;31m uninstall tor\033[0m")
    print("-----------------")
    print(" \033[1;32m4 -\033[0m get tor IP")
    print(" \033[1;32m5 -\033[0m cronjob(set time for change your tor IP)")
    print("-----------------")
    print(" \033[1;32m6 -\033[0m change tor IP")
    print(" \033[1;32m7 -\033[0m change tor Port")
    print(" \033[1;32m8 -\033[0m change tor Countries")
    print("-----------------")
    print(" \033[1;32m9 -\033[0m start tor")
    print(" \033[1;32m10-\033[0m stop tor")
    print(" \033[1;32m11-\033[0m restart tor")
    print(" \033[1;32m12-\033[0m reload tor")
    print(" \033[1;32m13-\033[0m status tor")
    print("-----------------")
    print(" \033[1;32m0 -\033[0m exit\n\n")

def check_tor():
    try:
        # Check if Tor is installed
        result = subprocess.run(['which', 'tor'], capture_output=True, text=True)
        if result.stdout:
            return True
        else:
            return False
    except subprocess.CalledProcessError as e:
        print(f"An error occurred: {e}")
        return False
            

def modify_torrc(file_path, new_socks_port=None, new_exit_nodes=None):
    try:
        if(check_tor()):
            with open(file_path, 'r') as file:
                lines = file.readlines()

            # Flags to check if SocksPort and ExitNodes are present
            socks_port_found = False
            exit_nodes_found = False

            modified_lines = []
            for line in lines:
                stripped_line = line.strip()
                if stripped_line.startswith('SocksPort'):
                    socks_port_found = True
                    if new_socks_port is not None:
                        modified_lines.append(f"SocksPort {new_socks_port}\n")
                    else:
                        modified_lines.append(line)
                elif stripped_line.startswith('ExitNodes'):
                    exit_nodes_found = True
                    if new_exit_nodes is not None:
                        modified_lines.append(f"ExitNodes {new_exit_nodes}\n")
                    else:
                        modified_lines.append(line)
                else:
                    modified_lines.append(line)

            # Add new entries if they were not found
            if not socks_port_found and new_socks_port is not None:
                modified_lines.append(f"SocksPort {new_socks_port}\n")
            
            if not exit_nodes_found and new_exit_nodes is not None:
                modified_lines.append(f"ExitNodes {new_exit_nodes}\n")

            with open(file_path, 'w') as file:
                file.writelines(modified_lines)

            print("The torrc file has been modified successfully.")
            input("Press Enter to continue")
        else:
            print("Tor is not installed, please install it first.")
            input("Press Enter to continue")
    except Exception as e:
        print(f"An error occurred: {e}")
        input("Press Enter to continue")

def read_torrc(file_path):
    try:
        if not os.path.exists(file_path):
            print(f"Error: {file_path} not found.")
            return None, None
        with open(file_path, 'r') as file:
            lines = file.readlines()

        socks_port = None
        exit_nodes = None
        for line in lines:
            stripped_line = line.strip()
            if stripped_line.startswith('SocksPort'):
                socks_port = stripped_line.split()[1]
            elif stripped_line.startswith('ExitNodes'):
                exit_nodes = stripped_line.split()[1]
        
        return socks_port, exit_nodes
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None, None


def get_server_location():
    try:
        result = subprocess.run(['curl', '--socks5', '127.0.0.1:9050', 'https://check.torproject.org/api/ip'], capture_output=True, text=True)
        if result.returncode == 0:
            json_data = result.stdout
            # Check if the json_data contains an IP and country code
            if 'ip' in json_data:
                country_code = json_data.split('"country_code":"')[1].split('"')[0].lower()
                if country_code in valid_country_codes:
                    country = valid_country_codes[country_code]
                    ip = json_data.split('"ip":"')[1].split('"')[0]
                    return country, ip
        return None, None
    except Exception as e:
        print(f"An error occurred while getting server location: {e}")
        return None, None













def main():
    while True:
        clear_screen()
        m3hran()  # Ensure this is used correctly
        show_numbers()
        
        # Get Input Number
        choise = input("Enter Your Choice [1-13]:")
        # Check input number
        match choise:
            case "0":
                clear_screen()
                break
            case "1":
                install_tor()

            case "2":
                update_tor()

            case "3":
                uninstall_tor()
            case "4":
                node_ip = get_tor_ip()
                print(f"Tor Server IP: {node_ip}")
                input("press Enter to continue")
            case "5":
                create_cron_job()
            case "6":
                reload_tor()
                restart_tor()
                print("Your Tor ip has been changed.")
                input("Press Enter to continue...")
            
            case "7":
                port = input("Enter Your Tor Port: ")
                check = False
                while True:
                    if not port.isdigit():
                        print("Your input is \033[1;31mnot valid\033[0m...")
                    elif check_portNumber(port) == False:
                        print(f"Port {port} is \033[1;31mBusy033[0m...")
                    else:
                        break  
                    port = input("Enter Your Tor Port: ")

                modify_torrc(torrc_path, new_socks_port=str(port))
                reload_tor()
                restart_tor()
                input("Your port has been change\nPress Enter to continue....")
            case "8":
                print("You can use these Countries:")
                for code, country in valid_country_codes.items():
                    print(f"{country} -> \033[0;32m{code}\033[0m")
                country_data = update_tor_country()
                while country_data == False:
                    country_data = update_tor_country()
                reload_tor()
                restart_tor()
                input(f"Countries of tor has been updated with: {country_data}\nPress Enter to continue....")

            case "9":
                start_tor()
                input("Tor has been started\nPress Enter to continue...")
            case "10":
                stop_tor()
                input("Tor has been stoped\nPress Enter to continue...")
            case "11":
                restart_tor()
                input("Tor has been restarted\nPress Enter to continue...")
            case "12":
                reload_tor()
                input("Tor has been reloaded\nPress Enter to continue...")
            case "13":
                status_tor()
                input("\nPress Enter to continue...")
            case _:
                print("Your input is invalid...")
                input("Press Enter to continue...")



    
if __name__ == "__main__":
    main()
