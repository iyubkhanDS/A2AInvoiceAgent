import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List
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

@app.post("/a2a/check")
async def check_invoice(payload: InvoicePackage):
    state = load_state()
    MAX_CHECKS = 10
    
    # Reserve the final check slot explicitly for Save
    if state["checks_used"] >= MAX_CHECKS - 1:
        raise HTTPException(status_code=400, detail="Check limit reached. Last check reserved for Save.")
    
    state["checks_used"] += 1
    save_state(state)

    # A payment for a different invoice is not a duplicate
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

    # Save task state so retries cannot repeat payments
    state["processed_invoices"][invoice_id] = {
        "action": action,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    save_state(state)

    return {
        "status": "success",
        "saved_record": state["processed_invoices"][invoice_id]
    }