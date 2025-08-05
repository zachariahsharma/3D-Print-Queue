from flask import Flask, render_template, request, redirect, url_for
import json
import os
from dotenv import load_dotenv
import uuid
import threading
import time
import bambulabs_api as bl
from datetime import datetime
import asyncio
from kasa import Discover

# Load environment variables from a .env file if present
load_dotenv()

# 3D Print Queue Manager with Auto-Resend Functionality
# This app manages a queue of 3D print jobs and automatically resends print commands
# when the printer is idle but an item is marked as printing

DATA_FILE = 'queue.json'
UPLOAD_FOLDER = 'uploads'

# BambuLab printer configuration
PRINTER_HOSTNAME = "192.168.1.70"
PRINTER_ACCESS_CODE = "25133451"
PRINTER_SERIAL = "0309CA4A0800457"

# Kasa Fan configuration (values can be overridden by environment variables)
FAN_HOST = "192.168.1.88"
FAN_USERNAME = os.getenv("FAN_USERNAME")
FAN_PASSWORD = os.getenv("FAN_PASSWORD")

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Global printer instance and connection state
printer = None
printer_lock = threading.Lock()
printer_connected = False
last_connection_attempt = 0
connection_retry_interval = 30  # seconds between retry attempts

def ensure_printer_connection():
    """Ensure printer is connected, with retry logic"""
    global printer, printer_connected, last_connection_attempt
    
    current_time = time.time()
    
    # If we're already connected and the connection is working, return True
    if printer_connected and printer and printer.mqtt_client_ready():
        return True
    
    # If we recently tried to connect, wait before retrying
    if current_time - last_connection_attempt < connection_retry_interval:
        return False
    
    last_connection_attempt = current_time
    
    try:
        with printer_lock:
            # Create new printer instance if needed
            if printer is None:
                printer = bl.Printer(PRINTER_HOSTNAME, PRINTER_ACCESS_CODE, PRINTER_SERIAL)
                print(f"Created new printer instance for {PRINTER_HOSTNAME}")
            
            # Try to connect
            print(f"Attempting to connect to printer at {PRINTER_HOSTNAME}...")
            printer.connect()
            time.sleep(2)  # Give connection time to establish
            
            # Verify connection
            if printer.mqtt_client_ready():
                printer_connected = True
                print(f"Successfully connected to printer at {PRINTER_HOSTNAME}")
                return True
            else:
                printer_connected = False
                print(f"Failed to connect to printer at {PRINTER_HOSTNAME} - MQTT client not ready")
                return False
                
    except Exception as e:
        printer_connected = False
        print(f"Error connecting to printer at {PRINTER_HOSTNAME}: {e}")
        return False

def get_printer():
    """Get printer instance, ensuring connection"""
    global printer
    with printer_lock:
        if printer is None:
            printer = bl.Printer(PRINTER_HOSTNAME, PRINTER_ACCESS_CODE, PRINTER_SERIAL)
        return printer

async def get_fan_status():
    """Get current fan status"""
    try:
        fan_device = await Discover.discover_single(
            host=FAN_HOST,
            username=FAN_USERNAME, 
            password=FAN_PASSWORD
        )
        if fan_device:
            # Get the current state of the fan
            await fan_device.update()
            return fan_device.is_on
        return None
    except Exception as e:
        print(f"Error getting fan status: {e}")
        return None

def get_print_percentage():
    """Get current print percentage with connection retry"""
    if not ensure_printer_connection():
        return None
    
    try:
        printer_instance = get_printer()
        if printer_instance and printer_instance.mqtt_client_ready():
            return printer_instance.get_percentage()
        else:
            return None
    except Exception as e:
        print(f"Error getting print percentage: {e}")
        # Mark as disconnected on error
        global printer_connected
        printer_connected = False
        return None

def get_remaining_time():
    """Get remaining time in seconds with connection retry"""
    if not ensure_printer_connection():
        return None
    
    try:
        printer_instance = get_printer()
        if printer_instance and printer_instance.mqtt_client_ready():
            return printer_instance.get_time()
        else:
            return None
    except Exception as e:
        print(f"Error getting remaining time: {e}")
        # Mark as disconnected on error
        global printer_connected
        printer_connected = False
        return None

def get_printer_state():
    """Get current printer state with connection retry"""
    if not ensure_printer_connection():
        return None
    
    try:
        printer_instance = get_printer()
        if printer_instance and printer_instance.mqtt_client_ready():
            return printer_instance.get_state()
        else:
            return None
    except Exception as e:
        print(f"Error getting printer state: {e}")
        # Mark as disconnected on error
        global printer_connected
        printer_connected = False
        return None

def load_queue():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, 'r') as f:
        return json.load(f)


def save_queue(queue):
    with open(DATA_FILE, 'w') as f:
        json.dump(queue, f, indent=2)


def get_next_queued_item():
    """Get the first item in the queue with 'queued' status"""
    queue = load_queue()
    for item in queue:
        if item['status'] == 'queued':
            return item
    return None


def is_printing_in_progress():
    """Check if any item is currently printing"""
    queue = load_queue()
    return any(item['status'] == 'printing' for item in queue)


def update_print_status():
    """Update the status of currently printing items and handle resend scenarios"""
    queue = load_queue()
    updated = False
    
    try:
        # Get printer state with connection retry
        state = get_printer_state()
        
        if state is None:
            print("Unable to get printer state - printer may be disconnected")
            return False
        
        # Check if printer is idle (print finished)
        if state == 'FINISH':
            # Find any items marked as printing and mark them as printed
            for item in queue:
                if item['status'] == 'printing':
                    item['status'] = 'printed'
                    item['completed_at'] = datetime.now().isoformat()
                    updated = True
                    print(f"Marked {item['original_name']} as completed")
        
        # Check if printer is printing but no item is marked as printing
        elif state == 'PRINTING':
            if not is_printing_in_progress():
                # Find the first queued item and mark it as printing
                for item in queue:
                    if item['status'] == 'queued':
                        item['status'] = 'printing'
                        item['started_at'] = datetime.now().isoformat()
                        updated = True
                        print(f"Marked {item['original_name']} as printing")
                        break
        
        # Check if printer is idle but we have an item marked as printing (resend scenario)
        elif state == 'IDLE' or state == 'FAILED':
            printing_item = next((item for item in queue if item['status'] == 'printing'), None)
            if printing_item:
                print(f"Printer is idle but {printing_item['original_name']} is marked as printing. Resending print command...")
                # Try to resend the print command
                if resend_print_command(printing_item):
                    print(f"Successfully resent print command for {printing_item['original_name']}")
                else:
                    print(f"Failed to resend print command for {printing_item['original_name']}")
                    # Mark as queued again so it can be retried
                    printing_item['status'] = 'queued'
                    updated = True
        
    except Exception as e:
        print(f"Error updating print status: {e}")
    
    if updated:
        save_queue(queue)
    
    return updated


def resend_print_command(item):
    """Resend print command for an item that should be printing but printer is idle"""
    if not ensure_printer_connection():
        print("Cannot resend print command - printer not connected")
        return False
    
    try:
        printer_instance = get_printer()
        
        # Upload file if not already uploaded
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], item['filename'])
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                printer_instance.upload_file(f, item['original_name'])
            
            # Start the print
            plate_number = int(item['plate'])
            printer_instance.start_print(item['original_name'], plate_number=plate_number, use_ams=False, flow_calibration=False)
            
            print(f"Resent print command for {item['original_name']} on plate {plate_number}")
            return True
        else:
            print(f"File not found for resend: {file_path}")
            return False
            
    except Exception as e:
        print(f"Error resending print command: {e}")
        # Mark as disconnected on error
        global printer_connected
        printer_connected = False
        return False


def start_next_print():
    """Start printing the next item in the queue"""
    if is_printing_in_progress():
        print("Print already in progress, skipping...")
        return False
    
    next_item = get_next_queued_item()
    if not next_item:
        print("No items in queue to print")
        return False
    
    if not ensure_printer_connection():
        print("Cannot start print - printer not connected")
        return False
    
    try:
        printer_instance = get_printer()
        
        # Upload file if not already uploaded
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], next_item['filename'])
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                printer_instance.upload_file(f, next_item['original_name'])
            
            # Start the print
            plate_number = int(next_item['plate'])
            printer_instance.start_print(next_item['original_name'], plate_number=plate_number, use_ams=False, flow_calibration=False)
            
            # Update status in queue
            queue = load_queue()
            for item in queue:
                if item['id'] == next_item['id']:
                    item['status'] = 'printing'
                    item['started_at'] = datetime.now().isoformat()
                    break
            save_queue(queue)
            
            print(f"Started printing {next_item['original_name']} on plate {plate_number}")
            return True
        else:
            print(f"File not found: {file_path}")
            return False
            
    except Exception as e:
        print(f"Error starting print: {e}")
        # Mark as disconnected on error
        global printer_connected
        printer_connected = False
        return False


def background_monitor():
    """Background thread to monitor print status and start new prints"""
    print("Background monitor started - will retry printer connection every 30 seconds if disconnected")
    
    while True:
        try:
            # Update print status
            update_print_status()
            
            # Start next print if nothing is printing
            if not is_printing_in_progress():
                start_next_print()
            
            # Wait before next check
            time.sleep(30)  # Check every 30 seconds
            
        except Exception as e:
            print(f"Error in background monitor: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(60)  # Wait longer on error


@app.route('/')
def index():
    queue = load_queue()
    
    # Separate active items (queued/printing) from finished items (printed)
    active_queue = [item for item in queue if item['status'] in ['queued', 'printing']]
    finished_items = [item for item in queue if item['status'] == 'printed']
    
    return render_template('index.html', queue=active_queue, finished_items=finished_items)


@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('file')
    plate = request.form.get('plate')
    if not file or not file.filename or not file.filename.endswith('.3mf'):
        return redirect(url_for('index'))
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    filename = f"{uuid.uuid4()}_{file.filename}"
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    item = {
        'id': str(uuid.uuid4()),
        'filename': filename,
        'original_name': file.filename,
        'plate': plate,
        'status': 'queued',
        'uploaded_at': datetime.now().isoformat()
    }
    queue = load_queue()
    queue.append(item)
    save_queue(queue)
    return redirect(url_for('index'))


@app.route('/move/<item_id>/<direction>')
def move(item_id, direction):
    queue = load_queue()
    idx = next((i for i, x in enumerate(queue) if x['id'] == item_id), None)
    if idx is not None:
        if direction == 'up' and idx > 0:
            queue[idx], queue[idx - 1] = queue[idx - 1], queue[idx]
        elif direction == 'down' and idx < len(queue) - 1:
            queue[idx], queue[idx + 1] = queue[idx + 1], queue[idx]
    save_queue(queue)
    return redirect(url_for('index'))


@app.route('/start/<item_id>')
def start(item_id):
    queue = load_queue()
    # Stop any currently printing items
    for item in queue:
        if item['status'] == 'printing':
            item['status'] = 'queued'
    
    # Start the selected item
    for item in queue:
        if item['id'] == item_id:
            item['status'] = 'printing'
            item['started_at'] = datetime.now().isoformat()
            break
    
    save_queue(queue)
    
    # Try to start the print immediately
    try:
        start_next_print()
    except Exception as e:
        print(f"Error starting print manually: {e}")
    
    return redirect(url_for('index'))


@app.route('/finish/<item_id>')
def finish(item_id):
    queue = load_queue()
    for item in queue:
        if item['id'] == item_id:
            item['status'] = 'printed'
            item['completed_at'] = datetime.now().isoformat()
            break
    save_queue(queue)
    return redirect(url_for('index'))


@app.route('/delete/<item_id>')
def delete(item_id):
    queue = load_queue()
    # Get the item to delete
    item_to_delete = next((item for item in queue if item['id'] == item_id), None)
    
    if item_to_delete:
        # Delete the file if it exists
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], item_to_delete['filename'])
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error deleting file {file_path}: {e}")
    
    queue = [item for item in queue if item['id'] != item_id]
    save_queue(queue)
    return redirect(url_for('index'))


@app.route('/printer_status')
def printer_status():
    """API endpoint to get current printer status"""
    try:
        # Try to ensure connection
        connection_status = ensure_printer_connection()
        
        if not connection_status:
            return {
                'status': 'disconnected',
                'printer_state': None,
                'print_percentage': None,
                'remaining_time': None,
                'fan_status': None,
                'queue_status': {
                    'total_items': len(load_queue()),
                    'queued': len([item for item in load_queue() if item['status'] == 'queued']),
                    'printing': len([item for item in load_queue() if item['status'] == 'printing']),
                    'printed': len([item for item in load_queue() if item['status'] == 'printed'])
                }
            }
        
        state = get_printer_state()
        queue = load_queue()
        
        # Get additional printer information
        percentage = get_print_percentage()
        remaining_time = get_remaining_time()
        
        # Get fan status (run async function in sync context)
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            fan_status = loop.run_until_complete(get_fan_status())
            loop.close()
        except Exception as e:
            print(f"Error getting fan status: {e}")
            fan_status = None
        
        return {
            'status': 'connected',
            'printer_state': state,
            'print_percentage': percentage,
            'remaining_time': remaining_time,
            'fan_status': fan_status,
            'queue_status': {
                'total_items': len(queue),
                'queued': len([item for item in queue if item['status'] == 'queued']),
                'printing': len([item for item in queue if item['status'] == 'printing']),
                'printed': len([item for item in queue if item['status'] == 'printed'])
            }
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }

# --- Webhook endpoint for print failures ---
@app.route('/webhook/print_failure', methods=['POST'])
def print_failure_webhook():
    """
    Receive webhook notifications from the printer when a job fails.
    The endpoint is deliberately flexible – any JSON payload is accepted
    and logged.  If the payload indicates a failure, the currently
    printing job in the local queue is moved back to 'queued' (so it can
    be re-tried later) and the queue file is persisted.
    """
    try:
        payload = request.get_json(force=True, silent=True) or {}
        print(f"Received print failure webhook: {payload}")

        # Detect a failure in a few common ways
        event_type = str(payload.get('event', '')).upper()
        state      = str(payload.get('state', '')).upper()
        status     = str(payload.get('print_status', '')).upper()

        failure_detected = any(val in ['PRINT_FAILED', 'FAILED', 'FAILURE', 'ERROR']
                               for val in [event_type, state, status])

        if failure_detected:
            queue = load_queue()
            updated = False
            for item in queue:
                if item['status'] == 'printing':
                    item['status'] = 'queued'
                    item['failed_at'] = datetime.now().isoformat()
                    updated = True
            if updated:
                save_queue(queue)
                print('Current printing job marked as queued after failure')

        return {'status': 'ok'}
    except Exception as e:
        print(f'Error processing print failure webhook: {e}')
        return {'status': 'error', 'error': str(e)}, 500


if __name__ == '__main__':
    # Start background monitoring thread
    monitor_thread = threading.Thread(target=background_monitor, daemon=True)
    monitor_thread.start()
    
    print("Starting BambuLab Queue Manager...")
    print(f"Printer: {PRINTER_HOSTNAME}")
    print("Background monitoring started")
    
    app.run(debug=True, host='0.0.0.0', port=5001)
