# -*- coding: utf-8 -*-
from __future__ import print_function
from signal import pause
from atexit import register
from threading import Timer
from os import system, popen

TITLE = 'title'
DESCRIPTION = 'description'
PREV = 'prev'
NEXT = 'next'
ACTION = 'action'
BACKLIGHT_DELAY = 30.0
REDRAW_DELAY = 5.0

SERVICE="lcdmenu"
SYSTEMD_EXEC_FILE = "/usr/local/bin/" + SERVICE + ".py"
SYSTEMD_CONF_FILENAME = "/etc/systemd/system/" + SERVICE + ".service"
SYSTEMD_CONF = """[Unit]
Description=System control menu on a HP44780LCD
Requires=basic.target
Conflicts=shutdown.target

[Service]
Type=simple
ExecStart=/usr/bin/python """ + SYSTEMD_EXEC_FILE + """

[Install]
WantedBy=multi-user.target
Alias=""" + SERVICE + """".service"""

LOAD_STATE = "LoadState"
ACTIVE_STATE = "ActiveState"
SUB_STATE = "SubState"

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
        print("\x1b\x5b\x48", end='')

    def clear(self):
        """Clears the termninal and moves the cursor to the top left"""
        print("\x1b\x5b\x48\x1b\x5b\x32\x4a", end='')

    def write_string(self, s):
        """Write characters to the terminal"""
        print(s, end='')

    def crlf(self):
        """Write a CRLF to the terminal"""
        print("\x0d\x0a", end='')


def get_char():
    """Read a single character from the terminal. This is compatible only
    with Unix, not Windows"""
    import sys, tty, termios
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


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
        # and scrolling/updating text
        self.update_timer = None
        self.backlight_timer = None

        # This manages the nested menus
        self._stack = []

        ###########################################
        # Set up the LCD device itself
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
        if self.is_real():
            self.UP = chr(0)
            self.LEFT_RIGHT = chr(1)
            self.EXEC = chr(2)
        else:
            self.UP = "^"
            self.LEFT_RIGHT = "="
            self.EXEC = "*"

        self._lcd.clear()
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

        # Set up a timer that will turn off the backlight after a short delay
        def dim():
            self.dim_backlight()

        if self.backlight_timer:
            try:
                self.backlight_timer.cancel()
            except ValueError:
                # if the event has already run, we will receive this error
                # It is safe to ignore
                pass

        self.backlight_timer = Timer(BACKLIGHT_DELAY, dim)
        self.backlight_timer.start()

        # If the update timer is running (it should be), cancel it so
        # the display is not redrawn1

        if self.update_timer:
            try:
                self.update_timer.cancel()
            except ValueError:
                # if the event has already run, we will receive this error
                # It is safe to ignore
                pass
            self.update_timer = None

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
        """Set the display to display the correct menu item (or nothing)"""
        self.touch()
        menu_item = self.peek()
        if menu_item:
            self.draw_text(menu_item)
        else:
            self._lcd.clear()

    def draw_text(self, menu_item):
        """Obtain the text for the menu item and draw it on the display,
        setting up a timer to redraw the item in a periodic fashion"""

        title = menu_item[TITLE](self)
        description = menu_item[DESCRIPTION](self)

        # Format them
        pre = "" if self.is_root_menu() else self.UP
        post = ""
        if menu_item[PREV]:
            post += self.LEFT_RIGHT
        if menu_item[ACTION]:
            post += self.EXEC

        first = self.format(title, pre, post)
        second = self.format(description, just=1)

        # Write them to the screen
        self._lcd.home()
        self._lcd.write_string(first)
        self._lcd.crlf()
        self._lcd.write_string(second)

        if not self.is_real():
            # Required to flush the write buffer on Unix
            self._lcd.crlf()
            self._lcd.write_string("Command? ")

        # Set up a timer that will redraw the menu item in a short time
        # But only do this if the backlight is on (i.e. the display is
        # visible)
        if self._lcd.backlight_enabled:
            def redraw():
                self.draw_text(menu_item)
                if not self.is_real():
                    self._lcd.crlf()

            self.update_timer = Timer(REDRAW_DELAY, redraw)
            self.update_timer.start()


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
        if self.backlight_timer:
            try:
                self.backlight_timer.cancel()
            except ValueError:
                # if the event has already run, we will receive this error
                # It is safe to ignore
                pass
            self.backlight_timer = None
        if self.update_timer:
            try:
                self.update_timer.cancel()
            except ValueError:
                # if the event has already run, we will receive this error
                # It is safe to ignore
                pass
            self.update_timer = None

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
            self.quit()
            return True
        elif command == "":
            self.display()
        else:
            print("\n\n\n\n"
                  "^ 6 : go (U)p the menu tree to the parent menu item\n"
                  "> . : (N)ext menu item\n"
                  "< , : (P)revious menu item\n"
                  "*   : e(X)ecute menu item or drill down into an item\n"
                  "<cr>: update the display\n"
                  "q   : (Q)uit\n")
            self.display()
        return False

    def run_keyboard(self):
        """Run using the keyboard for input rather than hardware buttons"""
        while True:
            command = get_char().lower()
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


################################################################################
# Functions and procedures for displaying and executing concrete menu items
def probe_system_service(name):
    """Query for systemctl for service _name_, returning a map of state
    information. The returned map has the keys:
    * LoadState
    * ActiveState
    * SubState
    :param name: The name of the service to query
    :type name: basestring
    :return: A map"""
    all_states = [LOAD_STATE, ACTIVE_STATE, SUB_STATE]
    states = "".join(["-p " + p + " " for p in all_states])
    s = popen("systemctl show " + states + name).read().strip()
    if not s:
        return {}
    ll = [ i.split("=") for i in s.split("\n")]
    properties = {i[0]:i[1] for i in ll}
    return properties


def add_menu_items(menu_state):
    # Import local to function to keep the namespace tight
    # This code is called once, so there is no performance issues
    from datetime import datetime, date
    import socket
    from platform import node

    # Helper methods for the menu
    def today(_):
        return str(date.today())


    def time(_):
        return datetime.now().strftime("%H:%M:%S")


    def uptime(_):
        return "Uptime: " + \
               popen("uptime").read().strip().split(',')[0].split('up ')[1]


    def shutdown(_):
        system("shutdown now")


    def reboot(_):
        system("reboot now")

    def lcdmenu_state(_):
        properties = probe_system_service(SERVICE)
        return properties[ACTIVE_STATE] + ", " + properties[SUB_STATE]


    def get_ip_address(_):
        # This method assumes a simple network:
        # * IPv4
        # * Pi is not a router or bridge (including running a NAT)
        # * Only one IP address on the network socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # doesn't even have to be reachable
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
        except:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip

    def get_hostname(_):
        return node().split(".")[0]

    dt = menu_state.link(
        MenuState.menu_item("Information", get_hostname),
        MenuState.menu_item("IP Address", get_ip_address),
        MenuState.menu_item("Uptime", uptime),
        MenuState.menu_item("Time", time),
        MenuState.menu_item("Date", today)
    )

    sys = menu_state.link(
        MenuState.menu_item("Services", ""),
        MenuState.menu_item("lcdmenu", lcdmenu_state)
    )

    reboot = menu_state.link(
        MenuState.menu_item("Reboot", ""),
        MenuState.menu_item("Reboot", "Are you sure?", action=reboot),
        MenuState.menu_item("Shutdown", "Are you sure?", action=shutdown)
    )

    menu_state.push(MenuState.link(None, dt, sys, reboot))


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

    from os import system
    print("Probing whether " + SERVICE + " already exists...")
    properties = probe_system_service(SERVICE)
    if properties[LOAD_STATE] == "loaded":
        print("... " + properties[ACTIVE_STATE] + " " + properties[SUB_STATE])
    else:
        print("... " + properties[LOAD_STATE])

    print("Copying this file to " + SYSTEMD_EXEC_FILE)
    try:
        import shutil
        shutil.copyfile(__file__, SYSTEMD_EXEC_FILE)
    except IOError:
        print("ERROR: Cannot copy the file to " +
              SYSTEMD_EXEC_FILE +
              ": Do you have the right permissions?")
        return

    print("Creating systemctl configuration file at " + SYSTEMD_CONF_FILENAME)
    try:
        f = open(SYSTEMD_CONF_FILENAME, "w")
        f.write(SYSTEMD_CONF)
        f.close()
    except IOError:
        print("ERROR: Cannot copy the file to " +
              SYSTEMD_CONF_FILENAME +
              ": Do you have the right permissions?")
        return

    print("Reloading systemctl daemon...")
    system("systemctl daemon-reload")

    if properties[LOAD_STATE] != "loaded":
        print("Enabling " + SERVICE + " to start on boot...")
        system("systemctl enable " + SERVICE)

    print("Starting " + SERVICE + "...")
    system("systemctl start " + SERVICE)


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

