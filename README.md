# 3D Print Queue

This is a minimal web application for managing a 3D print queue. Users can upload
`.3mf` files, specify the plate number, reorder queued jobs and mark prints as
started or finished. The app keeps track of which file is currently printing and
which ones have already been printed.

## Setup

Install dependencies and run the server:

```bash
pip install -r requirements.txt
python app.py
```

By default uploaded files are stored in the `uploads/` folder and queue state is
persisted in `queue.json`.
