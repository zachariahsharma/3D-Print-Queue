from flask import Flask, render_template, request, redirect, url_for
import json
import os
import uuid

DATA_FILE = 'queue.json'
UPLOAD_FOLDER = 'uploads'

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def load_queue():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, 'r') as f:
        return json.load(f)


def save_queue(queue):
    with open(DATA_FILE, 'w') as f:
        json.dump(queue, f, indent=2)


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
        'status': 'queued'
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
    for item in queue:
        if item['status'] == 'printing':
            item['status'] = 'queued'
    for item in queue:
        if item['id'] == item_id:
            item['status'] = 'printing'
            break
    save_queue(queue)
    return redirect(url_for('index'))


@app.route('/finish/<item_id>')
def finish(item_id):
    queue = load_queue()
    for item in queue:
        if item['id'] == item_id:
            item['status'] = 'printed'
            break
    save_queue(queue)
    return redirect(url_for('index'))


@app.route('/delete/<item_id>')
def delete(item_id):
    queue = load_queue()
    queue = [item for item in queue if item['id'] != item_id]
    save_queue(queue)
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
