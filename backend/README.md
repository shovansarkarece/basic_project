# 5G 3-Slice Framework UI — Backend (FastAPI)

This backend exposes a small local REST API that wraps your existing scripts:

- `scripts/framework.sh`
- `scripts/topology.sh`
- `scripts/transport.sh`

## 1) Install & Run (on your Ubuntu VM)

From your repo root:

```bash
cd ui/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# IMPORTANT: start from repo root so paths resolve
REPO_ROOT="$(pwd)/.." \
SCRIPTS_DIR="$(pwd)/../scripts" \
COMPOSE_FILE="compose-files/network-slicing/docker-compose.yaml" \
ENV_FILE="build-files/open5gs.env" \
DBCTL="./open5gs-dbctl" \
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open health endpoint:
- http://<VM_IP>:8000/api/health

Alternatively the `start-ui.sh` in the home directory can be used to install the backend along with the frontend.

## 2.1) Passwordless sudo for transport NAT

`transport.sh` requires root (iptables + sysctl). The backend runs:

```bash
sudo -n ./scripts/transport.sh nat on
sudo -n ./scripts/transport.sh nat off
```

To enable that **without typing a password**, add a sudoers rule:

```bash
sudo visudo
```

Add (adjust your username and repo path):

```
<YOURUSER> ALL=(root) NOPASSWD: /bin/bash <ABS_PATH_TO_REPO>/scripts/transport.sh nat on, /bin/bash <ABS_PATH_TO_REPO>/scripts/transport.sh nat off
```
Example:

```
wub ALL=(root) NOPASSWD: /bin/bash /home/wub/mobcomproject25-26-group_b/scripts/transport.sh nat on, /bin/bash /home/wub/mobcomproject25-26-group_b/scripts/transport.sh nat off
```
# 2.2) Recommended Method (Safe & Clean)

Instead of editing the main /etc/sudoers file directly, create a dedicated sudoers include file.

```bash
LINE="$(whoami) ALL=(root) NOPASSWD: /bin/bash $(pwd)/scripts/transport.sh nat on, /bin/bash $(pwd)/scripts/transport.sh nat off"
echo "$LINE"
```

Then install it safely:

```bash
echo "$LINE" | sudo tee /etc/sudoers.d/5g-ui-transport >/dev/null
sudo chmod 440 /etc/sudoers.d/5g-ui-transport
sudo visudo -cf /etc/sudoers.d/5g-ui-transport
```

### Verification

Test that passwordless sudo works:

sudo -n /bin/bash "$(pwd)/scripts/transport.sh" status

If it runs without asking for a password, configuration is correct.


## 3) Security notes (important for grading)

- Endpoints are **allow-listed** (only known services, targets, actions).
- Backend is intended for **local VM/demo** use.
- Do **not** expose this API publicly.

