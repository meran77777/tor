import os
import subprocess
import requests

torrc_path = '/etc/tor/torrc'
valid_country_codes = {'tr': 'Turkey', 'de': 'Germany', 'us': 'United States', 'fr': 'France', 'uk': 'United Kingdom',
                       'at': 'Austria', 'be': 'Belgium', 'ro': 'Romania', 'ca': 'Canada', 'sg': 'Singapore',
                       'jp': 'Japan', 'ie': 'Ireland', 'fi': 'Finland', 'es': 'Spain', 'pl': 'Poland'}


def clear_screen(): os.system("clear")


def m3hran(): print(
    '''\033[1;36m\n  M3hran \n    \033[0m''')


def show_numbers():
    print("Menu Options:")
    print("1. Install Tor")
    print("2. Update Tor")
    print("3. Uninstall Tor")
    print("4. Get Tor IP")
    print("5. Create Cron Job")
    print("6. Reload and Restart Tor")
    print("7. Change Tor Port")
    print("8. Update Tor Country")
    print("9. Start Tor")
    print("10. Stop Tor")
    print("11. Restart Tor")
    print("12. Reload Tor")
    print("13. Check Tor Status")
    print("0. Exit")


def run_subprocess(commands, input_needed=False):
    try:
        result = subprocess.run(commands, check=True, capture_output=True, text=True)
        if input_needed: input("Press Enter to continue")
        return result
    except subprocess.CalledProcessError as e:
        print(f"An error occurred: {e}")
        if input_needed: input("Press Enter to continue")


def install_tor():
    print("Installing Tor ...\n")
    run_subprocess(['sudo', 'apt', 'update'])
    run_subprocess(['sudo', 'apt', 'install', '-y', 'tor', 'tor-geoipdb', 'python3-pip'])
    run_subprocess(['pip3', 'install', 'requests', 'requests[socks]'], True)


def uninstall_tor(): run_subprocess(['sudo', 'apt', 'remove', '-y', 'tor'], True)


def update_tor():
    if run_subprocess(['which', 'tor']).stdout.strip():
        run_subprocess(['sudo', 'apt', 'update'])
        run_subprocess(['sudo', 'apt', 'upgrade', 'tor'], True)
    else:
        _X = input("Tor is not installed. Install Tor? [Y/n]: ")
        if _X.lower() in ['y', '']: install_tor()


def check_tor(): return bool(run_subprocess(['which', 'tor']).stdout.strip())


def modify_torrc(new_socks_port=None, new_exit_nodes=None):
    if not check_tor(): return print("\033[31mTor is not installed.\033[0m\nPlease install it first.")
    with open(torrc_path, 'r+') as file:
        lines = file.readlines()
        file.seek(0)
        for line in lines:
            if line.startswith('SocksPort') and new_socks_port:
                line = f"SocksPort {new_socks_port}\n"
            elif line.startswith('ExitNodes') and new_exit_nodes:
                line = f"ExitNodes {new_exit_nodes}\n"
            file.write(line)
        if new_socks_port and not any('SocksPort' in line for line in lines): file.write(
            f"SocksPort {new_socks_port}\n")
        if new_exit_nodes and not any('ExitNodes' in line for line in lines): file.write(
            f"ExitNodes {new_exit_nodes}\n")
        file.truncate()


def read_torrc():
    if not check_tor(): return None, None
    with open(torrc_path) as file:
        lines = file.readlines()
    socks_port = next((line.split()[1] for line in lines if line.startswith('SocksPort')), None)
    exit_nodes = next((line.split(maxsplit=1)[1] for line in lines if line.startswith('ExitNodes')), None)
    return socks_port, exit_nodes


def reload_tor(): os.system("service tor reload")


def restart_tor(): run_subprocess(['sudo', 'systemctl', 'restart', 'tor'])


def start_tor(): run_subprocess(['sudo', 'systemctl', 'start', 'tor'])


def stop_tor(): run_subprocess(['sudo', 'systemctl', 'stop', 'tor'])


def status_tor(): run_subprocess(['sudo', 'systemctl', 'status', 'tor'], True)


def create_cron_job():
    delay_map = {'1': 1, '2': 30, '3': 60, '4': 240, '5': 720, '6': 1440}
    option = input("Select your option [0-6]: ")
    if option == '0': return
    delay_minutes = delay_map.get(option)
    if delay_minutes:
        script_path = "/usr/bin/restart_tor.sh"
        with open(script_path, 'w') as script_file:
            script_file.write("#!/bin/bash\nservice tor reload\nsystemctl restart tor\n")
        subprocess.run(["chmod", "+x", script_path])
        cron_job = f"*/{delay_minutes} * * * * {script_path}\n"
        subprocess.run(['crontab', '-l'], stdout=open('temp_cron', 'w'))
        with open('temp_cron', 'a') as temp_cron_file: temp_cron_file.write(cron_job)
        subprocess.run(['crontab', 'temp_cron'])
        subprocess.run(['rm', 'temp_cron'])
        print(f"Cron job set for every {delay_minutes} minutes.")


def get_tor_ip():
    if not check_tor(): return print("\033[31mTor is not installed.\033[0m\nPlease install it first.")
    socks_port, _ = read_torrc()
    port = socks_port or 9050
    try:
        node_ip = requests.get('http://checkip.amazonaws.com', proxies={'http': f'socks5://127.0.0.1:{port}',
                                                                        'https': f'socks5://127.0.0.1:{port}'}).text.strip()
        return node_ip
    except requests.RequestException as e:
        print(f"An error occurred while trying to get the IP: {e}")


def update_tor_country():
    input_codes = input("Enter country codes (e.g., tr, de) separated by commas or spaces: ")
    codes = [code.strip() for code in input_codes.replace(',', ' ').split()]
    valid_codes = [code for code in codes if code in valid_country_codes]
    invalid_codes = set(codes) - set(valid_codes)

    if invalid_codes:
        print(f"Invalid country codes: \033[0;31m{', '.join(invalid_codes)}\033[0m")
    else:
        new_exit_nodes = "{" + ",".join(valid_codes) + "}"
        modify_torrc(torrc_path, new_exit_nodes=new_exit_nodes)
        print(f"ExitNodes has been updated successfully with {new_exit_nodes}")


def main():
    while True:
        clear_screen()
        m3hran()
        show_numbers()

        choice = input("Enter Your Choice [1-13]:")
        match choice:
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
                input("Press Enter to continue")
            case "5":
                create_cron_job()
            case "6":
                reload_tor()
                restart_tor()
                print("Your Tor IP has been changed.")
                input("Press Enter to continue...")
            case "7":
                port = input("Enter Your Tor Port: ")
                while not port.isdigit() or check_portNumber(port):
                    print("Invalid or busy port.")
                    port = input("Enter Your Tor Port: ")
                modify_torrc(torrc_path, new_socks_port=port)
                reload_tor()
                restart_tor()
                input("Your port has been changed\nPress Enter to continue....")
            case "8":
                print("You can use these Countries:")
                for code, country in valid_country_codes.items():
                    print(f"{country} -> \033[0;32m{code}\033[0m")
                update_tor_country()
                reload_tor()
                restart_tor()
                input("Countries of tor have been updated.\nPress Enter to continue....")
            case "9":
                start_tor()
                input("Tor has been started\nPress Enter to continue...")
            case "10":
                stop_tor()
                input("Tor has been stopped\nPress Enter to continue...")
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
                print("Invalid input.")
                input("Press Enter to continue...")

if __name__ == "__main__":
    main()
