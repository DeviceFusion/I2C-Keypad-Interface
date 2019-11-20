#-------------------------------------------------------------------------------
# Name:        keypad_manager
# Purpose:
#
# Author:      Dave Singer -
#
# Created:     05/04/2019
# Copyright:   (c) DeviceFusion LLC 2019
# Licence:     DeviceFusion LLC CONFIDENTIAL
#
#       [2019] DeviceFusion LLC
#       All Rights Reserved.
#
#       NOTICE:  All information contained herein is, and remains
#       the property of DeviceFusion LLC Incorporated and its suppliers,
#       if any.  The intellectual and technical concepts contained
#       herein are proprietary to DeviceFusion LLC
#       and its suppliers and may be covered by U.S. and Foreign Patents,
#       patents in process, and are protected by trade secret or copyright law.
#       Dissemination of this information or reproduction of this material
#       is strictly forbidden unless prior written permission is obtained
#       from DeviceFusion LLC.
#-------------------------------------------------------------------------------
# Provides an interface to an I2C SX1509
# Keypad decode engine and 3x4 numeric keypad for user input
# 1 Red and 1 Green LED for user feedback

import smbus
import time
import signal
import threading
import sys
import RPi.GPIO as GPIO
from db_manager import PASSCODE_DB
from remote_interface import remote_unlock_event
from remote_interface import RemoteCommandThread

RemoteCommandServer = RemoteCommandThread()



if __name__ == '__main__':
    GPIO.setmode(GPIO.BOARD)

# ========= define a class to interface with the keyboard =========
class I2C_KeyPad:

    def __init__(self, unlock_code_max=4, inter_keypress_time=6, kpad_interrupt_input_pin=7):

        self.unlock_code = ""
        self.unlock_code_read_event = threading.Event()
        self.unlock_code_update_lock = threading.RLock()
        self.unlock_code_max = unlock_code_max
        self.inter_keypress_time = inter_keypress_time
        self.display_unlock_code_reset=True
        self.key_interpress_timer = threading.Timer(self.inter_keypress_time,self.unlock_code_reset, [True])

        # key map for keypad row/col decoding
        self.keypad_row=4
        self.keypad_col=3
        self.keypad_matrix_size = 0x1A # defines #row/cols for RegKeyConfig2 as per SX1509 spec. sheet
        self.keypad_clock_enable = 0x50 # internal 2Mhz clock
        self.keypad_clock_disable = 0x10 # disable clock
        self.key_map = a = [['1', '2', '3'],
                            ['4', '5', '6'],
                            ['7', '8', '9'],
                            ['*', '0', '#'],
                           ]

        # SX1509 Interupt connection to the PI; pin 7
        self.KP_INT_PIN = kpad_interrupt_input_pin
        GPIO.setup(self.KP_INT_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(self.KP_INT_PIN, GPIO.FALLING, callback=self.read_key_press)

        print "unlock_code_max: " + str(self.unlock_code_max)
        print "KP_interupt_pin: " + str(self.KP_INT_PIN)

        # I2C channel 1 is connected to the SX1509 I/O expander with keyboard engine
        self.channel = 1
        # Initialize I2C (SMBus)
        self.bus = smbus.SMBus(self.channel)
        #  SX1509 address
        self.address = 0x3E

        # ===== define addresses of keypad engine registers =====

        # reset register
        reg_reset =  0x7D

        # clock control
        self.reg_clock = 0x1E

        # register A controls I/0 pins 0-7
        # register B controls I/O pins 8-15
        # I/O pin direction registers
        reg_dir_A = 0x0F
        reg_dir_B = 0X0E

        # I/O open drain setting registers
        reg_open_drain_A = 0x0B
        reg_open_drain_B = 0x0A

        # I/O pullup setting register
        reg_pullup_A = 0x07
        reg_pullup_B = 0x06

        # Input debounce setting registers
        reg_debounce_config = 0x22 # debounce time
        reg_debounce_enable_A = 0x24
        reg_debounce_enable_B = 0x23
        reg_key_config_1 = 0x25
        self.reg_key_config_2 = 0x26

        self.reg_key_data_1 = 0x27 # keypad input data: pressed key column
        self.reg_key_data_2 = 0x28 # keypad input data: pressed key row

        # ===== end of keypad register address definitions ======

        # ===== initilize the keypad engine =====

        # start by reseting the dSX1509 as per the datasheet write 0x12 then 0x34 to reset
        msg_data = 0x12
        self.bus.write_byte_data(self.address, reg_reset,  msg_data)
        msg_data = 0x34
        self.bus.write_byte_data(self.address, reg_reset,  msg_data)

        # init the internal clock 2Mhz
        msg_data = self.keypad_clock_enable
        self.bus.write_byte_data(self.address, self.reg_clock,  msg_data)

        # The I/O directions of the keypad's pins
        # 12 button key pad 4 rows, 3 columns
        # SX1509 uses I/O 0-7 for rows; I/O 8-15 for columns;
        # rows are outputs, columns are inputs
        # 3x4 keypad uses outputs 0-2 and inputs 0-3
        msg_data = 0x00
        # initialze output pins
        self.bus.write_byte_data(self.address, reg_dir_A,  msg_data) # set reg bit to 0 = outputs
        #print hex(self.bus.read_byte_data(self.address, reg_dir_A))+' : reg dir A\n'
        msg_data = 0xFF
        self.bus.write_byte_data(self.address, reg_open_drain_A,  msg_data) # set reg bit to 1 = open drain output
        #print hex(self.bus.read_byte_data(self.address, reg_open_drain_A))+' : open drain A\n'
        # initilize input pins
        msg_data = 0x3F #0xFF
        self.bus.write_byte_data(self.address, reg_dir_B,  msg_data) # set reg bit to 1 = inputs
        #print hex(self.bus.read_byte_data(self.address, reg_dir_B))+' : reg dir B\n'
        self.bus.write_byte_data(self.address, reg_pullup_B,  msg_data) # set reg bit to 1 = inputs to pullup
        #print hex(self.bus.read_byte_data(self.address, reg_pullup_B))+':  pullup B\n'

        # Enable and configure debouncing on the inputs
        msg_data = 0x05 # debounce time 16 ms as specd in the SX1509 datasheet : 0x05=16ms, 0x04=8ms
        self.bus.write_byte_data(self.address, reg_debounce_config, msg_data)
        #print hex(self.bus.read_byte_data(self.address, reg_debounce_config))+': debounce config\n'
        msg_data = 0x3F #0xFF
        self.bus.write_byte_data(self.address, reg_debounce_enable_B, msg_data) # set reg bit to 1 = enable debouncing on the input
        #print hex(self.bus.read_byte_data(self.address, reg_debounce_enable_B))+': debounce enable\n'

        # scan time per row bits(2:0) > debounce time = 32ms = 0b0110;  Auto sleep time bits(6:4) = 0 (off) = 0x05
        #                                               16ms = 0b0100;  Auto sleep time bits(6:0) = 0 (off) = 0x04
        msg_data = 0x05
        self.bus.write_byte_data(self.address, reg_key_config_1, msg_data)
        #print hex(self.bus.read_byte_data(self.address, reg_key_config_1))+': config 1 \n'
        # number of rows (outputs)  + key scan enable = 4 rows = bits(5:3) = 0b011
        # number of columns (inputs) = 3 cols = bits(2:0) = 0b010
        # = 00011010 = 0x1A
        msg_data = self.keypad_matrix_size #0x1A
        self.bus.write_byte_data(self.address, self.reg_key_config_2, msg_data)
        #print hex(self.bus.read_byte_data(self.address, reg_key_config_2))+' : config 2 \n'


        # create LED object
        self.LED = I2C_LED(self.bus, self.address)
        self.LED.red_steady_on()
        self.LED.green_steady_on()
        time.sleep(4)
        self.LED.green_off()
        self.LED.red_off()

        # ===== end of keypad initalization =====


    def read_key_press(self, channel):

        self.LED.green_steady_on() #green_blink_on()
        time.sleep(.25)
        self.LED.green_off()
        #print('reading key press: callback executing \n')
        col_byte = self.bus.read_byte_data(self.address, self.reg_key_data_1) ^ 0xFF
        #print "read_key_press - col_byte: " + str(col_byte)
        col = 255
        # determine which col bit is set by setting only that bit in the byte to 1 and then shifting right
        # to bit 0; the number of shifts = the column number
        if col_byte != 0: # in case of an errant 0xFF data read from keypad b/c 1 bit of read byte should always be 0
            col = 0
            while col_byte !=1 :
                col = col+1
                col_byte = col_byte >> 1
        # determine which row bit is set by setting only that bit in the byte to 1 and then shifting right
        # to bit 0; the number of shifts = the row number
        row_byte = self.bus.read_byte_data(self.address, self.reg_key_data_2) ^ 0xFF
        #print "read_key_press - row_byte:" + str(row_byte)
        row = 255
        if row_byte != 0: # in case of an errant 0xFF data read from keypad b/c 1 bit of read byte should always be 0
            row = 0
            while row_byte != 1:
                row = row+1
                row_byte = row_byte >> 1

        #print "read_key_press - row: "+ str(row) + "  col: " + str(col)
        if row < self.keypad_row  and col < self.keypad_col:
            pressed_key_val = self.key_map[row][col]
            print('key:'+ pressed_key_val)
            self.key_sequence_add(pressed_key_val)


    def key_sequence_add(self,new_key):


        with self.unlock_code_update_lock:

            # this functions keeps only a sequence of the last for keys that were pressed
            # if the sequence reaches a length of self.key_sequence_max (unlock code length) an event is triggered to notify listeners that
            # self.key_sequence_max keys have been pressed so the current sequence can be retieved

            # cancel the current inter key press timer
            self.key_interpress_timer.cancel()

            # if the sequence is already self.key_sequence_max the new key is ignored until the sequence has been reset
            # to less than self.key_sequence_max by an external call to key_sequence_reset
            if len(self.unlock_code) == self.unlock_code_max:
                #print('key_sequence_add - sequence == self.key_sequence_max, ignoring new key'+new_key)
                return
            else:
                self.unlock_code = self.unlock_code + new_key
                print('key_sequence_add - added new key:' + self.unlock_code)

            # key sequence has reached a length of self.key_sequence_max so trigger the notify event
            if len(self.unlock_code) == self.unlock_code_max:
                #print('key_sequence_add - new sequence = self.key_sequence_max - setting event')
                self.unlock_code_read_event.set()
                #self.LED.green_off()
            else:
                # only allow some much time in between key presses, if too much time then reset the current key sequence
                # and the user will have to start over
                self.display_unlock_code_reset=True
                self.key_interpress_timer = threading.Timer(self.inter_keypress_time,self.unlock_code_reset, [True])
                self.key_interpress_timer.start()
                pass

    def unlock_code_reset(self, LED_on):
        print "unlock_code_reset: reset code"
        with self.unlock_code_update_lock:
            self.unlock_code_read_event.clear()
            self.unlock_code = ""
            self.LED.green_off()
            self.LED.red_off()
            if LED_on == True: #self.display_unlock_code_reset==True:
                self.LED.red_steady_on()
                time.sleep(1.5)
                self.LED.red_off()

            self.display_unlock_code_reset=True


    # has to be set to detect keypad input : default is false - no detect
    def enable_keypad_scanning(self, EnableFlag):
        if EnableFlag == True :
            print "EnableKeyPadDetect = Enabled"
            # setup scanning of the 4x3 keypad matrix
            msg_data = self.keypad_matrix_size  # 0x1A
        elif EnableFlag == False:
            print "EnableKeyPadDetect = Disabled"
            # turn off scanning of keypad matrix
            msg_data = 0x00
        self.bus.write_byte_data(self.address, self.reg_key_config_2, msg_data)


    def enable_unlock_code_reading(self,LED_on):

        # for the new unlock code read cycle
                # make sure user feedback LEDs are off
                self.LED.green_off()
                self.LED.red_off()
                # clear the currently entered squence
                self.unlock_code_reset(LED_on)
                # start detection of user key presses
                self.enable_keypad_scanning(True)

# ========= END define a class to interface with the keyboard =========



# ==========   define a class to interface with the LED ===========
class I2C_LED:

    def __init__(self, bus, address):

        # I2C channel 1 is connected to the SX1509 I/O expander with keyboard engine
        # Initialize I2C (SMBus)
        self.bus = bus
        #  SX1509 address
        self.address = address #0x3E

        # ===== define addresses of keypad engine registers =====

        # LED clock driver and mode
        self.reg_misc = 0x1F

        # LED driver enable
        self.reg_leddriverenable_B = 0x20

        # LED driver start=0/stop=1
        self.reg_data_B = 0x10

        # input disable
        self.reg_inputdisable_B = 0x00

        # I/O pullup setting register + KP
        self.reg_pullup_B = 0x06

         # I/O open drain setting registers + KP
        self.reg_open_drain_B = 0x0A


        #LED Control regsters
        # on time for and intensity of blink
        self.reg_ton_14 = 0x5F
        self.reg_ion_14 = 0x60
        # off time and intensity of blink
        self.reg_toff_14 = 0x61
        # fade in time of breath
        self.reg_trise_14 = 0x62
        # fade out time of breath
        self.reg_tfall_14 = 0x63

        # on time for and intensity of blink
        self.reg_ton_15 = 0x64
        self.reg_ion_15 = 0x65
        # off time and intensity of blink
        self.reg_toff_15 = 0x66
        # fade in time of breath
        self.reg_trise_15 = 0x67
        # fade out time of breath
        self.reg_tfall_15 = 0x68

        # register B controls I/O pins 8-15
        # I/O pin direction registers
        self.reg_dir_B = 0X0E


        # ===== end of LED address definitions ======

        # ===== initilize the LED registers =====

        # disable LED pin 14 & 15 as input by setting it to 1 and preserve other B pins (8-14) values
        msg_data = self.bus.read_byte_data(self.address, self.reg_inputdisable_B)
        msg_data = msg_data | 0xC0 #0x80
        self.bus.write_byte_data(self.address, self.reg_inputdisable_B, msg_data )


        # disable pullup on pin 14 & 15 by setting to 0 and preserve the other B pins (8-14) values
        msg_data = self.bus.read_byte_data(self.address, self.reg_pullup_B)
        msg_data = msg_data & 0x3F #0x7F
        self.bus.write_byte_data(self.address, self.reg_pullup_B,  msg_data)
        #print hex(self.bus.read_byte_data(self.address, reg_pullup_B))+':  pullup B\n'

        # enable open drain on pin 14 & 15 by setting to 1 and preserve the other B pins (8-14) values
        msg_data = self.bus.read_byte_data(self.address, self.reg_open_drain_B)
        msg_data = msg_data |0xC0  #0x80
        self.bus.write_byte_data(self.address, self.reg_open_drain_B,  msg_data)

        # set direction of pin 14 & 15 to output by setting to 0 and preserve the othe B pins (8-14)
        msg_data = self.bus.read_byte_data(self.address, self.reg_dir_B)
        msg_data = msg_data & 0x3F #0x7F
        self.bus.write_byte_data(self.address, self.reg_dir_B,  msg_data)


        # configure LED clock and mode
        # divie system clock by 4 = 2Mz/4 = 250Khz, keep all other pins the same
        msg_data = self.bus.read_byte_data(self.address, self.reg_misc)
        msg_data = msg_data | 0x40
        self.bus.write_byte_data(self.address, self.reg_misc,  msg_data)

        # enable LED Driver on the pin 14 & 15 by setting it to 1, keep all other pins the same
        msg_data = self.bus.read_byte_data(self.address, self.reg_leddriverenable_B)
        msg_data = msg_data | 0xc0 #0x80
        self.bus.write_byte_data(self.address, self.reg_leddriverenable_B,  msg_data)

        # ===== end of LED initalization =====

    def green_blink_on(self):
        #LED Control regsters
        # on time for and intensity of blink
        msg_data = 0x05
        self.bus.write_byte_data(self.address, self.reg_ton_15,  msg_data)

        msg_data = 0xFF
        self.bus.write_byte_data(self.address, self.reg_ion_15,  msg_data)

        # off time and intensity of blink
        msg_data = 0x40
        self.bus.write_byte_data(self.address, self.reg_toff_15,  msg_data)

        msg_data = self.bus.read_byte_data(self.address, self.reg_data_B)
        msg_data = msg_data & 0x7F
        self.bus.write_byte_data(self.address, self.reg_data_B,  msg_data)

    def green_steady_on(self):
         # pin mode steady on = 0x00
        msg_data = 0x00
        self.bus.write_byte_data(self.address, self.reg_ton_15,  msg_data)
        # turn pin on
        msg_data = self.bus.read_byte_data(self.address, self.reg_data_B)
        msg_data = msg_data &  0x7F
        self.bus.write_byte_data(self.address, self.reg_data_B,  msg_data)

    def green_off(self):
        msg_data = self.bus.read_byte_data(self.address, self.reg_data_B)
        msg_data = msg_data |  0x80
        self.bus.write_byte_data(self.address, self.reg_data_B,  msg_data)

    def red_blink_on(self):
        #LED Control regsters
        # on time for and intensity of blink
        msg_data = 0x05
        self.bus.write_byte_data(self.address, self.reg_ton_14,  msg_data)

        msg_data = 0xFF
        self.bus.write_byte_data(self.address, self.reg_ion_14,  msg_data)

        # off time and intensity of blink
        msg_data = 0x40
        self.bus.write_byte_data(self.address, self.reg_toff_14,  msg_data)

        msg_data = self.bus.read_byte_data(self.address, self.reg_data_B)
        msg_data = msg_data & 0xBF
        self.bus.write_byte_data(self.address, self.reg_data_B,  msg_data)

    def red_steady_on(self):
         # pin mode steady on = 0x00
        msg_data = 0x00
        self.bus.write_byte_data(self.address, self.reg_ton_14,  msg_data)
        # turn pin on
        msg_data = self.bus.read_byte_data(self.address, self.reg_data_B)
        msg_data = msg_data &  0xBF
        self.bus.write_byte_data(self.address, self.reg_data_B,  msg_data)

    def red_off(self):
        msg_data = self.bus.read_byte_data(self.address, self.reg_data_B)
        msg_data = msg_data |  0x40
        self.bus.write_byte_data(self.address, self.reg_data_B,  msg_data)


# ==========   END define a class to interface with the LED ===========


# ========= Define thread to start the keypad and check for valid =========
#           unlock codes entered by the user
class UserInterfaceThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.DB = PASSCODE_DB()
        self.Keypad =  I2C_KeyPad(kpad_interrupt_input_pin=7)
        self.unlock_event = threading.Event()
        self.unlock_enable_timer = None
        self.unlock_reset_time= 90 # 1.5 minute

    def run(self):
        global RemoteCommandServer
        RemoteCommandServer.start()

        while True:
            # wait for an unlock code to be entered by the user via the keypad, timeout after 15 seconds
            self.Keypad.unlock_code_read_event.wait(.5)
            remote_unlock_event.wait(.5)

            if self.Keypad.unlock_code_read_event.is_set()==True or remote_unlock_event.is_set()==True:
                # a code was entered so process it

                # disable further detection of key presses during unlock code processing
                self.Keypad.enable_keypad_scanning(False)

                # if user entered  an unlock code via the keypad
                if self.Keypad.unlock_code_read_event.is_set()==True:
                    # see if the unlock code the user entered is valid
                    ret=self.DB.check_unlock_code(self.Keypad.unlock_code)
                # if the user entered an unlock remotely via the app just unlock
                elif remote_unlock_event.is_set()==True:
                    remote_unlock_event.clear()
                    ret = 1

                if ret >= 0:
                        # a valid unlock code was entered via the keyboard
                        print 'UserInterfaceThread:code found: '+ str(ret)
                        # signal any threads that are waiting for the unlock
                        self.unlock_event.set()
                        # signal the user that the entered code was valid
                        self.Keypad.LED.green_steady_on()
                        time.sleep(2)
                        # for unlock processing - disable signaling the user the current code is reset
                        self.Keypad.display_unlock_code_reset=False
                        LED_on = False

                        # only allow so much time for a successful unlock to take place
                        # before allowing the user to enter a new code
                        self.unlock_enable_timer = threading.Timer(self.unlock_reset_time,self.read_next_unlock_code)
                        self.unlock_enable_timer.start()
                else:
                        # an invalid unlock code was entered
                        print 'UserInterfaceThread:code NOT found: '+ str(ret)
                        # for invlaid code processing , enable signaling the user when the code is reset
                        self.Keypad.display_unlock_code_reset=True
                        LED_on = True

                # wait until the unlock event is cleared to start the next unlock code read cycle
                # this allows the user interface consumer to control when it's ready for the next unlock code cycle
                while self.unlock_event.is_set()==True:
                    time.sleep(.5)
                # fnished processing the current unlock code that the user entered
                # now enable reading of the next unlock code from the user
                self.Keypad.enable_unlock_code_reading(LED_on)

    # function to enable the reading of the next unlock code cycle
    # it is either called explicity by the user interface consumer to enable the next cycle
    # or by the unlock_enable_timer callback of the user interface to automtically enable the next cycle
    def read_next_unlock_code(self):
        try:
            if self.unlock_enable_timer != None:
                self.unlock_enable_timer.cancel()
        except:
            pass
        self.unlock_event.clear()
        self.Keypad.LED.green_off()
        self.Keypad.LED.red_off()

    def show_left_unlocked_warning(self):
        self.Keypad.LED.red_blink_on()
        self.DB.ceate_alert(alert_description="Device",alert_type="unlocked")


def signal_handler(signal, frame):
    print 'You pressed Ctrl+C!'
    # for p in jobs:
    #     p.terminate()
    sys.exit(0)


# main provides a quick test of the keypad inerface
def main():

     # catch a CtrlC exit
    signal.signal(signal.SIGINT, signal_handler)
    UserInterfaceThreadInstance = UserInterfaceThread()
    UserInterfaceThreadInstance.start()

    while True:
        UserInterfaceThreadInstance.unlock_event.wait(15)
        if UserInterfaceThreadInstance.unlock_event.is_set()==True:
            print '>>>>>>>>> main:USER UNLOCKED DEVICE <<<<<<<<<<<'
            print ' >>>>>>>> main: emulating consumer busy <<<<<<<<<<<<<'
            time.sleep(5)
            print ' >>>>>>>> main: resuming next unlock cycle <<<<<<<<<<<<<'
            UserInterfaceThreadInstance.read_next_unlock_code() #unlock_event.clear()
        else:
            print '>>>>>>>>> main:TIMEOUT WAITING FOR USER UNLOCK <<<<<<<<<<<'




if __name__ == '__main__':
    main()
