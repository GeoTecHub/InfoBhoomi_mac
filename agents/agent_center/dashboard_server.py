from __future__ import annotations

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import (
    AGENT_AI_PROVIDER,
    AGENT_DASHBOARD_HOST,
    AGENT_DASHBOARD_PORT,
    AGENT_DASHBOARD_TOKEN_FILE,
    AGENT_DEFAULT_LLM,
    AGENT_ENVIRONMENT,
    BASE_URL,
    GEMINI_MODEL,
    STATE_DIR,
)
from agent_center.architect_agent import ArchitectAgent, ArchitectOutput
from agent_center.ai_provider.router import list_provider_status
from agent_center.db_verification_agent import DBVerificationAgent
from agent_center.debug_router_agent import DebugRouterAgent
from agent_center.fix_proposal_agent import FixProposalAgent
from agent_center.function_qa_agent import FunctionQAAgent
from agent_center.function_registry import all_functions, categories, functions_by_category, get_function
from agent_center.issue_queue import IssueQueue
from agent_center.reporter_agent import ReporterAgent
from agent_center.applier import Applier
from agent_center.change_memory import ChangeMemory
from agent_center.cost_ledger import CostLedger
from agent_center.implementers import DBMigrationImplementer
from agent_center.implementers.db_migration import MigrationApplyResult
from agent_center.verification_qa_agent import VerificationQAAgent
from agent_center.verify_runner import VerifyRunner
from agent_center.solution_architect_agent import SolutionArchitectAgent, SolutionItem, merge_user_edits
from agent_center.solution_plan_store import SolutionPlanStore
from agent_center.structured_memory import StructuredMemory


# â”€â”€ Auth token â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_DASHBOARD_TOKEN: str = ""

# In-memory cache of the last ArchitectOutput per queue_id, so the Reporter
# step doesn't have to re-run all Investigators when the user picks a model.
_LAST_INVESTIGATION: dict[str, ArchitectOutput] = {}
# queue_id â†’ list[StagedFile] (most recent stage batch awaiting commit)
_LAST_STAGE: dict[str, list] = {}


def _generate_dashboard_token() -> str:
    global _DASHBOARD_TOKEN
    _DASHBOARD_TOKEN = secrets.token_urlsafe(32)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    AGENT_DASHBOARD_TOKEN_FILE.write_text(_DASHBOARD_TOKEN, encoding="utf-8")
    return _DASHBOARD_TOKEN


def _get_dashboard_token() -> str:
    return _DASHBOARD_TOKEN


# â”€â”€ HTML â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>InfoBhoomi Agent QA &amp; Debug Control Center</title>
  <style>
    :root{font-family:Inter,Segoe UI,Arial,sans-serif;color:#172033;background:#f5f7fb}
    body{margin:0}
    .top{background:#111827;color:#fff;padding:14px 22px;display:flex;justify-content:space-between;align-items:center}
    .top h1{font-size:17px;margin:0}
    .tabs{background:#1f2937;color:#fff;padding:0 22px;display:flex;gap:4px}
    .tab{padding:10px 14px;background:transparent;color:#cbd5e1;border:none;cursor:pointer;border-bottom:3px solid transparent}
    .tab.active{color:#fff;border-bottom:3px solid #3b82f6;background:#111827}
    .wrap{padding:18px;display:grid;grid-template-columns:280px 1fr;gap:18px;min-height:calc(100vh - 110px)}
    .wrap.single{grid-template-columns:1fr}
    nav{background:#fff;border:1px solid #d9e0ea;border-radius:8px;padding:14px;height:fit-content}
    main{display:flex;flex-direction:column;gap:14px}
    .btn{border:1px solid #b8c2d4;background:#fff;border-radius:6px;padding:8px 12px;cursor:pointer;font:inherit}
    .btn.primary{background:#1f6feb;color:#fff;border-color:#1f6feb}
    .btn.danger{background:#b42318;color:#fff;border-color:#b42318}
    .btn:disabled{opacity:.55;cursor:not-allowed}
    .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
    .card{background:#fff;border:1px solid #d9e0ea;border-radius:8px;padding:14px}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
    .fn{border:1px solid #d9e0ea;border-radius:8px;padding:12px;background:#fff}.fn h3{margin:0 0 6px;font-size:15px}
    .muted{color:#667085;font-size:13px}
    .pill{display:inline-block;border-radius:999px;background:#eef2ff;color:#1e3a8a;padding:2px 8px;font-size:12px}
    .pill.ok{background:#dcfce7;color:#15803d}
    .pill.warning{background:#fef3c7;color:#92400e}
    .pill.error{background:#fee2e2;color:#991b1b}
    textarea,input,select{font:inherit;border:1px solid #b8c2d4;border-radius:6px;padding:8px;background:#fff}
    textarea{width:100%;min-height:90px;box-sizing:border-box}
    pre{white-space:pre-wrap;background:#0b1020;color:#d8e2ff;padding:12px;border-radius:8px;overflow:auto;font-size:12.5px}
    table{border-collapse:collapse;width:100%;background:#fff}th,td{border-bottom:1px solid #e4e9f2;text-align:left;padding:8px;font-size:13px}th{color:#475467;background:#f8fafc}
    .hidden{display:none!important}
    .side-title{font-size:12px;text-transform:uppercase;color:#667085;margin:14px 0 6px}
    .cat{display:block;width:100%;text-align:left;margin:4px 0}
    .lock{max-width:480px;margin:80px auto;padding:24px;background:#fff;border:1px solid #d9e0ea;border-radius:10px}
    .lock h2{margin:0 0 8px}.lock .muted{margin-bottom:16px}.lock input{width:100%;box-sizing:border-box;margin:8px 0}
    .err{color:#b42318;font-size:13px;margin-top:8px}
    .modal{position:fixed;inset:0;background:rgba(15,23,42,.55);display:flex;align-items:center;justify-content:center;z-index:50}
    .modal-card{background:#fff;border-radius:10px;padding:20px;max-width:420px;width:90%}
    .modal-card h3{margin:0 0 8px}.modal-card .row{margin-top:14px;justify-content:flex-end}
    .layer-card{border-left:4px solid #94a3b8;padding:10px 12px;background:#fff;border-radius:6px;border:1px solid #d9e0ea}
    .layer-card.ok{border-left-color:#22c55e}
    .layer-card.warning{border-left-color:#f59e0b}
    .layer-card.error{border-left-color:#ef4444}
    .layer-card h4{margin:0;font-size:14px;display:flex;align-items:center;gap:8px}
    .layer-card ul{margin:8px 0 0 18px;padding:0}
    .layer-card li{font-size:13px;margin:2px 0}
    .queue-row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #f1f5f9}
    .queue-row:last-child{border-bottom:none}
    .step-badge{display:inline-block;background:#eef2ff;color:#1e3a8a;border-radius:4px;padding:1px 6px;font-size:11px;margin-left:6px}
    code{background:#f1f5f9;padding:1px 6px;border-radius:4px;font-size:12px}
  </style>
</head>
<body>
  <div id="lockScreen" class="hidden">
    <div class="lock">
      <h2>Agent Dashboard Login</h2>
      <p class="muted">Paste the token printed by <code>run_agent_dashboard.py</code>.
        Also saved at <code>.agent_state/dashboard_token.txt</code>.</p>
      <input id="tokenInput" type="password" placeholder="X-Agent-Token" autofocus onkeydown="if(event.key==='Enter') saveToken()">
      <button class="btn primary" onclick="saveToken()">Unlock</button>
      <div id="lockErr" class="err"></div>
    </div>
  </div>

  <div id="appShell" class="hidden">
    <div class="top">
      <h1>InfoBhoomi Agent QA &amp; Debug Control Center</h1>
      <div class="row"><span id="env" class="muted"></span><button class="btn" onclick="logout()">Lock</button></div>
    </div>
    <div class="tabs">
      <button class="tab" data-tab="investigate" onclick="setTab('investigate')">Investigate</button>
      <button class="tab" data-tab="history" onclick="setTab('history')">History</button>
      <button class="tab" data-tab="functions" onclick="setTab('functions')">Function QA</button>
      <button class="tab" data-tab="memory" onclick="setTab('memory')">Issue Memory</button>
    </div>

    <!-- INVESTIGATE TAB -->
    <div id="tab-investigate" class="wrap single tabpane">
      <main>
        <section class="card">
          <h2 style="margin:0 0 6px">Submit an issue</h2>
          <p class="muted">Sequential queue. New submissions wait until the current one finishes.</p>
          <textarea id="invPrompt" placeholder="Describe the bug. Example: RRR owner is not showing for a saved parcel"></textarea>
          <div class="row" style="margin-top:8px">
            <button class="btn primary" onclick="submitIssue()">Submit</button>
            <button class="btn" onclick="refreshQueue()">Refresh queue</button>
            <span id="qStatus" class="muted"></span>
          </div>
          <div id="queueView" style="margin-top:14px"></div>
        </section>

        <section class="card hidden" id="invRunCard">
          <h2 style="margin:0 0 6px">Investigation result</h2>
          <div id="invSummary"></div>
          <div id="invLayers" class="grid" style="margin-top:10px;grid-template-columns:1fr 1fr 1fr"></div>
          <div class="row" style="margin-top:14px">
            <button class="btn primary" onclick="openReporterPicker()">Generate plain-language report</button>
          </div>
        </section>

        <section class="card hidden" id="invReportCard">
          <h2 style="margin:0 0 6px">Plain-language report</h2>
          <div id="invReport"></div>
          <div class="row" style="margin-top:12px">
            <button class="btn primary" onclick="openSolutionPicker()">Resolve this issue</button>
          </div>
        </section>

        <section class="card hidden" id="solveCard">
          <h2 style="margin:0 0 6px">Solution plan</h2>
          <div id="solveMeta" class="muted"></div>
          <div id="solveItems" style="margin-top:10px"></div>
          <div class="row" style="margin-top:14px">
            <button class="btn primary" onclick="saveAmendedPlan()">Save my edits</button>
            <button class="btn" onclick="reloadSolution()">Discard edits and reload</button>
            <button class="btn" onclick="openApplyCard()">Continue to Apply</button>
            <span id="solveStatus" class="muted"></span>
          </div>
        </section>

        <section class="card hidden" id="applyCard">
          <h2 style="margin:0 0 6px">Apply</h2>
          <p class="muted">Per-item approval, scope check, staging diff preview, then commit. Backups and ChangeMemory entries are written automatically.</p>
          <div id="applyItems"></div>
          <div class="row" style="margin-top:14px">
            <button class="btn" onclick="previewApply()">Preview</button>
            <button class="btn primary" onclick="stageApply()">Stage approved</button>
            <button class="btn primary" onclick="commitApply()">Commit staged</button>
            <span id="applyStatus" class="muted"></span>
          </div>
          <div id="applyOut"></div>
          <div id="migPanel" class="hidden" style="margin-top:14px">
            <h3>Pending migrations</h3>
            <div id="migList"></div>
          </div>
        </section>

        <section class="card hidden" id="verifyCard">
          <h2 style="margin:0 0 6px">Verify</h2>
          <p class="muted">Per-layer smoke checks: <code>ng build --configuration development</code> for any FE edit, <code>manage.py check</code> + <code>py_compile</code> for BE, DB key-field probe, plus a registry rerun for the routed function ids.</p>
          <div class="row">
            <button class="btn primary" onclick="startVerify()">Run verification</button>
            <button class="btn danger" onclick="cancelVerify()">Cancel</button>
            <button class="btn" onclick="startNextRound()">Run another debugging round</button>
            <span id="verifyStatus" class="muted"></span>
          </div>
          <div id="verifyLayers" class="grid" style="margin-top:10px;grid-template-columns:1fr 1fr 1fr"></div>
          <h3 style="margin:14px 0 6px">Live log</h3>
          <pre id="verifyLog" style="max-height:280px;overflow:auto"></pre>
        </section>
      </main>
    </div>

    <!-- HISTORY TAB (P6) -->
    <div id="tab-history" class="wrap single tabpane hidden">
      <main>
        <section class="card">
          <h2 style="margin:0 0 6px">Change history</h2>
          <p class="muted">Every committed edit lives here. Filter by file, agent, outcome, or queue id; roll back any edit with one click.</p>
          <div class="row">
            <input id="histFile"    placeholder="Filter file path (substring)"        oninput="renderHistory()">
            <input id="histAgent"   placeholder="Filter agent (e.g. FrontendImplementer)" oninput="renderHistory()">
            <select id="histOutcome" onchange="renderHistory()">
              <option value="">Any outcome</option>
              <option value="passed">passed</option>
              <option value="partial">partial</option>
              <option value="failed">failed</option>
              <option value="pending">pending</option>
            </select>
            <input id="histQueue" placeholder="Queue id (run id)" oninput="renderHistory()">
            <button class="btn" onclick="loadHistory()">Refresh</button>
          </div>
          <div id="histTable" style="margin-top:10px"></div>
        </section>
      </main>
    </div>

    <!-- FUNCTION QA TAB (legacy) -->
    <div id="tab-functions" class="wrap tabpane hidden">
      <nav>
        <button class="btn primary" onclick="runAll()">Run All Safe Checks</button>
        <div class="side-title">Categories</div><div id="cats"></div>
        <button class="btn cat" onclick="showAllFunctions()">All Functions</button>
        <button class="btn cat" onclick="showDb()">DB Verification</button>
      </nav>
      <main>
        <section class="card">
          <h2 id="fnTitle">Function Test Dashboard</h2>
          <div class="row">
            <input id="filter" placeholder="Filter functions" oninput="renderFunctions()">
            <button class="btn hidden" id="runShown" onclick="runShownFunctions()">Run Shown</button>
            <span class="muted" id="count"></span>
          </div>
          <div id="functions" class="grid" style="margin-top:12px"></div>
        </section>
        <section class="card hidden" id="dbPanel">
          <h2>DB Verification Agent</h2>
          <div class="row">
            <button class="btn" onclick="dbStatus()">Check DB Setup</button>
            <button class="btn primary" onclick="runDbChecks()">Run DB Checks For Shown Functions</button>
          </div>
          <div id="dbOutput" style="margin-top:10px"></div>
        </section>
        <section class="card">
          <h2>Output</h2>
          <div id="output" class="muted">Ready.</div>
        </section>
      </main>
    </div>

    <!-- MEMORY TAB -->
    <div id="tab-memory" class="wrap single tabpane hidden">
      <main>
        <section class="card">
          <h2>Issue memory + fix proposals</h2>
          <div class="row">
            <button class="btn" onclick="loadMemory()">Refresh issue memory</button>
            <button class="btn" onclick="loadFixes()">Refresh fix proposals</button>
            <button class="btn" onclick="showLatest()">Latest QA report</button>
          </div>
          <div id="memOutput" class="muted" style="margin-top:10px">Click a button above.</div>
        </section>
      </main>
    </div>
  </div>

  <!-- LLM picker modal -->
  <div id="llmModal" class="modal hidden">
    <div class="modal-card">
      <h3>Choose an LLM</h3>
      <p class="muted">Decision #1: pick which model writes the plain-language report.</p>
      <div id="llmChoices"></div>
      <div class="row">
        <button class="btn" onclick="closeLlmModal()">Cancel</button>
        <button class="btn primary" onclick="confirmLlmChoice()">Continue</button>
      </div>
    </div>
  </div>

<script>
let functions=[], routed=[], activeCategory='', shownFunctions=[];
let currentInv=null, currentReport=null, llmChoice=null, llmModalCb=null;

function getToken(){return localStorage.getItem('agentToken')||'';}
function saveToken(){
  const t=document.getElementById('tokenInput').value.trim();
  if(!t){document.getElementById('lockErr').textContent='Token cannot be empty.';return;}
  localStorage.setItem('agentToken', t); bootstrap();
}
function logout(){localStorage.removeItem('agentToken'); showLock();}
function showLock(){document.getElementById('lockScreen').classList.remove('hidden');document.getElementById('appShell').classList.add('hidden');document.getElementById('tokenInput').focus();}
function showApp(){document.getElementById('lockScreen').classList.add('hidden');document.getElementById('appShell').classList.remove('hidden');}

function setTab(name){
  document.querySelectorAll('.tabpane').forEach(el=>el.classList.add('hidden'));
  document.querySelectorAll('.tab').forEach(el=>el.classList.remove('active'));
  document.getElementById('tab-'+name).classList.remove('hidden');
  document.querySelector(`.tab[data-tab="${name}"]`).classList.add('active');
  if(name==='investigate'){refreshQueue();}
}

async function api(path, opts={}) {
  const headers={'Content-Type':'application/json','X-Agent-Token':getToken()};
  const res = await fetch(path, {headers, ...opts});
  if(res.status===401){logout(); throw new Error('Unauthorised â€” token rejected.');}
  const text = await res.text();
  try { return JSON.parse(text); } catch { return {raw:text, ok:res.ok}; }
}
function esc(v){return String(v??'').replace(/[&<>]/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[s]));}
function setOut(data){document.getElementById('output').innerHTML='<pre>'+esc(JSON.stringify(data,null,2))+'</pre>';}
function setMemOut(data){document.getElementById('memOutput').innerHTML='<pre>'+esc(JSON.stringify(data,null,2))+'</pre>';}

async function bootstrap(){
  try {
    const meta=await api('/api/meta');
    document.getElementById('env').textContent='Environment: '+meta.environment+' | API: '+meta.base_url;
    showApp();
    setTab('investigate');
    const data=await api('/api/functions'); functions=data.functions||[];
    document.getElementById('cats').innerHTML=(data.categories||[]).map(c=>`<button class="btn cat" onclick="showCategory('${esc(c)}')">${esc(c)}</button>`).join('');
    renderFunctions();
  } catch(e) {
    document.getElementById('lockErr').textContent=e.message||String(e); showLock();
  }
}

// â”€â”€ Investigate tab â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async function submitIssue(){
  const prompt=document.getElementById('invPrompt').value.trim();
  if(!prompt){return;}
  document.getElementById('qStatus').textContent='Submitting...';
  const enq=await api('/api/queue',{method:'POST',body:JSON.stringify({prompt})});
  document.getElementById('qStatus').textContent='Queued as '+enq.queue_id;
  document.getElementById('invPrompt').value='';
  await refreshQueue();
  if(enq.is_current){await runInvestigation(enq.queue_id);}
}
async function refreshQueue(){
  const state=await api('/api/queue');
  const v=document.getElementById('queueView');
  let html='';
  if(state.current){
    html+=`<div class="queue-row"><div><b>Current:</b> <code>${esc(state.current.queue_id)}</code> â€” ${esc(state.current.prompt)} <span class="step-badge">${esc(state.current.step)}</span></div>
           <button class="btn" onclick="runInvestigation('${esc(state.current.queue_id)}')">Run / refresh</button></div>`;
  } else {
    html+=`<div class="muted">No issue currently in flight.</div>`;
  }
  if(state.pending && state.pending.length){
    html+='<h4 style="margin:8px 0 4px">Pending</h4>';
    for(const p of state.pending){
      html+=`<div class="queue-row"><div><code>${esc(p.queue_id)}</code> ${esc(p.prompt)}</div>
             <button class="btn danger" onclick="cancelPending('${esc(p.queue_id)}')">Cancel</button></div>`;
    }
  }
  v.innerHTML=html;
}
async function cancelPending(qid){await api('/api/queue/'+encodeURIComponent(qid),{method:'DELETE'}); refreshQueue();}

async function runInvestigation(qid){
  document.getElementById('qStatus').textContent='Running investigators (this may take a few seconds)...';
  document.getElementById('invRunCard').classList.add('hidden');
  document.getElementById('invReportCard').classList.add('hidden');
  const out=await api('/api/investigate/run',{method:'POST',body:JSON.stringify({queue_id:qid})});
  document.getElementById('qStatus').textContent='Investigation complete in '+out.elapsed_ms+' ms';
  currentInv=out;
  renderInvestigation(out);
}
function renderInvestigation(out){
  document.getElementById('invRunCard').classList.remove('hidden');
  const s=out.summary;
  const routes=(out.plan.routes||[]).map(r=>`${esc(r.display_name)} <span class="muted">(${esc(r.category)})</span>`).join(', ');
  document.getElementById('invSummary').innerHTML=`
    <div><b>Routed function(s):</b> ${routes||'<i>none</i>'}</div>
    <div class="muted" style="margin-top:4px">Issue id: <code>${esc(out.issue.issue_id)}</code></div>`;
  const layers=[
    ['Frontend', out.fe], ['Backend', out.be], ['Database', out.db],
  ];
  document.getElementById('invLayers').innerHTML=layers.map(([label, r])=>{
    const items=r.findings.filter(f=>f.severity==='warning'||f.severity==='error').slice(0,5)
      .map(f=>`<li>[${esc(f.severity.toUpperCase())}] ${esc(f.title)} <span class="muted">${esc(f.affected_subcomponent||'')}</span></li>`).join('');
    return `<div class="layer-card ${esc(r.status)}">
      <h4>${label} <span class="pill ${esc(r.status)}">${esc(r.status)}</span> <span class="muted">(${r.findings.length} findings, ${r.elapsed_ms}ms)</span></h4>
      <ul>${items||'<li class="muted">No warnings or errors</li>'}</ul></div>`;
  }).join('');
}

// â”€â”€ LLM picker for the Reporter â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async function openReporterPicker(){
  const status=await api('/api/llm/status');
  llmChoice=status.default || 'gemini';
  document.getElementById('llmChoices').innerHTML=status.providers.map(p=>`
    <label style="display:block;padding:6px 0;${p.available?'':'opacity:.55'}">
      <input type="radio" name="llmPick" value="${esc(p.name)}" ${p.name===llmChoice?'checked':''} ${p.available?'':'disabled'}>
      <b>${esc(p.name)}</b> <span class="muted">(${esc(p.model)}) ${p.available?'':'â€” no API key configured'}</span>
    </label>`).join('');
  llmModalCb=runReporter;
  document.getElementById('llmModal').classList.remove('hidden');
}
function closeLlmModal(){document.getElementById('llmModal').classList.add('hidden'); llmModalCb=null;}
function confirmLlmChoice(){
  const sel=document.querySelector('input[name="llmPick"]:checked');
  llmChoice=sel?sel.value:llmChoice;
  document.getElementById('llmModal').classList.add('hidden');
  if(llmModalCb){const cb=llmModalCb; llmModalCb=null; cb();}
}
async function runReporter(){
  if(!currentInv){return;}
  document.getElementById('qStatus').textContent='Calling '+llmChoice+'...';
  const data=await api('/api/report',{method:'POST',body:JSON.stringify({queue_id:currentInv.plan.queue_id, llm:llmChoice})});
  document.getElementById('qStatus').textContent='Report ready';
  currentReport=data;
  renderReport(data);
}
function renderReport(rep){
  document.getElementById('invReportCard').classList.remove('hidden');
  const banner = rep.fallback ? `<div class="pill warning">Fallback (no LLM): ${esc(rep.fallback_reason||'')}</div>` :
                                `<div class="pill ok">Generated by ${esc(rep.llm_used)} (${esc(rep.llm_model||'')})</div>`;
  // Render markdown roughly: bullets and headings.
  const md=(rep.body_markdown||'').split('\n').map(line=>{
    if(line.startsWith('### ')) return '<h4>'+esc(line.slice(4))+'</h4>';
    if(line.startsWith('- ')) return '<li>'+esc(line.slice(2))+'</li>';
    if(line.startsWith('> ')) return '<blockquote class="muted">'+esc(line.slice(2))+'</blockquote>';
    if(line.startsWith('**')) return '<p><b>'+esc(line.replace(/\*\*/g,''))+'</b></p>';
    if(line.trim()==='') return '';
    return '<p>'+esc(line)+'</p>';
  }).join('');
  // Wrap consecutive <li> in <ul>
  const wrapped=md.replace(/(<li>.*?<\/li>)+/gs, m=>'<ul>'+m+'</ul>');
  document.getElementById('invReport').innerHTML=banner+'<div style="margin-top:10px">'+wrapped+'</div>';
}

// â”€â”€ Solve tab (P3) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
let currentPlan=null;
async function openSolutionPicker(){
  const status=await api('/api/llm/status');
  llmChoice=status.default || 'gemini';
  document.getElementById('llmChoices').innerHTML=status.providers.map(p=>`
    <label style="display:block;padding:6px 0;${p.available?'':'opacity:.55'}">
      <input type="radio" name="llmPick" value="${esc(p.name)}" ${p.name===llmChoice?'checked':''} ${p.available?'':'disabled'}>
      <b>${esc(p.name)}</b> <span class="muted">(${esc(p.model)}) ${p.available?'':'â€” no API key configured'}</span>
    </label>`).join('');
  llmModalCb=runSolutionArchitect;
  document.getElementById('llmModal').classList.remove('hidden');
}
async function runSolutionArchitect(){
  if(!currentInv){return;}
  document.getElementById('qStatus').textContent='Calling '+llmChoice+' for fix proposal...';
  document.getElementById('solveCard').classList.remove('hidden');
  document.getElementById('solveStatus').textContent='Generating...';
  const data=await api('/api/solve',{method:'POST',body:JSON.stringify({queue_id:currentInv.plan.queue_id, llm:llmChoice})});
  document.getElementById('solveStatus').textContent='Plan ready';
  currentPlan=data;
  renderSolutionPlan(data);
}
async function reloadSolution(){
  if(!currentInv){return;}
  const data=await api('/api/solve/'+encodeURIComponent(currentInv.plan.queue_id));
  if(data && !data.error){currentPlan=data; renderSolutionPlan(data); document.getElementById('solveCard').classList.remove('hidden');}
}
function renderSolutionPlan(p){
  const banner = p.fallback ? `<span class="pill warning">Fallback (no LLM): ${esc(p.fallback_reason||'')}</span>` :
                              `<span class="pill ok">By ${esc(p.llm_used)} (${esc(p.llm_model||'')})</span>`;
  document.getElementById('solveMeta').innerHTML = `${banner} <span class="muted">${esc(p.headline||'')}</span>
    <div class="muted" style="margin-top:4px">${esc(p.summary||'')}</div>`;
  const groups = {frontend:[], backend:[], db:[], migration:[]};
  for(const it of (p.items||[])){ (groups[it.layer]||groups.frontend).push(it); }
  const labels = {frontend:'Frontend', backend:'Backend', db:'Database', migration:'Migrations'};
  let html='';
  for(const layer of ['frontend','backend','db','migration']){
    const items=groups[layer]; if(!items.length) continue;
    html+=`<h3 style="margin:14px 0 6px">${labels[layer]}</h3>`;
    for(const it of items){
      html+=renderSolutionItem(it);
    }
  }
  if(!html){ html='<div class="muted">The Solution Architect returned no items.</div>'; }
  document.getElementById('solveItems').innerHTML=html;
}
function renderSolutionItem(it){
  const conf = it.confidence==='high' ? 'ok' : (it.confidence==='low' ? 'error' : 'warning');
  return `
    <div class="layer-card ${esc(conf)}" style="margin-bottom:10px" data-item-id="${esc(it.item_id)}">
      <h4>${esc(it.sub_component||'(no name)')} <span class="pill ${esc(conf)}">${esc(it.confidence||'medium')}</span>
        ${it.user_edited?'<span class="pill warning">edited</span>':''}</h4>
      <div class="muted" style="font-size:12px">File: <code>${esc(it.file_path)}</code></div>
      <label class="muted" style="display:block;margin-top:8px">Rationale</label>
      <textarea data-field="rationale" style="min-height:60px">${esc(it.rationale||'')}</textarea>
      <label class="muted" style="display:block;margin-top:8px">Proposed diff (unified)</label>
      <textarea data-field="proposed_diff" style="min-height:120px;font-family:monospace;font-size:12px">${esc(it.proposed_diff||'')}</textarea>
      <details style="margin-top:6px">
        <summary class="muted">Full file replacement (optional)</summary>
        <textarea data-field="proposed_full_text" style="min-height:120px;font-family:monospace;font-size:12px">${esc(it.proposed_full_text||'')}</textarea>
      </details>
      <label class="muted" style="display:block;margin-top:8px">Risk notes (one per line)</label>
      <textarea data-field="risk_notes_raw" style="min-height:50px">${esc((it.risk_notes||[]).join('\n'))}</textarea>
      <label class="muted" style="display:block;margin-top:8px">Tests to rerun (comma-separated function ids)</label>
      <input data-field="tests_to_rerun_raw" style="width:100%" value="${esc((it.tests_to_rerun||[]).join(', '))}">
      <label class="muted" style="display:block;margin-top:8px">Confidence</label>
      <select data-field="confidence">
        <option value="high"   ${it.confidence==='high'?'selected':''}>high</option>
        <option value="medium" ${it.confidence==='medium'?'selected':''}>medium</option>
        <option value="low"    ${it.confidence==='low'?'selected':''}>low</option>
      </select>
    </div>`;
}
async function saveAmendedPlan(){
  if(!currentPlan){return;}
  const cards=document.querySelectorAll('#solveItems .layer-card');
  const edits=[];
  for(const card of cards){
    const id=card.getAttribute('data-item-id');
    const grab = field => {
      const el=card.querySelector(`[data-field="${field}"]`);
      return el ? el.value : '';
    };
    const risk_raw  = grab('risk_notes_raw');
    const tests_raw = grab('tests_to_rerun_raw');
    edits.push({
      item_id: id,
      rationale:           grab('rationale'),
      proposed_diff:       grab('proposed_diff'),
      proposed_full_text:  grab('proposed_full_text'),
      risk_notes:          risk_raw.split('\n').map(s=>s.trim()).filter(Boolean),
      tests_to_rerun:      tests_raw.split(',').map(s=>s.trim()).filter(Boolean),
      confidence:          grab('confidence'),
    });
  }
  document.getElementById('solveStatus').textContent='Saving...';
  const data=await api('/api/solve/save',{method:'POST',body:JSON.stringify({queue_id:currentPlan.queue_id, edits})});
  document.getElementById('solveStatus').textContent='Saved at '+(data.generated_at||'now');
  currentPlan=data;
  renderSolutionPlan(data);
}

// â”€â”€ Apply tab (P4) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function openApplyCard(){
  document.getElementById('applyCard').classList.remove('hidden');
  renderApplyItems();
}
function renderApplyItems(){
  if(!currentPlan){return;}
  document.getElementById('applyItems').innerHTML = (currentPlan.items||[]).map(it => `
    <div class="layer-card warning" style="margin-bottom:8px" data-item-id="${esc(it.item_id)}">
      <h4>
        <input type="checkbox" data-approve="1">
        ${esc(it.sub_component||'(no name)')} <span class="pill ${esc(it.confidence||'medium')}">${esc(it.layer)}</span>
      </h4>
      <div class="muted" style="font-size:12px">File: <code>${esc(it.file_path)}</code></div>
      ${it.proposed_full_text? '' : '<div class="muted" style="color:#b54708">No proposed_full_text â€” auto-apply will skip this item. Edit in Solve tab to fill it.</div>'}
    </div>`).join('');
}
function approvedItemIds(){
  const cards=document.querySelectorAll('#applyItems .layer-card');
  const out=[];
  for(const c of cards){
    const cb=c.querySelector('input[data-approve]');
    if(cb && cb.checked){ out.push(c.getAttribute('data-item-id')); }
  }
  return out;
}
async function previewApply(){
  if(!currentPlan){return;}
  document.getElementById('applyStatus').textContent='Previewing...';
  const ids=approvedItemIds();
  if(!ids.length){document.getElementById('applyStatus').textContent='Select at least one item to preview.';return;}
  const data=await api('/api/apply/preview',{method:'POST',body:JSON.stringify({queue_id:currentPlan.queue_id, item_ids:ids})});
  document.getElementById('applyStatus').textContent='Preview ready';
  document.getElementById('applyOut').innerHTML='<pre>'+esc(JSON.stringify(data,null,2))+'</pre>';
}
async function stageApply(){
  if(!currentPlan){return;}
  document.getElementById('applyStatus').textContent='Staging...';
  const ids=approvedItemIds();
  if(!ids.length){document.getElementById('applyStatus').textContent='Select at least one item to stage.';return;}
  const data=await api('/api/apply/stage',{method:'POST',body:JSON.stringify({queue_id:currentPlan.queue_id, item_ids:ids})});
  document.getElementById('applyStatus').textContent=`Staged ${data.staged.length}, rejected ${data.rejected.length}`;
  document.getElementById('applyOut').innerHTML='<pre>'+esc(JSON.stringify(data,null,2))+'</pre>';
}
async function commitApply(){
  if(!currentPlan){return;}
  if(!confirm('Commit all staged files to the source tree? Backups are kept; rollback is one click.')) return;
  document.getElementById('applyStatus').textContent='Committing...';
  const data=await api('/api/apply/commit',{method:'POST',body:JSON.stringify({queue_id:currentPlan.queue_id})});
  document.getElementById('applyStatus').textContent=`Committed ${data.results.filter(r=>r.ok).length}/${data.results.length}`;
  document.getElementById('applyOut').innerHTML='<pre>'+esc(JSON.stringify(data,null,2))+'</pre>';
  // After commit, expose the Verify card.
  document.getElementById('verifyCard').classList.remove('hidden');
  // If any committed item was a migration, surface the migration panel.
  const migCommits=(data.results||[]).filter(r=>r.ok && (r.file_path||'').includes('/migrations/'));
  if(migCommits.length){
    const panel=document.getElementById('migPanel');
    panel.classList.remove('hidden');
    document.getElementById('migList').innerHTML = migCommits.map(r => `
      <div class="layer-card warning" style="margin-bottom:8px">
        <div><b>${esc(r.file_path)}</b></div>
        <div class="muted" style="font-size:12px">edit_id: <code>${esc(r.edit_id)}</code></div>
        <div class="row" style="margin-top:6px">
          <button class="btn primary" onclick="applyMigration('${esc(r.edit_id)}')">Apply migration now (dev only)</button>
          <button class="btn" onclick="showMigrateCommand()">Show me the command</button>
          <button class="btn danger" onclick="rollbackEdit('${esc(r.edit_id)}')">Rollback</button>
        </div>
      </div>`).join('');
  }
}
async function applyMigration(edit_id){
  document.getElementById('applyStatus').textContent='Running manage.py migrate...';
  const data=await api('/api/apply/migrate',{method:'POST',body:JSON.stringify({edit_id})});
  document.getElementById('applyStatus').textContent=data.ok?'Migration applied':'Migration refused/failed';
  document.getElementById('applyOut').innerHTML='<pre>'+esc(JSON.stringify(data,null,2))+'</pre>';
}
async function showMigrateCommand(){
  const data=await api('/api/apply/migrate/command');
  alert(data.command);
}
async function rollbackEdit(edit_id){
  if(!confirm('Roll back '+edit_id+'? This restores the original file from the backup.')) return;
  const data=await api('/api/apply/rollback',{method:'POST',body:JSON.stringify({edit_id})});
  document.getElementById('applyStatus').textContent='Rollback: '+(data.ok?'ok':'failed');
  document.getElementById('applyOut').innerHTML='<pre>'+esc(JSON.stringify(data,null,2))+'</pre>';
}

// â”€â”€ Verify tab (P5) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
let verifyOffset=0, verifyTimer=null;

async function startVerify(){
  if(!currentInv){return;}
  const qid = currentInv.plan.queue_id;
  // Send committed edit_ids from the last commit response if available; the
  // backend can also derive this from ChangeMemory by linked_run_id.
  const data=await api('/api/verify',{method:'POST',body:JSON.stringify({
    queue_id: qid,
    function_ids: currentInv.plan.selected_function_ids || [],
  })});
  document.getElementById('verifyStatus').textContent = data.ok ? 'Running...' : ('Could not start: '+(data.error||''));
  document.getElementById('verifyCard').classList.remove('hidden');
  document.getElementById('verifyLog').textContent = '';
  document.getElementById('verifyLayers').innerHTML = '';
  verifyOffset = 0;
  if(verifyTimer){clearInterval(verifyTimer);}
  verifyTimer = setInterval(()=>pollVerify(qid), 1500);
  pollVerify(qid);
}

async function pollVerify(qid){
  const snap = await api(`/api/verify/${encodeURIComponent(qid)}?log_offset=${verifyOffset}`);
  if(!snap.found){return;}
  if(snap.log && snap.log.length){
    const el=document.getElementById('verifyLog');
    el.textContent += snap.log.join('\n') + '\n';
    el.scrollTop = el.scrollHeight;
    verifyOffset = snap.log_offset;
  }
  document.getElementById('verifyStatus').textContent =
    snap.running ? 'Running... (status='+snap.status+')' :
    'Complete â€” status='+snap.status;
  if(snap.result){renderVerifyLayers(snap.result);}
  if(!snap.running){clearInterval(verifyTimer); verifyTimer=null;}
}

function renderVerifyLayers(r){
  const layers = ['frontend','backend','db'];
  const labels = {frontend:'Frontend', backend:'Backend', db:'Database'};
  document.getElementById('verifyLayers').innerHTML = layers.map(k=>{
    const v = r[k];
    if(!v){return `<div class="layer-card"><h4>${labels[k]} <span class="pill">n/a</span></h4></div>`;}
    const cls = v.status==='ok'?'ok':(v.status==='warning'?'warning':(v.status==='error'?'error':''));
    const head = esc(v.headline||'');
    const recent = (v.details||[]).slice(-6).map(d=>'<li>'+esc(d)+'</li>').join('');
    return `<div class="layer-card ${cls}">
      <h4>${labels[k]} <span class="pill ${cls}">${esc(v.status)}</span>
        <span class="muted">${v.elapsed_ms||0}ms</span></h4>
      <div class="muted">${head}</div>
      <ul>${recent}</ul>
    </div>`;
  }).join('');
}

async function cancelVerify(){
  if(!currentInv){return;}
  const data=await api(`/api/verify/${encodeURIComponent(currentInv.plan.queue_id)}/cancel`,{method:'POST',body:'{}'});
  document.getElementById('verifyStatus').textContent = data.ok ? 'Cancellation requested.' : 'Cancel failed.';
}

// â”€â”€ History tab (P6) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
let historyEdits = [];
async function loadHistory(){
  const data = await api('/api/history');
  historyEdits = data.edits || [];
  renderHistory();
}
function renderHistory(){
  const file = document.getElementById('histFile').value.toLowerCase();
  const agent = document.getElementById('histAgent').value.toLowerCase();
  const outcome = document.getElementById('histOutcome').value;
  const queue = document.getElementById('histQueue').value;
  const list = historyEdits.filter(e => {
    if (file    && !(e.file_path||'').toLowerCase().includes(file))   return false;
    if (agent   && !(e.agent||'').toLowerCase().includes(agent))      return false;
    if (outcome && e.verification_outcome !== outcome)                return false;
    if (queue   && (e.linked_run_id||'') !== queue)                   return false;
    return true;
  });
  if (!list.length){
    document.getElementById('histTable').innerHTML = '<div class="muted">No edits match.</div>';
    return;
  }
  const rows = list.map(e => `
    <tr>
      <td><code>${esc(e.edit_id)}</code></td>
      <td><code>${esc(e.file_path)}</code></td>
      <td>${esc(e.agent||'')}</td>
      <td><span class="pill ${esc(e.verification_outcome==='passed'?'ok':(e.verification_outcome==='failed'?'error':'warning'))}">${esc(e.verification_outcome||'pending')}</span></td>
      <td><code>${esc(e.linked_run_id||'')}</code></td>
      <td>${e.rolled_back ? '<span class="pill warning">rolled back</span>' :
            `<button class="btn danger" onclick="historyRollback('${esc(e.edit_id)}')">Rollback</button>`}</td>
      <td>${esc(e.applied_at||'')}</td>
    </tr>`).join('');
  document.getElementById('histTable').innerHTML = `
    <table><thead><tr>
      <th>Edit</th><th>File</th><th>Agent</th><th>Outcome</th><th>Queue</th><th>Action</th><th>Applied at</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
}
async function historyRollback(edit_id){
  if(!confirm('Rollback '+edit_id+'? This restores the original file from the backup.')) return;
  const data = await api('/api/apply/rollback',{method:'POST',body:JSON.stringify({edit_id})});
  alert(data.ok?'Rolled back.':'Failed: '+JSON.stringify(data));
  await loadHistory();
}

// â”€â”€ Round button (P6, Decision #2: explicit click) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async function startNextRound(){
  if(!currentInv){return;}
  if(!confirm('Start a new debugging round? The current queue entry will be marked complete and a new entry enqueued with prior verification context. ChangeMemory anti-suggestions will exclude already-tried fixes.')) return;
  const data = await api('/api/round',{method:'POST',body:JSON.stringify({queue_id: currentInv.plan.queue_id})});
  if(!data.ok){alert('Round refused: '+(data.error||'')); return;}
  document.getElementById('verifyStatus').textContent = 'New round queued: '+data.next_queue_id;
  // Reset UI so the user can re-investigate.
  await refreshQueue();
  // Auto-run investigation against the new entry.
  if(data.is_current){await runInvestigation(data.next_queue_id);}
}

// â”€â”€ Function QA tab (legacy) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function showAllFunctions(){activeCategory='';document.getElementById('dbPanel').classList.add('hidden');renderFunctions();}
function showCategory(category){activeCategory=category;document.getElementById('dbPanel').classList.add('hidden');renderFunctions();}
function renderFunctions(){
  const q=document.getElementById('filter').value.toLowerCase();
  const list=functions.filter(f=>(!activeCategory || f.category===activeCategory) && JSON.stringify(f).toLowerCase().includes(q));
  shownFunctions=list;
  document.getElementById('fnTitle').textContent=activeCategory ? activeCategory+' Functions' : 'Function Test Dashboard';
  document.getElementById('count').textContent=list.length+' function(s)';
  document.getElementById('runShown').classList.toggle('hidden', !activeCategory);
  document.getElementById('functions').innerHTML=list.map(f=>`
    <div class="fn">
      <h3>${esc(f.display_name)}</h3>
      <div><span class="pill">${esc(f.category)}</span> <span class="muted">${esc(f.subcategory)}</span></div>
      <p class="muted">${esc(f.frontend)}</p>
      <div class="row">
        <button class="btn primary" onclick="runFunction('${esc(f.id)}')">Run</button>
        <button class="btn" onclick="runDbChecks('${esc(f.id)}')">DB</button>
      </div>
    </div>`).join('');
}
async function runShownFunctions(){if(activeCategory){return runCategory(activeCategory);}return runAll();}
async function runFunction(id){setOut({running:id}); setOut(await api('/api/run',{method:'POST',body:JSON.stringify({scope:'function',id})}));}
async function runCategory(category){setOut({running:category}); setOut(await api('/api/run',{method:'POST',body:JSON.stringify({scope:'category',category})}));}
async function runAll(){setOut({running:'all'}); setOut(await api('/api/run',{method:'POST',body:JSON.stringify({scope:'all'})}));}
async function showDb(){document.getElementById('dbPanel').classList.remove('hidden');await dbStatus();}
async function dbStatus(){const data=await api('/api/db/status');document.getElementById('dbOutput').innerHTML='<pre>'+esc(JSON.stringify(data,null,2))+'</pre>';}
async function runDbChecks(id=''){
  document.getElementById('dbPanel').classList.remove('hidden');
  const body=id ? {scope:'function', id} : (activeCategory ? {scope:'category', category:activeCategory} : {scope:'all'});
  const data=await api('/api/db/checks',{method:'POST',body:JSON.stringify(body)});
  document.getElementById('dbOutput').innerHTML='<pre>'+esc(JSON.stringify(data,null,2))+'</pre>';
}
async function loadMemory(){setMemOut(await api('/api/memory'));}
async function loadFixes(){setMemOut(await api('/api/fixes'));}
async function showLatest(){setMemOut(await api('/api/reports/latest'));}

(function init(){if(getToken()){bootstrap();} else {showLock();}})();
</script>
</body></html>"""


# â”€â”€ HTTP handler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "InfoBhoomiAgentDashboard/1.2"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._html(HTML)
        if parsed.path == "/favicon.ico":
            return self._json({"ok": True}, 204)

        if not self._authorised():
            return self._json({"error": "unauthorised"}, 401)

        if parsed.path == "/api/meta":
            return self._json({
                "environment": AGENT_ENVIRONMENT,
                "base_url": BASE_URL,
                "ai_provider": AGENT_AI_PROVIDER,
                "gemini_model": GEMINI_MODEL,
            })
        if parsed.path == "/api/functions":
            return self._json({"categories": categories(), "functions": [fn.to_dict() for fn in all_functions()]})
        if parsed.path.startswith("/api/functions/"):
            fid = parsed.path.rsplit("/", 1)[-1]
            try:
                return self._json(get_function(fid).to_dict())
            except KeyError:
                return self._json({"error": "Unknown function"}, 404)
        if parsed.path == "/api/memory":
            query = parse_qs(parsed.query)
            memory = StructuredMemory()
            return self._json({
                "issues": memory.list_issues(status=query.get("status", [None])[0], query=query.get("q", [""])[0]),
                "runs": memory.data.get("runs", []),
            })
        if parsed.path == "/api/fixes":
            return self._json({"fixes": FixProposalAgent().list_fixes()})
        if parsed.path == "/api/db/status":
            return self._json(DBVerificationAgent().status())
        if parsed.path == "/api/reports/latest":
            return self._json(FunctionQAAgent.latest_report())
        if parsed.path == "/api/queue":
            return self._json(IssueQueue().list_state())
        if parsed.path.startswith("/api/solve/") and not parsed.path.endswith("/save"):
            qid = parsed.path.rsplit("/", 1)[-1]
            plan = SolutionPlanStore().get(qid)
            return self._json(plan or {"error": "no plan for queue_id"}, 200 if plan else 404)
        if parsed.path.startswith("/api/verify/"):
            qid = parsed.path.rsplit("/", 1)[-1]
            try:
                offset = int(parse_qs(parsed.query).get("log_offset", ["0"])[0])
            except (TypeError, ValueError):
                offset = 0
            snap = VerifyRunner.singleton().snapshot(qid, log_offset=offset)
            # Decision #8: when verification finishes cleanly, auto-advance the
            # sequential queue. Only acts when this is the current entry AND
            # we haven't already advanced it.
            try:
                result = snap.get("result")
                if result and result.get("status") == "complete" and result.get("overall") == "ok":
                    queue = IssueQueue()
                    cur = queue.list_state().get("current") or {}
                    if cur.get("queue_id") == qid and cur.get("step") in ("verifying", "applying"):
                        queue.complete_current(outcome="resolved", issue_id=(result.get("function_qa") or {}).get("issue_id", ""))
                        snap["queue_advanced"] = True
            except Exception:
                pass  # never let auto-advance crash the snapshot endpoint
            return self._json(snap)
        if parsed.path == "/api/cost":
            qs = parse_qs(parsed.query)
            qid = qs.get("queue_id", [""])[0] or ""
            ledger = CostLedger()
            return self._json({
                "totals": ledger.totals(queue_id=qid),
                "calls":  ledger.calls_for_queue(qid) if qid else ledger.all_calls()[:50],
            })
        if parsed.path == "/api/history":
            qs = parse_qs(parsed.query)
            edits = ChangeMemory().all_edits()
            return self._json({"edits": filter_history_edits(
                edits,
                file    = qs.get("file",    [""])[0] or "",
                agent   = qs.get("agent",   [""])[0] or "",
                outcome = qs.get("outcome", [""])[0] or "",
                queue_id= qs.get("queue_id",[""])[0] or "",
            )})
        if parsed.path == "/api/apply/migrate/command":
            return self._json({"command": DBMigrationImplementer.manual_command()})
        if parsed.path == "/api/llm/status":
            return self._json({"providers": list_provider_status(), "default": AGENT_DEFAULT_LLM})
        return self._json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if not self._authorised():
            return self._json({"error": "unauthorised"}, 401)
        body = self._body()

        if parsed.path == "/api/run":
            # P0 hardening: ALWAYS ignore body's allow_destructive â€” env var only.
            agent = FunctionQAAgent()
            scope = body.get("scope", "function")
            if scope == "all":      return self._json(agent.run_all())
            if scope == "category": return self._json(agent.run_category(body.get("category", "")))
            return self._json(agent.run_function(body.get("id", "")))

        if parsed.path == "/api/debug":
            prompt = body.get("prompt", "")
            provider = body.get("provider", AGENT_AI_PROVIDER)
            routes = DebugRouterAgent().route(prompt)
            memory = StructuredMemory()
            issue = None
            if prompt.strip() and routes:
                top = routes[0]
                issue = memory.record_issue(
                    function_category=top.category, sub_function=top.display_name,
                    symptom=prompt.strip(), detected_by="Debug Router Agent",
                    proposed_solution="Run the routed function checks, then generate a fix proposal for any failing evidence.",
                    debug_notes=f"Matched terms: {', '.join(top.matched_terms)}",
                )
                FixProposalAgent(memory=memory).propose_from_issue(issue, provider=provider)
            return self._json({"routes": [r.to_dict() for r in routes], "memory_issue": issue})

        if parsed.path == "/api/db/checks":
            agent = DBVerificationAgent()
            scope = body.get("scope", "all")
            if scope == "function": return self._json(agent.run_registry_checks(function_id=body.get("id", ""), record_issues=True))
            if scope == "category": return self._json(agent.run_registry_checks(category=body.get("category", ""), record_issues=True))
            return self._json(agent.run_registry_checks(record_issues=True))

        if parsed.path.startswith("/api/fixes/") and parsed.path.endswith("/approve"):
            return self._json(FixProposalAgent().approve(parsed.path.split("/")[-2]))
        if parsed.path.startswith("/api/fixes/") and parsed.path.endswith("/reject"):
            return self._json(FixProposalAgent().reject(parsed.path.split("/")[-2]))

        # â”€â”€ P2: queue + investigate + report â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if parsed.path == "/api/queue":
            prompt = (body.get("prompt") or "").strip()
            if not prompt:
                return self._json({"error": "prompt required"}, 400)
            queue = IssueQueue()
            entry = queue.enqueue(prompt)
            return self._json({**entry, "is_current": queue.list_state()["current"]["queue_id"] == entry["queue_id"]})

        if parsed.path == "/api/investigate/run":
            queue_id = (body.get("queue_id") or "").strip()
            queue = IssueQueue()
            current = queue.list_state()["current"]
            if not current or current["queue_id"] != queue_id:
                return self._json({"error": "queue_id is not the current entry"}, 400)
            queue.update_step(queue_id, "investigating")
            arch = ArchitectAgent()
            out  = arch.investigate(queue_id=queue_id, prompt=current["prompt"])
            queue.update_step(queue_id, "awaiting_resolve")
            _LAST_INVESTIGATION[queue_id] = out
            return self._json(out.to_dict())

        if parsed.path == "/api/report":
            queue_id = (body.get("queue_id") or "").strip()
            llm      = (body.get("llm") or "").strip() or AGENT_DEFAULT_LLM
            cached = _LAST_INVESTIGATION.get(queue_id)
            if cached is None:
                return self._json({"error": "no investigation cached for queue_id; run /api/investigate/run first"}, 400)
            rep = ReporterAgent().report(cached, llm_choice=llm)
            return self._json(rep.to_dict())

        if parsed.path == "/api/solve":
            queue_id = (body.get("queue_id") or "").strip()
            llm      = (body.get("llm") or "").strip() or AGENT_DEFAULT_LLM
            cached_inv = _LAST_INVESTIGATION.get(queue_id)
            if cached_inv is None:
                return self._json({"error": "no investigation cached; run /api/investigate/run first"}, 400)
            # Optional: surface the previously-rendered report markdown if cached.
            report_md = ""
            try:
                store = SolutionPlanStore()
                # We don't cache the report markdown separately; safe to leave blank.
            except Exception:
                pass
            agent = SolutionArchitectAgent()
            plan  = agent.propose(architect_output=cached_inv, report_markdown=report_md, llm_choice=llm)
            SolutionPlanStore().put(queue_id, plan.to_dict())
            IssueQueue().update_step(queue_id, "solution")
            return self._json(plan.to_dict())

        if parsed.path == "/api/solve/save":
            queue_id = (body.get("queue_id") or "").strip()
            edits    = body.get("edits") or []
            store = SolutionPlanStore()
            existing = store.get(queue_id)
            if existing is None:
                return self._json({"error": "no plan to amend; run /api/solve first"}, 400)
            merged = merge_user_edits(existing, edits)
            store.put(queue_id, merged)
            IssueQueue().update_step(queue_id, "awaiting_apply")
            return self._json(merged)



        if parsed.path == "/api/apply/preview":
            queue_id = (body.get("queue_id") or "").strip()
            ids      = body.get("item_ids") or []
            plan = SolutionPlanStore().get(queue_id)
            if plan is None:
                return self._json({"error": "no plan for queue_id"}, 404)
            items = _items_from_plan(plan, ids)
            return self._json(Applier().preview(items))

        if parsed.path == "/api/apply/stage":
            queue_id = (body.get("queue_id") or "").strip()
            ids      = body.get("item_ids") or []
            plan = SolutionPlanStore().get(queue_id)
            if plan is None:
                return self._json({"error": "no plan for queue_id"}, 404)
            items = _items_from_plan(plan, ids)
            batch = Applier().stage(items, queue_id=queue_id)
            _LAST_STAGE[queue_id] = batch.staged
            try:
                IssueQueue().update_step(queue_id, "applying")
            except KeyError:
                pass
            return self._json(batch.to_dict())

        if parsed.path == "/api/apply/commit":
            queue_id = (body.get("queue_id") or "").strip()
            staged   = _LAST_STAGE.get(queue_id) or []
            if not staged:
                return self._json({"error": "no staged batch; call /api/apply/stage first"}, 400)
            plan = SolutionPlanStore().get(queue_id) or {}
            batch = Applier().commit(
                staged,
                linked_issue_id=plan.get("issue_id", ""),
                linked_run_id=queue_id,
                llm_used=plan.get("llm_model") or plan.get("llm_used", ""),
            )
            try:
                IssueQueue().update_step(queue_id, "verifying")
            except KeyError:
                pass
            return self._json(batch.to_dict())

        if parsed.path == "/api/apply/rollback":
            edit_id = (body.get("edit_id") or "").strip()
            if not edit_id:
                return self._json({"error": "edit_id required"}, 400)
            try:
                return self._json(Applier().rollback(edit_id))
            except KeyError:
                return self._json({"error": "edit_id not found"}, 404)

        if parsed.path.startswith("/api/queue/") and parsed.path.endswith("/abandon"):
            qid = parsed.path.split("/")[-2]
            queue = IssueQueue()
            current = queue.list_state().get("current") or {}
            if not current or current.get("queue_id") != qid:
                return self._json({"ok": False, "error": "queue_id is not the current entry"}, 400)
            queue.complete_current(outcome="cancelled")
            new_state = queue.list_state()
            return self._json({"ok": True, "abandoned": qid, "current": new_state.get("current")})

        if parsed.path == "/api/round":
            queue_id = (body.get("queue_id") or "").strip()
            queue = IssueQueue()
            current = queue.list_state().get("current") or {}
            if not current or current.get("queue_id") != queue_id:
                return self._json({"ok": False, "error": "queue_id is not the current entry"}, 400)
            # Pull verification snapshot for context (best-effort).
            snap = VerifyRunner.singleton().snapshot(queue_id)
            verify_ctx = ""
            if snap.get("found") and snap.get("result"):
                r = snap["result"]
                verify_ctx = (
                    f"Prior round verification overall={r.get('overall','?')}; "
                    f"FE={(r.get('frontend') or {}).get('status','?')} "
                    f"BE={(r.get('backend')  or {}).get('status','?')} "
                    f"DB={(r.get('db')       or {}).get('status','?')}."
                )
            # Count prior failed edits for context.
            failed_edits = [
                e for e in ChangeMemory().all_edits()
                if e.get("linked_run_id") == queue_id
                and e.get("verification_outcome") in {"failed", "partial"}
                and not e.get("rolled_back")
            ]
            # Mark the current entry complete with the appropriate outcome.
            outcome = "failed" if failed_edits else "partial"
            queue.complete_current(outcome=outcome, issue_id="")
            # Augment the prompt for the next round.
            base_prompt = current.get("prompt", "")
            new_prompt = build_round_followup_prompt(
                prior_prompt=base_prompt,
                prior_queue_id=queue_id,
                verify_snapshot=snap,
                prior_failed_count=len(failed_edits),
            )
            entry = queue.enqueue(new_prompt)
            is_current = queue.list_state()["current"]["queue_id"] == entry["queue_id"]
            return self._json({
                "ok": True,
                "previous_queue_id": queue_id,
                "next_queue_id":     entry["queue_id"],
                "is_current":        is_current,
                "augmented_prompt":  new_prompt,
                "prior_failed_count": len(failed_edits),
            })

        if parsed.path == "/api/verify":
            queue_id = (body.get("queue_id") or "").strip()
            function_ids = list(body.get("function_ids") or [])
            # Pull edit ids from ChangeMemory by linked_run_id (= queue_id).
            ledger = ChangeMemory()
            edit_ids = [
                e["edit_id"] for e in ledger.all_edits()
                if e.get("linked_run_id") == queue_id and not e.get("rolled_back")
            ]
            return self._json(VerifyRunner.singleton().start(
                queue_id=queue_id,
                committed_edit_ids=edit_ids,
                function_ids_to_rerun=function_ids,
            ))

        if parsed.path.startswith("/api/verify/") and parsed.path.endswith("/cancel"):
            qid = parsed.path.split("/")[-2]
            return self._json(VerifyRunner.singleton().cancel(qid))

        if parsed.path == "/api/apply/migrate":
            # Dev-only: actually run python manage.py migrate.
            edit_id = (body.get("edit_id") or "").strip()
            ok, error, status = _validate_migration_edit(edit_id)
            if not ok:
                return self._json({"ok": False, "error": error, "edit_id": edit_id}, status)
            result  = DBMigrationImplementer().apply_migration()
            return self._json({**result.to_dict(), "edit_id": edit_id})

        return self._json({"error": "Not found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if not self._authorised():
            return self._json({"error": "unauthorised"}, 401)
        if parsed.path.startswith("/api/queue/"):
            qid = parsed.path.rsplit("/", 1)[-1]
            try:
                cancelled = IssueQueue().cancel_pending(qid)
                return self._json(cancelled)
            except KeyError:
                return self._json({"error": "queue_id not in pending"}, 404)
        return self._json({"error": "Not found"}, 404)

    # â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def log_message(self, format, *args):
        print("[agent-dashboard]", format % args)

    def _authorised(self) -> bool:
        provided = self.headers.get("X-Agent-Token", "")
        expected = _get_dashboard_token()
        if not expected:
            return False
        return secrets.compare_digest(provided, expected)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _json(self, data, status: int = 200):
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _html(self, html: str):
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)


def run_server(host: str = AGENT_DASHBOARD_HOST, port: int = AGENT_DASHBOARD_PORT):
    token = _generate_dashboard_token()
    bar = "=" * 64
    print(f"\n{bar}")
    print("  InfoBhoomi Agent QA & Debug Control Center")
    print(f"  Listening on  http://{host}:{port}")
    print(f"  Auth token    {token}")
    print(f"  (also saved at {AGENT_DASHBOARD_TOKEN_FILE})")
    print(bar)
    print("  Paste the token in the dashboard login screen.")
    print("  Press Ctrl+C to stop.\n")
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.serve_forever()

def _items_from_plan(plan: dict, item_ids: list[str] | None = None) -> list[SolutionItem]:
    """Turn a persisted plan dict into typed SolutionItem objects."""
    keep = None if item_ids is None else set(item_ids)
    out: list[SolutionItem] = []
    for raw in plan.get("items", []):
        if keep is not None and raw.get("item_id") not in keep:
            continue
        out.append(SolutionItem(
            item_id=           raw.get("item_id", ""),
            layer=             raw.get("layer", "backend"),
            sub_component=     raw.get("sub_component", ""),
            file_path=         raw.get("file_path", ""),
            rationale=         raw.get("rationale", ""),
            proposed_diff=     raw.get("proposed_diff", ""),
            proposed_full_text=raw.get("proposed_full_text", ""),
            risk_notes=        list(raw.get("risk_notes", []) or []),
            tests_to_rerun=    list(raw.get("tests_to_rerun", []) or []),
            confidence=        raw.get("confidence", "medium"),
            fingerprint=       raw.get("fingerprint", ""),
            user_edited=       bool(raw.get("user_edited", False)),
        ))
    return out


def _validate_migration_edit(edit_id: str) -> tuple[bool, str, int]:
    if not edit_id:
        return False, "edit_id required", 400
    edit = ChangeMemory().get_edit(edit_id)
    if edit is None:
        return False, "edit_id not found in ChangeMemory", 404
    if edit.get("rolled_back"):
        return False, "cannot apply migration for a rolled-back edit", 400
    if edit.get("agent") != "DBMigrationImplementer":
        return False, "edit_id is not a committed DB migration edit", 400
    file_path = (edit.get("file_path") or "").replace("\\", "/")
    if "/migrations/" not in file_path:
        return False, "edit_id does not point to a migrations file", 400
    return True, "", 200

# â”€â”€ P6 helpers (extracted for testability) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def build_round_followup_prompt(
    prior_prompt: str,
    prior_queue_id: str,
    verify_snapshot: dict | None,
    prior_failed_count: int,
) -> str:
    """
    Compose the prompt for the next debugging round. Includes the verification
    summary and the count of prior failed edits so the Architect + Solution
    Architect can see why the previous round failed.
    """
    verify_ctx = ""
    if verify_snapshot and verify_snapshot.get("found") and verify_snapshot.get("result"):
        r = verify_snapshot["result"]
        verify_ctx = (
            f"Prior round verification overall={r.get('overall','?')}; "
            f"FE={(r.get('frontend') or {}).get('status','?')} "
            f"BE={(r.get('backend')  or {}).get('status','?')} "
            f"DB={(r.get('db')       or {}).get('status','?')}."
        )
    return (
        f"[Round follow-up of {prior_queue_id}] {prior_prompt}\n\n"
        f"Context: {verify_ctx} {prior_failed_count} prior fix attempt(s) on this issue "
        f"have been recorded as failed in ChangeMemory; the Solution Architect will avoid "
        f"re-proposing them via fingerprint match."
    )


def filter_history_edits(edits: list[dict], *, file: str = "", agent: str = "",
                         outcome: str = "", queue_id: str = "") -> list[dict]:
    """Pure filter for the History tab â€” used by GET /api/history."""
    f_file = (file or "").lower()
    f_agent = (agent or "").lower()
    out = []
    for e in edits:
        if f_file    and f_file    not in (e.get("file_path","")  ).lower(): continue
        if f_agent   and f_agent   not in (e.get("agent","")      ).lower(): continue
        if outcome   and e.get("verification_outcome") != outcome:           continue
        if queue_id  and e.get("linked_run_id","") != queue_id:              continue
        out.append(e)
    return out
