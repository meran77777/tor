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
                                                                    
M3hran - Call us > @mizbaneto7777 Telegram
                                                      
          
    \033[0m''')

# Update function names and strings to match the requested changes
def show_numbers():
    tor_status = check_tor()
    if tor_status:
        tor = True
    else:
        tor = False
    print(" \033[1;32mM3hran tor management:\033[0m\n")
    print(" \033[0;32mversion: \033[0;33mv1.0\033[0m")
    print(" \033[0;32mgithub: \033[0;33mgithub.com/m3hran/torx")
    print(" \033[0;32mTelegram ID: \033[0;33m@mizbaneto77777")
    print("\033[0;33m═════════════════════════════════════════════\033[0m")
    if tor:
        print(" \033[0;36mTor: \033[0;32mInstalled")
    else:
        print(" \033[0;36mTor: \033[0;31mNot installed")

    socks_port, countries = read_torrc(torrc_path)
    if socks_port is None:
        socks_port = 9050
    print(f" \033[0;36mYour Tor Server: \033[0;33m127.0.0.1:{socks_port}\033[0m")
    print(f" \033[0;36mYour Tor Countries: \033[0;33m{countries}\033[0m")
    print("\033[0;33m═════════════════════════════════════════════\033[0m\n")

# Other functions like install_tor, uninstall_tor, etc. remain the same
# Ensure you replace all occurrences of "sinasims" with "m3hran"
# and update "torsina" to "torx" throughout the code
