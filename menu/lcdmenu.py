# -*- coding: utf-8 -*-
from __future__ import print_function
from signal import pause
from atexit import register
from threading import Timer
from os import system, popen
from uuid import uuid4

# Magic constants for the LCD menu itself
ID = 'id'
TITLE = 'title'
DESCRIPTION = 'description'
PREV = 'prev'
NEXT = 'next'
ACTION = 'action'
REFRESH_RATE = 'refresh'
# A set of useful refresh rates, expressed as redraws per second.
REFRESH_SLOW = 0.2
REFRESH_MEDIUM = 1.0
REFRESH_FAST = 4.0

JIFFY = 0.01  # A very short period of time
BACKLIGHT_DELAY = 30.0

# Constants for configuring/installing/managing services
SERVICE = "lcdmenu"
SYSTEMD_EXEC_FILE = "/usr/local/bin/" + SERVICE + ".py"
SYSTEMD_CONF_FILENAME = "/etc/systemd/system/" + SERVICE + ".service"
SYSTEMD_CONF = """[Unit]
Description=System control menu on a HP44780LCD
Requires=basic.target
Conflicts=shutdown.target

[Service]
Type=simple
ExecStart=/usr/bin/python """ + SYSTEMD_EXEC_FILE + """ lcd

[Install]
WantedBy=multi-user.target
Alias=""" + SERVICE + """".service"""

LOAD_STATE = "LoadState"
ACTIVE_STATE = "ActiveState"
SUB_STATE = "SubState"


################################################################################
# Classes for simulating a LCD on the terminal
# noinspection PyMethodMayBeStatic
class FakeLCD(object):
    """Faking the LCD object in RPLCD library"""
    def __init__(self):
        self.backlight_enabled = True
        self._cursor_pos = (0, 0)

    def _set_cursor_pos(self, (row, col)):
        system("tput cup " + str(row) + " " + str(col))

    cursor_pos = property(fset=_set_cursor_pos)

    def clear(self):
        """Clears the terminal and moves the cursor to the top left"""
        system("tput clear")

    def write_string(self, s):
        """Write characters to the terminal"""
        print(s, end='\x0d\x0a')

    def crlf(self):
        """Write a CRLF to the terminal"""
        print("\x0d\x0a", end='')


def get_char():
    """Read a single character from the terminal. This is compatible only
    with Unix, not Windows"""
    import sys
    import tty
    import termios
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


################################################################################
# LCD Buffer - a buffer for managing updates to the LCD screen and backlight
class LCDBuffer(object):
    def __init__(self, lcd=None):
        if lcd:
            self._lcd = lcd
            self.rows = self._lcd.lcd.rows
            self.cols = self._lcd.lcd.cols
        else:
            self._lcd = FakeLCD()
            self.rows = 2
            self.cols = 16

        self._buffer = ["".ljust(self.cols)] * self.rows
        self._written = list(self._buffer)

        ###########################################
        # Set up the LCD device itself
        # Create special menu characters
        self.clear()
        self.backlight_on()

        if self.is_real():
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
            self.UP = chr(0)

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
            self.LEFT_RIGHT = chr(1)

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
            self.EXEC = chr(2)
        else:
            self.UP = "^"
            self.LEFT_RIGHT = "="
            self.EXEC = "*"
        ########################################

    def is_real(self):
        """Returns false if this instance is simulating a real LCD"""
        return not isinstance(self._lcd, FakeLCD)

    def is_backlight_on(self):
        """Returns whether the backlight is enabled or not"""
        return self._lcd.backlight_enabled

    def backlight_on(self):
        """Turns the backlight to the LCD on"""
        if not self._lcd.backlight_enabled:
            self._lcd.backlight_enabled = True

    def backlight_off(self):
        """Turns the backlight to the LCD off"""
        if self._lcd.backlight_enabled:
            self._lcd.backlight_enabled = False

    def clear(self):
        self._lcd.clear()

    def set_line(self, line, text):
        """
        Sets the text for a line on the LCD screen
        :param line: The line number
        :type line: int
        :param text: The text for the line can be longer than the display
        :type text: basestring
        """
        self._buffer[line] = text

    @staticmethod
    def _diff(a, b):
        if a == b:
            return None

        length = len(a)

        # Normalise b
        if not b:
            b = ""
        if len(b) < length:
            b = b.ljust(len(b) - length + 1)

        diffs = []
        last_diff = None
        for i in range(length):
            if a[i] == b[i]:
                if last_diff is not None:
                    diffs.append((last_diff, i + 1))
                    last_diff = None
            elif i == 0 or last_diff is None:
                # Capture the index of the first difference between the two
                # strings, with special care at the beginning of a string
                last_diff = i
        else:
            if last_diff is not None:
                diffs.append((last_diff, l))

        # Now condense differences that are close together
        condensed = []
        prev = None
        for diff in diffs:
            if prev:
                a, b = prev
                c, d = diff
                if b + 2 > c:
                    # these two differences are so close it is more efficient
                    # to update them together
                    prev = a, d
                else:
                    condensed.append(prev)
                    prev = diff
            else:
                # First time round the loop, just capture the first diff
                prev = diff
        else:
            if prev:
                condensed.append(prev)

        return condensed

    def flush(self):
        """Flush all changes to the buffer to the LCD"""
        for i in range(len(self._buffer)):
            if self._buffer[i] != self._written[i]:
                diffs = self._diff(self._buffer[i], self._written[i])
                for start, end in diffs:
                    self._lcd.cursor_pos = (i, start)
                    self._lcd.write_string(self._buffer[i][start:end])
                self._written[i] = self._buffer[i]

        if not self.is_real():
            self._lcd.cursor_pos = (3, 0)
            self._lcd.write_string("Command? ")

    def flash(self, message):
        """
        Write a simple message to the screen, replacing all previous content
        :param message: The message
        :type message: basestring
        """
        self.clear()
        self.set_line(0, message)
        self.flush()


################################################################################
# Main class for modelling a hierarchical menu
class MenuState(object):
    # The scheduler and scheduled event are used to manage the backlight
    # and scrolling/updating text

    def __init__(self, lcd=None):
        """
        Creates a Menu for writing to the LCD defined by lcd
        :param lcd:
        :type lcd: CharLCD
        """
        self.lcd = LCDBuffer(lcd)

        # Timer callbacks for the LCD
        self._backlight_timer = None
        self._update_timer = None

        # Binding actions to the physical buttons
        self._button_up = None
        self._button_prev = None
        self._button_next = None
        self._button_action = None

        # This manages the nested menus
        self._stack = []

        # Make sure the screen is cleared when Python terminates
        register(self.quit)

        self._counter = 0
        self._touch()

    def _cancel_backlight_timer(self):
        """Cancel and clear any backlight timer"""
        if self._backlight_timer:
            try:
                self._backlight_timer.cancel()
            except ValueError:
                # if the event has already run, we will receive this error
                # It is safe to ignore
                pass
            self._backlight_timer = None

    def _cancel_update_timer(self):
        """Cancel and clear any update time"""
        if self._update_timer:
            try:
                self._update_timer.cancel()
            except ValueError:
                # if the event has already run, we will receive this error
                # It is safe to ignore
                pass
            self._update_timer = None

    def _touch(self):
        """
        Update the object indicating the user has interacted with it at this
        point in time. This is used to manage the backlight
        :return:
        """
        self._counter = 0
        self.lcd.backlight_on()

        # Set up a timer that will turn off the backlight after a short delay
        def dim():
            self._backlight_timer = None
            self._cancel_update_timer()
            self.lcd.backlight_off()

        self._cancel_backlight_timer()
        self._backlight_timer = Timer(BACKLIGHT_DELAY, dim)
        self._backlight_timer.start()

    ###########################################################################
    # Add/remove/query the items on the menu
    def push(self, menu_item):
        """
        Pushes a new create_submenu to the display
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

    ###########################################################################
    # Methods associated with the update of the LCD screen
    def display(self):
        """Set the display to display the correct menu item (or nothing)"""
        self._touch()
        menu_item = self.peek()
        if menu_item:
            # Set the timer to draw the screen as soon as reasonably possible
            self._set_update_time(menu_item, JIFFY)
        else:
            self._cancel_update_timer()
            self.lcd.clear()

    def _set_update_time(self, menu_item, delay):
        """
        Set up a timer that will redraw the menu item in a short time
        But only do this if the backlight is on (i.e. the display is visible)
        :param menu_item: The menu item to draw
        """
        if self.lcd.is_backlight_on():
            def redraw():
                self._draw_text(menu_item)

            self._cancel_update_timer()
            self._update_timer = Timer(delay, redraw)
            self._update_timer.start()

    def _draw_text(self, menu_item):
        """Obtain the text for the menu item and draw it on the display,
        setting up a timer to redraw the item in a periodic fashion"""

        title = menu_item[TITLE](self)
        description = menu_item[DESCRIPTION](self)

        # Format them
        pre = "" if self.is_root_menu() else self.lcd.UP
        post = ""
        if menu_item[PREV] and \
                menu_item[NEXT] and \
                menu_item[PREV][ID] != menu_item[NEXT][ID]:
            post += self.lcd.LEFT_RIGHT
        if menu_item[ACTION]:
            post += self.lcd.EXEC

        self.lcd.set_line(0, self._format(title, pre, post))
        self.lcd.set_line(1, self._format(description, just=1))
        self.lcd.flush()
        delay = 1.0 / menu_item[REFRESH_RATE]
        self._set_update_time(menu_item, delay)

    def _format(self, message, pre="", post="", just=-1):
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
        length = self.lcd.cols - len(pre) - len(post)
        if len(message) > length:
            start = self._counter % (length + 1)
            justified = (message + "|" + message)[start:start + length]
        else:
            justified = message
        if just < 0:
            justified = justified.ljust(length)
        elif just == 0:
            justified = justified.center(length)
        else:
            justified = justified.rjust(length)
        return pre + justified + post

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
        next = menu_item[NEXT]
        if next:
            self.swap(next)

    def quit(self):
        """A handler that is called when the program quits."""
        self._cancel_backlight_timer()
        self._cancel_update_timer()
        self.lcd.backlight_off()
        self.lcd.clear()

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
            if self.lcd.is_real():
                print("ERROR initialising button bindings")
                print("      install the gpiozero package")

    ###########################################################################
    # Methods that can be used to run the menu without an LCD attached
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

    def run(self):
        if self.lcd.is_real():
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
    ll = [i.split("=") for i in s.split("\n")]
    properties = {i[0]: i[1] for i in ll}
    return properties


###########################################################################
# Methods for creating and managing menu item structures
def create_menu_item(title, description, action=None, refresh_rate=REFRESH_SLOW):
    """Create a menu item data structure, returning it. Both title and
    description may be strings (or things that can be turned into strings),
    or a function that returns a string
    :param title: The title of the menu item, a function taking MenuState as
    argument
    :param description: The description of the menu item, a function taking
    MenuState as argument
    :param action: A function with a single argument of the MenuState, which
    may perform arbitrary work
    :param refresh_rate: The rate at which this menu item is re-evaluated and
    redrawn on the LCD display, expressed as a number of times per second
    :type refresh_rate: float"""

    title_resolved = title if callable(title) else lambda _: str(title)
    description_resolved = description if callable(description) \
        else lambda _: str(description)

    return {ID: uuid4(),
            TITLE: title_resolved,
            DESCRIPTION: description_resolved,
            REFRESH_RATE: refresh_rate,
            ACTION: action,
            PREV: None,
            NEXT: None}


def create_submenu(parent, *menu_items):
    """Link menu items together, optionally under a parent menu item.
    :param parent: A menu item that, when invoked, opens a sub menu
    :type parent: dict (a menu item)
    :param menu_items: An unbounded number of menu item data structures
    that comprise the create_submenu
    :type menu_items: dict
    :return: the parent menu item (if present), else the first item in the
    sub-menu"""
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


def add_menu_items(menu_state):
    # Import local to function to keep the namespace tight
    # This code is called once, so there is no performance issues
    from datetime import datetime
    import socket
    from platform import node

    # Helper methods for the menu
    def time(_):
        """Return the current date and time"""
        return datetime.now().strftime("%-d %b, %H:%M:%S")


    def uptime(_):
        """Return the time component of the uptime command"""
        return "Uptime: " + \
               popen("uptime").read().strip().split(',')[0].split('up ')[1]


    def load_average(_):
        """Return the load average component of the uptime command"""
        values = popen("uptime").read().strip().split(' ')[-3:]

        out = []
        for value in values:
            if len(value) > 4:
                # This value is too big to display well
                try:
                    f = float(value)
                    if f > 100.0:
                        # Unfortunately this load avg is inherently too big
                        # Just display the integer
                        value = "{:.0f}".format(f)
                    else:
                        # Round to 3 sig fig to display in 4 digits or less
                        value = "{:0.3g}".format(f)
                except ValueError:
                    pass
            out.append(value)

        # Ensure the output is at least 14 characters to ensure stability during
        # potential text rotation
        return " ".join(out).ljust(14)


    def shutdown(menu_item):
        system("nohup shutdown now &")
        menu_item.quit()
        menu_item.lcd.flash("Shutting down...")


    def reboot(menu_item):
        system("nohup reboot now &")
        menu_item.quit()
        menu_item.lcd.flash("Rebooting...")

    def lcdmenu_state(_):
        properties = probe_system_service(SERVICE)
        try:
            return properties[ACTIVE_STATE] + ", " + properties[SUB_STATE]
        except KeyError:
            return "Unknown state"

    def get_ip_address(_):
        # This method assumes a simple network:
        # * IPv4
        # * Pi is not a router or bridge (including running a NAT)
        # * Only one IP address on the network socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # noinspection PyBroadException,PyPep8
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

    dt = create_submenu(
        create_menu_item("Information", get_hostname),
        create_menu_item("IP Address", get_ip_address),
        create_menu_item("Uptime", uptime),
        create_menu_item("Load average", load_average,
                         refresh_rate=REFRESH_MEDIUM),
        create_menu_item("Date/Time", time,
                         refresh_rate=REFRESH_FAST)
    )

    sys = create_submenu(
        create_menu_item("Services", "start, stop, ..."),
        create_menu_item("lcdmenu", lcdmenu_state)
    )

    reboot = create_submenu(
        create_menu_item("Reboot", ""),
        create_menu_item("Reboot", "Are you sure?", action=reboot),
        create_menu_item("Shutdown", "Are you sure?", action=shutdown)
    )

    root = create_submenu(None, dt, sys, reboot)
    menu_state.push(root)


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
        print("Stopping service...")
        system("systemctl stop " + SERVICE)
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


def run():
    """Run the configured menu"""
    lcd = None
    try:
        # noinspection PyUnresolvedReferences
        from RPLCD.i2c import CharLCD
        lcd = CharLCD('PCF8574', 0x27,
                      auto_linebreaks=True, charmap='A00',
                      rows=2, cols=16, dotsize=8,
                      backlight_enabled=True)
    except ImportError:
        print("ERROR: cannot load RPLCD library")
        exit(1)

    menu_state = MenuState(lcd)
    menu_state.bind_buttons(5, 6, 12, 13)
    add_menu_items(menu_state)
    menu_state.run()


def simulate():
    menu_state = MenuState()
    add_menu_items(menu_state)
    menu_state.run()


def create_arg_parser():
    """Create an argparse object for lcdmenu parameters"""
    from argparse import ArgumentParser
    parser = ArgumentParser(
        description="System control menu on HD44780 LCD panel")
    parser.add_argument("mode",
                        nargs="?",
                        choices=["simulate", "lcd", "install"],
                        default="simulate",
                        help="Choose how to execute this script, either to "
                             "<simulate> an lcd on the terminal, running on a "
                             "physical <lcd> or install the script as a service"
                        )
    return parser


if __name__ == "__main__":
    args = create_arg_parser().parse_args()
    if args.mode == "lcd":
        run()
    elif args.mode == "simulate":
        simulate()
    elif args.mode == "install":
        install()
    else:
        print("Unknown choice {0}".format(args.mode))
        exit(1)