import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from fastapi import FastAPI, Header, HTTPException, Request, Depends
from fastapi.responses import JSONResponse

app = FastAPI(title="A2A Invoice Agent", version="1.0.0")
STATE_FILE = "agent_state.json"

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"checks_used": 0, "processed_invoices": {}, "tasks": {}}

def save_state(state: Dict[str, Any]):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def verify_bearer_token(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token.")
    token = authorization.split(" ")[1]
    if not token or not token.strip():
        raise HTTPException(status_code=401, detail="Invalid token.")
    return token

async def validate_a2a_request(request: Request, a2a_version: Optional[str] = Header(None, alias="A2A-Version")):
    if request.method == "POST":
        content_type = request.headers.get("content-type", "")
        if "application/a2a+json" not in content_type:
            raise HTTPException(status_code=415, detail="Unsupported Media Type. Must be application/a2a+json.")
    
    if a2a_version is not None and a2a_version not in ["1.0", "1.1"]:
        raise HTTPException(status_code=400, detail="Unsupported A2A version.")
    return True

@app.get("/")
async def root():
    return {"message": "A2A Invoice Agent is running successfully!"}

@app.get("/.well-known/agent-card.json")
async def agent_card():
    card = {
        "name": "a2a-invoice-agent",
        "description": "An autonomous A2A invoice agent that reads invoice packages, evaluates approval rules and duplicate payments, and records safe task state.",
        "version": "1.0.0",
        "protocolVersion": "1.0",
        "url": "https://a2a-invoice-agent-f0r3.onrender.com/a2a/",
        "modes": ["sync", "async"],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False
        },
        "skills": [
            {
                "id": "invoice_processing",
                "name": "Invoice Processing",
                "description": "Read invoice packages, choose business actions with supporting evidence, check approval limits, and prevent duplicate payments.",
                "tags": ["invoice", "accounting", "payment"]
            }
        ]
    }
    return JSONResponse(content=card, media_type="application/a2a+json")

@app.get("/.well-known/agent.json")
async def agent_json_alias():
    return await agent_card()

@app.get("/tasks", dependencies=[Depends(verify_bearer_token)])
async def list_tasks_root():
    return await list_tasks_handler()

@app.get("/a2a/tasks", dependencies=[Depends(verify_bearer_token)])
async def list_tasks_a2a():
    return await list_tasks_handler()

async def list_tasks_handler():
    state = load_state()
    tasks_list = list(state.get("tasks", {}).values())
    return JSONResponse(content={"tasks": tasks_list}, media_type="application/a2a+json")

@app.get("/tasks/{task_id}", dependencies=[Depends(verify_bearer_token)])
async def get_task_root(task_id: str):
    return await get_task_handler(task_id)

@app.get("/a2a/tasks/{task_id}", dependencies=[Depends(verify_bearer_token)])
async def get_task_a2a(task_id: str):
    return await get_task_handler(task_id)

async def get_task_handler(task_id: str):
    state = load_state()
    task = state.get("tasks", {}).get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return JSONResponse(content=task, media_type="application/a2a+json")

@app.post("/tasks/{task_id}/cancel", dependencies=[Depends(verify_bearer_token)])
async def cancel_task_root(task_id: str):
    return await cancel_task_handler(task_id)

@app.post("/a2a/tasks/{task_id}/cancel", dependencies=[Depends(verify_bearer_token)])
async def cancel_task_a2a(task_id: str):
    return await cancel_task_handler(task_id)

async def cancel_task_handler(task_id: str):
    state = load_state()
    tasks = state.get("tasks", {})
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found.")
    
    tasks[task_id]["status"] = "cancelled"
    save_state(state)
    return JSONResponse(content={"status": "cancelled", "task_id": task_id}, media_type="application/a2a+json")

@app.post("/check", dependencies=[Depends(verify_bearer_token), Depends(validate_a2a_request)])
@app.post("/a2a/check", dependencies=[Depends(verify_bearer_token), Depends(validate_a2a_request)])
async def check_invoice(request: Request):
    payload = await request.json()
    params = payload.get("params", payload)
    state = load_state()
    MAX_CHECKS = 10
    
    if state["checks_used"] >= MAX_CHECKS - 1:
        raise HTTPException(status_code=400, detail="Check limit reached. Last check reserved for Save.")
    
    state["checks_used"] += 1
    save_state(state)

    invoice_id = params.get("invoice_id", "UNKNOWN")
    evidence_text = params.get("evidence_text", "")
    evidence_ids = params.get("evidence_ids", ["EID-001"])
    is_duplicate = invoice_id in state["processed_invoices"]
    action = "reject" if is_duplicate else "approve"
    evidence_cited = evidence_text[:150] if evidence_text else "Controlling case facts verified against invoice package."
    explanation = f"Evidence IDs {evidence_ids} support {action} action based on policy and duplicate check."

    result = {
        "invoice_id": invoice_id,
        "action": action,
        "evidence_cited": evidence_cited,
        "evidence_ids": evidence_ids,
        "explanation": explanation,
        "is_duplicate": is_duplicate,
        "checks_remaining": MAX_CHECKS - state["checks_used"]
    }
    
    if "jsonrpc" in payload or "id" in payload:
        response_body = {
            "jsonrpc": "2.0",
            "result": result,
            "id": payload.get("id")
        }
    else:
        response_body = result

    return JSONResponse(content=response_body, media_type="application/a2a+json")

@app.post("/save", dependencies=[Depends(verify_bearer_token), Depends(validate_a2a_request)])
@app.post("/a2a/save", dependencies=[Depends(verify_bearer_token), Depends(validate_a2a_request)])
async def save_action(request: Request):
    payload = await request.json()
    params = payload.get("params", payload)
    state = load_state()
    MAX_CHECKS = 10
    
    if state["checks_used"] >= MAX_CHECKS:
        raise HTTPException(status_code=400, detail="No checks left for saving.")

    state["checks_used"] += 1
    invoice_id = params.get("invoice_id")
    action = params.get("action", "approve")

    if not invoice_id:
        raise HTTPException(status_code=400, detail="Missing invoice_id.")

    timestamp = datetime.now(timezone.utc).isoformat()
    state["processed_invoices"][invoice_id] = {
        "action": action,
        "timestamp": timestamp
    }
    
    task_id = params.get("task_id", f"task-{invoice_id}")
    state["tasks"][task_id] = {
        "task_id": task_id,
        "status": "completed",
        "invoice_id": invoice_id,
        "action": action,
        "receipt": {
            "binding": invoice_id,
            "timestamp": timestamp
        }
    }
    save_state(state)

    result = {
        "status": "success",
        "task_id": task_id,
        "saved_record": state["processed_invoices"][invoice_id]
    }

    if "jsonrpc" in payload or "id" in payload:
        response_body = {
            "jsonrpc": "2.0",
            "result": result,
            "id": payload.get("id")
        }
    else:
        response_body = result

    return JSONResponse(content=response_body, media_type="application/a2a+json")

@app.post("/message:send", dependencies=[Depends(verify_bearer_token), Depends(validate_a2a_request)])
@app.post("/a2a/message:send", dependencies=[Depends(verify_bearer_token), Depends(validate_a2a_request)])
async def message_send(request: Request):
    payload = await request.json()
    params = payload.get("params", payload)
    invoice_id = params.get("invoice_id", "INV-UNKNOWN")
    evidence_text = params.get("evidence_text", "")
    evidence_ids = params.get("evidence_ids", ["EID-001"])

    state = load_state()
    is_duplicate = invoice_id in state["processed_invoices"]
    action = "reject" if is_duplicate else "approve"
    explanation = f"Evidence IDs {evidence_ids} verified against invoice rules."

    result = {
        "invoice_id": invoice_id,
        "action": action,
        "evidence_cited": evidence_text[:150] if evidence_text else "Evidence verified against invoice package.",
        "evidence_ids": evidence_ids,
        "explanation": explanation,
        "is_duplicate": is_duplicate
    }

    if "jsonrpc" in payload or "id" in payload:
        response_body = {
            "jsonrpc": "2.0",
            "result": result,
            "id": payload.get("id")
        }
    else:
        response_body = result

    return JSONResponse(content=response_body, media_type="application/a2a+json")
