from controller import MenuState, add_menu_items

if __name__ == "__main__":
    try:
        from RPLCD.i2c import CharLCD
        lcd = CharLCD('PCF8574', 0x27,
                       auto_linebreaks=True, charmap='A00',
                       rows=2, cols=16, dotsize=8,
                       backlight_enabled=True)
    except:
        lcd = None

    menu_state = MenuState(lcd)
    menu_state.bind_buttons(5, 6, 12, 13)
    add_menu_items(menu_state)
    menu_state.run()

