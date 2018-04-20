# -*- coding: utf-8 -*-
from gpiozero import Button
from atexit import register
from threading import Timer
import time

TITLE = 'title'
DESCRIPTION = 'description'
PREV = 'prev'
NEXT = 'next'
ACTION = 'action'
BACKLIGHT_DELAY = 10.0


class MenuState(object):
    def __init__(self, lcd):
        """
        Creates a Menu for writing to the LCD defined by lcd
        :param lcd:
        :type lcd: CharLCD
        """
        self._lcd = lcd
        self._button_up = None
        self._button_prev = None
        self._button_next = None
        self._button_action = None

        # The scheduler and scheduled event are used to manage the backlight
        self.timer = None

        # This manages the nested menus
        self._stack = []

        # Create special menu characters
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

        if self.timer is not None:
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

    def format(self, message, pre=None, post=None):
        """
        Formats a message for the screen, padding any shortfall with spaces.
        :param message: The main message to display
        :type message: basestring
        :param pre: A possible prefix for the message
        :param post: A possible suffix displayed a the RHS
        :return: The formatted string, padded with spaces to the width of the
        screen
        """
        length = self._lcd.lcd.cols
        line = pre if pre else ""
        line += message
        line = line.ljust(length)[:length]
        if post:
            line = line[:-len(post)] + post
        return line

    def display(self):
        self.touch()
        menu_item = self.peek()
        if menu_item:
            pre = None if self.is_root_menu() else chr(0)
            post = "*" if menu_item[ACTION] else None
            first = self.format(menu_item[TITLE](self), pre, post)
            self._lcd.home()
            self._lcd.write_string(first)

            pre = "<" if menu_item[PREV] else None
            post = ">" if menu_item[NEXT] else None
            second = self.format(menu_item[DESCRIPTION](self), pre, post)
            self._lcd.crlf()
            self._lcd.write_string(second)
        else:
            self._lcd.clear()

    def do_action(self):
        menu_item = self.peek()
        action = menu_item[ACTION]
        if action:
            action(self)
        self.display()

    def do_prev(self):
        menu_item = self.peek()
        prev = menu_item[PREV]
        if prev:
            self.swap(prev)

    def do_next(self):
        menu_item = self.peek()
        nxt = menu_item[NEXT]
        if nxt:
            self.swap(nxt)

    def quit(self):
        self._lcd.clear()
        self.dim_backlight()

    def bind_buttons(self, up_gpio, prev_gpio, next_gpio, action_gpio):
        self._button_up = Button(up_gpio)
        self._button_prev = Button(prev_gpio)
        self._button_next = Button(next_gpio)
        self._button_action = Button(action_gpio)

        self._button_up.when_pressed = self.pop
        self._button_prev.when_pressed = self.do_prev
        self._button_next.when_pressed = self.do_next
        self._button_action.when_pressed = self.do_action

    def execute_command(self, command):
        if command in ["^", "u", "6"]:
            self.pop()
        elif command in ["<", "p", ","]:
            self.do_prev()
        elif command in [">", "n", "."]:
            self.do_next()
        elif command in ["*", "x", " "]:
            self.do_action()
        elif command in ["q", "quit"]:
            while not self.is_empty():
                self.pop()
            return True
        elif command == "":
            self.display()
        else:
            print "^ 6 : go (U)p the menu tree to the parent menu item\n" \
                  "> . : (N)ext menu item\n" \
                  "< , : (P)revious menu item\n" \
                  "*   : e(X)ecute menu item or drill down into an item" \
                  "<cr>: update the display" \
                  "q   : (Q)uit"
            self.display()
        return False

    def run_keyboard(self):
        while True:
            command = raw_input("Command: ").lower()
            if self.execute_command(command):
                break

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

    def __str__(self):
        descent = " > ".join([item[TITLE](self) for item in self._stack])
        return "Menu: {}".format(descent)


