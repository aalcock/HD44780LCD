# -*- coding: utf-8 -*-
from __future__ import print_function
from signal import pause
from atexit import register
from threading import Timer

TITLE = 'title'
DESCRIPTION = 'description'
PREV = 'prev'
NEXT = 'next'
ACTION = 'action'
BACKLIGHT_DELAY = 30.0

SYSTEMD_EXEC_FILE = "/usr/local/bin/lcdmenu.py"
SYSTEMD_CONF_FILENAME = "/etc/systemd/system/lcdmenu.service"
SYSTEMD_CONF = """[Unit]
Description=System control menu on a HP44780LCD
Requires=basic.target
Conflicts=shutdown.target

[Service]
Type=simple
ExecStart=/usr/bin/python """ + SYSTEMD_EXEC_FILE + """

[Install]
WantedBy=multi-user.target
Alias=lcdmenu.service"""


################################################################################
# Classes for simulating a LCD on the terminal

class FakeLCDInner(object):
    """Faking the inner LCD object in RPLCD library"""
    def __init__(self, rows, cols):
        self.cols = cols
        self.rows = rows


class FakeLCD(object):
    """Faking the LCD object in RPLCD library"""
    def __init__(self):
        self.backlight_enabled = True
        self.lcd = FakeLCDInner(2, 16)

    def create_char(self, a, b):
        """Doesn't do anything"""
        pass

    def home(self):
        """Moves the cursor to the top left"""
        print(chr(27) + '[H')

    def clear(self):
        """Clears the termninal and moves the cursor to the top left"""
        print(chr(27) + "[2J" + chr(27) + '[H')

    def write_string(self, s):
        """Write characters to the terminal"""
        print(s, end='')

    def crlf(self):
        """Write a CRLF to the terminal"""
        print()


################################################################################
# Main class for modelling a heirarchical menu
class MenuState(object):
    def __init__(self, lcd=None):
        """
        Creates a Menu for writing to the LCD defined by lcd
        :param lcd:
        :type lcd: CharLCD
        """
        if lcd:
            self._lcd = lcd
        else:
            self._lcd = FakeLCD()

        self._button_up = None
        self._button_prev = None
        self._button_next = None
        self._button_action = None

        # The scheduler and scheduled event are used to manage the backlight
        self.timer = None

        # This manages the nested menus
        self._stack = []

        # Create special menu characters
        # First is an up-menu symbol
        char = (
            0b11100,
            0b11000,
            0b10100,
            0b00010,
            0b00001,
            0b00000,
            0b00000,
            0b00000)
        self._lcd.create_char(0, char)

        # Next is a left/right symbol
        char = (
            0b00100,
            0b01000,
            0b11111,
            0b01100,
            0b00110,
            0b11111,
            0b00010,
            0b00100
        )
        self._lcd.create_char(1, char)

        # Next is the CR/action symbol
        char = (
            0b00001,
            0b00001,
            0b00001,
            0b00101,
            0b01001,
            0b11111,
            0b01000,
            0b00100
        )
        self._lcd.create_char(2, char)

        self.touch()

        # Make sure the screen is cleared when Python terminates
        register(self.quit)

    def dim_backlight(self):
        """
        Turns off the backlight
        :return:
        """
        self._lcd.backlight_enabled = False

    def touch(self):
        """
        Update the object indicating the user has interacted with it at this
        point in time. This is used to manage the backlight
        :return:
        """
        if not self._lcd.backlight_enabled:
            self._lcd.backlight_enabled = True

        if self.timer:
            try:
                self.timer.cancel()
            except ValueError:
                # if the event has already run, we will receive this error
                # It is safe to ignore
                pass

        # Set up a timer that will turn off the backlight after a short delay
        def dim():
            self.dim_backlight()

        self.timer = Timer(BACKLIGHT_DELAY, dim)
        self.timer.start()

    def push(self, menu_item):
        """
        Pushes a new submenu to the display
        :param menu_item:
        :type menu_item: dict
        :return:
        """
        self._stack.append(menu_item)
        self.display()

    def swap(self, menu_item):
        """
        Swaps the current menu with another one, and displays it
        :param menu_item:
        :type menu_item: dict
        :return:
        """
        self._stack[-1] = menu_item
        self.display()

    def peek(self):
        """
        Returns the current menu item
        :return:
        """
        if self.is_empty():
            return None
        else:
            return self._stack[-1]

    def pop(self):
        """
        Removes the current menu item and displays its parent
        :return: the previous menu item
        """
        item = self._stack[-1]
        if not self.is_root_menu():
            # Do not pop the last item on the menu
            self._stack = self._stack[:-1]
            self.display()
        return item

    def is_root_menu(self):
        """
        :return: True is the current menu item is the topmost item
        """
        return len(self._stack) == 1

    def is_empty(self):
        """
        :return: True if there are no menu items
        """
        return len(self._stack) == 0

    def format(self, message, pre="", post="", just=-1):
        """
        Formats a message for the screen, padding any shortfall with spaces.
        :param message: The main message to display
        :type message: basestring
        :param pre: A possible prefix for the message
        :param post: A possible suffix displayed a the RHS
        :param just: -1 for left justified, 0 for center and 1 for right
        :return: The formatted string, padded with spaces to the width of the
        screen
        """
        length = self._lcd.lcd.cols - len(pre) - len(post)
        justified = message[0:length]
        if just < 0:
            justified = justified.ljust(length)
        elif just == 0:
            justified = justified.center(length)
        else:
            justified = justified.rjust(length)
        return pre + justified + post

    def display(self):
        self.touch()
        menu_item = self.peek()
        if menu_item:
            pre = "" if self.is_root_menu() else chr(0)
            post = ""
            if menu_item[PREV]:
                post += chr(1)
            if menu_item[ACTION]:
                post += chr(2)

            first = self.format(menu_item[TITLE](self), pre, post)
            self._lcd.home()
            self._lcd.write_string(first)

            second = self.format(menu_item[DESCRIPTION](self), just=1)
            self._lcd.crlf()
            self._lcd.write_string(second)
        else:
            self._lcd.clear()

    ###########################################################################
    # Methods to handle hardware events:
    # * Up button
    # * Action button
    # * Next button
    # * Previous button
    # * Quit/exit program

    def do_up(self):
        """This method is called when the 'up' button is pressed"""
        self.pop()

    def do_action(self):
        """This method is called when the 'action' button is pressed"""
        menu_item = self.peek()
        action = menu_item[ACTION]
        if action:
            action(self)
        self.display()

    def do_prev(self):
        """This method is called when the 'prev' button is pressed"""
        menu_item = self.peek()
        prev = menu_item[PREV]
        if prev:
            self.swap(prev)

    def do_next(self):
        """This method is called when the 'next' button is pressed"""
        menu_item = self.peek()
        nxt = menu_item[NEXT]
        if nxt:
            self.swap(nxt)

    def quit(self):
        """A handler that is called when the program quits."""
        self._lcd.clear()
        if self.timer:
            try:
                self.timer.cancel()
            except ValueError:
                # if the event has already run, we will receive this error
                # It is safe to ignore
                pass

        self.dim_backlight()

    def bind_buttons(self, up_gpio, prev_gpio, next_gpio, action_gpio):
        try:
            from gpiozero import Button
            self._button_up = Button(up_gpio)
            self._button_prev = Button(prev_gpio)
            self._button_next = Button(next_gpio)
            self._button_action = Button(action_gpio)

            self._button_up.when_pressed = self.do_up
            self._button_prev.when_pressed = self.do_prev
            self._button_next.when_pressed = self.do_next
            self._button_action.when_pressed = self.do_action
        except ImportError:
            if self.is_real():
                print("ERROR initialising button bindings")
                print("      install the gpiozero package")

    ###########################################################################
    # Methods that can be used to run the menu without an LCD attached

    def is_real(self):
        """Returns false if this instance is simulating a real LCD"""
        return not isinstance(self._lcd, FakeLCD)

    def execute_command(self, command):
        """Process a command from the keyboard"""
        if command in ["^", "u", "6"]:
            self.pop()
        elif command in ["<", "p", ","]:
            self.do_prev()
        elif command in [">", "n", "."]:
            self.do_next()
        elif command in ["*", "x", " "]:
            self.do_action()
        elif command in ["q", "quit"]:
            return True
        elif command == "":
            self.display()
        else:
            print("^ 6 : go (U)p the menu tree to the parent menu item\n"
                  "> . : (N)ext menu item\n"
                  "< , : (P)revious menu item\n"
                  "*   : e(X)ecute menu item or drill down into an item"
                  "<cr>: update the display"
                  "q   : (Q)uit")
            self.display()
        return False

    def run_keyboard(self):
        """Run using the keyboard for input rather than hardware buttons"""
        while True:
            command = raw_input("\n\nCommand: ").lower()
            if self.execute_command(command):
                break

    ###########################################################################
    # Methods for managing the menu items for display

    @staticmethod
    def menu_item(title, description, action=None):
        """Create a menu item datastructure, returning it. Both title and
        description may be strings (or things that can be turned into strings),
        or a function that returns a string
        :param title: The title of the menu item
        :param description: The description of the menu item
        :param action: A function with a single argument of the MenuState, which
        may perform arbitrary work"""

        title_resolved = title if callable(title) else lambda _: str(title)
        description_resolved = description if callable(description) \
            else lambda _: str(description)

        return {TITLE: title_resolved,
                DESCRIPTION: description_resolved,
                ACTION: action,
                PREV: None,
                NEXT: None}

    @staticmethod
    def link(parent, *menu_items):
        def link(a, b):
            a[NEXT] = b
            b[PREV] = a

        prev = menu_items[-1]
        for menu_item in menu_items:
            link(prev, menu_item)
            prev = menu_item

        if parent:
            parent[ACTION] = lambda state: state.push(menu_items[0])
            return parent
        else:
            return menu_items[0]

    def run(self):
        if self.is_real():
            pause()
        else:
            self.run_keyboard()

    def __str__(self):
        descent = " > ".join([item[TITLE](self) for item in self._stack])
        return "Menu: {}".format(descent)


def add_menu_items(menu_state):
    # Import local to function to keep the namespace tight
    # This code is called once, so there is no performance issues
    from datetime import datetime, date
    from os import system, popen
    import socket
    from platform import node

    # Helper methods for the menu
    def today(_):
        return str(date.today())


    def time(_):
        return datetime.now().strftime("%H:%M:%S")


    def runlevel(_):
        return "Runlevel: " + popen("/sbin/runlevel").read().strip()


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

    def get_hostname(_):
        return node().split(".")[0];

    dt = menu_state.link(
        MenuState.menu_item("Information", get_hostname),
        MenuState.menu_item("IP Address", get_ip_address),
        MenuState.menu_item("Time", time),
        MenuState.menu_item("Date", today)
    )

    sys = menu_state.link(
        MenuState.menu_item("System", ""),
        MenuState.menu_item("System", "Shutdown", action=shutdown),
        MenuState.menu_item("System", "Reboot", action=reboot),
        MenuState.menu_item("Run level", runlevel)
    )

    menu_state.push(MenuState.link(None, dt, sys))


def install():
    """Install this into a system. Must be root"""

    # First - do we the correct libraries installed?
    print("Testing that we have the right libraries...")
    try:
        import RPLCD.i2c
        import gpiozero
    except ImportError:
        print("ERROR: Please install the RPLCD and gpiozero Python libraries")
        return

    print("Copying this file to " + SYSTEMD_EXEC_FILE)
    try:
        import shutil
        shutil.copyfile(__file__, SYSTEMD_EXEC_FILE)
    except IOError:
        print("ERROR: Cannot copy the file to " + SYSTEMD_EXEC_FILE + ": Do you have the right permissions?")
        return

    print("Creating systemctl configuration file at " + SYSTEMD_CONF_FILENAME)
    try:
        f = open(SYSTEMD_CONF_FILENAME, "w")
        f.write(SYSTEMD_CONF)
        f.close()
    except IOError:
        print("ERROR: Cannot copy the file to " + SYSTEMD_CONF_FILENAME + ": Do you have the right permissions?")
        return

    from os import system
    print("Reloading systemctl daemon...")
    system("systemctl daemon-reload")

    print("Enabling lcdmenu to start on boot...")
    system("systemctl enable lcdmenu")

    print("Starting lcdmenu...")
    system("systemctl start lcdmenu")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="System control menu on HD44780 LCD panel")
    parser.add_argument("install", nargs="?", help="Install as a system service on a Raspberry Pi")
    parser.add_argument("--service", nargs="?", help="Refuse to run unless the LCD is present")

    args = parser.parse_args()

    if args.install:
        install()
    else:
        try:
            from RPLCD.i2c import CharLCD
            lcd = CharLCD('PCF8574', 0x27,
                          auto_linebreaks=True, charmap='A00',
                          rows=2, cols=16, dotsize=8,
                          backlight_enabled=True)
        except:
            if args.service:
                print("ERROR: cannot load RPLCD library")
                exit(1)
            else:
                lcd = None

        menu_state = MenuState(lcd)
        menu_state.bind_buttons(5, 6, 12, 13)
        add_menu_items(menu_state)
        menu_state.run()

