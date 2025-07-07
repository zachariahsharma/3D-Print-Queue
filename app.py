from flask import Flask, render_template, request, redirect, url_for
import json
import os
import uuid
import threading
import time
import bambulabs_api as bl
from datetime import datetime

DATA_FILE = 'queue.json'
UPLOAD_FOLDER = 'uploads'

# BambuLab printer configuration
PRINTER_HOSTNAME = "192.168.1.6"
PRINTER_ACCESS_CODE = "25133451"
PRINTER_SERIAL = "0309CA4A0800457"

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Global printer instance
printer = None
printer_lock = threading.Lock()

def get_printer():
    """Get or create printer instance with thread safety"""
    global printer
    with printer_lock:
        if printer is None:
            printer = bl.Printer(PRINTER_HOSTNAME, PRINTER_ACCESS_CODE, PRINTER_SERIAL)
        return printer

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
    """Update the status of currently printing items"""
    queue = load_queue()
    updated = False
    
    try:
        printer_instance = get_printer()
        if not printer_instance.mqtt_client_ready():
            printer_instance.connect()
            time.sleep(2)
        
        # Get printer state
        state = printer_instance.get_state()
        
        # Check if printer is idle (print finished)
        if state and state == 'FINISH':
            # Find any items marked as printing and mark them as printed
            for item in queue:
                if item['status'] == 'printing':
                    item['status'] = 'printed'
                    item['completed_at'] = datetime.now().isoformat()
                    updated = True
                    print(f"Marked {item['original_name']} as completed")
        
        # Check if printer is printing but no item is marked as printing
        elif state and state == 'PRINTING':
            if not is_printing_in_progress():
                # Find the first queued item and mark it as printing
                for item in queue:
                    if item['status'] == 'queued':
                        item['status'] = 'printing'
                        item['started_at'] = datetime.now().isoformat()
                        updated = True
                        print(f"Marked {item['original_name']} as printing")
                        break
        
    except Exception as e:
        print(f"Error updating print status: {e}")
    
    if updated:
        save_queue(queue)
    
    return updated


def start_next_print():
    """Start printing the next item in the queue"""
    if is_printing_in_progress():
        print("Print already in progress, skipping...")
        return False
    
    next_item = get_next_queued_item()
    if not next_item:
        print("No items in queue to print")
        return False
    
    try:
        printer_instance = get_printer()
        if not printer_instance.mqtt_client_ready():
            printer_instance.connect()
            time.sleep(2)
        
        # Upload file if not already uploaded
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], next_item['filename'])
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                printer_instance.upload_file(f, next_item['original_name'])
            
            # Start the print
            plate_number = int(next_item['plate'])
            printer_instance.start_print(next_item['original_name'], plate_number=plate_number, use_ams=False)
            
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
        return False


def background_monitor():
    """Background thread to monitor print status and start new prints"""
    while True:
        try:
            # Update print status
            update_print_status()
            
            # Start next print if nothing is printing
            print('hello')
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
    return render_template('index.html', queue=queue)


@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('file')
    plate = request.form.get('plate')
    if not file or not file.filename.endswith('.3mf'):
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
        printer_instance = get_printer()
        if not printer_instance.mqtt_client_ready():
            printer_instance.connect()
            time.sleep(2)
        
        state = printer_instance.get_state()
        return {
            'status': 'connected',
            'printer_state': state,
            'queue_status': {
                'total_items': len(load_queue()),
                'queued': len([item for item in load_queue() if item['status'] == 'queued']),
                'printing': len([item for item in load_queue() if item['status'] == 'printing']),
                'printed': len([item for item in load_queue() if item['status'] == 'printed'])
            }
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }


if __name__ == '__main__':
    # Start background monitoring thread
    monitor_thread = threading.Thread(target=background_monitor, daemon=True)
    monitor_thread.start()
    
    print("Starting BambuLab Queue Manager...")
    print(f"Printer: {PRINTER_HOSTNAME}")
    print("Background monitoring started")
    
    app.run(debug=True, host='0.0.0.0', port=5001)
