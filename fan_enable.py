import asyncio
import time
import bambulabs_api as bl
from kasa import Discover
from config import *

# Load environment variables (e.g., from a .env file)
import os
from dotenv import load_dotenv

load_dotenv()

# Fan control thresholds (in minutes)
FAN_ON_THRESHOLD_MINUTES = 2   # Turn fan ON when remaining time is <= 2 minutes
FAN_OFF_THRESHOLD_MINUTES = 5  # Turn fan OFF again only after time rises above 5 minutes

class FanController:
    def __init__(self, printer_hostname, printer_access_code, printer_serial, fan_host, fan_username, fan_password):
        self.printer_hostname = printer_hostname
        self.printer_access_code = printer_access_code
        self.printer_serial = printer_serial
        self.fan_host = fan_host
        self.fan_username = fan_username
        self.fan_password = fan_password
        self.printer = None
        self.fan_device = None
        self.fan_turned_on = False
        self.last_state_check = 0  # Track when we last checked the actual fan state
        
    async def setup_fan(self):
        """Setup connection to Kasa fan"""
        try:
            self.fan_device = await Discover.discover_single(
                host=self.fan_host,
                username=self.fan_username, 
                password=self.fan_password
            )
            print(f"Connected to fan at {self.fan_host}")
        except Exception as e:
            print(f"Failed to connect to fan: {e}")
            return False
        return True
    
    async def check_actual_fan_state(self):
        """Check the actual state of the Kasa fan device"""
        try:
            if self.fan_device:
                await self.fan_device.update()
                actual_state = self.fan_device.is_on
                return actual_state
            else:
                return None
        except Exception as e:
            print(f"Failed to check actual fan state: {e}")
            return None
    
    async def sync_fan_state(self, remaining_time=None, printer_state=None):
        """Sync our tracked state with the actual device state and correct mismatches"""
        actual_state = await self.check_actual_fan_state()
        if actual_state is not None:
            # Determine what the fan state should be based on current conditions
            should_be_on = False
            if printer_state in ['PRINTING', 'RUNNING'] and remaining_time is not None:
                try:
                    remaining_time_int = int(remaining_time)
                    # Hysteresis: keep fan ON until remaining time climbs above the OFF threshold
                    if remaining_time_int <= FAN_ON_THRESHOLD_MINUTES:
                        should_be_on = True
                    elif self.fan_turned_on and remaining_time_int < FAN_OFF_THRESHOLD_MINUTES:
                        should_be_on = True
                    else:
                        should_be_on = False
                except (ValueError, TypeError):
                    should_be_on = False
            elif printer_state in ['IDLE', 'FINISH']:
                should_be_on = False
            
            # Check if there's a mismatch between what it should be and what it actually is
            if should_be_on != actual_state:
                print(f"Fan state mismatch detected! Should be: {'ON' if should_be_on else 'OFF'}, Actual: {'ON' if actual_state else 'OFF'}")
                
                # Correct the actual fan state
                if self.fan_device:
                    if should_be_on and not actual_state:
                        # Fan should be ON but is actually OFF - turn it on
                        await self.fan_device.turn_on()
                        print("Correcting fan state: turned ON")
                        self.fan_turned_on = True
                    elif not should_be_on and actual_state:
                        # Fan should be OFF but is actually ON - turn it off
                        await self.fan_device.turn_off()
                        print("Correcting fan state: turned OFF")
                        self.fan_turned_on = False
                else:
                    print("Cannot correct fan state - fan device not connected")
                    # Update tracked state to match actual state if we can't correct it
                    self.fan_turned_on = actual_state
            else:
                # No mismatch, just update tracked state to match actual state
                if self.fan_turned_on != actual_state:
                    self.fan_turned_on = actual_state
                    print(f"Fan state synced to: {'ON' if self.fan_turned_on else 'OFF'}")
            
            return True
        return False
    
    def setup_printer(self):
        """Setup connection to Bambu printer"""
        try:
            self.printer = bl.Printer(self.printer_hostname, self.printer_access_code, self.printer_serial)
            self.printer.connect()
            time.sleep(2)
            print(f"Connected to printer at {self.printer_hostname}")
            return True
        except Exception as e:
            print(f"Failed to connect to printer: {e}")
            return False
    
    def get_print_percentage(self):
        """Get current print percentage"""
        try:
            if self.printer and self.printer.mqtt_client_ready():
                return self.printer.get_percentage()
            else:
                return None
        except Exception as e:
            print(f"Error getting print percentage: {e}")
            return None
    
    def get_remaining_time(self):
        """Get remaining time in seconds"""
        try:
            if self.printer and self.printer.mqtt_client_ready():
                return self.printer.get_time()
            else:
                return None
        except Exception as e:
            print(f"Error getting remaining time: {e}")
            return None
    
    def get_printer_state(self):
        """Get current printer state"""
        try:
            if self.printer and self.printer.mqtt_client_ready():
                return self.printer.get_state()
            else:
                return None
        except Exception as e:
            print(f"Error getting printer state: {e}")
            return None
    
    async def turn_on_fan(self):
        """Turn on the Kasa fan"""
        try:
            if self.fan_device and not self.fan_turned_on:
                await self.fan_device.turn_on()
                self.fan_turned_on = True
                print("Fan turned ON - Less than 2 minutes remaining!")
        except Exception as e:
            print(f"Failed to turn on fan: {e}")
    
    async def turn_off_fan(self):
        """Turn off the Kasa fan"""
        try:
            if self.fan_device and self.fan_turned_on:
                await self.fan_device.turn_off()
                self.fan_turned_on = False
                print("Fan turned OFF")
        except Exception as e:
            print(f"Failed to turn off fan: {e}")
    
    async def monitor_print(self):
        """Main monitoring loop - checks print progress and printer state"""
        print("Starting print monitoring...")
        print(f"Fan will turn ON when <= {FAN_ON_THRESHOLD_MINUTES} minutes remain, "
              f"and turn OFF when printer is idle/finished or remaining time > {FAN_OFF_THRESHOLD_MINUTES} minutes")
        print("Fan state will be verified and corrected every 10 seconds")
        
        while True:
            try:
                percentage = self.get_print_percentage()
                remaining_time = self.get_remaining_time()
                state = self.get_printer_state()
                
                # Check actual fan state every 10 seconds to catch any mismatches
                current_time = time.time()
                if (current_time - self.last_state_check) >= 10:
                    await self.sync_fan_state(remaining_time, state)
                    self.last_state_check = current_time
                
                if remaining_time is not None and state is not None:
                    # Convert remaining time to int for comparison
                    try:
                        remaining_time_int = int(remaining_time)
                    except (ValueError, TypeError):
                        remaining_time_int = None
                    
                    print(f"Print progress: {percentage}%, Remaining time: {remaining_time}m, Printer state: {state}, Fan: {'ON' if self.fan_turned_on else 'OFF'}")
                    
                    # Priority 1: Turn off fan when printer is idle or finished (regardless of time)
                    if (state == 'IDLE' or state == 'FINISH') and self.fan_turned_on:
                        await self.turn_off_fan()
                        print(f"Fan turned off - printer state: {state}")
                    
                    # Priority 2: Turn on fan when less than 120 seconds remaining AND printer is printing
                    elif (remaining_time_int is not None and remaining_time_int <= FAN_ON_THRESHOLD_MINUTES and 
                          (state == 'PRINTING' or state == 'RUNNING') and not self.fan_turned_on):
                        await self.turn_on_fan()
                    
                    # Priority 3: Reset fan state if print restarts (remaining time increases above 120)
                    elif (remaining_time_int is not None and remaining_time_int > FAN_OFF_THRESHOLD_MINUTES and 
                          self.fan_turned_on and (state == 'PRINTING' or state == 'RUNNING')):
                        await self.turn_off_fan()
                        print("Remaining time increased above threshold - fan turned OFF; it will come back ON when within threshold again")
                        
                elif state is not None:
                    print(f"Printer state: {state} (no time data), Fan: {'ON' if self.fan_turned_on else 'OFF'}")
                    
                    # Turn off fan if printer is idle or finished, even without time data
                    if (state == 'IDLE' or state == 'FINISH') and self.fan_turned_on:
                        await self.turn_off_fan()
                        print(f"Fan turned off - printer state: {state}")
                        
                else:
                    print(f"Unable to get print status - printer may be disconnected, Fan: {'ON' if self.fan_turned_on else 'OFF'}")
                
                # Wait before next check
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                
            except KeyboardInterrupt:
                print("\nMonitoring stopped by user")
                break
            except Exception as e:
                print(f"Error in monitoring loop: {e}")
                await asyncio.sleep(5)  # Wait longer on error
    
    async def cleanup(self):
        """Cleanup connections"""
        if self.printer:
            try:
                self.printer.disconnect()
                print("Printer disconnected")
            except:
                pass
        
        if self.fan_device:
            try:
                await self.fan_device.turn_off()
                print("Fan turned off during cleanup")
            except:
                pass

async def main():
    # Import configuration & environment overrides

    # Prefer environment variables for sensitive data like credentials
    fan_username = os.getenv("FAN_USERNAME")
    fan_password = os.getenv("FAN_PASSWORD")

    controller = FanController(
        PRINTER_HOSTNAME, PRINTER_ACCESS_CODE, PRINTER_SERIAL,
        FAN_HOST, fan_username, fan_password
    )
    
    # Setup connections
    if not controller.setup_printer():
        print("Failed to connect to printer. Exiting.")
    
    if not await controller.setup_fan():
        print("Failed to connect to fan. Exiting.")
    
    try:
        # Start monitoring
        await controller.monitor_print()
    finally:
        # Cleanup
        await controller.cleanup()

if __name__ == "__main__":
    asyncio.run(main()) 