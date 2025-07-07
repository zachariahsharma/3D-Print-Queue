import bambulabs_api as bl
import zipfile
import time
hostname = "192.168.1.6"
access_code = "25133451"
serial = "0309CA4A0800457"
printer = bl.Printer(hostname, access_code, serial)
printer.connect()
time.sleep(2)
with open('./sigma.3mf', "rb") as f:
    printer.upload_file(f, f"sigma.3mf") 
# print(printer.get_state())
print(printer.mqtt_client_ready())
printer.start_print('sigma.3mf', plate_number=2, use_ams=False)
# # printer.turn_light_off()
# printer.home_printer()
# print(printer.home_printer())
printer.disconnect()