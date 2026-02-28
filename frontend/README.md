# 5G 3-Slice Framework UI — Frontend (Static HTML)

This is a **zero-build** UI (pure HTML/CSS/JS). It talks to the backend REST API.

## Run

Option A) Use Python to serve static files:

```bash
cd ui/frontend
python3 -m http.server 5173
```
Alternatively the `start-ui.sh` in the home directory can be used to install the frontend along with the backend.

Open:
- http://<VM_IP>:5173

Set "API Base" to:
- http://<VM_IP>:8000
