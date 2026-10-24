from fastapi import APIRouter

from app.api import agent, ai, auth, dashboard, knowledge, org, settlement

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(org.router)
api_router.include_router(knowledge.router)
api_router.include_router(ai.router)
api_router.include_router(dashboard.router)
api_router.include_router(settlement.router)
api_router.include_router(agent.router)
