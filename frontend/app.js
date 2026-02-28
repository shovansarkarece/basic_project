(function(){
  const $ = (id) => document.getElementById(id);

  // Persist API base
  const apiInput = $("apiBase");
  if (apiInput) {
    apiInput.value = localStorage.getItem("apiBase") || apiInput.value;
    $("btnSaveApi")?.addEventListener("click", () => {
      localStorage.setItem("apiBase", apiInput.value.trim());
    });
  }

  function apiBase(){
    const v = (localStorage.getItem("apiBase") || apiInput?.value || "http://localhost:8000");
    return v.replace(/\/+$/, "");
  }

  async function call(path, opts={}){
    const url = apiBase() + path;
    const res = await fetch(url, { headers: {"Content-Type":"application/json"}, ...opts });
    const txt = await res.text();
    try { return {ok: res.ok, status: res.status, data: JSON.parse(txt)}; }
    catch { return {ok: res.ok, status: res.status, data: {raw: txt}}; }
  }

  function showPre(el, obj){
    if (!el) return;
    el.textContent = (typeof obj === "string") ? obj : JSON.stringify(obj, null, 2);
  }

  function escapeHtml(s){
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // Tabs
  const navs = document.querySelectorAll(".nav");
  const tabs = {
    usecases: $("tab-usecases"),
    topology: $("tab-topology"),
    transport: $("tab-transport"),
    control: $("tab-control"),
    logs: $("tab-logs"),
  };

  // ✅ only declared ONCE
  let logStreamAbort = null;

  function setTab(name){
    navs.forEach(b => b.classList.toggle("active", b.dataset.tab === name));
    Object.entries(tabs).forEach(([k, el]) => {
      if (!el) return;
      el.classList.toggle("hidden", k !== name);
    });

    // Stop log stream if leaving Logs tab
    if (name !== "logs" && logStreamAbort){
      logStreamAbort.abort();
      logStreamAbort = null;
    }
  }
  navs.forEach(b => b.addEventListener("click", () => setTab(b.dataset.tab)));
  setTab("usecases");

  // Use case selection
  function selectedUsecases(){
    const u = [];
    if ($("uc-embb")?.checked) u.push("embb");
    if ($("uc-urllc")?.checked) u.push("urllc");
    if ($("uc-mmtc")?.checked) u.push("mmtc");
    return u;
  }

  function buildPayload(usecases){
    const transport = $("transportMode")?.value || "auto";
    const target = ($("pingTarget")?.value || "").trim() || "8.8.8.8";

    const urllc = {
      count: parseInt($("urllcCount")?.value || "50", 10),
      interval: parseFloat($("urllcInterval")?.value || "0.2"),
    };
    const mmtc = {
      count: parseInt($("mmtcCount")?.value || "10", 10),
      interval: parseInt($("mmtcInterval")?.value || "2", 10),
    };
    const embb = {
      iperfServer: ($("embbIperfServer")?.value || "").trim() || null,
      duration: parseInt($("embbDuration")?.value || "10", 10),
    };

    return { usecases, transport, target, urllc, mmtc, embb };
  }

  // KPI cards
  function kpiCard(title, value){
    const div = document.createElement("div");
    div.className = "kpi";
    div.innerHTML = `<div class="k">${escapeHtml(title)}</div><div class="v">${escapeHtml(value)}</div>`;
    return div;
  }

  function renderKpis(summary){
    const host = $("ucKpis");
    if (!host) return;
    host.innerHTML = "";

    const passed = summary?.passed;
    host.appendChild(kpiCard("Overall", passed === true ? "PASS" : (passed === false ? "FAIL" : "—")));

    const kpis = summary?.kpis || {};
    const u = summary?.profile || [];

    if (u.includes("embb")){
      host.appendChild(kpiCard("eMBB PDU IP", kpis?.embb?.pdu_ip || "—"));
      host.appendChild(kpiCard("eMBB Throughput (Mbps)", (kpis?.embb?.throughput_mbps ?? "—")));
    }
    if (u.includes("urllc")){
      host.appendChild(kpiCard("URLLC PDU IP", kpis?.urllc?.pdu_ip || "—"));
      host.appendChild(kpiCard("URLLC Avg RTT (ms)", (kpis?.urllc?.avg_rtt_ms ?? "—")));
      host.appendChild(kpiCard("URLLC Loss (%)", (kpis?.urllc?.loss_pct ?? "—")));
    }
    if (u.includes("mmtc")){
      host.appendChild(kpiCard("mMTC PDU IP", kpis?.mmtc?.pdu_ip || "—"));
      host.appendChild(kpiCard("mMTC Ping OK rate (%)", (kpis?.mmtc?.ping_ok_rate_pct ?? "—")));
      host.appendChild(kpiCard("mMTC Restart count", (kpis?.mmtc?.restart_count ?? "—")));
    }
  }

  // Active slice profile
  function renderProfile(profileInfo){
    const body = $("profileBody");
    if (!body) return;

    if (!profileInfo?.slices?.length){
      body.innerHTML = `<div class="muted">No profile yet.</div>`;
      return;
    }

    body.innerHTML = "";
    profileInfo.slices.forEach(s => {
      const div = document.createElement("div");
      div.className = "profile-row";
      div.innerHTML = `
        <div class="profile-title">${escapeHtml(s.label)}</div>
        <div class="profile-meta">
          Slice <b>${escapeHtml(s.slice)}</b> • ${escapeHtml(s.ue)} • ${escapeHtml(s.smf)} → ${escapeHtml(s.upf)} • Pool ${escapeHtml(s.pool)}
        </div>
      `;
      body.appendChild(div);
    });
  }

  // Dynamic node-chain diagram
  function makeNode(text){
    const span = document.createElement("span");
    span.className = "node";
    span.textContent = text;
    return span;
  }
  function makeArrow(){
    const span = document.createElement("span");
    span.className = "arrow";
    span.textContent = "→";
    return span;
  }

  function renderFlows(abstraction){
    const host = $("flows");
    if (!host) return;
    host.innerHTML = "";

    if (!abstraction?.mapping?.length){
      host.innerHTML = `<div class="muted small">No flow yet. Activate a use case to see the NF path.</div>`;
      return;
    }

    abstraction.mapping.forEach(m => {
      const box = document.createElement("div");
      box.className = "flow-row";

      const header = document.createElement("div");
      header.className = "flow-label";
      header.innerHTML = `<b>${escapeHtml(m.label)}</b> <span class="muted small">• Slice ${escapeHtml(m.slice)}</span>`;
      box.appendChild(header);

      const chain = document.createElement("div");
      chain.className = "chain";

      (m.nf_path || []).forEach((n, i) => {
        chain.appendChild(makeNode(n));
        if (i < m.nf_path.length - 1) chain.appendChild(makeArrow());
      });

      box.appendChild(chain);
      host.appendChild(box);
    });
  }

  async function runActivate(usecases){
    const out = $("ucOut");
    if (out) out.textContent = "Activating...";
    const payload = buildPayload(usecases);
    const r = await call("/api/usecases/activate", {method:"POST", body: JSON.stringify(payload)});
    showPre(out, r.data.stdout || r.data);
    if (r.data.summary) renderKpis(r.data.summary);
    if (r.data.profile_info) renderProfile(r.data.profile_info);
    if (r.data.abstraction) renderFlows(r.data.abstraction);
  }

  async function runVerify(usecases){
    const out = $("ucOut");
    if (out) out.textContent = "Verifying...";
    const payload = buildPayload(usecases);
    delete payload.transport;
    const r = await call("/api/usecases/verify", {method:"POST", body: JSON.stringify(payload)});
    showPre(out, r.data.stdout || r.data);
    if (r.data.summary) renderKpis(r.data.summary);
    if (r.data.profile_info) renderProfile(r.data.profile_info);
    if (r.data.abstraction) renderFlows(r.data.abstraction);
  }

  $("btnActivateUC")?.addEventListener("click", async () => {
    const u = selectedUsecases();
    if (!u.length) return;
    await runActivate(u);
  });

  $("btnVerifyUC")?.addEventListener("click", async () => {
    const u = selectedUsecases();
    if (!u.length) return;
    await runVerify(u);
  });

  $("btnVerifyAllUC")?.addEventListener("click", async () => {
    await runVerify(["embb","urllc","mmtc"]);
  });

  $("btnStopNetwork")?.addEventListener("click", async () => {
    const out = $("ucOut");
    if (out) out.textContent = "Stopping network...";
    const r = await call("/api/deployment/stop", {method:"POST", body:"{}"});
    showPre(out, r.data.stdout || r.data);
  });

  // History
  function renderHistory(items){
    const host = $("historyList");
    if (!host) return;
    host.innerHTML = "";
    (items || []).slice().reverse().forEach(it => {
      const div = document.createElement("div");
      div.className = "hist";
      const ok = it.ok === true ? "PASS" : "FAIL";
      div.innerHTML = `
        <div class="hist-top">
          <div class="hist-ts">${escapeHtml(it.ts || "")}</div>
          <div class="hist-badge ${ok === "PASS" ? "pass" : "fail"}">${ok}</div>
        </div>
        <div class="hist-mid">${escapeHtml((it.action || "").toUpperCase())} • ${escapeHtml((it.usecases || []).join(" + "))}</div>
        <details class="details">
          <summary>summary</summary>
          <pre class="pre small">${escapeHtml(JSON.stringify(it.summary || {}, null, 2))}</pre>
        </details>
      `;
      host.appendChild(div);
    });
  }

  $("btnLoadHistory")?.addEventListener("click", async () => {
    const r = await call("/api/usecases/history?limit=20");
    if (!r.ok) return;
    renderHistory(r.data.items);
  });

  // Network View
  function statusBadge(s){
    const cls = (s === "running") ? "st-run" : (s === "not_created" ? "st-off" : "st-mid");
    return `<span class="st ${cls}">${escapeHtml(s)}</span>`;
  }

  function renderTopology(rows){
    const body = $("topologyBody");
    if (!body) return;
    body.innerHTML = "";
    const filter = $("topoFilter")?.value || "all";

    (rows || []).forEach(r => {
      if (filter !== "all" && r.type !== filter) return;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(r.type)}</td>
        <td>${escapeHtml(r.component)}</td>
        <td>${statusBadge(r.status)}</td>
        <td class="mono">${escapeHtml(r.open5gs_ip || "-")}</td>
        <td class="mono">${escapeHtml(r.pdu_session_ip || "-")}</td>
      `;
      body.appendChild(tr);
    });
  }

  async function loadTopology(){
    const raw = $("topologyRaw");
    if (raw) raw.textContent = "Loading...";
    const r = await call("/api/topology");
    showPre(raw, r.data);
    if (r.ok && r.data.rows) renderTopology(r.data.rows);
  }

  $("btnTopology")?.addEventListener("click", loadTopology);
  $("topoFilter")?.addEventListener("change", loadTopology);

  // Control
  $("btnRestart")?.addEventListener("click", async () => {
    const out = $("restartOut");
    if (out) out.textContent = "Restarting...";
    const service = $("restartService")?.value || "all";
    const r = await call("/api/deployment/restart", {method:"POST", body: JSON.stringify({service})});
    showPre(out, r.data.stdout || r.data);
  });

  $("btnStart")?.addEventListener("click", async () => {
    const out = $("deploymentStatus");
    if (out) out.textContent = "Starting...";
    const r = await call("/api/deployment/start", {method:"POST", body:"{}"});
    showPre(out, r.data.stdout || r.data);
  });

  $("btnStop")?.addEventListener("click", async () => {
    const out = $("deploymentStatus");
    if (out) out.textContent = "Stopping...";
    const r = await call("/api/deployment/stop", {method:"POST", body:"{}"});
    showPre(out, r.data.stdout || r.data);
  });

  $("btnStatus")?.addEventListener("click", async () => {
    const out = $("deploymentStatus");
    if (out) out.textContent = "Loading...";
    const r = await call("/api/deployment/status");
    showPre(out, r.data.stdout || r.data);
  });

  // Transport
  $("btnNatOn")?.addEventListener("click", async () => {
    const out = $("transportOut");
    if (out) out.textContent = "Enabling NAT...";
    const r = await call("/api/transport/nat", {method:"POST", body: JSON.stringify({state:"on"})});
    showPre(out, r.data.stdout || r.data);
  });

  $("btnNatOff")?.addEventListener("click", async () => {
    const out = $("transportOut");
    if (out) out.textContent = "Disabling NAT...";
    const r = await call("/api/transport/nat", {method:"POST", body: JSON.stringify({state:"off"})});
    showPre(out, r.data.stdout || r.data);
  });

  $("btnTransportStatus")?.addEventListener("click", async () => {
    const out = $("transportOut");
    if (out) out.textContent = "Loading...";
    const r = await call("/api/transport/status");
    showPre(out, r.data.stdout || r.data);
  });

  // Logs (stream)
  $("btnLogs")?.addEventListener("click", async () => {
    const service = $("logService")?.value || "amf";
    const follow = $("logFollow")?.checked || false;
    const out = $("logsOut");
    if (!out) return;

    out.textContent = follow ? "Streaming logs...\n" : "Loading logs...";

    if (logStreamAbort){ logStreamAbort.abort(); logStreamAbort = null; }

    if (!follow){
      const r = await call(`/api/logs/${service}?follow=0&tail=200`);
      showPre(out, r.data.stdout || r.data);
      return;
    }

    const controller = new AbortController();
    logStreamAbort = controller;

    const url = apiBase() + `/api/logs/${service}?follow=1&tail=50`;
    const res = await fetch(url, {signal: controller.signal});
    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    out.textContent = "";

    try{
      while(true){
        const {value, done} = await reader.read();
        if (done) break;
        out.textContent += decoder.decode(value, {stream:true});
        out.scrollTop = out.scrollHeight;
      }
    }catch(e){
      // abort is normal
    }
  });

})();
