# -*- coding: utf-8 -*-
from datetime import datetime
from os import system, popen
from controller import MenuState


def today(_):
    return str(datetime.today())


def time(_):
    return str(datetime.today())


def runlevel(_):
    return popen("/sbin/runlevel").read().strip()


def shutdown(_):
    system("sudo shutdown now")


def reboot(_):
    system("sudo reboot now")


def add_menu_items(menu_state):

    dt = menu_state.link(
        MenuState.menu_item("Date/Time", ""),
        MenuState.menu_item("Date", today),
        MenuState.menu_item("Time", time))

    sys = menu_state.link(
        MenuState.menu_item("Run level", runlevel),
        MenuState.menu_item("System", "Shutdown", action=shutdown),
        MenuState.menu_item("System", "Reboot", action=reboot))

    menu_state.push(MenuState.link(None, dt, sys))
