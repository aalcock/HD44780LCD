from controller import MenuState
from RPLCD.i2c import CharLCD
from menu import add_menu_items
from signal import pause

if __name__ == "__main__":
    menu_state = MenuState(CharLCD('PCF8574', 0x27,
                                   auto_linebreaks=True, charmap='A00',
                                   rows=2, cols=16, dotsize=8,
                                   backlight_enabled=True))

    add_menu_items(menu_state)

    menu_state.bind_buttons(5, 6, 12, 13)

    pause()
