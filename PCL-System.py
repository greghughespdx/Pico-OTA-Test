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

import network
import ntptime
import utime
import machine
from machine import Pin, ADC, UART
import time

# ==== CONFIGURATION VARIABLES ====
WIFI_SSID = "YourNetworkSSID"
WIFI_PASSWORD = "YourPasswordHere"
GMT_OFFSET = -5  # Set your GMT offset in hours (e.g., -5 for EST, 1 for CET)
NTP_UPDATE_INTERVAL = 12 * 60 * 60  # Sync every 12 hours
GPS_BAUDRATE = 9600
GPS_TX_PIN = 4
GPS_RX_PIN = 5

# ==== LIGHT CONTROL VARIABLES ====
AUTO_LIGHT_ON = True
TURN_OFF_TIME = None

# ==== PIN CONFIGURATION ====
RUNWAY_LIGHT_PIN = 15
ONBOARD_LED_PIN = 25
LIGHT_SENSOR_PIN = 26
OVERRIDE_SWITCH_PIN = 14
MAINTENANCE_BUTTON_PIN = 13
RADIO_INPUT_PIN = 12
MOMENTARY_BUTTON_PIN = 11

# ==== INITIALIZE PINS ====
runway_light = Pin(RUNWAY_LIGHT_PIN, Pin.OUT)
onboard_led = Pin(ONBOARD_LED_PIN, Pin.OUT)
light_sensor = ADC(LIGHT_SENSOR_PIN)
override_switch = Pin(OVERRIDE_SWITCH_PIN, Pin.IN, Pin.PULL_DOWN)
maintenance_button = Pin(MAINTENANCE_BUTTON_PIN, Pin.IN, Pin.PULL_DOWN)
radio_input = Pin(RADIO_INPUT_PIN, Pin.IN, Pin.PULL_DOWN)
momentary_button = Pin(MOMENTARY_BUTTON_PIN, Pin.IN, Pin.PULL_DOWN)

# ==== GPS INITIALIZATION ====
gps_uart = UART(1, baudrate=GPS_BAUDRATE, tx=Pin(GPS_TX_PIN), rx=Pin(GPS_RX_PIN))

# ==== CONTROL VARIABLES ====
LIGHT_THRESHOLD = 2000
DAYLIGHT_STABLE_DURATION = 300
RADIO_CLICK_WINDOW = 5
LIGHT_ON_DURATION = 600
WARNING_FLASH_DURATION = 15
FLASH_OFF_TIME = 250
FLASH_CYCLE_TIME = 2000
MIN_CLICK_DURATION = 100

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

# ==== WARNING FLASH FUNCTION ====
def warning_flash():
    """Flashes the runway lights twice per cycle during the warning period."""
    global warning_flashing, last_flash_cycle_time, lights_off_in_cycle, warning_start_time

    current_time = utime.ticks_ms()

    # If warning just started, reset timers
    if warning_start_time is None:
        warning_start_time = current_time
        last_flash_cycle_time = current_time
        lights_off_in_cycle = False

    # Stop warning flashing after the total warning duration
    if utime.ticks_diff(current_time, warning_start_time) > WARNING_FLASH_DURATION * 1000:
        warning_flashing = False
        warning_start_time = None
        set_light_state(0)
        print("Warning flash completed, lights turned off.")
        return

    # First flash off
    cycle_progress = utime.ticks_diff(current_time, last_flash_cycle_time)
    if cycle_progress < FLASH_OFF_TIME:
        set_light_state(0)
    # Lights on after first flash
    elif cycle_progress < FLASH_OFF_TIME * 2:
        set_light_state(1)
    # Second flash off
    elif cycle_progress < FLASH_OFF_TIME * 3:
        set_light_state(0)
    # Lights on for the remainder of the cycle
    elif cycle_progress < FLASH_CYCLE_TIME:
        set_light_state(1)
    # Reset the cycle once 2 seconds have passed
    else:
        last_flash_cycle_time = current_time

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

        # Execute the warning flash if active
        if warning_flashing:
            warning_flash()

