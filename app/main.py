from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session
import os
import logging
import time
import json
from datetime import datetime
from contextlib import asynccontextmanager

from .models import ChatCompletionRequest, ChatCompletionResponse
from .pruner import SkillPruner
from .brain import Brain
from .dashboard import router as dashboard_router
from .database import init_db, get_db, InteractionLog, SessionLocal, Config
from . import security
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load config from env or set defaults
load_dotenv()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini/gemini-2.5-flash")
API_KEY = os.getenv("GEMINI_API_KEY") 

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing Sen-Gateway (Reborn)...")
    init_db() 
    
    # Ensure default admin exists
    db = SessionLocal()
    try:
        from .database import User
        if not db.query(User).filter(User.username == "admin").first():
            # Create default admin
            hashed_pw = security.get_password_hash("88888888")
            admin = User(username="admin", hashed_password=hashed_pw)
            db.add(admin)
            db.commit()
            logger.info("Created default admin user (admin/88888888)")
    except Exception as e:
        logger.error(f"Failed to init user db: {e}")
    finally:
        db.close()
    
    # Load Proxy Config
    db = SessionLocal()
    try:
        proxy_enabled = db.query(Config).filter_by(key="proxy_enabled").first()
        proxy_url = db.query(Config).filter_by(key="proxy_url").first()
        
        if proxy_enabled and proxy_enabled.value == "true":
            url = proxy_url.value if proxy_url else "http://127.0.0.1:7897"
            os.environ["http_proxy"] = url
            os.environ["https_proxy"] = url
            logger.info(f"Proxy enabled: {url}")
        else:
            # Explicitly unset if disabled in DB, overriding any system/cron defaults
            os.environ.pop("http_proxy", None)
            os.environ.pop("https_proxy", None)
            logger.info("Proxy disabled (env vars cleared)")
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
    finally:
        db.close()

    app.state.pruner = SkillPruner(qmd_path="qmd_data.bin")
    app.state.brain = Brain(model_name=GEMINI_MODEL, api_key=API_KEY)
    yield
    # Shutdown
    logger.info("Shutting down Sen-Gateway...")

app = FastAPI(lifespan=lifespan)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Prevent Pydantic's complex ValidationError schema from reaching the LLM.
    We convert it to a simple string.
    """
    logger.warning(f"Validation error intercepted: {exc}")
    return JSONResponse(
        status_code=422,
        content={
            "message": "Parameter validation failed, check format.",
            "details": str(exc)
        }
    )

app.include_router(dashboard_router)

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, raw_request: Request, db: Session = Depends(get_db)):
    """
    OpenAI-compatible Chat Completion endpoint.
    """
    start_time = time.time()
    
    # Extract API Key if present
    api_key = None
    auth_header = raw_request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        api_key = auth_header.split(" ")[1]
        logger.info(f"DEBUG: Extracted API Key (first 5 chars): {api_key[:5] if api_key else 'None'} from header: {auth_header[:20]}...")
    else:
        logger.warning(f"DEBUG: No Bearer token found in Authorization header: {auth_header}")
    
    logger.info(f"Received request for model: {request.model} (API Key Provided: {bool(api_key)})")
    
    # 1. Capture RAW request
    raw_request_dict = request.model_dump(mode='json')
    
    # Check Pruning Config (Now only affects History Compression)
    pruning_enabled_cfg = db.query(Config).filter_by(key="pruning_enabled").first()
    pruning_enabled = pruning_enabled_cfg.value == "true" if pruning_enabled_cfg else True 

    # Tool Pruning Removed to maximize Cache Hits (0.1x pricing)
    # We pass full tools.
    pruned_tools_list = request.tools if request.tools else []
    
    if pruning_enabled:
        # Message Compression (QWD)
        request.messages = await app.state.pruner.prune_messages(request.messages)
    else:
        logger.info("History Compression DISABLED. Passing full raw context.")
    
    # 2. Capture payload structure (we will update 'model' later)
    final_payload_dict = request.model_dump(mode='json')

    # Brain Execution
    actual_model_used = request.model # Default to requested model

    try:
        # Load Model Override Config
        model_override = None
        key_to_use = API_KEY # Default from .env
        
        # Check DB for overrides
        # We need a new session or use `db` but be careful about async
        # Since `db` is injected via Depends, it's safe to use here
        try:
            db_model_provider = db.query(Config).filter_by(key="model_provider").first()
            db_model_name = db.query(Config).filter_by(key="model_name").first()
            db_api_key = db.query(Config).filter_by(key="api_key").first()
            
            if db_model_provider and db_model_name and db_model_name.value:
                provider = db_model_provider.value
                model_name = db_model_name.value
                
                # Construct LiteLLM model string
                if provider == "openai":
                    model_override = model_name # OpenAI usually just needs the model name or "openai/..."
                elif provider == "anthropic":
                    model_override = f"anthropic/{model_name}"
                elif provider == "gemini":
                    # If user just typed "gemini-1.5", make it "gemini/gemini-1.5"
                    if not model_name.startswith("gemini/"):
                        model_override = f"gemini/{model_name}"
                    else:
                        model_override = model_name
                else:
                    model_override = model_name # Raw fallback
                
                logger.info(f"Model override active: {model_override}")
                actual_model_used = model_override # Update actual used model

            if db_api_key and db_api_key.value:
                # Decrypt the key before use
                try:
                    # If it looks like a raw key (e.g. starts with 'sk-' or 'AIza'), use it directly 
                    # But ideally we assume all DB keys are encrypted. 
                    # For backward compatibility, we try decrypt, if fail (returns empty or error), fallback to raw?
                    # security.decrypt_value returns "" on fail.
                    decrypted = security.decrypt_value(db_api_key.value)
                    if decrypted:
                        key_to_use = decrypted
                        logger.info("API Key override active from DB (Decrypted)")
                    else:
                        # Fallback for unencrypted keys (migration period)
                        key_to_use = db_api_key.value
                        logger.warning("Using raw API Key from DB (Decryption failed or legacy key)")
                except Exception as e:
                    logger.error(f"Error handling API Key: {e}")
                    key_to_use = db_api_key.value
                
        except Exception as e:
            logger.warning(f"Failed to load dynamic model config: {e}")

        # Update Final Payload to reflect REAL model being used
        if model_override:
            final_payload_dict["model"] = model_override

        # FORCE use of internal API Key (from .env or DB)
        # Ignore whatever OpenClaw sends (e.g. "sk-local", "any")
        
        response = await app.state.brain.chat(request, api_key=key_to_use, model_override=model_override)
        
        # Helper function for logging
        def log_interaction(raw_response_data, status="success"):
            new_db = SessionLocal()
            try:
                # Create a NEW session for the log, because `db` might be closed or tricky in generator
                # Actually `db` is session-scoped, so if stream is long, check if session is open
                # For simplicity, we use the passed `db` but handle errors
                latency = int((time.time() - start_time) * 1000)
                pruned_tool_count = len(pruned_tools_list)
                # Serialize tools to dict for JSON storage
                tools_json = [t.model_dump() for t in pruned_tools_list] if pruned_tools_list else []
                entry = InteractionLog(
                    timestamp=datetime.utcnow(),
                    raw_request=raw_request_dict,
                    pruned_tools=tools_json,
                    final_payload=final_payload_dict,
                    raw_response=raw_response_data,
                    model_used=actual_model_used, # Log actual model used
                    latency_ms=latency,
                    status=status,
                    pruned_tool_count=pruned_tool_count
                )
                new_db.add(entry)
                new_db.commit()
                logger.info(f"Interaction logged successfully (status: {status}, latency: {latency}ms)")
            except Exception as e:
                logger.error(f"Failed to log interaction: {e}")
            finally:
                new_db.close()

        if request.stream:
            async def stream_generator():
                full_content = ""
                try:
                    async for chunk in response:
                        # LiteLLM chunk usually has model_dump or similar
                        if hasattr(chunk, "model_dump"):
                            data = chunk.model_dump()
                        else:
                            data = dict(chunk)
                        
                        # Try to capture content for logging
                        try:
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                full_content += content
                        except:
                            pass

                        yield f"data: {json.dumps(data)}\n\n"
                    
                    yield "data: [DONE]\n\n"
                    # Log after stream completes
                    log_interaction({"content": full_content, "stream": True}, status="success")
                except Exception as e:
                    logger.error(f"Streaming error: {e}")
                    log_interaction({"error": str(e), "partial_content": full_content}, status="error")
                    yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"

            return StreamingResponse(stream_generator(), media_type="text/event-stream")

        # 3. Log Success (Non-streaming)
        log_interaction(response.model_dump(mode='json'), status="success")
        return response
        
    except Exception as e:
        logger.error(f"Error in chat_completions: {e}")
        latency = int((time.time() - start_time) * 1000)
        pruned_tool_count = len(pruned_tools_list)
        # Serialize tools to dict for JSON storage
        tools_json = [t.model_dump() for t in pruned_tools_list] if pruned_tools_list else []
        log_entry = InteractionLog(
            timestamp=datetime.utcnow(),
            raw_request=raw_request_dict,
            pruned_tools=tools_json,
            final_payload=final_payload_dict,
            raw_response={"error": str(e)},
            model_used=actual_model_used, # Log actual model used even on error
            latency_ms=latency,
            status="error",
            pruned_tool_count=pruned_tool_count
        )
        db.add(log_entry)
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "Sen-Gateway"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
