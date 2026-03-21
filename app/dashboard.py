from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .database import get_db, InteractionLog, Config, User, CustomModel
from pydantic import BaseModel
import json
import os
from . import security
from datetime import timedelta

router = APIRouter()

# --- Auth Helpers ---
def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    
    if not token:
        raise HTTPException(status_code=401)
        
    payload = security.decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401)
        
    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401)
    return user

# --- Models ---
class ProxyConfig(BaseModel):
    enabled: bool
    url: str

class PruningConfig(BaseModel):
    enabled: bool

class ModelConfig(BaseModel):
    provider: str
    name: str
    api_key: str = ""

# --- Routes ---

@router.post("/api/login")
async def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not security.verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401)
    
    access_token = security.create_access_token(data={"sub": user.username})
    response = JSONResponse(content={"access_token": access_token})
    response.set_cookie(key="access_token", value=access_token, httponly=True)
    return response

@router.post("/api/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response

@router.get("/api/config")
def get_config(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    def get_val(k, d):
        obj = db.query(Config).filter_by(key=k).first()
        return obj.value if obj else d
    return {
        "proxy": {"enabled": get_val("proxy_enabled", "false") == "true", "url": get_val("proxy_url", "http://127.0.0.1:7897")},
        "pruning": {"enabled": get_val("pruning_enabled", "true") == "true"},
        "model": {"provider": get_val("model_provider", "gemini"), "name": get_val("model_name", "gemini-3.1-pro-preview"), "has_key": bool(get_val("api_key", ""))}
    }

@router.post("/api/config/{part}")
def set_config(part: str, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for k, v in body.items():
        key = f"{part}_{k}"
        val = str(v).lower() if isinstance(v, bool) else str(v)
        if part == "model" and k == "api_key" and v:
            val = security.encrypt_value(v)
        obj = db.query(Config).filter_by(key=key).first()
        if not obj:
            db.add(Config(key=key, value=val))
        else:
            obj.value = val
    db.commit()
    return {"status": "ok"}

@router.get("/api/logs")
def list_logs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    logs = db.query(InteractionLog).order_by(InteractionLog.timestamp.desc()).limit(50).all()
    return [
        {
            "id": l.id,
            "timestamp": (l.timestamp + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S'),
            "status": l.status,
            "model": l.model_used,
            "latency": l.latency_ms
        } for l in logs
    ]

@router.get("/api/logs/{log_id}")
def get_log(log_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    l = db.query(InteractionLog).filter(InteractionLog.id == log_id).first()
    if not l: raise HTTPException(status_code=404)
    return {
        "id": l.id,
        "raw_request": l.raw_request,
        "final_payload": l.final_payload,
        "raw_response": l.raw_response,
        "model": l.model_used,
        "status": l.status,
        "timestamp": (l.timestamp + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S'),
        "latency": l.latency_ms
    }

@router.delete("/api/logs")
def clear_logs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(InteractionLog).delete()
    db.commit()
    return {"status": "ok"}

@router.get("/api/models/custom")
def list_custom_models(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    models = db.query(CustomModel).all()
    return [{"id": m.id, "provider": m.provider, "name": m.name, "value": m.value} for m in models]

@router.post("/api/models/custom")
async def add_custom_model(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    model = CustomModel(provider=body['provider'], name=body['name'], value=body['value'])
    db.add(model)
    db.commit()
    return {"status": "ok", "id": model.id}

@router.delete("/api/models/custom/{model_id}")
def delete_custom_model(model_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(CustomModel).filter(CustomModel.id == model_id).delete()
    db.commit()
    return {"status": "ok"}

@router.get("/login", response_class=HTMLResponse)
async def login_page():
    return """
    <!DOCTYPE html><html><head><meta charset="UTF-8"><title>Login</title><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-gray-900 h-screen flex items-center justify-center font-sans">
        <div class="bg-white p-8 rounded-xl shadow-2xl max-w-sm w-full text-center">
            <h1 class="text-2xl font-black italic mb-8">SEN<span class="text-blue-600">GATEWAY</span></h1>
            <form onsubmit="event.preventDefault(); const f=new URLSearchParams(new FormData(event.target)); fetch('/api/login',{method:'POST',body:f}).then(r=>r.ok?window.location.href='/dashboard':alert('Login Failed'))">
                <div class="space-y-4">
                    <input type="text" name="username" placeholder="Username" class="w-full p-2 border rounded" required>
                    <input type="password" name="password" placeholder="Password" class="w-full p-2 border rounded" required>
                    <button class="w-full bg-blue-600 text-white py-2 rounded font-bold hover:bg-blue-700 transition-colors">Sign In</button>
                </div>
            </form>
        </div>
    </body></html>
    """

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except:
        return RedirectResponse(url="/login")

    # JAVASCRIPT - Plain String to avoid f-string curly brace hell
    JS_CONTENT = """
    let SELECTED_LOGS = [];
    let CURRENT_LOG_DATA = null;
    let CUSTOM_MODELS = [];
    const STATIC_MODEL_OPTIONS = {
        "gemini": [
            {"val": "gemini/gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro"},
            {"val": "gemini/gemini-3-flash-preview", "label": "Gemini 3 Flash"},
            {"val": "gemini/gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash-Lite"},
            {"val": "gemini/gemini-3.1-flash-image", "label": "Nano Banana 2"},
            {"val": "gemini/veo-3.1-generate", "label": "Veo 3.1"}
        ],
        "openai": [
            {"val": "openai/gpt-5.4-pro-2026-03", "label": "GPT-5.4 Pro"},
            {"val": "openai/gpt-5.4-thinking", "label": "GPT-5.4 Thinking"},
            {"val": "openai/gpt-5.4-mini-2026-03", "label": "GPT-5.4 mini"},
            {"val": "openai/o3-2025-04-16", "label": "OpenAI o3"},
            {"val": "openai/o3-mini-2026-01", "label": "OpenAI o3-mini"}
        ],
        "anthropic": [
            {"val": "anthropic/claude-opus-4-6", "label": "Claude 4.6 Opus"},
            {"val": "anthropic/claude-sonnet-4-6", "label": "Claude 4.6 Sonnet"},
            {"val": "anthropic/claude-haiku-4-5", "label": "Claude 4.5 Haiku"},
            {"val": "anthropic/claude-4-6-code-preview", "label": "Claude Code v2"}
        ],
        "bedrock": [
            {"val": "bedrock/anthropic.claude-opus-4-6-v1", "label": "Bedrock Claude 4.6 Opus"},
            {"val": "bedrock/anthropic.claude-sonnet-4-5-v1", "label": "Bedrock Claude 4.5 Sonnet"},
            {"val": "bedrock/anthropic.claude-haiku-4-5-v1", "label": "Bedrock Claude 4.5 Haiku"},
            {"val": "bedrock/anthropic.claude-3-7-sonnet-v1", "label": "Bedrock Claude 3.7 Sonnet"},
            {"val": "bedrock/us.anthropic.claude-sonnet-4-5-v1", "label": "Bedrock Claude 4.5 Sonnet (US)"},
            {"val": "bedrock/amazon.nova-pro-v1:0", "label": "Amazon Nova Pro"},
            {"val": "bedrock/amazon.nova-lite-v1:0", "label": "Amazon Nova Lite"},
            {"val": "bedrock/amazon.nova-micro-v1:0", "label": "Amazon Nova Micro"},
            {"val": "bedrock/meta.llama4-400b-maverick-v1:0", "label": "Llama 4 Maverick (400B)"},
            {"val": "bedrock/meta.llama4-17b-scout-v1:0", "label": "Llama 4 Scout (17B)"},
            {"val": "bedrock/meta.llama3-3-70b-instruct-v1:0", "label": "Llama 3.3 (70B)"},
            {"val": "bedrock/mistral.mistral-large-3-2512-v1:0", "label": "Mistral Large 3"},
            {"val": "bedrock/deepseek.deepseek-v3-instruct-v1", "label": "DeepSeek-V3 (Bedrock)"},
            {"val": "bedrock/cohere.command-r-plus-v1:0", "label": "Cohere Command R+"}
        ]
    };

    function getModelOptions() {
        const options = JSON.parse(JSON.stringify(STATIC_MODEL_OPTIONS));
        CUSTOM_MODELS.forEach(m => {
            if (!options[m.provider]) options[m.provider] = [];
            options[m.provider].push({"val": m.value, "label": m.name + " (Custom)", "id": m.id});
        });
        return options;
    }

    async function loadLogList() {
        const res = await fetch('/api/logs');
        if(res.status === 401) { window.location.href = '/login'; return; }
        const logs = await res.json();
        const listEl = document.getElementById('log-list');
        if(logs.length === 0) { listEl.innerHTML = '<div class="p-8 text-center text-gray-400">No logs.</div>'; return; }
        listEl.innerHTML = logs.map(l => `
            <div id="log-item-${l.id}" class="border-b p-3 hover:bg-gray-50 cursor-pointer flex gap-3 transition-all" onclick="selectLog(${l.id})">
                <input type="checkbox" class="mt-1" onclick="event.stopPropagation(); toggleSelection(${l.id})" ${SELECTED_LOGS.includes(l.id)?'checked':''}>
                <div class="flex-1 overflow-hidden">
                    <div class="flex justify-between text-[10px] text-gray-400 mb-1"><span>#${l.id}</span><span class="font-bold uppercase ${l.status==='success'?'text-green-500':'text-red-500'}">${l.status}</span></div>
                    <div class="text-xs font-bold truncate text-gray-700">${l.model || 'Unknown'}</div>
                    <div class="text-[10px] text-gray-400 mt-1">${l.timestamp}</div>
                </div>
            </div>`).join('');
    }

    function toggleSelection(id) {
        const i = SELECTED_LOGS.indexOf(id);
        if(i > -1) SELECTED_LOGS.splice(i, 1); else SELECTED_LOGS.push(id);
        document.getElementById('log-item-'+id).classList.toggle('bg-pink-50', i===-1);
        document.getElementById('btn-audit').classList.toggle('hidden', SELECTED_LOGS.length < 1);
    }

    async function selectLog(id) {
        document.querySelectorAll('.log-item').forEach(el => el.classList.remove('bg-blue-50', 'border-l-4', 'border-blue-500'));
        const item = document.getElementById('log-item-'+id);
        if(item) { item.classList.add('bg-blue-50', 'border-l-4', 'border-blue-500'); }
        
        ['code-raw','code-final','code-resp'].forEach(k => {
            const el = document.getElementById(k);
            el.textContent = '';
            el.removeAttribute('data-highlighted');
        });
        
        document.getElementById('empty-state').classList.add('hidden');
        document.getElementById('loading-state').classList.remove('hidden');
        document.getElementById('detail-content').classList.add('hidden');

        const res = await fetch('/api/logs/'+id);
        const log = await res.json();
        
        document.getElementById('loading-state').classList.add('hidden');
        document.getElementById('detail-content').classList.remove('hidden');
        document.getElementById('detail-id').textContent = '#'+log.id;
        document.getElementById('detail-model').textContent = log.model;
        
        CURRENT_LOG_DATA = log; // Store for download

        const setCode = (cid, data) => {
            const el = document.getElementById(cid);
            const str = JSON.stringify(data, null, 2);
            el.textContent = str.length > 50000 ? str.substring(0, 50000) + '\\n\\n... [TRUNCATED] ...' : str;
            hljs.highlightElement(el);
            const lenEl = document.getElementById(cid+'-len');
            if(lenEl) { lenEl.textContent = (str.length/1000).toFixed(1)+'k chars'; }
        };
        
        setCode('code-raw', log.raw_request);
        setCode('code-final', log.final_payload);
        setCode('code-resp', log.raw_response);
    }

    async function runAudit() {
        const overlay = document.getElementById('audit-overlay');
        overlay.classList.remove('hidden');
        const resultsEl = document.getElementById('audit-results');
        const tableEl = document.getElementById('audit-table-body');
        
        resultsEl.innerHTML = '<div class="text-center w-full py-12 animate-pulse">Analyzing Cache Streams (Echo Retention Audit)...</div>';
        tableEl.innerHTML = '';

        const sorted = [...SELECTED_LOGS].sort((a,b) => a - b);
        const data = [];
        for(const id of sorted) data.push(await (await fetch('/api/logs/'+id)).json());
        
        // Gemini V2 Pricing Rules (Input: $1.25/M, Output: $5.00/M, Cache Hit: $0.3125/M ~75% off)
        // Token Estimation: 1 char ~= 0.25 tokens (English), 1 char ~= 2 tokens (Chinese)
        const COST_INPUT_BASE = 1.25 / 1000000;
        const COST_INPUT_CACHE = 0.3125 / 1000000;
        const COST_OUTPUT = 5.00 / 1000000;

        function estimateTokens(str) {
            if (!str) return 0;
            let tokens = 0;
            for (let i = 0; i < str.length; i++) {
                // Detect Chinese/CJK characters
                if (str.charCodeAt(i) > 255) tokens += 2; 
                else tokens += 0.25; 
            }
            return Math.ceil(tokens);
        }

        let curRaw = "", curFin = "", totalCostRaw = 0, totalCostFin = 0;
        
        let rows = data.map(l => {
            const rS = JSON.stringify(l.raw_request);
            const fS = JSON.stringify(l.final_payload);
            const respS = JSON.stringify(l.raw_response);

            // Calculate Token Counts
            const rTok = estimateTokens(rS);
            const fTok = estimateTokens(fS);
            const outTok = estimateTokens(respS);

            // Prefix Matching for Implicit Cache
            // We assume 'curFin' is the previous turn's context. 
            // If the current request STARTS with a significant portion of the previous context, we count it as a cache hit.
            // Simplified: We check if the System Prompt (usually first part) matches. 
            // Actually, in multi-turn, the prefix grows.
            const fMatchLen = getMatch(curFin, fS);
            const fMatchTok = estimateTokens(fS.substring(0, fMatchLen));
            const fMissTok = fTok - fMatchTok;

            // Cost Calculation
            // Original (Raw): Also uses caching! 
            // We assume that even without pruning, if the prompt prefix matches, Gemini applies caching.
            // Raw Request vs Raw Request (Prev)
            const rMatchLen = getMatch(curRaw, rS);
            const rMatchTok = estimateTokens(rS.substring(0, rMatchLen));
            const rMissTok = rTok - rMatchTok;
            const rCost = (rMissTok * COST_INPUT_BASE) + (rMatchTok * COST_INPUT_CACHE) + (outTok * COST_OUTPUT);
            
            // Gateway (Final): Uses Pruning + Cache Discounts
            const fCost = (fMissTok * COST_INPUT_BASE) + (fMatchTok * COST_INPUT_CACHE) + (outTok * COST_OUTPUT);

            totalCostRaw += rCost; 
            totalCostFin += fCost;
            
            // Update Context for next turn
            curRaw = rS; 
            curFin = fS;
            
            const savings = ((1 - fCost/rCost)*100).toFixed(1);
            
            return `<tr class=\"border-b border-gray-800\">
                <td class=\"py-2\">#${l.id}</td>
                <td class=\"font-bold\">${rTok} <span class="text-[9px] text-gray-500 font-normal">(Hit:${rMatchTok})</span></td>
                <td>$${rCost.toFixed(6)}</td>
                <td class=\"font-bold\">${fTok} <span class="text-[9px] text-gray-500 font-normal">(Hit:${fMatchTok})</span></td>
                <td class=\"text-pink-400 font-bold\">$${fCost.toFixed(6)}</td>
                <td class=\"text-green-400 font-bold\">${savings}%</td>
            </tr>`;
        }).join('');
        
        resultsEl.innerHTML = `
            <div class=\"bg-gray-800 p-6 rounded-xl border-l-4 border-gray-600\">
                <div class=\"text-xs text-gray-500 uppercase mb-1\">Standard Cost</div>
                <div class=\"text-2xl font-mono\">$${totalCostRaw.toFixed(5)}</div>
            </div>
            <div class=\"bg-gray-800 p-6 rounded-xl border-l-4 border-pink-500\">
                <div class=\"text-xs text-gray-500 uppercase mb-1\">Gateway Cost</div>
                <div class=\"text-2xl font-mono text-pink-500\">$${totalCostFin.toFixed(5)}</div>
            </div>
            <div class=\"bg-pink-600 p-6 rounded-xl\">
                <div class=\"text-xs text-pink-200 uppercase mb-1\">Efficiency</div>
                <div class=\"text-3xl font-black\">${((1-totalCostFin/totalCostRaw)*100).toFixed(1)}%</div>
            </div>`;
        tableEl.innerHTML = rows;
    }

    function getMatch(s1, s2) { let i = 0; while(i < s1.length && i < s2.length && s1[i] === s2[i]) i++; return i; }
    function closeAudit() { document.getElementById('audit-overlay').classList.add('hidden'); }
    
    function showSection(id) {
        document.getElementById('section-monitor').classList.toggle('hidden', id !== 'monitor');
        document.getElementById('section-config').classList.toggle('hidden', id !== 'config');
        document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.id === 'nav-'+id));
        if(id==='monitor') loadLogList();
        if(id==='config') loadConfig();
    }

    async function loadConfig() {
        const customRes = await fetch('/api/models/custom');
        CUSTOM_MODELS = await customRes.json();
        
        const d = await (await fetch('/api/config')).json();
        document.getElementById('model-provider').value = d.model.provider;
        updateModelOptions(d.model.name);
        document.getElementById('comp-enabled').checked = d.pruning.enabled;
        document.getElementById('proxy-enabled').checked = d.proxy.enabled;
        document.getElementById('proxy-url').value = d.proxy.url;
        renderCustomModelList();
    }

    function updateModelOptions(sel=null) {
        const p = document.getElementById('model-provider').value;
        const opts = getModelOptions()[p] || [];
        document.getElementById('model-select').innerHTML = opts.map(o => `<option value="${o.val}" ${sel===o.val?'selected':''}>${o.label}</option>`).join('');
    }

    async function addCustomModel() {
        const provider = document.getElementById('add-model-provider').value;
        const name = document.getElementById('add-model-name').value;
        const value = document.getElementById('add-model-value').value;
        if(!name || !value) { alert('Please fill name and value'); return; }
        
        const res = await fetch('/api/models/custom', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({provider, name, value})
        });
        if(res.ok) {
            document.getElementById('add-model-name').value = '';
            document.getElementById('add-model-value').value = '';
            await loadConfig();
        }
    }

    async function deleteCustomModel(id) {
        if(!confirm('Delete this model?')) return;
        await fetch('/api/models/custom/' + id, {method: 'DELETE'});
        await loadConfig();
    }

    function renderCustomModelList() {
        const listEl = document.getElementById('custom-model-list');
        listEl.innerHTML = CUSTOM_MODELS.map(m => `
            <div class="flex justify-between items-center bg-gray-50 p-2 rounded-lg text-xs">
                <span><b class="uppercase">${m.provider}</b>: ${m.name} (${m.value})</span>
                <button onclick="deleteCustomModel(${m.id})" class="text-red-500 hover:text-red-700">Delete</button>
            </div>
        `).join('') || '<div class="text-center text-gray-400 text-[10px]">No custom models.</div>';
    }

    async function saveModel() {
        const body = { provider: document.getElementById('model-provider').value, name: document.getElementById('model-select').value, api_key: document.getElementById('api-key').value };
        await fetch('/api/config/model', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        alert('Saved');
    }

    async function saveComp(v) { await fetch('/api/config/pruning', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({enabled:v})}); }
    async function saveProxy() {
        const body = { enabled: document.getElementById('proxy-enabled').checked, url: document.getElementById('proxy-url').value };
        await fetch('/api/config/proxy', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        alert('Proxy Settings Saved');
    }
    
    async function clearLogs() { if(confirm('Clear all logs?')) { await fetch('/api/logs', {method:'DELETE'}); loadLogList(); } }

    function downloadJson(id) {
        // Download logic needs to fetch the FULL content, not just what's in the DOM (which might be truncated)
        // We actually have the full data in the 'log' object in selectLog scope, but passing it is tricky.
        // Easiest is to fetch it again or store it globally.
        // Let's rely on the global CURRENT_LOG_DATA
        if (!CURRENT_LOG_DATA) return;
        
        let data = null;
        if (id === 'code-raw') data = CURRENT_LOG_DATA.raw_request;
        else if (id === 'code-final') data = CURRENT_LOG_DATA.final_payload;
        else if (id === 'code-resp') data = CURRENT_LOG_DATA.raw_response;
        
        if (!data) return;
        
        const blob = new Blob([JSON.stringify(data, null, 2)], {type:'application/json'});
        const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = id + '-' + CURRENT_LOG_DATA.id + '.json'; a.click();
    }

    document.addEventListener('DOMContentLoaded', loadLogList);
    """

    return f"""
    <!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Sen-Gateway</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <style>
        ::-webkit-scrollbar{{width:6px}} ::-webkit-scrollbar-thumb{{background:#4b5563;border-radius:10px}}
        .nav-item.active{{background:#374151;color:white}}
        code{{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}}
    </style></head>
    <body class="bg-gray-100 font-sans h-screen flex flex-col overflow-hidden text-sm">
        <header class="bg-gray-900 text-gray-400 h-14 flex items-center justify-between px-6 shadow-md z-20 shrink-0">
            <div class="flex items-center gap-6"><h1 class="text-xl font-black text-white italic tracking-tighter">SEN<span class="text-blue-500">GATEWAY</span></h1>
            <nav class="flex gap-2">
                <button onclick="showSection('monitor')" id="nav-monitor" class="nav-item active px-3 py-1 rounded-md transition-colors">Monitor</button>
                <button onclick="showSection('config')" id="nav-config" class="nav-item px-3 py-1 rounded-md transition-colors">Config</button>
            </nav></div>
            <div class="flex items-center gap-4">
                <button onclick="clearLogs()" class="text-xs hover:text-red-400 transition-colors">🗑️ Clear Logs</button>
                <form action="/api/logout" method="post"><button class="bg-gray-800 hover:bg-gray-700 px-3 py-1 rounded text-xs font-bold transition-colors">Sign Out</button></form>
            </div>
        </header>

        <main class="flex-1 flex overflow-hidden">
            <!-- Monitor View -->
            <div id="section-monitor" class="flex-1 flex w-full">
                <!-- Sidebar -->
                <div class="w-64 bg-white border-r border-gray-200 flex flex-col shadow-lg z-10">
                    <div class="p-3 border-b bg-gray-50 flex justify-between items-center">
                        <span class="text-[10px] font-bold text-gray-400 uppercase">Traffic Logs</span>
                        <div class="flex gap-1">
                            <button onclick="loadLogList()" class="text-gray-400 hover:text-blue-500 transition-colors" title="Refresh Logs">🔄</button>
                            <button onclick="runAudit()" id="btn-audit" class="hidden bg-pink-600 text-white text-[10px] px-2 py-1 rounded font-bold hover:bg-pink-700">🚀 Audit</button>
                        </div>
                    </div>
                    <div class="flex-1 overflow-y-auto" id="log-list"></div>
                </div>

                <!-- Content Area -->
                <div class="flex-1 bg-gray-50 overflow-y-auto p-6 relative">
                    <!-- Audit Overlay -->
                    <div id="audit-overlay" class="hidden absolute inset-0 bg-gray-900/95 z-50 p-12 overflow-y-auto text-white">
                        <div class="max-w-4xl mx-auto">
                            <div class="flex justify-between items-start mb-8"><h2 class="text-3xl font-black italic tracking-tighter">CACHE <span class="text-pink-500">AUDIT</span></h2><button onclick="closeAudit()" class="text-3xl hover:text-pink-500 transition-colors">&times;</button></div>
                            <div id="audit-results" class="grid grid-cols-3 gap-6 mb-12"></div>
                            <div class="bg-gray-800 rounded-xl p-6 border border-gray-700">
                                <table class="w-full text-left text-xs">
                                    <thead><tr class="text-gray-500 border-b border-gray-700">
                                        <th class="pb-2">Turn</th><th class="pb-2">Raw (Tok)</th><th class="pb-2">Raw $</th><th class="pb-2">Final (Tok)</th><th class="pb-2 text-pink-400">Final $</th><th class="pb-2">Saved</th>
                                    </tr></thead>
                                    <tbody id="audit-table-body" class="divide-y divide-gray-700"></tbody>
                                </table>
                            </div>
                        </div>
                    </div>

                    <!-- Detail View -->
                    <div id="empty-state" class="h-full flex flex-col items-center justify-center text-gray-400"><p>Select a log to inspect payload integrity.</p></div>
                    <div id="loading-state" class="hidden h-full flex items-center justify-center"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div></div>
                    
                    <div id="detail-content" class="hidden space-y-6">
                        <div class="flex justify-between items-end">
                            <div><h2 class="text-2xl font-bold text-gray-800"><span id="detail-id" class="text-gray-400 font-mono"></span> <span id="detail-model"></span></h2></div>
                            <div id="detail-status" class="px-2 py-1 rounded text-xs font-bold uppercase"></div>
                        </div>
                        <div class="grid grid-cols-3 gap-4">
                            <div class="bg-white rounded shadow-sm border flex flex-col h-[650px] overflow-hidden">
                                <div class="bg-gray-100 px-3 py-1 flex justify-between text-[10px] font-bold"><span>REQUEST (RAW)</span><span id="code-raw-len" class="text-gray-400"></span></div>
                                <pre class="flex-1 overflow-auto bg-[#282c34]"><code id="code-raw" class="text-[10px] text-gray-300 p-4 block leading-relaxed"></code></pre>
                                <button onclick="downloadJson('code-raw')" class="text-[10px] py-1 bg-gray-50 hover:bg-gray-100 border-t">Download</button>
                            </div>
                            <div class="bg-white rounded shadow-sm border flex flex-col h-[650px] overflow-hidden">
                                <div class="bg-gray-100 px-3 py-1 flex justify-between text-[10px] font-bold"><span>FINAL PAYLOAD</span><span id="code-final-len" class="text-gray-400"></span></div>
                                <pre class="flex-1 overflow-auto bg-[#282c34]"><code id="code-final" class="text-[10px] text-gray-300 p-4 block leading-relaxed"></code></pre>
                                <button onclick="downloadJson('code-final')" class="text-[10px] py-1 bg-gray-50 hover:bg-gray-100 border-t">Download</button>
                            </div>
                            <div class="bg-white rounded shadow-sm border flex flex-col h-[650px] overflow-hidden">
                                <div class="bg-gray-100 px-3 py-1 flex justify-between text-[10px] font-bold"><span>RESPONSE</span><span id="code-resp-len" class="text-gray-400"></span></div>
                                <pre class="flex-1 overflow-auto bg-[#282c34]"><code id="code-resp" class="text-[10px] text-gray-300 p-4 block leading-relaxed"></code></pre>
                                <button onclick="downloadJson('code-resp')" class="text-[10px] py-1 bg-gray-50 hover:bg-gray-100 border-t">Download</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Config View -->
            <div id="section-config" class="hidden p-12 max-w-xl mx-auto w-full overflow-y-auto">
                <div class="bg-white p-8 rounded-2xl shadow-xl space-y-8 border border-gray-100">
                    <h2 class="text-2xl font-black tracking-tight border-b pb-4">System Settings</h2>
                    <div class="space-y-2">
                        <label class="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Model Provider</label>
                        <select id="model-provider" class="w-full p-3 bg-gray-50 border-0 rounded-xl focus:ring-2 focus:ring-blue-500" onchange="updateModelOptions()">
                            <option value="gemini">Google Gemini</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="bedrock">AWS Bedrock</option>
                        </select>
                    </div>
                    <div class="space-y-2">
                        <label class="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Model Name</label>
                        <select id="model-select" class="w-full p-3 bg-gray-50 border-0 rounded-xl focus:ring-2 focus:ring-blue-500"></select>
                    </div>
                    <div class="space-y-2">
                        <label class="text-[10px] font-bold text-gray-400 uppercase tracking-widest">API Key</label>
                        <input type="password" id="api-key" class="w-full p-3 bg-gray-50 border-0 rounded-xl focus:ring-2 focus:ring-blue-500" placeholder="••••••••••••••••">
                    </div>
                    <button onclick="saveModel()" class="w-full bg-blue-600 text-white py-3 rounded-xl font-bold shadow-lg shadow-blue-200 hover:scale-[1.02] active:scale-[0.98] transition-all">Apply Changes</button>
                    
                    <div class="pt-6 border-t space-y-4">
                        <h3 class="font-bold">Add Custom Model</h3>
                        <div class="grid grid-cols-2 gap-2">
                            <select id="add-model-provider" class="p-2 bg-gray-50 border-0 rounded-lg text-xs">
                                <option value="gemini">Gemini</option>
                                <option value="openai">OpenAI</option>
                                <option value="anthropic">Anthropic</option>
                                <option value="bedrock">Bedrock</option>
                            </select>
                            <input type="text" id="add-model-name" placeholder="Model Name (Label)" class="p-2 bg-gray-50 border-0 rounded-lg text-xs">
                        </div>
                        <input type="text" id="add-model-value" placeholder="Model ID (e.g. gpt-4-turbo)" class="w-full p-2 bg-gray-50 border-0 rounded-lg text-xs">
                        <button onclick="addCustomModel()" class="w-full bg-gray-800 text-white py-2 rounded-lg text-xs font-bold hover:bg-black transition-all">Add Model</button>
                        <div id="custom-model-list" class="space-y-2 mt-4"></div>
                    </div>

                    <div class="flex items-center justify-between pt-6 border-t">
                        <div><h3 class="font-bold">History Compression</h3><p class="text-xs text-gray-500">Enable Echo Retention (V3) pruning</p></div>
                        <input type="checkbox" id="comp-enabled" onchange="saveComp(this.checked)" class="w-6 h-6 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer">
                    </div>

                    <div class="pt-6 border-t space-y-4">
                        <div class="flex items-center justify-between">
                            <div><h3 class="font-bold">Outbound Proxy</h3><p class="text-xs text-gray-500">Global proxy for API requests</p></div>
                            <input type="checkbox" id="proxy-enabled" class="w-6 h-6 rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer">
                        </div>
                        <div class="space-y-2">
                            <label class="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Proxy URL (e.g. http://127.0.0.1:7897)</label>
                            <input type="text" id="proxy-url" class="w-full p-3 bg-gray-50 border-0 rounded-xl focus:ring-2 focus:ring-blue-500">
                        </div>
                        <button onclick="saveProxy()" class="w-full bg-gray-200 text-gray-700 py-2 rounded-xl font-bold hover:bg-gray-300 transition-all">Save Proxy Settings</button>
                    </div>
                </div>
            </div>
        </main>
        <script>{JS_CONTENT}</script>
    </body></html>
    """
