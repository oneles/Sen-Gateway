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
    current_provider = get_val("model_provider", "gemini")
    legacy_key = get_val("model_api_key", "")
    legacy_owner = get_val("model_api_key_provider", "")
    providers = ("gemini", "openai", "anthropic", "deepseek", "bedrock")
    provider_keys = {
        provider: bool(get_val(f"provider_api_key_{provider}", ""))
        for provider in providers
    }
    # Backward compatibility: the original schema stored one global key. It
    # belongs only to the provider that was active when the scoped schema was
    # introduced, never to a newly selected provider.
    if legacy_key and (not legacy_owner or legacy_owner == current_provider):
        provider_keys[current_provider] = True

    return {
        "proxy": {"enabled": get_val("proxy_enabled", "false") == "true", "url": get_val("proxy_url", "http://127.0.0.1:7897")},
        "pruning": {"enabled": get_val("pruning_enabled", "true") == "true", "language": get_val("pruning_language", "en")},
        "reasoning": {"mode": get_val("reasoning_mode", "fast")},
        "model": {"provider": current_provider, "name": get_val("model_name", "gemini/gemini-3.1-pro-preview"), "has_key": provider_keys[current_provider], "provider_keys": provider_keys}
    }

@router.post("/api/config/{part}")
def set_config(part: str, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if part == "reasoning" and body.get("mode") not in {"fast", "deep", "max"}:
        raise HTTPException(status_code=422, detail="Invalid reasoning mode")
    if part == "model":
        previous_provider_obj = db.query(Config).filter_by(key="model_provider").first()
        previous_provider = previous_provider_obj.value if previous_provider_obj else "gemini"
        legacy_key = db.query(Config).filter_by(key="model_api_key").first()
        scoped_key = db.query(Config).filter_by(key=f"provider_api_key_{previous_provider}").first()
        if legacy_key and legacy_key.value and not scoped_key:
            db.add(Config(key=f"provider_api_key_{previous_provider}", value=legacy_key.value))
        if legacy_key and legacy_key.value:
            owner = db.query(Config).filter_by(key="model_api_key_provider").first()
            if owner:
                owner.value = previous_provider
            else:
                db.add(Config(key="model_api_key_provider", value=previous_provider))

    for k, v in body.items():
        # An empty API-key field means "keep the existing key". This lets users
        # change the provider/model without accidentally erasing credentials.
        if part == "model" and k == "api_key" and not v:
            continue
        if part == "model" and k == "api_key":
            provider = body.get("provider")
            if provider not in {"gemini", "openai", "anthropic", "deepseek", "bedrock"}:
                raise HTTPException(status_code=422, detail="Invalid model provider")
            key = f"provider_api_key_{provider}"
        else:
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
    <!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in — Sen Gateway</title>
    <style>
      :root{--ink:#f1f3f7;--muted:#a8adb8;--panel:#202126;--panel-2:#292b32;--line:#34363e;--signal:#6f8cff;--signal-hover:#88a0ff;--bg:#17181d;--field:#292b32;--shadow:0 30px 80px rgba(0,0,0,.28);--grid:rgba(111,140,255,.03)}
      html[data-theme="light"]{--ink:#20232d;--muted:#6e7482;--panel:#fff;--panel-2:#f7f8fc;--line:#e2e5ed;--signal:#4d6bfe;--signal-hover:#3f5be7;--bg:#f7f8fc;--field:#f7f8fc;--shadow:0 30px 80px rgba(31,42,79,.12);--grid:rgba(77,107,254,.04)}
      *{box-sizing:border-box} body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;transition:background .2s ease,color .2s ease}
      body:before{content:"";position:fixed;inset:0;pointer-events:none;background:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:40px 40px;mask-image:linear-gradient(to bottom,black,transparent 82%)}
      .shell{width:min(920px,calc(100% - 32px));display:grid;grid-template-columns:1.15fr .85fr;border:1px solid var(--line);border-radius:24px;overflow:hidden;background:var(--panel);box-shadow:var(--shadow)}
      .story{padding:56px;border-right:1px solid var(--line);display:flex;flex-direction:column;justify-content:space-between;min-height:520px;background:radial-gradient(circle at 20% 0%,rgba(77,107,254,.15),transparent 42%)}
      .brand{font-size:18px;font-weight:800;letter-spacing:.08em}.brand span{color:var(--signal)}
      .eyebrow{color:var(--signal);font-size:11px;letter-spacing:.18em;text-transform:uppercase;font-weight:700}.story h1{font-size:42px;line-height:1.05;letter-spacing:-.04em;margin:16px 0 18px;max-width:420px}.story p{color:var(--muted);line-height:1.7;max-width:430px}
      .signal{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:12px}.signal i{width:8px;height:8px;border-radius:50%;background:var(--signal);box-shadow:0 0 18px var(--signal)}
      .auth{padding:56px 44px;display:flex;flex-direction:column;justify-content:center}.auth h2{font-size:24px;margin:0 0 8px}.auth>p{color:var(--muted);margin:0 0 32px;font-size:14px}.field{display:grid;gap:8px;margin-bottom:18px}.field label{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-weight:700}.field input{width:100%;background:var(--field);border:1px solid var(--line);border-radius:12px;color:var(--ink);padding:13px 14px;font-size:15px;outline:none}.field input:focus{border-color:var(--signal);box-shadow:0 0 0 3px rgba(77,107,254,.12)}button{width:100%;border:0;border-radius:12px;background:var(--signal);color:#fff;padding:13px;font-weight:800;font-size:14px;cursor:pointer}button:hover{background:var(--signal-hover)}button:focus-visible{outline:3px solid var(--signal);outline-offset:3px}.error{min-height:18px;color:#ff7b87;font-size:12px;margin-top:14px}
      .top-controls{position:fixed;top:20px;right:20px;display:flex;gap:8px}.language-switch{width:auto;border:1px solid var(--line);border-radius:11px;background:var(--panel);color:var(--muted);padding:9px 11px;font-size:12px;font-weight:700;outline:none}.language-switch:focus{border-color:var(--signal)}
      @media(max-width:760px){.shell{grid-template-columns:1fr}.story{display:none}.auth{padding:40px 28px;min-height:480px}}
    </style></head>
    <body><div class="top-controls"><select id="theme-switch" class="language-switch" aria-label="Theme"><option value="system" data-i18n="theme_system">System</option><option value="light" data-i18n="theme_light">Light</option><option value="dark" data-i18n="theme_dark">Dark</option></select><select id="language-switch" class="language-switch" aria-label="Language"><option value="en">English</option><option value="zh-CN">简体中文</option></select></div><main class="shell"><section class="story"><div class="brand">SEN<span>GATEWAY</span></div><div><div class="eyebrow" data-i18n="brand_sub">Model traffic control</div><h1 data-i18n-html="hero_title">One route.<br>Every model.</h1><p data-i18n="hero_body">Inspect requests, control model routing, and keep agent context efficient from a single local gateway.</p></div><div class="signal"><i></i><span data-i18n="ready">Local control plane ready</span></div></section>
    <section class="auth"><h2 data-i18n="welcome">Welcome back</h2><p data-i18n="sign_in_body">Sign in to manage gateway traffic and routing.</p>
      <form id="login-form"><div class="field"><label for="username" data-i18n="username">Username</label><input id="username" type="text" name="username" autocomplete="username" required></div><div class="field"><label for="password" data-i18n="password">Password</label><input id="password" type="password" name="password" autocomplete="current-password" required></div><button type="submit" data-i18n="open">Open control plane</button><div id="login-error" class="error" role="alert"></div></form>
    </section></main><script>
    const loginMessages={en:{brand_sub:'Model traffic control',hero_title:'One route.<br>Every model.',hero_body:'Inspect requests, control model routing, and keep agent context efficient from a single local gateway.',ready:'Local control plane ready',welcome:'Welcome back',sign_in_body:'Sign in to manage gateway traffic and routing.',username:'Username',password:'Password',open:'Open control plane',invalid:'The username or password is incorrect.',theme_label:'Theme',language_label:'Language',theme_system:'System',theme_light:'Light',theme_dark:'Dark'},'zh-CN':{brand_sub:'模型流量控制台',hero_title:'一个网关，<br>连接所有模型',hero_body:'统一查看请求、切换模型，并减少不必要的上下文开销。',ready:'本地网关已就绪',welcome:'登录 Sen Gateway',sign_in_body:'登录后管理模型、请求记录和网关设置。',username:'用户名',password:'密码',open:'登录',invalid:'用户名或密码不正确。',theme_label:'主题',language_label:'语言',theme_system:'跟随系统',theme_light:'浅色',theme_dark:'深色'}};
    let loginLanguage=localStorage.getItem('sengateway-language')||'en';
    function applyLoginLanguage(lang){loginLanguage=loginMessages[lang]?lang:'en';localStorage.setItem('sengateway-language',loginLanguage);document.documentElement.lang=loginLanguage;document.getElementById('language-switch').value=loginLanguage;document.getElementById('theme-switch').setAttribute('aria-label',loginMessages[loginLanguage].theme_label);document.getElementById('language-switch').setAttribute('aria-label',loginMessages[loginLanguage].language_label);document.querySelectorAll('[data-i18n]').forEach(el=>el.textContent=loginMessages[loginLanguage][el.dataset.i18n]);document.querySelectorAll('[data-i18n-html]').forEach(el=>el.innerHTML=loginMessages[loginLanguage][el.dataset.i18nHtml]);document.title=loginLanguage==='zh-CN'?'登录 — Sen Gateway':'Sign in — Sen Gateway';}
    function applyLoginTheme(theme,persist=true){const selected=['system','light','dark'].includes(theme)?theme:'system';if(persist)localStorage.setItem('sengateway-theme',selected);const resolved=selected==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):selected;document.documentElement.dataset.theme=resolved;document.documentElement.style.colorScheme=resolved;document.getElementById('theme-switch').value=selected;}
    const loginSystemTheme=matchMedia('(prefers-color-scheme: dark)');loginSystemTheme.addEventListener('change',()=>{if((localStorage.getItem('sengateway-theme')||'system')==='system')applyLoginTheme('system',false)});
    document.getElementById('theme-switch').addEventListener('change',e=>applyLoginTheme(e.target.value));document.getElementById('language-switch').addEventListener('change',e=>applyLoginLanguage(e.target.value));applyLoginTheme(localStorage.getItem('sengateway-theme')||'system',false);applyLoginLanguage(loginLanguage);
    document.getElementById('login-form').addEventListener('submit',async(e)=>{e.preventDefault();const error=document.getElementById('login-error');error.textContent='';const r=await fetch('/api/login',{method:'POST',body:new URLSearchParams(new FormData(e.target))});if(r.ok)location.href='/dashboard';else error.textContent=loginMessages[loginLanguage].invalid});</script></body></html>
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
    let LAST_CONFIG = null;
    let CURRENT_LANGUAGE = localStorage.getItem('sengateway-language') || 'en';
    const I18N = {
        en: {
            brand_sub:'Model traffic control', traffic:'Traffic', routing:'Routing', gateway_online:'Gateway online', clear_logs:'Clear logs', sign_out:'Sign out', refresh:'Refresh', audit:'Audit', theme_label:'Theme', language_label:'Language', theme_system:'System', theme_light:'Light', theme_dark:'Dark',
            audit_title:'Context efficiency audit', audit_eyebrow:'Echo Retention V5 · Cost estimate', audit_subtitle:'Compare the captured request with the payload sent upstream.', close_audit:'Close audit', turn:'Turn', raw_tokens:'Raw tokens', raw_cost:'Raw cost', final_tokens:'Final tokens', final_cost:'Final cost', cost_change:'Cost change',
            empty_kicker:'Request observability', empty_title:'Follow every payload through the gateway.', empty_body:'Select a request to compare its original context, optimized payload, and model response side by side.', request:'Request', retention:'Retention', response:'Response', loading_request:'Loading request',
            request_inspection:'Request inspection', captured:'Captured', latency:'Latency', original_request:'Original request', optimized_payload:'Optimized payload', model_response:'Model response', download_json:'Download JSON',
            runtime_configuration:'Runtime configuration', config_title:'Route models with intent.', config_body:'Choose the upstream model, protect credentials, and tune how requests leave this local control plane.', model_route:'Model route', model_route_help:'The active upstream for all OpenAI-compatible requests.', provider:'Provider', model:'Model', upstream_key:'Upstream API key', not_configured:'Not configured', save_routing:'Save routing configuration',
            context_retention:'Context retention', retention_help:'Echo Retention V5 trims historical tool output.', history_compression:'History compression', compression_help:'Reduce repeated context while preserving recent reasoning.', content_language:'Content language', enable_compression:'Enable history compression', outbound_network:'Outbound network', outbound_help:'Optional proxy for all upstream requests.', use_proxy:'Use proxy', proxy_help:'Route provider traffic through a local or remote proxy.', enable_proxy:'Enable outbound proxy', proxy_url:'Proxy URL', save_proxy:'Save proxy settings',
            custom_registry:'Custom model registry', custom_help:'Add an unlisted model without changing the built-in catalog.', display_name:'Display name', model_id_placeholder:'Provider model ID, e.g. openai/gpt-5.6', add_custom:'Add custom model', no_custom:'No custom models registered.', remove:'Remove', custom_suffix:'Custom',
            no_traffic:'No traffic yet', no_traffic_help:'Requests sent through the gateway will appear here.', select_for_audit:'Select request {id} for audit', unknown_model:'Unknown model', success:'success', error:'error', chars:'k chars', truncated:'TRUNCATED', analyzing:'Analyzing Cache Streams (Echo Retention Audit)...', standard_cost:'Baseline cost', gateway_cost:'Gateway cost', efficiency:'Efficiency', hit:'Hit', savings:'Savings', overhead:'Overhead', audit_positive:'The optimized payload reduced the estimated cost across the selected requests.', audit_negative:'No savings in this sample. For short requests, fixed routing fields may outweigh pruning gains.', audit_neutral:'The estimated cost is unchanged for the selected requests.', selected_requests:'{count} requests selected', estimate_note:'Estimate based on payload characters and reference token rates; actual billing may differ.',
            reasoning_strength:'Reasoning strength', reasoning_help:'Choose response speed or deeper model deliberation. Explicit request parameters take priority.', reasoning_fast:'Fast', reasoning_deep:'Deep', reasoning_max:'Maximum', reasoning_saved:'Reasoning strength saved.', reasoning_save_error:'Reasoning strength could not be saved.',
            key_keep_placeholder:'Leave blank to keep the saved key', key_configured:'Configured — leave blank to keep unchanged.', add_model_error:'Add a model name and model ID.', custom_added:'Custom model added.', delete_model:'Delete this model?', model_save_error:'Model configuration could not be saved.', model_saved:'Routing configuration saved.', proxy_save_error:'Proxy settings could not be saved.', proxy_saved:'Proxy settings saved.', clear_confirm:'Clear all logs?'
        },
        'zh-CN': {
            brand_sub:'模型流量控制台', traffic:'请求', routing:'模型路由', gateway_online:'网关运行正常', clear_logs:'清空记录', sign_out:'退出', refresh:'刷新', audit:'分析', theme_label:'主题', language_label:'语言', theme_system:'跟随系统', theme_light:'浅色', theme_dark:'深色',
            audit_title:'上下文优化分析', audit_eyebrow:'Echo Retention V5 · 成本试算', audit_subtitle:'对比原始请求与上游实际收到的内容，估算上下文优化效果。', close_audit:'关闭分析', turn:'请求', raw_tokens:'优化前 Token', raw_cost:'优化前成本', final_tokens:'优化后 Token', final_cost:'优化后成本', cost_change:'成本增减',
            empty_kicker:'请求追踪', empty_title:'查看请求在网关中的处理过程', empty_body:'选择左侧请求，查看原始内容、优化结果和模型返回。', request:'原始请求', retention:'上下文优化', response:'模型返回', loading_request:'正在加载请求',
            request_inspection:'请求详情', captured:'请求时间', latency:'耗时', original_request:'原始内容', optimized_payload:'发送内容', model_response:'模型返回', download_json:'下载 JSON',
            runtime_configuration:'网关设置', config_title:'配置模型与网络', config_body:'选择默认模型、管理 API 密钥，并设置上下文优化和网络代理。', model_route:'默认模型', model_route_help:'所有 OpenAI 兼容请求默认转发到这里。', provider:'服务商', model:'模型', upstream_key:'API 密钥', not_configured:'尚未配置', save_routing:'保存模型设置',
            context_retention:'上下文优化', retention_help:'自动清理历史工具输出，减少重复内容。', history_compression:'压缩历史消息', compression_help:'保留近期上下文，同时减少重复或过期内容。', content_language:'内容语言', enable_compression:'启用历史消息压缩', outbound_network:'网络代理', outbound_help:'如有需要，可让上游请求通过代理发送。', use_proxy:'启用代理', proxy_help:'通过指定的代理地址访问模型服务。', enable_proxy:'启用网络代理', proxy_url:'代理地址', save_proxy:'保存代理设置',
            custom_registry:'自定义模型', custom_help:'添加内置列表中没有的模型。', display_name:'显示名称', model_id_placeholder:'模型 ID，例如 openai/gpt-5.6', add_custom:'添加模型', no_custom:'还没有自定义模型。', remove:'删除', custom_suffix:'自定义',
            no_traffic:'还没有请求记录', no_traffic_help:'通过网关调用模型后，请求会显示在这里。', select_for_audit:'选择请求 {id} 进行上下文分析', unknown_model:'未知模型', success:'成功', error:'失败', chars:'k 字符', truncated:'内容已截断', analyzing:'正在分析上下文优化效果…', standard_cost:'优化前成本', gateway_cost:'优化后成本', efficiency:'优化效果', hit:'缓存命中', savings:'预计节省', overhead:'额外成本', audit_positive:'所选请求经过优化后，预计成本有所下降。', audit_negative:'这组请求较短，新增的路由信息超过了裁剪掉的内容，因此暂未节省成本。', audit_neutral:'优化前后的预计成本基本一致。', selected_requests:'已选 {count} 条请求', estimate_note:'结果按字符数和参考价格估算，仅供比较；实际费用以服务商账单为准。',
            reasoning_strength:'推理强度', reasoning_help:'在响应速度和思考深度之间选择；请求中显式传入的参数优先。', reasoning_fast:'快速', reasoning_deep:'深入', reasoning_max:'极致', reasoning_saved:'推理强度已保存。', reasoning_save_error:'推理强度保存失败。',
            key_keep_placeholder:'不填写将继续使用已保存的密钥', key_configured:'密钥已保存；如不更换，请留空。', add_model_error:'请填写模型名称和模型 ID。', custom_added:'模型已添加。', delete_model:'确定删除这个模型吗？', model_save_error:'模型设置保存失败。', model_saved:'模型设置已保存。', proxy_save_error:'代理设置保存失败。', proxy_saved:'代理设置已保存。', clear_confirm:'确定清空所有请求记录吗？'
        }
    };

    function t(key, vars={}) {
        let value = (I18N[CURRENT_LANGUAGE] || I18N.en)[key] || I18N.en[key] || key;
        Object.entries(vars).forEach(([name, replacement]) => value = value.replace('{'+name+'}', replacement));
        return value;
    }

    function translateStatus(status) { return status === 'success' ? t('success') : status === 'error' ? t('error') : status; }

    function applyTheme(theme, persist=true) {
        const selected = ['system','light','dark'].includes(theme) ? theme : 'system';
        if(persist) localStorage.setItem('sengateway-theme', selected);
        const resolved = selected === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : selected;
        document.documentElement.dataset.theme = resolved;
        document.documentElement.style.colorScheme = resolved;
        const control = document.getElementById('theme-switch');
        if(control) control.value = selected;
    }

    function applyLanguage(language, persist=true) {
        CURRENT_LANGUAGE = I18N[language] ? language : 'en';
        if(persist) localStorage.setItem('sengateway-language', CURRENT_LANGUAGE);
        document.documentElement.lang = CURRENT_LANGUAGE;
        document.getElementById('language-switch').value = CURRENT_LANGUAGE;
        document.querySelectorAll('[data-i18n]').forEach(el => el.textContent = t(el.dataset.i18n));
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => el.placeholder = t(el.dataset.i18nPlaceholder));
        document.querySelectorAll('[data-i18n-title]').forEach(el => el.title = t(el.dataset.i18nTitle));
        document.querySelectorAll('[data-i18n-aria-label]').forEach(el => el.setAttribute('aria-label', t(el.dataset.i18nAriaLabel)));
        document.title = CURRENT_LANGUAGE === 'zh-CN' ? 'Sen Gateway — 控制台' : 'Sen Gateway — Control Plane';
        if(LAST_CONFIG) updateApiKeyState();
        if(CURRENT_LOG_DATA) {
            document.getElementById('detail-status').textContent = translateStatus(CURRENT_LOG_DATA.status);
            ['code-raw','code-final','code-resp'].forEach(id => {
                const lenEl = document.getElementById(id+'-len');
                if(lenEl && document.getElementById(id).textContent) lenEl.textContent = (document.getElementById(id).textContent.length/1000).toFixed(1) + t('chars');
            });
        }
        loadLogList();
        renderCustomModelList();
        const auditOverlay = document.getElementById('audit-overlay');
        if(auditOverlay && !auditOverlay.classList.contains('hidden') && SELECTED_LOGS.length) runAudit();
    }
    const STATIC_MODEL_OPTIONS = {
        "gemini": [
            {"val": "gemini/gemini-3.7-flash", "label": "Gemini 3.7 Flash"},
            {"val": "gemini/gemini-3.6-flash", "label": "Gemini 3.6 Flash"},
            {"val": "gemini/gemini-3.5-flash", "label": "Gemini 3.5 Flash"},
            {"val": "gemini/gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite"},
            {"val": "gemini/gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro"},
            {"val": "gemini/gemini-3-flash-preview", "label": "Gemini 3 Flash"},
            {"val": "gemini/gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash-Lite"},
            {"val": "gemini/gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
            {"val": "gemini/gemini-2.5-flash", "label": "Gemini 2.5 Flash"}
        ],
        "openai": [
            {"val": "openai/gpt-5.6", "label": "GPT-5.6"},
            {"val": "openai/gpt-5.6-sol", "label": "GPT-5.6 Sol"},
            {"val": "openai/gpt-5.6-terra", "label": "GPT-5.6 Terra"},
            {"val": "openai/gpt-5.6-luna", "label": "GPT-5.6 Luna"},
            {"val": "openai/gpt-5.5", "label": "GPT-5.5"},
            {"val": "openai/gpt-5.4", "label": "GPT-5.4"},
            {"val": "openai/gpt-5.4-mini", "label": "GPT-5.4 Mini"},
            {"val": "openai/gpt-5.4-nano", "label": "GPT-5.4 Nano"},
            {"val": "openai/o3-2025-04-16", "label": "OpenAI o3"},
            {"val": "openai/o4-mini-2025-04-16", "label": "OpenAI o4-mini"}
        ],
        "anthropic": [
            {"val": "anthropic/claude-opus-5", "label": "Claude Opus 5"},
            {"val": "anthropic/claude-sonnet-5", "label": "Claude Sonnet 5"},
            {"val": "anthropic/claude-opus-4-8", "label": "Claude Opus 4.8"},
            {"val": "anthropic/claude-opus-4-7", "label": "Claude Opus 4.7"},
            {"val": "anthropic/claude-opus-4-6", "label": "Claude 4.6 Opus"},
            {"val": "anthropic/claude-sonnet-4-6", "label": "Claude 4.6 Sonnet"},
            {"val": "anthropic/claude-haiku-4-5", "label": "Claude 4.5 Haiku"}
        ],
        "deepseek": [
            {"val": "deepseek/deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
            {"val": "deepseek/deepseek-v4-flash", "label": "DeepSeek V4 Flash"}
        ],
        "bedrock": [
            {"val": "bedrock/global.anthropic.claude-opus-5", "label": "Bedrock Claude Opus 5 (Global)"},
            {"val": "bedrock/global.anthropic.claude-sonnet-5", "label": "Bedrock Claude Sonnet 5 (Global)"},
            {"val": "bedrock/global.anthropic.claude-opus-4-8", "label": "Bedrock Claude Opus 4.8 (Global)"},
            {"val": "bedrock/global.anthropic.claude-opus-4-7", "label": "Bedrock Claude Opus 4.7 (Global)"},
            {"val": "bedrock/global.anthropic.claude-opus-4-6-v1", "label": "Bedrock Claude Opus 4.6 (Global)"},
            {"val": "bedrock/global.anthropic.claude-sonnet-4-6", "label": "Bedrock Claude Sonnet 4.6 (Global)"},
            {"val": "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0", "label": "Bedrock Claude Haiku 4.5 (Global)"}
        ]
    };

    function getModelOptions() {
        const options = JSON.parse(JSON.stringify(STATIC_MODEL_OPTIONS));
        CUSTOM_MODELS.forEach(m => {
            if (!options[m.provider]) options[m.provider] = [];
            options[m.provider].push({"val": m.value, "label": m.name + " (" + t('custom_suffix') + ")", "id": m.id});
        });
        return options;
    }

    async function loadLogList() {
        const res = await fetch('/api/logs');
        if(res.status === 401) { window.location.href = '/login'; return; }
        const logs = await res.json();
        const listEl = document.getElementById('log-list');
        document.getElementById('traffic-count').textContent = logs.length;
        if(logs.length === 0) {
            listEl.innerHTML = `<div class="empty-list"><span class="empty-list-mark">0</span><strong>${t('no_traffic')}</strong><p>${t('no_traffic_help')}</p></div>`;
            return;
        }
        listEl.innerHTML = logs.map(l => `
            <div id="log-item-${l.id}" class="log-item ${SELECTED_LOGS.includes(l.id)?'is-audit-selected':''}" onclick="selectLog(${l.id})">
                <input type="checkbox" aria-label="${t('select_for_audit',{id:l.id})}" onclick="event.stopPropagation(); toggleSelection(${l.id})" ${SELECTED_LOGS.includes(l.id)?'checked':''}>
                <div class="flex-1 overflow-hidden">
                    <div class="log-meta"><span>REQ-${String(l.id).padStart(4,'0')}</span><span class="status-dot ${l.status==='success'?'is-success':'is-error'}">${translateStatus(l.status)}</span></div>
                    <div class="log-model">${l.model || t('unknown_model')}</div>
                    <div class="log-foot"><span>${l.timestamp}</span><span>${l.latency || 0} ms</span></div>
                </div>
            </div>`).join('');
    }

    function toggleSelection(id) {
        const i = SELECTED_LOGS.indexOf(id);
        if(i > -1) SELECTED_LOGS.splice(i, 1); else SELECTED_LOGS.push(id);
        document.getElementById('log-item-'+id).classList.toggle('is-audit-selected', i===-1);
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
        document.getElementById('detail-time').textContent = log.timestamp;
        document.getElementById('detail-latency').textContent = (log.latency || 0) + ' ms';
        const statusEl = document.getElementById('detail-status');
        statusEl.textContent = translateStatus(log.status);
        statusEl.className = 'detail-status ' + (log.status === 'success' ? 'is-success' : 'is-error');
        
        CURRENT_LOG_DATA = log; // Store for download

        const setCode = (cid, data) => {
            const el = document.getElementById(cid);
            const str = JSON.stringify(data, null, 2);
            el.textContent = str.length > 50000 ? str.substring(0, 50000) + '\\n\\n... [' + t('truncated') + '] ...' : str;
            hljs.highlightElement(el);
            const lenEl = document.getElementById(cid+'-len');
            if(lenEl) { lenEl.textContent = (str.length/1000).toFixed(1) + t('chars'); }
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
        
        resultsEl.innerHTML = `<div class="audit-loading"><span></span>${t('analyzing')}</div>`;
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
            
            const costChange = rCost > 0 ? ((fCost - rCost) / rCost) * 100 : 0;
            const rowTone = costChange > 0.05 ? 'negative' : costChange < -0.05 ? 'positive' : 'neutral';
            const rowChange = `${costChange > 0 ? '+' : ''}${costChange.toFixed(1)}%`;
            
            return `<tr>
                <td data-label="${t('turn')}"><span class="audit-turn">#${l.id}</span></td>
                <td data-label="${t('raw_tokens')}"><span><strong>${rTok}</strong> <span class="audit-hit">${t('hit')} ${rMatchTok}</span></span></td>
                <td data-label="${t('raw_cost')}">$${rCost.toFixed(6)}</td>
                <td data-label="${t('final_tokens')}"><span><strong>${fTok}</strong> <span class="audit-hit">${t('hit')} ${fMatchTok}</span></span></td>
                <td data-label="${t('final_cost')}"><strong>$${fCost.toFixed(6)}</strong></td>
                <td data-label="${t('cost_change')}"><span class="audit-change ${rowTone}">${rowChange}</span></td>
            </tr>`;
        }).join('');

        const totalDelta = totalCostFin - totalCostRaw;
        const efficiency = totalCostRaw > 0 ? ((totalCostRaw - totalCostFin) / totalCostRaw) * 100 : 0;
        const tone = efficiency > 0.05 ? 'positive' : efficiency < -0.05 ? 'negative' : 'neutral';
        const outcomeLabel = tone === 'positive' ? t('savings') : tone === 'negative' ? t('overhead') : t('efficiency');
        const outcomeText = tone === 'positive' ? t('audit_positive') : tone === 'negative' ? t('audit_negative') : t('audit_neutral');
        const outcomeValue = `${tone === 'negative' || tone === 'positive' ? '+' : ''}${Math.abs(efficiency).toFixed(1)}%`;
        resultsEl.innerHTML = `
            <div class="audit-outcome ${tone}">
                <div><span class="audit-outcome-label">${outcomeLabel}</span><strong>${outcomeValue}</strong></div>
                <p>${outcomeText}</p>
            </div>
            <div class="audit-metrics">
                <div class="audit-metric"><span>${t('standard_cost')}</span><strong>$${totalCostRaw.toFixed(6)}</strong></div>
                <div class="audit-metric"><span>${t('gateway_cost')}</span><strong>$${totalCostFin.toFixed(6)}</strong></div>
                <div class="audit-metric"><span>${t('cost_change')}</span><strong class="${tone}">${totalDelta >= 0 ? '+' : '−'}$${Math.abs(totalDelta).toFixed(6)}</strong></div>
            </div>`;
        tableEl.innerHTML = rows;
        document.getElementById('audit-selection-count').textContent = t('selected_requests', {count:data.length});
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
        LAST_CONFIG = d;
        document.getElementById('model-provider').value = d.model.provider;
        updateModelOptions(d.model.name);
        document.getElementById('api-key').value = '';
        updateApiKeyState();
        document.getElementById('comp-enabled').checked = d.pruning.enabled;
        document.getElementById('comp-language').value = d.pruning.language || 'en';
        document.getElementById('reasoning-mode').value = d.reasoning?.mode || 'fast';
        document.getElementById('proxy-enabled').checked = d.proxy.enabled;
        document.getElementById('proxy-url').value = d.proxy.url;
        renderCustomModelList();
    }

    function updateApiKeyState() {
        if(!LAST_CONFIG) return;
        const apiKeyInput = document.getElementById('api-key');
        const apiKeyStatus = document.getElementById('api-key-status');
        const provider = document.getElementById('model-provider').value;
        const hasKey = Boolean(LAST_CONFIG.model.provider_keys?.[provider]);
        apiKeyInput.placeholder = hasKey ? t('key_keep_placeholder') : '';
        apiKeyStatus.textContent = hasKey ? t('key_configured') : t('not_configured');
        apiKeyStatus.className = hasKey ? 'field-help is-success' : 'field-help';
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
        if(!name || !value) { showToast(t('add_model_error'), 'error'); return; }
        
        const res = await fetch('/api/models/custom', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({provider, name, value})
        });
        if(res.ok) {
            document.getElementById('add-model-name').value = '';
            document.getElementById('add-model-value').value = '';
            await loadConfig();
            showToast(t('custom_added'));
        }
    }

    async function deleteCustomModel(id) {
        if(!confirm(t('delete_model'))) return;
        await fetch('/api/models/custom/' + id, {method: 'DELETE'});
        await loadConfig();
    }

    function renderCustomModelList() {
        const listEl = document.getElementById('custom-model-list');
        listEl.innerHTML = CUSTOM_MODELS.map(m => `
            <div class="custom-model">
                <span><b>${m.provider.toUpperCase()}</b> · ${m.name} <span class="text-gray-500">${m.value}</span></span>
                <button onclick="deleteCustomModel(${m.id})">${t('remove')}</button>
            </div>
        `).join('') || `<div class="field-help" style="margin-top:14px">${t('no_custom')}</div>`;
    }

    async function saveModel() {
        const body = { provider: document.getElementById('model-provider').value, name: document.getElementById('model-select').value, api_key: document.getElementById('api-key').value };
        const res = await fetch('/api/config/model', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        if (!res.ok) { showToast(t('model_save_error'), 'error'); return; }
        await loadConfig();
        showToast(t('model_saved'));
    }

    async function saveComp(v) { await fetch('/api/config/pruning', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({enabled:v})}); }
    async function saveCompLang(v) { await fetch('/api/config/pruning', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({language:v})}); }
    async function saveReasoning(v) {
        const res = await fetch('/api/config/reasoning', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({mode:v})});
        if (!res.ok) { showToast(t('reasoning_save_error'), 'error'); return; }
        showToast(t('reasoning_saved'));
    }
    async function saveProxy() {
        const body = { enabled: document.getElementById('proxy-enabled').checked, url: document.getElementById('proxy-url').value };
        const res = await fetch('/api/config/proxy', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        if (!res.ok) { showToast(t('proxy_save_error'), 'error'); return; }
        showToast(t('proxy_saved'));
    }

    function showToast(message, kind='success') {
        const toast = document.getElementById('toast');
        toast.textContent = message;
        toast.className = 'toast is-visible ' + (kind === 'error' ? 'is-error' : 'is-success');
        clearTimeout(window.__toastTimer);
        window.__toastTimer = setTimeout(() => toast.classList.remove('is-visible'), 2600);
    }
    
    async function clearLogs() { if(confirm(t('clear_confirm'))) { await fetch('/api/logs', {method:'DELETE'}); loadLogList(); } }

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

    const systemTheme = matchMedia('(prefers-color-scheme: dark)');
    systemTheme.addEventListener('change', () => {
        if((localStorage.getItem('sengateway-theme') || 'system') === 'system') applyTheme('system', false);
    });
    document.addEventListener('DOMContentLoaded', () => {
        applyTheme(localStorage.getItem('sengateway-theme') || 'system', false);
        applyLanguage(CURRENT_LANGUAGE, false);
    });
    """

    return f"""
    <!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sen Gateway — Control Plane</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <style>
        :root{{--bg:#17181d;--panel:#202126;--panel-2:#272930;--line:#34363e;--line-soft:#2b2d34;--ink:#f1f3f7;--muted:#a8adb8;--faint:#747a87;--signal:#6f8cff;--signal-hover:#88a0ff;--signal-soft:rgba(111,140,255,.15);--positive:#43c58a;--positive-soft:rgba(67,197,138,.12);--danger:#ff7b87;--danger-soft:rgba(255,123,135,.12);--warn:#f0bf67;--code:#14151a;--header:rgba(23,24,29,.9);--field:#292b32;--hover:#292b32;--shadow:0 18px 45px rgba(0,0,0,.22);--grid:rgba(111,140,255,.025)}}
        html[data-theme="light"]{{--bg:#f7f8fc;--panel:#ffffff;--panel-2:#f3f5fa;--line:#e2e5ed;--line-soft:#eceef4;--ink:#20232d;--muted:#6e7482;--faint:#9298a5;--signal:#4d6bfe;--signal-hover:#3f5be7;--signal-soft:rgba(77,107,254,.1);--positive:#16895c;--positive-soft:rgba(22,137,92,.09);--danger:#dc5965;--danger-soft:rgba(220,89,101,.09);--warn:#b17a20;--code:#f7f8fb;--header:rgba(255,255,255,.88);--field:#f7f8fc;--hover:#f3f5fb;--shadow:0 18px 45px rgba(31,42,79,.08);--grid:rgba(77,107,254,.03)}}
        *{{box-sizing:border-box}} html,body{{height:100%}} body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px;transition:background .2s ease,color .2s ease}}
        button,input,select{{font:inherit}} button{{cursor:pointer}} ::selection{{background:var(--signal-soft)}}
        ::-webkit-scrollbar{{width:7px;height:7px}} ::-webkit-scrollbar-track{{background:transparent}} ::-webkit-scrollbar-thumb{{background:var(--line);border-radius:10px}}
        .app-header{{height:72px;display:flex;align-items:center;justify-content:space-between;padding:0 24px;border-bottom:1px solid var(--line);background:var(--header);backdrop-filter:blur(18px);position:relative;z-index:30;flex:none}}
        .brand-lockup{{display:flex;align-items:center;gap:14px}} .brand-mark{{width:36px;height:36px;border:0;border-radius:11px;background:var(--signal);display:grid;place-items:center;color:#fff;font:800 11px ui-monospace,monospace;box-shadow:0 8px 20px var(--signal-soft)}}
        .brand-name{{font-weight:800;letter-spacing:.07em}} .brand-name span{{color:var(--signal)}} .brand-sub{{font-size:10px;color:var(--faint);letter-spacing:.12em;text-transform:uppercase;margin-top:2px}}
        .header-left,.header-actions,.main-nav{{display:flex;align-items:center}} .header-left{{gap:34px}} .main-nav{{gap:4px;background:var(--panel-2);border:1px solid var(--line-soft);padding:4px;border-radius:12px}}
        .nav-item{{border:0;border-radius:9px;background:transparent;color:var(--muted);padding:8px 14px;font-size:12px;font-weight:700;letter-spacing:.02em;transition:.18s ease}} .nav-item:hover{{color:var(--ink);background:var(--hover)}} .nav-item.active{{background:var(--panel);color:var(--signal);box-shadow:0 2px 9px rgba(0,0,0,.08)}}
        .header-actions{{gap:12px}} .status-live{{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:11px;margin-right:8px}} .status-live i{{width:7px;height:7px;border-radius:50%;background:var(--signal);box-shadow:0 0 14px var(--signal)}}
        .ghost-action{{border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--muted);padding:8px 11px;font-size:11px;font-weight:700}} .ghost-action:hover{{border-color:var(--signal);color:var(--ink)}} .ghost-action.danger:hover{{border-color:rgba(255,120,120,.6);color:var(--danger)}}
        .language-control{{border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--muted);padding:8px 9px;font-size:11px;font-weight:700;outline:none}} .language-control:focus{{border-color:var(--signal)}}
        .app-main{{height:calc(100vh - 72px);min-height:0;padding:14px;background:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px),var(--bg);background-size:34px 34px}} #section-monitor{{height:100%;display:grid;grid-template-columns:300px minmax(0,1fr);gap:14px}}
        .traffic-rail{{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:18px;overflow:hidden;display:flex;flex-direction:column;box-shadow:var(--shadow)}} .rail-head{{height:62px;padding:0 16px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line-soft)}}
        .section-label{{font-size:10px;text-transform:uppercase;letter-spacing:.15em;color:var(--muted);font-weight:800}} .count-badge{{display:inline-grid;place-items:center;min-width:22px;height:22px;padding:0 6px;margin-left:7px;background:var(--signal-soft);color:var(--signal);font:700 10px ui-monospace,monospace}}
        .rail-actions{{display:flex;gap:6px}} .rail-action{{min-height:32px;border:1px solid var(--line);border-radius:9px;background:var(--panel-2);color:var(--muted);padding:0 9px;font-size:10px;font-weight:700}} .rail-action:hover{{color:var(--signal);border-color:var(--signal)}} .rail-action.primary{{background:var(--signal);border-color:var(--signal);color:#fff}}
        #log-list{{flex:1;overflow:auto;padding:6px}} .log-item{{display:flex;gap:11px;padding:15px 12px;border:1px solid transparent;border-radius:12px;cursor:pointer;transition:.16s ease}} .log-item:hover{{background:var(--hover)}} .log-item.bg-blue-50{{background:var(--signal-soft)!important;border-color:var(--signal)!important}} .log-item input{{margin-top:2px;accent-color:var(--signal)}}
        .log-item.is-audit-selected{{background:rgba(243,198,107,.07)}} .log-meta,.log-foot{{display:flex;justify-content:space-between;gap:10px;font:600 9px ui-monospace,monospace;color:var(--faint);letter-spacing:.04em}} .log-model{{font-size:12px;font-weight:750;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:7px 0}} .status-dot{{display:inline-flex;align-items:center;gap:5px;text-transform:uppercase}} .status-dot:before{{content:"";width:5px;height:5px;border-radius:50%;background:currentColor}} .is-success{{color:var(--signal)!important}} .is-error{{color:var(--danger)!important}}
        .empty-list{{min-height:260px;padding:42px 24px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:var(--muted)}} .empty-list-mark{{width:44px;height:44px;border:1px solid var(--line);border-radius:14px;background:var(--panel-2);display:grid;place-items:center;font:700 12px ui-monospace,monospace;color:var(--faint);margin-bottom:15px}} .empty-list strong{{color:var(--ink);font-size:13px}} .empty-list p{{font-size:11px;line-height:1.6;max-width:180px;margin:7px 0 0}}
        .workspace{{min-width:0;overflow:auto;background:radial-gradient(circle at 100% 0%,var(--signal-soft),transparent 32%),var(--panel);border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);position:relative;padding:26px}}
        .empty-workspace{{height:100%;min-height:360px;display:grid;place-items:center}} .empty-workspace-inner{{max-width:460px}} .empty-kicker{{font:700 10px ui-monospace,monospace;color:var(--signal);letter-spacing:.15em;text-transform:uppercase}} .empty-workspace h2{{font-size:30px;letter-spacing:-.035em;margin:13px 0 12px}} .empty-workspace p{{color:var(--muted);line-height:1.7;margin:0}} .empty-flow{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:28px}} .empty-flow span{{background:var(--panel-2);border:1px solid var(--line);border-radius:10px;padding:13px 11px;font:650 9px ui-monospace,monospace;text-transform:uppercase;color:var(--muted);text-align:center}}
        .loading-ring{{width:34px;height:34px;border:2px solid var(--line);border-top-color:var(--signal);border-radius:50%;animation:spin .8s linear infinite}} @keyframes spin{{to{{transform:rotate(360deg)}}}}
        #detail-content{{max-width:1600px;margin:0 auto}} .detail-head{{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:20px}} .detail-kicker{{font:700 10px ui-monospace,monospace;color:var(--signal);text-transform:uppercase;letter-spacing:.14em}} .detail-title{{font-size:24px;letter-spacing:-.025em;margin:7px 0 0}} #detail-id{{color:var(--faint);font:600 13px ui-monospace,monospace;margin-right:8px}}
        .detail-facts{{display:flex;align-items:center;gap:18px}} .fact{{display:grid;gap:4px}} .fact label{{font-size:9px;text-transform:uppercase;letter-spacing:.12em;color:var(--faint)}} .fact span{{font:650 11px ui-monospace,monospace;color:var(--muted)}} .detail-status{{padding:7px 10px;border:1px solid currentColor;border-radius:999px;font:750 9px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.08em}}
        .payload-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}} .payload-panel{{min-width:0;height:calc(100vh - 184px);min-height:480px;display:flex;flex-direction:column;background:var(--panel-2);border:1px solid var(--line);border-radius:15px;overflow:hidden}} .payload-head{{height:42px;display:flex;align-items:center;justify-content:space-between;padding:0 13px;border-bottom:1px solid var(--line);font:750 9px ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase}} .payload-head>span:last-child{{color:var(--faint);letter-spacing:0;text-transform:none}} .payload-panel pre{{margin:0;flex:1;min-height:0;overflow:auto;background:var(--code)}} .payload-panel code,.payload-panel code.hljs{{display:block;background:transparent;padding:16px;font:11px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink)}} html[data-theme="light"] .hljs-attr{{color:#a626a4}} html[data-theme="light"] .hljs-string{{color:#50a14f}} html[data-theme="light"] .hljs-literal,html[data-theme="light"] .hljs-number{{color:#0184bc}} .download-action{{height:36px;border:0;border-top:1px solid var(--line);background:var(--panel-2);color:var(--muted);font-size:10px;font-weight:700}} .download-action:hover{{background:var(--hover);color:var(--signal)}}
        .audit-overlay{{position:absolute;inset:0;z-index:50;background:var(--header);backdrop-filter:blur(18px);overflow:auto;padding:40px;border-radius:18px}} .audit-shell{{max-width:1050px;margin:0 auto}} .audit-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;margin-bottom:24px}} .audit-head h2{{font-size:28px;margin:6px 0 8px}} .audit-head p{{color:var(--muted);font-size:12px;margin:0}} .icon-close{{flex:none;border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--muted);width:38px;height:38px;font-size:22px}} .icon-close:hover{{border-color:var(--signal);color:var(--signal)}}
        #audit-results{{display:grid;gap:14px;margin-bottom:16px}} .audit-loading{{min-height:180px;display:flex;align-items:center;justify-content:center;gap:12px;border:1px solid var(--line);border-radius:16px;background:var(--panel);color:var(--muted);font-size:12px}} .audit-loading span{{width:18px;height:18px;border:2px solid var(--line);border-top-color:var(--signal);border-radius:50%;animation:spin .8s linear infinite}} .audit-outcome{{display:flex;align-items:center;justify-content:space-between;gap:28px;border:1px solid var(--line);border-radius:16px;padding:20px 22px;background:var(--panel)}} .audit-outcome>div{{display:grid;gap:6px;min-width:150px}} .audit-outcome-label{{font-size:10px;font-weight:750;letter-spacing:.1em;text-transform:uppercase}} .audit-outcome strong{{font:800 32px/1 ui-monospace,monospace}} .audit-outcome p{{max-width:520px;margin:0;color:var(--muted);font-size:12px;line-height:1.65}} .audit-outcome.positive{{border-color:var(--positive);background:var(--positive-soft)}} .audit-outcome.positive .audit-outcome-label,.audit-outcome.positive strong,.positive{{color:var(--positive)}} .audit-outcome.negative{{border-color:var(--danger);background:var(--danger-soft)}} .audit-outcome.negative .audit-outcome-label,.audit-outcome.negative strong,.negative{{color:var(--danger)}} .audit-outcome.neutral{{background:var(--panel-2)}} .neutral{{color:var(--muted)}}
        .audit-metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}} .audit-metric{{display:grid;gap:8px;border:1px solid var(--line);border-radius:14px;background:var(--panel);padding:16px 18px}} .audit-metric span{{color:var(--faint);font-size:9px;font-weight:750;letter-spacing:.1em;text-transform:uppercase}} .audit-metric strong{{font:750 18px ui-monospace,monospace;color:var(--ink)}}
        .audit-table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:15px;background:var(--panel);box-shadow:var(--shadow)}} .audit-table{{width:100%;border-collapse:collapse;text-align:left;font-size:11px}} .audit-table th{{background:var(--panel-2);color:var(--faint);text-transform:uppercase;letter-spacing:.08em;padding:13px 16px;white-space:nowrap}} .audit-table td{{padding:15px 16px;border-top:1px solid var(--line-soft);color:var(--muted);white-space:nowrap}} .audit-table td strong{{color:var(--ink)}} .audit-turn{{display:inline-flex;padding:5px 8px;border-radius:8px;background:var(--signal-soft);color:var(--signal);font:700 10px ui-monospace,monospace}} .audit-hit{{display:inline-flex;margin-left:5px;padding:3px 6px;border-radius:999px;background:var(--panel-2);color:var(--faint);font-size:9px}} .audit-change{{display:inline-flex;padding:5px 8px;border-radius:999px;font-weight:800}} .audit-change.positive{{background:var(--positive-soft)}} .audit-change.negative{{background:var(--danger-soft)}} .audit-footnote{{display:flex;justify-content:space-between;gap:20px;margin-top:12px;color:var(--faint);font-size:10px}} #audit-selection-count{{color:var(--muted);font-weight:700}}
        #section-config{{height:100%;overflow:auto;background:radial-gradient(circle at 80% 0%,var(--signal-soft),transparent 34%),var(--panel);border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);padding:36px}} .config-shell{{max-width:1120px;margin:0 auto}} .config-intro{{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:26px}} .config-intro h2{{font-size:30px;letter-spacing:-.04em;margin:6px 0 0}} .config-intro p{{color:var(--muted);max-width:420px;line-height:1.6;margin:0}}
        .config-grid{{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr);gap:16px;align-items:start}} .config-card{{background:var(--panel-2);border:1px solid var(--line);border-radius:16px;padding:24px}} .config-card.primary{{box-shadow:inset 0 3px 0 var(--signal)}} .config-card h3{{font-size:15px;margin:0}} .card-heading{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:22px}} .card-index{{font:700 10px ui-monospace,monospace;color:var(--signal)}} .field{{display:grid;gap:8px;margin-bottom:17px}} .field label{{font-size:9px;text-transform:uppercase;letter-spacing:.13em;color:var(--muted);font-weight:750}} .field input,.field select,.compact-input,.compact-select{{width:100%;border:1px solid var(--line);border-radius:11px;background:var(--field);color:var(--ink);padding:11px 12px;outline:none}} .field input:focus,.field select:focus,.compact-input:focus,.compact-select:focus{{border-color:var(--signal);box-shadow:0 0 0 3px var(--signal-soft)}} .field-help{{font-size:10px;color:var(--faint);margin:-2px 0 0}}
        .primary-action{{width:100%;border:0;border-radius:11px;background:var(--signal);color:#fff;padding:12px;font-weight:800}} .primary-action:hover{{background:var(--signal-hover)}} .secondary-action{{width:100%;border:1px solid var(--line);border-radius:11px;background:var(--panel);color:var(--ink);padding:10px;font-weight:700}} .secondary-action:hover{{border-color:var(--signal);color:var(--signal)}}
        .stack{{display:grid;gap:16px}} .setting-row{{display:flex;align-items:center;justify-content:space-between;gap:18px}} .setting-copy h3{{margin:0 0 5px}} .setting-copy p{{color:var(--muted);font-size:11px;margin:0;line-height:1.5}} .setting-controls{{display:flex;align-items:flex-end;gap:10px}} .setting-controls select{{width:auto}} .content-language{{display:grid;gap:6px;color:var(--faint);font-size:9px;font-weight:750;letter-spacing:.08em;text-transform:uppercase}} input[type="checkbox"]{{width:18px;height:18px;accent-color:var(--signal)}} .divider{{height:1px;background:var(--line-soft);margin:22px 0}}
        .custom-form{{display:grid;grid-template-columns:.75fr 1.25fr;gap:10px}} .custom-form .full{{grid-column:1/-1}} #custom-model-list{{display:grid;gap:8px;margin-top:14px}} .custom-model{{display:flex;align-items:center;justify-content:space-between;gap:12px;border:1px solid var(--line-soft);border-radius:11px;background:var(--panel);padding:10px;font-size:11px;color:var(--muted)}} .custom-model b{{color:var(--signal)}} .custom-model button{{border:0;background:transparent;color:var(--danger);font-size:10px}}
        .toast{{position:fixed;right:22px;bottom:22px;z-index:100;transform:translateY(20px);opacity:0;pointer-events:none;padding:12px 15px;background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow);color:var(--ink);font-size:12px;transition:.2s ease}} .toast.is-visible{{transform:none;opacity:1}} .toast.is-success{{border-left:3px solid var(--signal)}} .toast.is-error{{border-left:3px solid var(--danger)}}
        button:focus-visible,input:focus-visible,select:focus-visible{{outline:2px solid var(--signal);outline-offset:2px}} .hidden{{display:none!important}}
        @media(max-width:1080px){{.payload-grid{{grid-template-columns:1fr}} .payload-panel{{height:460px}} .config-grid{{grid-template-columns:1fr}}}}
        @media(max-width:760px){{.app-header{{height:auto;min-height:68px;padding:12px 10px;align-items:flex-start}} .brand-mark,.brand-name,.brand-sub,.status-live,.header-actions .danger{{display:none}} .header-left{{gap:6px;align-items:flex-start}} .brand-lockup{{display:none}} .main-nav{{margin-top:1px}} .nav-item{{padding:7px 9px}} .header-actions{{gap:4px}} .header-actions .ghost-action,.language-control{{padding:7px 6px;font-size:10px;max-width:78px}} .app-main{{height:calc(100vh - 68px);padding:10px}} #section-monitor{{grid-template-columns:1fr;grid-template-rows:230px minmax(0,1fr);gap:10px}} .traffic-rail{{border-right:1px solid var(--line);border-bottom:1px solid var(--line);border-radius:15px}} .workspace{{padding:18px;border-radius:15px}} .detail-head{{align-items:flex-start;flex-direction:column}} .detail-facts{{width:100%;justify-content:space-between;gap:10px}} .payload-panel{{height:420px;min-height:360px}} #section-config{{padding:22px 16px;border-radius:15px}} .config-intro{{align-items:flex-start;flex-direction:column}} .config-intro h2{{font-size:25px}} .config-card{{padding:19px}} .custom-form{{grid-template-columns:1fr}} .custom-form .full{{grid-column:auto}} .setting-row{{align-items:flex-start;flex-direction:column}} .setting-controls{{width:100%}} .setting-controls select{{flex:1}} .audit-overlay{{padding:22px 16px}}}}
        @media(max-width:760px){{.audit-overlay{{position:fixed;inset:68px 10px 10px;z-index:90;border:1px solid var(--line);padding:20px 16px;box-shadow:var(--shadow)}} .audit-head h2{{font-size:23px}} .audit-outcome{{align-items:flex-start;flex-direction:column;gap:12px;padding:18px}} .audit-outcome strong{{font-size:28px}} .audit-metrics{{grid-template-columns:1fr}} .audit-table-wrap{{overflow:visible;box-shadow:none;background:transparent;border:0}} .audit-table,.audit-table tbody,.audit-table tr,.audit-table td{{display:block;width:100%}} .audit-table thead{{display:none}} .audit-table tr{{border:1px solid var(--line);border-radius:14px;background:var(--panel);padding:8px 14px}} .audit-table td{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:10px 0;border-top:1px solid var(--line-soft);white-space:normal;text-align:right}} .audit-table td:first-child{{border-top:0}} .audit-table td:before{{content:attr(data-label);color:var(--faint);font-size:9px;font-weight:750;letter-spacing:.06em;text-transform:uppercase;text-align:left}} .audit-footnote{{flex-direction:column;gap:5px}}}}
        @media(prefers-reduced-motion:reduce){{*,*:before,*:after{{scroll-behavior:auto!important;animation:none!important;transition:none!important}}}}
    </style></head>
    <body>
        <header class="app-header">
            <div class="header-left"><div class="brand-lockup"><div class="brand-mark">SG</div><div><div class="brand-name">SEN<span>GATEWAY</span></div><div class="brand-sub" data-i18n="brand_sub">Model traffic control</div></div></div>
            <nav class="main-nav" aria-label="Primary navigation">
                <button onclick="showSection('monitor')" id="nav-monitor" class="nav-item active" data-i18n="traffic">Traffic</button>
                <button onclick="showSection('config')" id="nav-config" class="nav-item" data-i18n="routing">Routing</button>
            </nav></div>
            <div class="header-actions"><span class="status-live"><i></i><span data-i18n="gateway_online">Gateway online</span></span><select id="theme-switch" class="language-control" aria-label="Theme" data-i18n-aria-label="theme_label" onchange="applyTheme(this.value)"><option value="system" data-i18n="theme_system">System</option><option value="light" data-i18n="theme_light">Light</option><option value="dark" data-i18n="theme_dark">Dark</option></select><select id="language-switch" class="language-control" aria-label="Language" data-i18n-aria-label="language_label" onchange="applyLanguage(this.value)"><option value="en">English</option><option value="zh-CN">简体中文</option></select><button onclick="clearLogs()" class="ghost-action danger" data-i18n="clear_logs">Clear logs</button><form action="/api/logout" method="post"><button class="ghost-action" data-i18n="sign_out">Sign out</button></form></div>
        </header>

        <main class="app-main">
            <!-- Monitor View -->
            <div id="section-monitor">
                <!-- Sidebar -->
                <aside class="traffic-rail">
                    <div class="rail-head">
                        <span class="section-label"><span data-i18n="traffic">Traffic</span> <span id="traffic-count" class="count-badge">0</span></span>
                        <div class="rail-actions">
                            <button onclick="loadLogList()" class="rail-action" title="Refresh traffic logs" data-i18n="refresh" data-i18n-title="refresh">Refresh</button>
                            <button onclick="runAudit()" id="btn-audit" class="rail-action primary hidden" data-i18n="audit">Audit</button>
                        </div>
                    </div>
                    <div class="flex-1 overflow-y-auto" id="log-list"></div>
                </aside>

                <!-- Content Area -->
                <section class="workspace">
                    <!-- Audit Overlay -->
                    <div id="audit-overlay" class="audit-overlay hidden">
                        <div class="audit-shell">
                            <div class="audit-head"><div><div class="detail-kicker" data-i18n="audit_eyebrow">Echo Retention V5 · Cost estimate</div><h2 data-i18n="audit_title">Context efficiency audit</h2><p data-i18n="audit_subtitle">Compare the captured request with the payload sent upstream.</p></div><button onclick="closeAudit()" class="icon-close" aria-label="Close audit" data-i18n-aria-label="close_audit">&times;</button></div>
                            <div id="audit-results"></div>
                            <div class="audit-table-wrap">
                                <table class="audit-table">
                                    <thead><tr>
                                        <th data-i18n="turn">Turn</th><th data-i18n="raw_tokens">Raw tokens</th><th data-i18n="raw_cost">Raw cost</th><th data-i18n="final_tokens">Final tokens</th><th data-i18n="final_cost">Final cost</th><th data-i18n="cost_change">Cost change</th>
                                    </tr></thead>
                                    <tbody id="audit-table-body"></tbody>
                                </table>
                            </div>
                            <div class="audit-footnote"><span id="audit-selection-count"></span><span data-i18n="estimate_note">Estimate based on payload characters and reference token rates; actual billing may differ.</span></div>
                        </div>
                    </div>

                    <!-- Detail View -->
                    <div id="empty-state" class="empty-workspace"><div class="empty-workspace-inner"><div class="empty-kicker" data-i18n="empty_kicker">Request observability</div><h2 data-i18n="empty_title">Follow every payload through the gateway.</h2><p data-i18n="empty_body">Select a request to compare its original context, optimized payload, and model response side by side.</p><div class="empty-flow"><span data-i18n="request">Request</span><span data-i18n="retention">Retention</span><span data-i18n="response">Response</span></div></div></div>
                    <div id="loading-state" class="empty-workspace hidden"><div class="loading-ring" aria-label="Loading request" data-i18n-aria-label="loading_request"></div></div>
                    
                    <div id="detail-content" class="hidden">
                        <div class="detail-head">
                            <div><div class="detail-kicker" data-i18n="request_inspection">Request inspection</div><h2 class="detail-title"><span id="detail-id"></span><span id="detail-model"></span></h2></div>
                            <div class="detail-facts"><div class="fact"><label data-i18n="captured">Captured</label><span id="detail-time">—</span></div><div class="fact"><label data-i18n="latency">Latency</label><span id="detail-latency">—</span></div><div id="detail-status" class="detail-status"></div></div>
                        </div>
                        <div class="payload-grid">
                            <div class="payload-panel">
                                <div class="payload-head"><span>01 / <span data-i18n="original_request">Original request</span></span><span id="code-raw-len"></span></div>
                                <pre><code id="code-raw"></code></pre>
                                <button onclick="downloadJson('code-raw')" class="download-action" data-i18n="download_json">Download JSON</button>
                            </div>
                            <div class="payload-panel">
                                <div class="payload-head"><span>02 / <span data-i18n="optimized_payload">Optimized payload</span></span><span id="code-final-len"></span></div>
                                <pre><code id="code-final"></code></pre>
                                <button onclick="downloadJson('code-final')" class="download-action" data-i18n="download_json">Download JSON</button>
                            </div>
                            <div class="payload-panel">
                                <div class="payload-head"><span>03 / <span data-i18n="model_response">Model response</span></span><span id="code-resp-len"></span></div>
                                <pre><code id="code-resp"></code></pre>
                                <button onclick="downloadJson('code-resp')" class="download-action" data-i18n="download_json">Download JSON</button>
                            </div>
                        </div>
                    </div>
                </section>
            </div>

            <!-- Config View -->
            <div id="section-config" class="hidden">
                <div class="config-shell">
                    <div class="config-intro"><div><div class="detail-kicker" data-i18n="runtime_configuration">Runtime configuration</div><h2 data-i18n="config_title">Route models with intent.</h2></div><p data-i18n="config_body">Choose the upstream model, protect credentials, and tune how requests leave this local control plane.</p></div>
                    <div class="config-grid">
                        <section class="config-card primary">
                            <div class="card-heading"><div><h3 data-i18n="model_route">Model route</h3><p class="field-help" data-i18n="model_route_help">The active upstream for all OpenAI-compatible requests.</p></div><span class="card-index">01</span></div>
                            <div class="field"><label for="model-provider" data-i18n="provider">Provider</label><select id="model-provider" onchange="updateModelOptions(); updateApiKeyState()"><option value="gemini">Google Gemini</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="deepseek">DeepSeek</option><option value="bedrock">AWS Bedrock</option></select></div>
                            <div class="field"><label for="model-select" data-i18n="model">Model</label><select id="model-select"></select></div>
                            <div class="field"><label for="reasoning-mode" data-i18n="reasoning_strength">Reasoning strength</label><select id="reasoning-mode" onchange="saveReasoning(this.value)" aria-label="Reasoning strength" data-i18n-aria-label="reasoning_strength"><option value="fast" data-i18n="reasoning_fast">Fast</option><option value="deep" data-i18n="reasoning_deep">Deep</option><option value="max" data-i18n="reasoning_max">Maximum</option></select><p class="field-help" data-i18n="reasoning_help">Choose response speed or deeper model deliberation. Explicit request parameters take priority.</p></div>
                            <div class="field"><label for="api-key" data-i18n="upstream_key">Upstream API key</label><input type="password" id="api-key" autocomplete="new-password"><p id="api-key-status" class="field-help" data-i18n="not_configured">Not configured</p></div>
                            <button onclick="saveModel()" class="primary-action" data-i18n="save_routing">Save routing configuration</button>
                        </section>

                        <div class="stack">
                            <section class="config-card">
                                <div class="card-heading"><div><h3 data-i18n="context_retention">Context retention</h3><p class="field-help" data-i18n="retention_help">Echo Retention V5 trims historical tool output.</p></div><span class="card-index">02</span></div>
                                <div class="setting-row"><div class="setting-copy"><h3 data-i18n="history_compression">History compression</h3><p data-i18n="compression_help">Reduce repeated context while preserving recent reasoning.</p></div><div class="setting-controls"><label class="content-language" for="comp-language"><span data-i18n="content_language">Content language</span><select id="comp-language" onchange="saveCompLang(this.value)" class="compact-select" aria-label="Content language" data-i18n-aria-label="content_language"><option value="en">English</option><option value="zh">中文</option></select></label><input type="checkbox" id="comp-enabled" onchange="saveComp(this.checked)" aria-label="Enable history compression" data-i18n-aria-label="enable_compression"></div></div>
                            </section>
                            <section class="config-card">
                                <div class="card-heading"><div><h3 data-i18n="outbound_network">Outbound network</h3><p class="field-help" data-i18n="outbound_help">Optional proxy for all upstream requests.</p></div><span class="card-index">03</span></div>
                                <div class="setting-row"><div class="setting-copy"><h3 data-i18n="use_proxy">Use proxy</h3><p data-i18n="proxy_help">Route provider traffic through a local or remote proxy.</p></div><input type="checkbox" id="proxy-enabled" aria-label="Enable outbound proxy" data-i18n-aria-label="enable_proxy"></div>
                                <div class="field" style="margin-top:18px"><label for="proxy-url" data-i18n="proxy_url">Proxy URL</label><input type="text" id="proxy-url" placeholder="http://127.0.0.1:7897"></div><button onclick="saveProxy()" class="secondary-action" data-i18n="save_proxy">Save proxy settings</button>
                            </section>
                        </div>

                        <section class="config-card" style="grid-column:1/-1">
                            <div class="card-heading"><div><h3 data-i18n="custom_registry">Custom model registry</h3><p class="field-help" data-i18n="custom_help">Add an unlisted model without changing the built-in catalog.</p></div><span class="card-index">04</span></div>
                            <div class="custom-form"><select id="add-model-provider" class="compact-select"><option value="gemini">Gemini</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="deepseek">DeepSeek</option><option value="bedrock">Bedrock</option></select><input type="text" id="add-model-name" placeholder="Display name" data-i18n-placeholder="display_name" class="compact-input"><input type="text" id="add-model-value" placeholder="Provider model ID, e.g. openai/gpt-5.6" data-i18n-placeholder="model_id_placeholder" class="compact-input full"><button onclick="addCustomModel()" class="secondary-action full" data-i18n="add_custom">Add custom model</button></div><div id="custom-model-list"></div>
                        </section>
                    </div>
                </div>
            </div>
        </main>
        <div id="toast" class="toast" role="status" aria-live="polite"></div>
        <script>{JS_CONTENT}</script>
    </body></html>
    """
