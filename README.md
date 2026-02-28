## UI Implementation (Backend + Frontend)

This folder contains a minimal web-based UI for operating and
visualizing the **5G 3-Slice Network Slicing Framework**.

It consists of:

-   `backend/` → FastAPI server wrapping existing CLI scripts\
-   `frontend/` → Static Web UI (no build tools required)\
-   `start-ui.sh` → One-command startup script

------------------------------------------------------------------------

## 🚀 Quick Start (One Command)

Instead of manually starting backend and frontend separately, use the
unified startup script.

### 1️⃣ Navigate to the UI directory

``` bash
cd mobcomproject25-26-group_b/ui
```

### 2️⃣ Start Backend and Frontend

``` bash
./start-ui.sh
```

This will automatically:

-   Create `.venv` (first run only)
-   Install required Python packages
-   Start the FastAPI backend
-   Start the frontend HTTP server
-   Print access URLs

After the first run, startup is immediate.

------------------------------------------------------------------------

## 🌐 Access the UI

### Frontend

Open in your browser:

    http://<VM_IP>:5173

Example (VirtualBox default):

    http://10.0.2.15:5173

------------------------------------------------------------------------

### 🔧 IMPORTANT -- Set API Base

In the UI header:

Set **API Base** to:

    http://<VM_IP>:8000

Example:

    http://10.0.2.15:8000

This connects the frontend to the backend API running inside the VM.

------------------------------------------------------------------------

## 🔍 Backend Endpoints

### Health Check

    http://localhost:8000/api/health

------------------------------------------------------------------------

### Full API Documentation (Swagger UI)

    http://localhost:8000/docs

This allows interactive API testing.

------------------------------------------------------------------------

## 🔄 First Run Behavior

On the first execution:

-   `.venv/` is created inside `ui/backend/`
-   `pip install -r requirements.txt` is executed
-   The environment is fully isolated

This virtual environment:

-   Does NOT affect system Python
-   Does NOT interfere with other projects
-   Is self-contained inside `ui/backend/`

------------------------------------------------------------------------

## 🧹 Cleanup / Remove UI Backend Environment

If you want to remove everything related to the UI backend:

``` bash
rm -rf ui/backend/.venv
```

Running `./start-ui.sh` again will recreate everything automatically.

------------------------------------------------------------------------

## 🏗 Architecture Context

Logical flow:

    UE → gNB → AMF → SMF (slice-specific) → UPF (slice-specific) → Internet

The backend wraps existing scripts in mobcomproject25-26-group_b/scripts:

-   `framework.sh`
-   `transport.sh`
-   `topology.sh`

No slicing logic is duplicated.

------------------------------------------------------------------------

## 🎯 Design Goals

-   Simple static frontend
-   FastAPI backend abstraction
-   Clean integration with existing slicing framework
-   Reproducible environment via `.venv`
