# I2C-Keypad-Interface

I2C Bus Interface to SX1509 Keypad Engine


SX150_keypad_I2C_interface.py

This sample is a Python module from a project that uses a numeric keypad as a means for a user to enter a security access code into a device. The security code that is entered is compared against codes stored in a database and if there is a match then the device is signaled to unlock itself. The module also provides control of two LEDS that are mounted near the keyboard and that provide the user with accept/reject feedback regarding the keyed-in code.  The keypad and LEDS are connected to a Semtech SX1508 keypad engine/GPIO extender that is configured and controlled via an I2C bus.

The SX150_keypad_I2C_interface.py module contains three object classes: 
I2C_KeyPad  – configures and controls with the keypad engine
I2C_LED  – configures and controls the LEDs
UserInterfaceThread -  provides the application with a high level interface via an ‘unlock event’ 

Associated files:
-	sx1509.pdf– SX150 Device communications spec.

