# -*- coding: utf-8 -*-
from controller import MenuState

def add_menu_items(menu_state):
    # Import local to function to keep the namespace tight
    # This code is called once, so there is no performance issues
    from datetime import datetime, date
    from os import system, popen
    import socket

    # Helper methods for the menu
    def today(_):
        return str(date.today())


    def time(_):
        return datetime.now().strftime("%H:%M:%S")


    def runlevel(_):
        return popen("/sbin/runlevel").read().strip()


    def shutdown(_):
        system("shutdown now")


    def reboot(_):
        system("reboot now")



    def get_ip_address(_):
        # This method assumes a simple network:
        # * IPv4
        # * Pi is not a router or bridge (including running a NAT)
        # * Only one IP address on the network socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # doesn't even have to be reachable
            s.connect(('10.255.255.255', 1))
            IP = s.getsockname()[0]
        except:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP

    dt = menu_state.link(
        MenuState.menu_item("System", ""),
        MenuState.menu_item("IP Address", get_ip_address),
        MenuState.menu_item("Time", time),
        MenuState.menu_item("Date", today))

    sys = menu_state.link(
        MenuState.menu_item("Run level", runlevel),
        MenuState.menu_item("System", "Shutdown", action=shutdown),
        MenuState.menu_item("System", "Reboot", action=reboot))

    menu_state.push(MenuState.link(None, dt, sys))
