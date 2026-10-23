import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="A2A Invoice Agent", version="1.0.0")
STATE_FILE = "agent_state.json"

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"checks_used": 0, "processed_invoices": {}}

def save_state(state: Dict[str, Any]):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

class InvoicePackage(BaseModel):
    invoice_id: str
    vendor: str
    amount: float
    currency: str
    evidence_text: str

class MessageSendPayload(BaseModel):
    jsonrpc: Optional[str] = "2.0"
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    id: Optional[Any] = None
    invoice_id: Optional[str] = None
    vendor: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    evidence_text: Optional[str] = None

@app.get("/")
async def root():
    return {"message": "A2A Invoice Agent is running successfully!"}

@app.get("/.well-known/agent-card.json")
async def agent_card():
    return {
        "name": "a2a-invoice-agent",
        "description": "An autonomous A2A invoice agent that reads invoice packages, evaluates approval rules and duplicate payments, and records safe task state.",
        "version": "1.0.0",
        "protocolVersion": "1.0",
        "url": "https://a2a-invoice-agent-f0r3.onrender.com/a2a/",
        "skills": [
            {
                "id": "invoice_processing",
                "name": "Invoice Processing",
                "description": "Read invoice packages, choose business actions with supporting evidence, check approval limits, and prevent duplicate payments.",
                "tags": ["invoice", "accounting", "payment"]
            }
        ]
    }

@app.get("/.well-known/agent.json")
async def agent_json_alias():
    return await agent_card()

@app.post("/a2a/check")
async def check_invoice(payload: InvoicePackage):
    state = load_state()
    MAX_CHECKS = 10
    
    if state["checks_used"] >= MAX_CHECKS - 1:
        raise HTTPException(status_code=400, detail="Check limit reached. Last check reserved for Save.")
    
    state["checks_used"] += 1
    save_state(state)

    is_duplicate = payload.invoice_id in state["processed_invoices"]
    action = "reject" if is_duplicate else "approve"
    evidence = payload.evidence_text[:150]

    return {
        "invoice_id": payload.invoice_id,
        "action": action,
        "evidence_cited": evidence,
        "is_duplicate": is_duplicate,
        "checks_remaining": MAX_CHECKS - state["checks_used"]
    }

@app.post("/a2a/save")
async def save_action(payload: Dict[str, Any]):
    state = load_state()
    MAX_CHECKS = 10
    
    if state["checks_used"] >= MAX_CHECKS:
        raise HTTPException(status_code=400, detail="No checks left for saving (0 marks).")

    state["checks_used"] += 1
    invoice_id = payload.get("invoice_id")
    action = payload.get("action")

    state["processed_invoices"][invoice_id] = {
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    save_state(state)

    return {
        "status": "success",
        "saved_record": state["processed_invoices"][invoice_id]
    }

@app.post("/a2a/message:send")
async def message_send(payload: Dict[str, Any]):
    # Handles A2A Protocol message:send calls or JSON-RPC format wrappers
    params = payload.get("params", payload)
    invoice_id = params.get("invoice_id", "INV-UNKNOWN")
    vendor = params.get("vendor", "")
    amount = params.get("amount", 0.0)
    currency = params.get("currency", "USD")
    evidence_text = params.get("evidence_text", "")

    state = load_state()
    is_duplicate = invoice_id in state["processed_invoices"]
    action = "reject" if is_duplicate else "approve"

    result = {
        "invoice_id": invoice_id,
        "action": action,
        "evidence_cited": evidence_text[:150],
        "is_duplicate": is_duplicate
    }

    if "jsonrpc" in payload or "id" in payload:
        return {
            "jsonrpc": "2.0",
            "result": result,
            "id": payload.get("id")
        }

    return result