from machine import Pin
import utime

button = Pin(15, Pin.IN, Pin.PULL_UP) # set pull-up resistor internally for switch circuit
led = Pin(16, Pin.OUT) # Set up Pin 16 connected to LED
led2 = Pin('LED', Pin.OUT) # Set up Pin 25 - LED on the micro board
relay = Pin(17, Pin.OUT) #Pin for relay input/activation signal

led.value(0)   #turn the LED out
led2.value(0)   #turn the LED out
relay.value(0)

# button.value() == 1 #initialize with switch state value off

print(">> STARTING <<")

while True:  #loop below forever
    
    if button.value() == 0:
        led.value(1)   # turn the LED on
        led2.value(1)   # turn the LED on
        print("LED ON", button.value())
        relay.value(0)    # activate the relay (connect normally-open circuit)
        utime.sleep(.1)
    else:
        led.value(0)   # turn the LED out
        led2.value(0)   # turn the LED out
        print("LED OFF", button.value())
        relay.value(1)    # DEactivate the relay (connect normally-closed circuit)
        utime.sleep(.1)
        
    utime.sleep(.025) # pause the program to ensure no stray noise affecting state
    led2.value(1)
    utime.sleep(.025) # pause the program to ensure no stray noise affecting state