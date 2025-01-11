# Version: v2025-01-04_08:50:43PM

# AUTOMATED AIRPORT RUNWAY LIGHTING CONTROLLER SYSTEM
#
# This system provides automated comntrol of airport runway lights.
#
# Features:
#
#   * Pilot-controlled lighting (PCL), activated by five radio "click" transmissions
#     if all 5 clicks are received within a 5-second window.
#        - Once activated lights remain active for configured time period.
#        - Lights will flash for 15 seconds to warn pilots so they can reactivate.
#
#   * Light-sensitive sensor capability, which disables the runway lights when
#     the sensor detects that sufficient daylight is present.
#
#   * Clock capabilities to allow lights to stay on until a specific time before
#     switching to PCL mode. Configured via NTP or GPS  depending on which modules or
#     services are present in the deployment (note: requires configuring GMT_OFFSET).
#
#   * Tunable radio to allow monitoring of tuned frequency for pilot lighting commands.
#
#   * Switches to activate lights-on override and maintenance/testing modes/functions.
#
#   * WiFi connectivity to local WiFi network to allow Internet access for time updates
#     and to control and monitor the system from wireless LAN via a web page interface.
#
# Configurable values include:
#
#   * Number of radio clicks required to activate the lights
#   * Time length of window in which the clicks must be sent (in seconds, default = 5)
#   * How long lights remain on before automatically shut off (in seconds, default = 600)
#   * How long lights flash just prior to lights shutting off (in seconds, default = 15)
#   * Frequency of flashes prior to shut off event (in milliseconds, default = 2000)
#   * Length of time lights cycle off each flash cycle (in milliseconds, default = 250)
#   * Threshold value for light sensor to turn runway lights on when dark (default = 2000)

# Version: v2025-01-10_09:10:00PM
import network
import ntptime
import utime
import machine
from machine import Pin, ADC, UART, I2C
import time

# ==== CONFIGURATION VARIABLES ====
WIFI_SSID = "YourNetworkSSID"
WIFI_PASSWORD = "YourPasswordHere"
GMT_OFFSET = -5  
NTP_UPDATE_INTERVAL = 12 * 60 * 60  
GPS_BAUDRATE = 9600
GPS_TX_PIN = 4  
GPS_RX_PIN = 5  

# ==== LIGHT CONTROL VARIABLES ====
AUTO_LIGHT_ON = True
TURN_OFF_TIME = None

# ==== PIN CONFIGURATION ====
RUNWAY_LIGHT_PIN = 17
ONBOARD_LED_PIN = 25
LIGHT_SENSOR_PIN = 26
OVERRIDE_SWITCH_PIN = 14
MAINTENANCE_BUTTON_PIN = 13
RADIO_INPUT_PIN = 12
MOMENTARY_BUTTON_PIN = 15
LCD_SDA_PIN = 8  
LCD_SCL_PIN = 9  

# ==== INITIALIZE PINS ====
runway_light = Pin(RUNWAY_LIGHT_PIN, Pin.OUT)
onboard_led = Pin(ONBOARD_LED_PIN, Pin.OUT)
light_sensor = ADC(LIGHT_SENSOR_PIN)
override_switch = Pin(OVERRIDE_SWITCH_PIN, Pin.IN, Pin.PULL_DOWN)
maintenance_button = Pin(MAINTENANCE_BUTTON_PIN, Pin.IN, Pin.PULL_DOWN)
radio_input = Pin(RADIO_INPUT_PIN, Pin.IN, Pin.PULL_DOWN)
momentary_button = Pin(MOMENTARY_BUTTON_PIN, Pin.IN, Pin.PULL_DOWN)

# ==== I2C LCD1602 DISPLAY INITIALIZATION ====
i2c = I2C(0, scl=Pin(LCD_SCL_PIN), sda=Pin(LCD_SDA_PIN))

# ==== LCD1602 DRIVER (NO EXTERNAL LIBRARY) ====
class LCD1602:
    def __init__(self, i2c, addr=0x27):
        self.i2c = i2c
        self.addr = addr
        self.init_display()
        
    def send(self, data, mode):
        high = data & 0xF0
        low = (data << 4) & 0xF0
        self.i2c.writeto(self.addr, bytes([high | mode | 0x08]))
        self.pulse()
        self.i2c.writeto(self.addr, bytes([low | mode | 0x08]))
        self.pulse()

    def pulse(self):
        self.i2c.writeto(self.addr, bytes([0x04]))
        utime.sleep_us(50)
        self.i2c.writeto(self.addr, bytes([0x08]))
        utime.sleep_us(50)

    def init_display(self):
        utime.sleep_ms(20)
        self.send(0x03, 0)
        utime.sleep_ms(5)
        self.send(0x03, 0)
        utime.sleep_us(100)
        self.send(0x03, 0)
        self.send(0x02, 0)
        self.send(0x28, 0)  
        self.send(0x0C, 0)  
        self.send(0x06, 0)  
        self.clear()

    def clear(self):
        self.send(0x01, 0)
        utime.sleep_ms(2)

    def write(self, text):
        for char in text:
            self.send(ord(char), 1)

    def move_to(self, col, row):
        addr = 0x80 + col + (0x40 * row)
        self.send(addr, 0)

# ==== INITIALIZE THE LCD ====
lcd = LCD1602(i2c)

# ==== STATE VARIABLES ====
activation_clicks = []
lights_on = False
lights_on_timer = 0
warning_flashing = False
warning_start_time = None
daylight_timer = None
last_ntp_sync = 0
last_status_message = None
last_flash_cycle_time = 0
lights_off_in_cycle = False
last_loop_time = utime.ticks_ms()

# ==== DISPLAY UPDATE FUNCTION ====
def update_display():
    """Update the LCD with real-time system status."""
    lcd.clear()
    if lights_on:
        remaining_time = max(0, lights_on_timer - utime.time())
        minutes = remaining_time // 60
        seconds = remaining_time % 60
        lcd.move_to(0, 0)
        lcd.write("RUNWAY LIGHTS: ON")
        lcd.move_to(0, 1)
        if warning_flashing and (utime.ticks_ms() // FLASH_CYCLE_TIME % 2 == 0):
            lcd.write("  FLASHING...")
        else:
            lcd.write(f"TIMER: {minutes:02}:{seconds:02}")
    else:
        current_time = utime.localtime()
        lcd.move_to(0, 0)
        lcd.write("RUNWAY LIGHTS: OFF")
        lcd.move_to(0, 1)
        lcd.write(f"{current_time[3]:02}:{current_time[4]:02}:{current_time[5]:02}")

# ==== WARNING FLASH FUNCTION ====
def warning_flash():
    global warning_flashing, last_flash_cycle_time, warning_start_time
    current_time = utime.ticks_ms()
    if warning_start_time is None:
        warning_start_time = current_time
        last_flash_cycle_time = current_time

    if utime.ticks_diff(current_time, warning_start_time) > WARNING_FLASH_DURATION * 1000:
        warning_flashing = False
        warning_start_time = None
        set_light_state(0)
        return

    cycle_progress = utime.ticks_diff(current_time, last_flash_cycle_time)
    if cycle_progress < FLASH_OFF_TIME:
        set_light_state(0)
    elif cycle_progress < FLASH_OFF_TIME * 2:
        set_light_state(1)
    elif cycle_progress < FLASH_OFF_TIME * 3:
        set_light_state(0)
    elif cycle_progress < FLASH_CYCLE_TIME:
        set_light_state(1)
    else:
        last_flash_cycle_time = current_time

# ==== TIMER RESET FLASH FUNCTION ====
def timer_reset_flash():
    global last_flash_cycle_time
    set_light_state(0)
    utime.sleep_ms(FLASH_OFF_TIME)
    set_light_state(1)
    utime.sleep_ms(FLASH_OFF_TIME)
    set_light_state(0)
    utime.sleep_ms(FLASH_OFF_TIME)
    set_light_state(1)

# ==== OTHER FUNCTIONS ====
def set_light_state(state):
    runway_light.value(state)
    onboard_led.value(state)

def auto_light_control():
    global daylight_timer, lights_on
    if not AUTO_LIGHT_ON:
        return
    light_level = light_sensor.read_u16()
    if light_level < LIGHT_THRESHOLD:
        daylight_timer = None
        if not lights_on:
            set_light_state(1)
            lights_on = True
    else:
        if daylight_timer is None:
            daylight_timer = utime.time()
        elif utime.time() - daylight_timer >= DAYLIGHT_STABLE_DURATION:
            if lights_on:
                set_light_state(0)
                lights_on = False

def detect_click(source_pin):
    global activation_clicks, lights_on, lights_on_timer
    current_time = utime.ticks_ms()
    if source_pin.value():
        signal_start = current_time
        while source_pin.value():
            pass
        signal_end = utime.ticks_ms()
        if utime.ticks_diff(signal_end, signal_start) >= MIN_CLICK_DURATION:
            activation_clicks.append(current_time)
    activation_clicks = [click for click in activation_clicks if utime.ticks_diff(current_time, click) <= RADIO_CLICK_WINDOW * 1000]
    if len(activation_clicks) >= 5:
        activation_clicks = []
        lights_on = True
        lights_on_timer = utime.time() + LIGHT_ON_DURATION
        set_light_state(1)
        timer_reset_flash()

def check_turn_off_time():
    global lights_on, warning_flashing, warning_start_time
    if TURN_OFF_TIME is not None:
        current_time = utime.localtime()
        current_hour = int(f"{current_time[3]:02}{current_time[4]:02}")
        if current_hour >= int(TURN_OFF_TIME) and lights_on and not warning_flashing:
            warning_flashing = True
            warning_start_time = utime.ticks_ms()

# ==== MAIN LOOP ====
while True:
    current_time = utime.ticks_ms()
    if utime.ticks_diff(current_time, last_loop_time) >= 100:
        last_loop_time = current_time

        detect_click(radio_input)
        detect_click(momentary_button)
        auto_light_control()
        check_turn_off_time()
        update_display()

        if warning_flashing:
            warning_flash()
