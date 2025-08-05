# 3D Printer Fan Controller

This program monitors a Bambu Lab 3D printer and automatically controls a Kasa smart fan based on print progress and printer state.

## Features

- Monitors print progress and printer state every second
- Automatically turns on Kasa fan when print reaches 99%
- Automatically turns off fan when printer is idle or finished
- Handles connection errors gracefully
- Clean shutdown with proper cleanup
- Configurable settings

## Requirements

- Python 3.7+
- `bambulabs_api` library
- `kasa` library for Kasa smart devices

## Installation

1. Install required packages:
```bash
pip install bambulabs_api kasa
```

2. Update the configuration in `config.py` with your device information:
   - Printer IP address, access code, and serial number
   - Kasa fan IP address, username, and password

## Usage

Run the program:
```bash
python fan_enable.py
```

The program will:
1. Connect to your Bambu Lab printer
2. Connect to your Kasa fan
3. Start monitoring print progress and printer state
4. Turn on the fan when print reaches 99%
5. Turn off the fan when printer becomes idle or finished
6. Continue monitoring until you stop the program (Ctrl+C)

## Configuration

Edit `config.py` to update your device settings:

```python
# Bambu Lab 3D Printer Settings
PRINTER_HOSTNAME = "192.168.1.6"
PRINTER_ACCESS_CODE = "your_access_code"
PRINTER_SERIAL = "your_serial_number"

# Kasa Fan Settings
FAN_HOST = "192.168.1.65"
FAN_USERNAME = "your_email@example.com"
FAN_PASSWORD = "your_password"

# Monitoring Settings
CHECK_INTERVAL_SECONDS = 1  # How often to check print progress
```

## How it Works

1. **Setup Phase**: Connects to both the printer and fan
2. **Monitoring Loop**: Checks print percentage and printer state every second
3. **Fan Control**: 
   - Turns on fan when print reaches 99%
   - Turns off fan when printer state is 'IDLE' or 'FINISH'
4. **Error Handling**: Gracefully handles connection issues
5. **Cleanup**: Properly disconnects devices on exit

## Troubleshooting

- **Printer Connection Failed**: Check IP address, access code, and serial number
- **Fan Connection Failed**: Verify Kasa credentials and IP address
- **Permission Errors**: Make sure you have network access to both devices

## Safety Notes

- The fan will turn ON when print reaches 99% and turn OFF when printer is idle/finished
- The program includes error handling to prevent crashes
- Use Ctrl+C to stop the program safely
- The fan will be turned off during cleanup
