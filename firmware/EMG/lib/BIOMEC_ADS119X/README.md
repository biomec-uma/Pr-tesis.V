# BIOMEC_ADS119X
ADS119X library compatible with Arduino IDE 
Compatible IC: ADS1194, ADS1196 and ADS1198

## Installing
Download and install zip library in Arduino IDE 

## Compatible Microcontrollers
Any board supported in Arduino IDE should work. Tested with ESP32

## Dependencies
This library uses SPI class

## Usage examples
The library comes with 6 examples

Original examples:
- Test internally generated signal
- Basic
- Serial Commands

BIOMEC examples:
- BIOMEC_EMG_Basic: continuous EMG signal acquisition from surface electrodes via Serial.
- BIOMEC_EMG_Threshold: muscle contraction detection by threshold on CH1.
- BIOMEC_EMG_ESPNOW: wireless EMG data transmission via ESP-NOW to a second ESP32.

## Wiring
Connect SPI's pins (MISO, MOSI, SCLK), additionally the user can select DRDY, RST, and CS pins (example's default are pins 6, 5 and 10 with arduino UNO) 

## Boards known to have an ADS119X
- ECG2 Click from MikroE uses a ADS1194 (this library is tested with this breakout board)

- Bare chips are sold in Aliexpress


## Status: Working as June 2020. Updated April 2026 by Biomec.
