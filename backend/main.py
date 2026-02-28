from __future__ import annotations

import os
import re
import json
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Generator

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# 5G 3-Slice Framework API (Use-Case + KPI + Topology Table + Dynamic Flow data)
#
# Key endpoints for the GUI:
# - POST /api/usecases/activate  -> start + provision + verify, returns KPIs + profile + flows
# - POST /api/usecases/verify    -> verify only, returns KPIs + profile + flows
# - GET  /api/usecases/history   -> run history for the UI
# - GET  /api/topology           -> table rows: Type | Component | Status | Open5GS IP | PDU Session IP
#
# Existing operational endpoints kept:
# - /api/deployment/start|stop|status|restart
# - /api/transport/status + /api/transport/nat
# - /api/logs/{service}
# - /api/subscribers/provision (legacy)
# - /api/verify (legacy)
#
# Required scripts:
# - scripts/framework.sh
# - scripts/transport.sh
# - scripts/usecase.sh   (wrapper; called by the new endpoints)
#
# Notes:
# - For transport NAT, backend runs: sudo -n ./scripts/transport.sh nat on|off
#   Configure passwordless sudo for that command.
# - Topology rows are built via docker compose + docker inspect + docker exec for stability.
# -----------------------------------------------------------------------------

APP_TITLE = "5G 3-Slice Framework API"

# IMPORTANT:
# If you start uvicorn from ui/backend, os.getcwd() becomes ui/backend (wrong).
# Prefer exporting REPO_ROOT or starting uvicorn from repo root.
REPO_ROOT = os.getenv("REPO_ROOT", os.getcwd())
SCRIPTS_DIR = os.getenv("SCRIPTS_DIR", os.path.join(REPO_ROOT, "scripts"))

FRAMEWORK = os.path.join(SCRIPTS_DIR, "framework.sh")
TRANSPORT = os.path.join(SCRIPTS_DIR, "transport.sh")
USECASE = os.path.join(SCRIPTS_DIR, "usecase.sh")

COMPOSE_FILE = os.getenv("COMPOSE_FILE", "compose-files/network-slicing/docker-compose.yaml")
ENV_FILE = os.getenv("ENV_FILE", "build-files/open5gs.env")
DBCTL = os.getenv("DBCTL", "./open5gs-dbctl")

RESULTS_DIR = os.getenv("RESULTS_DIR", os.path.join(REPO_ROOT, "ui", "backend", "data"))
RESULTS_FILE = os.path.join(RESULTS_DIR, "usecase_runs.jsonl")

ALLOWED_VERIFY_TARGETS = {"ue1", "ue2", "ue3", "all"}
ALLOWED_PROVISION_TARGETS = {"ue1", "ue2", "ue3", "all"}
ALLOWED_TRANSPORT_ACTIONS = {"on", "off"}
ALLOWED_TRANSPORT_MODES = {"auto", "on", "off"}
ALLOWED_USECASES = {"embb", "urllc", "mmtc"}

ALLOWED_SERVICES = {
    "db","nrf","amf","nssf","udm","udr","ausf","pcf","bsf",
    "smf1","smf2","smf3","upf1","upf2","upf3","gnb","ue1","ue2","ue3","webui"
}

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)

@dataclass
class CmdResult:
    ok: bool
    code: int
    stdout: str
    stderr: str
    cmd: List[str]

def run_cmd(
    cmd: List[str],
    timeout_s: int = 60,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
) -> CmdResult:
    e = os.environ.copy()
    if env:
        e.update(env)

    p = subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        env=e,
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
    return CmdResult(
        ok=(p.returncode == 0),
        code=p.returncode,
        stdout=strip_ansi(p.stdout),
        stderr=strip_ansi(p.stderr),
        cmd=cmd,
    )

def ensure_exists(path: str, label: str):
    if not os.path.exists(path):
        raise HTTPException(status_code=500, detail=f"{label} not found: {path}")

def framework_env() -> Dict[str, str]:
    return {"COMPOSE_FILE": COMPOSE_FILE, "ENV_FILE": ENV_FILE, "DBCTL": DBCTL}

# ----------------------------- Use case mapping -------------------------------

USECASE_MAP: Dict[str, Dict[str, Any]] = {
    "embb":  {"label": "Mobile Broadband (eMBB)", "ue": "ue1", "smf": "smf1", "upf": "upf1", "slice": "1/000001", "pool": "10.45.0.0/16"},
    "urllc": {"label": "Connected Cars (URLLC)",  "ue": "ue2", "smf": "smf2", "upf": "upf2", "slice": "1/000002", "pool": "10.46.0.0/16"},
    "mmtc":  {"label": "Industrial IoT (mMTC)",   "ue": "ue3", "smf": "smf3", "upf": "upf3", "slice": "1/000003", "pool": "10.47.0.0/16"},
}

def validate_usecases(usecases: List[str]) -> List[str]:
    norm = [u.strip().lower() for u in usecases if u and u.strip()]
    if not norm:
        raise HTTPException(status_code=400, detail="usecases must not be empty")
    bad = [u for u in norm if u not in ALLOWED_USECASES]
    if bad:
        raise HTTPException(status_code=400, detail=f"unsupported usecases: {bad}")
    # unique preserve order
    seen = set()
    out: List[str] = []
    for u in norm:
        if u not in seen:
            out.append(u)
            seen.add(u)
    return out

def build_profile_info(usecases: List[str]) -> Dict[str, Any]:
    slices = []
    for u in usecases:
        m = USECASE_MAP[u]
        slices.append({
            "usecase": u,
            "label": m["label"],
            "ue": m["ue"].upper(),
            "slice": m["slice"],
            "smf": m["smf"].upper(),
            "upf": m["upf"].upper(),
            "pool": m["pool"],
        })
    return {"selected": usecases, "slices": slices}

def build_abstraction(usecases: List[str]) -> Dict[str, Any]:
    mapping = []
    for u in usecases:
        m = USECASE_MAP[u]
        mapping.append({
            "usecase": u,
            "label": m["label"],
            "slice": m["slice"],
            "nf_path": [m["ue"].upper(), "gNB", "AMF", m["smf"].upper(), m["upf"].upper(), "Internet"]
        })
    return {"usecases": usecases, "mapping": mapping}

# ----------------------------- History helpers --------------------------------

def ensure_results_dir():
    os.makedirs(RESULTS_DIR, exist_ok=True)

def append_run(record: Dict[str, Any]):
    ensure_results_dir()
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def read_runs(limit: int = 50) -> List[Dict[str, Any]]:
    if not os.path.exists(RESULTS_FILE):
        return []
    out: List[Dict[str, Any]] = []
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out[-limit:]

# ----------------------------- KPI parsers ------------------------------------

def parse_ping_loss_and_rtt(text: str) -> Dict[str, Any]:
    """
    Parses classic ping output:
      - 'X% packet loss'
      - 'rtt min/avg/max/mdev = a/b/c/d ms'
    """
    loss_pct: Optional[float] = None
    avg_rtt_ms: Optional[float] = None

    m_loss = re.search(r"(\d+(?:\.\d+)?)%\s+packet loss", text)
    if m_loss:
        try:
            loss_pct = float(m_loss.group(1))
        except Exception:
            loss_pct = None

    m_rtt = re.search(r"rtt .* = ([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)\s*ms", text)
    if m_rtt:
        try:
            avg_rtt_ms = float(m_rtt.group(2))
        except Exception:
            avg_rtt_ms = None

    return {"loss_pct": loss_pct, "avg_rtt_ms": avg_rtt_ms}

def parse_mmtc_ping_ok_rate(text: str) -> Optional[float]:
    # Example: "10 packets transmitted, 10 received, 0% packet loss"
    m = re.search(r"(\d+)\s+packets transmitted,\s+(\d+)\s+(?:packets\s+)?received", text)
    if not m:
        return None
    tx = int(m.group(1))
    rx = int(m.group(2))
    if tx <= 0:
        return None
    return (rx / tx) * 100.0

def parse_embb_throughput_mbps(text: str) -> Optional[float]:
    """
    Best-effort throughput parsing.
    Supports either:
      - a custom line like: THROUGHPUT_Mbps=123.45
      - iperf3 text lines like: '...  946 Mbits/sec'
    """
    m = re.search(r"THROUGHPUT_Mbps\s*=\s*([0-9.]+)", text)
    if m:
        return float(m.group(1))

    mbits = None
    for mm in re.finditer(r"([0-9.]+)\s*(Kbits|Mbits|Gbits)\/sec", text):
        val = float(mm.group(1))
        unit = mm.group(2)
        if unit == "Kbits":
            mbits = val / 1000.0
        elif unit == "Mbits":
            mbits = val
        elif unit == "Gbits":
            mbits = val * 1000.0
    return mbits

# ----------------------------- Docker topology helpers ------------------------

def docker_compose_base() -> List[str]:
    return ["docker", "compose", "-f", COMPOSE_FILE, "--env-file", ENV_FILE]

def compose_container_id(service: str) -> Optional[str]:
    r = run_cmd(docker_compose_base() + ["ps", "-q", service], timeout_s=30)
    if not r.ok:
        return None
    cid = r.stdout.strip()
    return cid or None

def container_status(cid: str) -> str:
    r = run_cmd(["docker", "inspect", "-f", "{{.State.Status}}", cid], timeout_s=20)
    return r.stdout.strip() if r.ok and r.stdout.strip() else "unknown"

def container_running(cid: str) -> bool:
    r = run_cmd(["docker", "inspect", "-f", "{{.State.Running}}", cid], timeout_s=20)
    return r.ok and r.stdout.strip().lower() == "true"

def container_ip(cid: str) -> str:
    r = run_cmd(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", cid], timeout_s=20)
    ip = r.stdout.strip() if r.ok else ""
    return ip if ip else "-"

def container_restart_count(cid: str) -> Optional[int]:
    r = run_cmd(["docker", "inspect", "-f", "{{.RestartCount}}", cid], timeout_s=20)
    if not r.ok:
        return None
    try:
        return int(r.stdout.strip())
    except Exception:
        return None

def ue_pdu_ip(service: str) -> str:
    cid = compose_container_id(service)
    if not cid or not container_running(cid):
        return "-"
    cmd = ["docker", "exec", cid, "sh", "-lc", "ip -4 addr show uesimtun0 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -n1"]
    r = run_cmd(cmd, timeout_s=20)
    ip = r.stdout.strip() if r.ok else ""
    return ip if ip else "-"

def classify_type(service: str) -> str:
    s = service.lower()
    if s == "gnb":
        return "RAN"
    if s.startswith("ue"):
        return "UE"
    return "Core"

def pretty_component(service: str) -> str:
    if service == "gnb":
        return "gNB"
    if service.startswith("ue"):
        return service.upper()
    return service.upper()

def build_topology_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    def sort_key(svc: str):
        t = classify_type(svc)
        order = {"Core": 0, "RAN": 1, "UE": 2}.get(t, 9)
        return (order, svc)
    for svc in sorted(ALLOWED_SERVICES, key=sort_key):
        cid = compose_container_id(svc)
        if not cid:
            rows.append({
                "type": classify_type(svc),
                "component": pretty_component(svc),
                "status": "not_created",
                "open5gs_ip": "-",
                "pdu_session_ip": "-",
            })
            continue

        status = container_status(cid)
        ip = container_ip(cid)
        pdu = ue_pdu_ip(svc) if svc.startswith("ue") else "-"

        rows.append({
            "type": classify_type(svc),
            "component": pretty_component(svc),
            "status": status,
            "open5gs_ip": ip,
            "pdu_session_ip": pdu,
        })
    return rows

# ----------------------------- Legacy verify parser ---------------------------

def parse_verify_output(output: str) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"slice_checks": [], "ping": [], "passed": None}
    for line in output.splitlines():
        m = re.search(r"Slice/IP check:\s*(ue[123])\s*got IP=([0-9.]+).*expected prefix\s*([0-9.]+)\*", line)
        if m:
            summary["slice_checks"].append({
                "ue": m.group(1),
                "ip": m.group(2),
                "expected_prefix": m.group(3),
                "pass": True
            })
        if "Ping OK:" in line:
            summary["ping"].append({"pass": True, "line": line})
        if "Ping FAILED:" in line:
            summary["ping"].append({"pass": False, "line": line})
        if "== VERIFY PASSED" in line:
            summary["passed"] = True
        if line.startswith("ERROR:") or "VERIFY FAILED" in line:
            summary["passed"] = False
    return summary

# ----------------------------- API models -------------------------------------

class RestartReq(BaseModel):
    service: str = Field(..., description="docker compose service/container name, e.g. amf, smf1, upf1, ue1")

class ProvisionReq(BaseModel):
    target: str = Field("all", description="ue1|ue2|ue3|all")

class VerifyReq(BaseModel):
    target: str = Field("all", description="ue1|ue2|ue3|all")
    ping: bool = False
    target_ip: str = "8.8.8.8"

class TransportNatReq(BaseModel):
    state: str = Field(..., description="on|off")

class UsecaseTuningURLLC(BaseModel):
    count: int = 50
    interval: float = 0.2

class UsecaseTuningMMTC(BaseModel):
    count: int = 10
    interval: int = 2

class UsecaseTuningEMBB(BaseModel):
    iperfServer: Optional[str] = None
    duration: int = 10

class UsecaseActivateReq(BaseModel):
    usecases: List[str]
    transport: str = "auto"
    target: str = "8.8.8.8"
    urllc: UsecaseTuningURLLC = UsecaseTuningURLLC()
    mmtc: UsecaseTuningMMTC = UsecaseTuningMMTC()
    embb: UsecaseTuningEMBB = UsecaseTuningEMBB()

class UsecaseVerifyReq(BaseModel):
    usecases: List[str]
    target: str = "8.8.8.8"
    urllc: UsecaseTuningURLLC = UsecaseTuningURLLC()
    mmtc: UsecaseTuningMMTC = UsecaseTuningMMTC()
    embb: UsecaseTuningEMBB = UsecaseTuningEMBB()

# ----------------------------- FastAPI app ------------------------------------

app = FastAPI(title=APP_TITLE)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {
        "ok": True,
        "repo_root": REPO_ROOT,
        "scripts_dir": SCRIPTS_DIR,
        "compose_file": COMPOSE_FILE,
        "env_file": ENV_FILE,
        "dbctl": DBCTL,
        "results_file": RESULTS_FILE,
        "has_usecase_sh": os.path.exists(USECASE),
    }

# ----------------------------- Transport helpers ------------------------------

def apply_transport_mode(mode: str):
    mode = mode.strip().lower()
    if mode not in ALLOWED_TRANSPORT_MODES:
        raise HTTPException(status_code=400, detail=f"transport must be one of {sorted(ALLOWED_TRANSPORT_MODES)}")
    if mode == "auto":
        return {"mode": "auto", "applied": False}

    ensure_exists(TRANSPORT, "transport.sh")
    r = run_cmd(["sudo", "-n", TRANSPORT, "nat", "on" if mode == "on" else "off"], timeout_s=60, cwd=REPO_ROOT)
    if not r.ok:
        raise HTTPException(status_code=500, detail={
            "hint": "transport nat requires passwordless sudo for scripts/transport.sh",
            "stdout": r.stdout, "stderr": r.stderr, "code": r.code
        })
    return {"mode": mode, "applied": True, "stdout": r.stdout}

# ----------------------------- KPI builder ------------------------------------

def compute_kpis_for_usecases(usecases: List[str], stdout: str, stderr: str) -> Dict[str, Any]:
    text = stdout + "\n" + stderr
    kpis: Dict[str, Any] = {}

    for u in usecases:
        ue = USECASE_MAP[u]["ue"]
        kpis.setdefault(u, {})["pdu_ip"] = ue_pdu_ip(ue)

    if "urllc" in usecases:
        kpis.setdefault("urllc", {}).update(parse_ping_loss_and_rtt(text))

    if "mmtc" in usecases:
        ok_rate = parse_mmtc_ping_ok_rate(text)
        if ok_rate is not None:
            kpis.setdefault("mmtc", {})["ping_ok_rate_pct"] = round(ok_rate, 2)
        cid = compose_container_id("ue3")
        if cid:
            rc = container_restart_count(cid)
            if rc is not None:
                kpis.setdefault("mmtc", {})["restart_count"] = rc

    if "embb" in usecases:
        thr = parse_embb_throughput_mbps(text)
        if thr is not None:
            kpis.setdefault("embb", {})["throughput_mbps"] = round(thr, 2)

    return kpis

# ----------------------------- Use-case endpoints -----------------------------

@app.post("/api/usecases/activate")
def usecases_activate(req: UsecaseActivateReq):
    usecases = validate_usecases(req.usecases)
    ensure_exists(USECASE, "usecase.sh")

    transport_info = apply_transport_mode(req.transport)

    env = framework_env()
    env.update({
        "PING_TARGET": req.target,
        "URLLC_COUNT": str(req.urllc.count),
        "URLLC_INTERVAL": str(req.urllc.interval),
        "MMTC_COUNT": str(req.mmtc.count),
        "MMTC_INTERVAL": str(req.mmtc.interval),
        "EMBB_IPERF_SERVER": (req.embb.iperfServer or ""),
        "EMBB_DURATION": str(req.embb.duration),
    })

    r = run_cmd([USECASE, "activate", *usecases], timeout_s=600, env=env, cwd=REPO_ROOT)

    profile_info = build_profile_info(usecases)
    abstraction = build_abstraction(usecases)
    kpis = compute_kpis_for_usecases(usecases, r.stdout, r.stderr)
    summary = {"passed": bool(r.ok), "profile": usecases, "kpis": kpis}

    record = {
        "ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "action": "activate",
        "usecases": usecases,
        "transport": req.transport,
        "ok": r.ok,
        "code": r.code,
        "summary": summary,
        "profile_info": profile_info,
        "abstraction": abstraction,
    }
    append_run(record)

    return {
        "status": "running" if r.ok else "error",
        "profile": usecases,
        "transport": transport_info,
        "ok": r.ok,
        "code": r.code,
        "stdout": r.stdout,
        "stderr": r.stderr,
        "summary": summary,
        "profile_info": profile_info,
        "abstraction": abstraction,
    }

@app.post("/api/usecases/verify")
def usecases_verify(req: UsecaseVerifyReq):
    usecases = validate_usecases(req.usecases)
    ensure_exists(USECASE, "usecase.sh")

    env = framework_env()
    env.update({
        "PING_TARGET": req.target,
        "URLLC_COUNT": str(req.urllc.count),
        "URLLC_INTERVAL": str(req.urllc.interval),
        "MMTC_COUNT": str(req.mmtc.count),
        "MMTC_INTERVAL": str(req.mmtc.interval),
        "EMBB_IPERF_SERVER": (req.embb.iperfServer or ""),
        "EMBB_DURATION": str(req.embb.duration),
    })

    r = run_cmd([USECASE, "verify", *usecases], timeout_s=600, env=env, cwd=REPO_ROOT)

    profile_info = build_profile_info(usecases)
    abstraction = build_abstraction(usecases)
    kpis = compute_kpis_for_usecases(usecases, r.stdout, r.stderr)
    summary = {"passed": bool(r.ok), "profile": usecases, "kpis": kpis}

    record = {
        "ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "action": "verify",
        "usecases": usecases,
        "ok": r.ok,
        "code": r.code,
        "summary": summary,
        "profile_info": profile_info,
        "abstraction": abstraction,
    }
    append_run(record)

    return {
        "result": "PASS" if r.ok else "FAIL",
        "ok": r.ok,
        "code": r.code,
        "stdout": r.stdout,
        "stderr": r.stderr,
        "summary": summary,
        "profile_info": profile_info,
        "abstraction": abstraction,
    }

@app.get("/api/usecases/history")
def usecases_history(limit: int = Query(50, ge=1, le=200)):
    return {"ok": True, "items": read_runs(limit=limit)}

# ----------------------------- Deployment endpoints ---------------------------

@app.post("/api/deployment/start")
def deployment_start():
    ensure_exists(FRAMEWORK, "framework.sh")
    r = run_cmd([FRAMEWORK, "start"], timeout_s=300, env=framework_env(), cwd=REPO_ROOT)
    if not r.ok:
        raise HTTPException(status_code=500, detail={"stderr": r.stderr, "stdout": r.stdout})
    return {"ok": True, "stdout": r.stdout}

@app.post("/api/deployment/stop")
def deployment_stop():
    ensure_exists(FRAMEWORK, "framework.sh")
    r = run_cmd([FRAMEWORK, "stop"], timeout_s=300, env=framework_env(), cwd=REPO_ROOT)
    if not r.ok:
        raise HTTPException(status_code=500, detail={"stderr": r.stderr, "stdout": r.stdout})
    return {"ok": True, "stdout": r.stdout}

@app.get("/api/deployment/status")
def deployment_status():
    ensure_exists(FRAMEWORK, "framework.sh")
    r = run_cmd([FRAMEWORK, "status"], timeout_s=120, env=framework_env(), cwd=REPO_ROOT)
    return {"ok": r.ok, "code": r.code, "stdout": r.stdout, "stderr": r.stderr}

@app.post("/api/deployment/restart")
def deployment_restart(req: RestartReq):
    svc = req.service.strip()
    if svc != "all" and svc not in ALLOWED_SERVICES:
        raise HTTPException(status_code=400, detail=f"Service not allowed: {svc}")
    ensure_exists(FRAMEWORK, "framework.sh")
    r = run_cmd([FRAMEWORK, "restart", svc], timeout_s=300, env=framework_env(), cwd=REPO_ROOT)
    if not r.ok:
        raise HTTPException(status_code=500, detail={"stderr": r.stderr, "stdout": r.stdout})
    return {"ok": True, "stdout": r.stdout}

# ----------------------------- Logs endpoint ----------------------------------

@app.get("/api/logs/{service}")
def logs(service: str, follow: int = Query(0), tail: int = Query(200, ge=1, le=2000)):
    service = service.strip()
    if service not in ALLOWED_SERVICES:
        raise HTTPException(status_code=400, detail=f"Service not allowed: {service}")

    cmd_base = docker_compose_base() + ["logs", "--tail", str(tail)]
    if follow == 1:
        cmd = cmd_base + ["-f", service]

        def gen() -> Generator[bytes, None, None]:
            p = subprocess.Popen(
                cmd,
                cwd=REPO_ROOT,
                env=os.environ.copy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            try:
                assert p.stdout is not None
                for line in p.stdout:
                    yield strip_ansi(line).encode("utf-8", errors="ignore")
            finally:
                p.terminate()

        return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")

    r = run_cmd(cmd_base + [service], timeout_s=60, cwd=REPO_ROOT)
    return {"ok": r.ok, "stdout": r.stdout, "stderr": r.stderr, "code": r.code}

# ----------------------------- Legacy endpoints (keep) ------------------------

@app.post("/api/subscribers/provision")
def subscribers_provision(req: ProvisionReq):
    target = req.target.strip()
    if target not in ALLOWED_PROVISION_TARGETS:
        raise HTTPException(status_code=400, detail=f"Target not allowed: {target}")
    ensure_exists(FRAMEWORK, "framework.sh")
    r = run_cmd([FRAMEWORK, "provision", target], timeout_s=180, env=framework_env(), cwd=REPO_ROOT)
    if not r.ok:
        raise HTTPException(status_code=500, detail={"stderr": r.stderr, "stdout": r.stdout})
    return {"ok": True, "stdout": r.stdout}

@app.post("/api/verify")
def legacy_verify(req: VerifyReq):
    target = req.target.strip()
    if target not in ALLOWED_VERIFY_TARGETS:
        raise HTTPException(status_code=400, detail=f"Target not allowed: {target}")
    ensure_exists(FRAMEWORK, "framework.sh")

    cmd = [FRAMEWORK, "verify", target]
    if req.ping:
        cmd += ["--ping", "--target", req.target_ip]

    r = run_cmd(cmd, timeout_s=300, env=framework_env(), cwd=REPO_ROOT)
    if not r.ok:
        return JSONResponse(status_code=200, content={
            "ok": False,
            "code": r.code,
            "stdout": r.stdout,
            "stderr": r.stderr,
            "summary": parse_verify_output(r.stdout + "\n" + r.stderr),
        })
    return {"ok": True, "stdout": r.stdout, "summary": parse_verify_output(r.stdout)}

# ----------------------------- Topology (table-ready) -------------------------

@app.get("/api/topology")
def topology():
    rows = build_topology_rows()
    return {"ok": True, "rows": rows}

# ----------------------------- Transport endpoints ----------------------------

@app.get("/api/transport/status")
def transport_status():
    ensure_exists(TRANSPORT, "transport.sh")
    r = run_cmd([TRANSPORT, "status"], timeout_s=30, cwd=REPO_ROOT)
    return {"ok": r.ok, "stdout": r.stdout, "stderr": r.stderr, "code": r.code}

@app.post("/api/transport/nat")
def transport_nat(req: TransportNatReq):
    state = req.state.strip().lower()
    if state not in ALLOWED_TRANSPORT_ACTIONS:
        raise HTTPException(status_code=400, detail=f"State must be on|off, got: {state}")
    ensure_exists(TRANSPORT, "transport.sh")

    r = run_cmd(["sudo", "-n", TRANSPORT, "nat", state], timeout_s=60, cwd=REPO_ROOT)
    if not r.ok:
        raise HTTPException(status_code=500, detail={
            "hint": "transport nat requires passwordless sudo. See backend/README.md",
            "stdout": r.stdout, "stderr": r.stderr, "code": r.code,
        })
    return {"ok": True, "stdout": r.stdout}
