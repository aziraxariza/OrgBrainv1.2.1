import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.tenancy import get_current_user, CurrentUser
from app.schemas.entities import WhatIfRequest, DecisionValidationRequest, ChatRequest
from app.services import decision_service, explainability_service, chat_service
from app.models.recommendation import Recommendation

router = APIRouter(prefix="/api/v1", tags=["decisions"])


@router.post("/simulate")
def simulate_what_if(payload: WhatIfRequest, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """US-3.1: Simulate "What-If" Scenarios."""
    changes = {"reassign": payload.reassign, "add_capacity": payload.add_capacity}
    return decision_service.run_what_if_scenario(db, current_user.tenant_id, payload.project_id, changes)


@router.post("/validate-decision")
def validate_decision(payload: DecisionValidationRequest, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """US-3.2: Validate Strategic Decisions."""
    result = decision_service.validate_strategic_decision(db, current_user.tenant_id, payload.model_dump())
    explanation = explainability_service.explain(result)

    rec = Recommendation(
        tenant_id=current_user.tenant_id,
        title=f"Decision validation: {payload.type}",
        action=result.get("rationale", ""),
        confidence=0.7 if result.get("recommended") else 0.5,
        evidence=result,
        assumptions=["MVP heuristic model — see ADR-002", "Post-MVP: optimization-based validation"],
        alternatives=[],
        llm_explanation=explanation,
    )
    db.add(rec)
    db.commit()

    return {"recommendation_id": str(rec.recommendation_id), **result, "explanation": explanation}


@router.get("/recommendations/allocation")
def allocation_recommendations(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """US-3.3: Optimize Hiring Strategy / FR-503."""
    return decision_service.recommend_resource_allocation(db, current_user.tenant_id)


@router.get("/explainability/{decision_id}")
def get_explainability(decision_id: uuid.UUID, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """US-5.1: Get Explainable Recommendations."""
    rec = db.query(Recommendation).filter(
        Recommendation.tenant_id == current_user.tenant_id, Recommendation.recommendation_id == decision_id
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return {
        "recommendation_id": str(rec.recommendation_id),
        "title": rec.title,
        "action": rec.action,
        "confidence": rec.confidence,
        "evidence": rec.evidence,
        "assumptions": rec.assumptions,
        "alternatives": rec.alternatives,
        "explanation": rec.llm_explanation,
    }


@router.post("/chat")
def chat(payload: ChatRequest, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """Backward-compatible assistant endpoint using grounded Havn data."""
    return chat_service.answer(db, current_user.tenant_id, payload.question)


@router.post("/chat/ask")
def ask_havn(payload: ChatRequest, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    """Answer a natural-language question using live, tenant-scoped Havn data."""
    return chat_service.answer(db, current_user.tenant_id, payload.question)


@router.get("/chat/history")
def chat_history(current_user: CurrentUser = Depends(get_current_user)):
    return {"messages": chat_service.history(current_user.tenant_id)}


@router.post("/chat/clear")
def clear_chat(current_user: CurrentUser = Depends(get_current_user)):
    chat_service.clear_history(current_user.tenant_id)
    return {"cleared": True}
