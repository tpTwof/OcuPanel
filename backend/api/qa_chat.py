from fastapi import APIRouter, Request, HTTPException
from models import ChatRequest, ChatResponse
from .utils import is_valid_uuid
from datetime import datetime, timedelta

chat_router = APIRouter()
@chat_router.post("/chat/", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest):
    # Access the global app instance
    if not is_valid_uuid(str(body.user_id)):
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    async with request.app.state.cache_lock:
        report_generator = request.app.state.report_generators[str(body.user_id)][0]
        request.app.state.report_generators[str(body.user_id)][1] = datetime.now() + timedelta(seconds=request.app.state.EXPIRY_SECONDS)

    # Use the parsed body directly
    response = report_generator.chat_with_gpt(body.message, conversation=True, reset=False)
    return ChatResponse(response=response)

@chat_router.post("/chat/reset/")
async def reset_chat(request: Request, body: ChatRequest):
    if not is_valid_uuid(str(body.user_id)):
        raise HTTPException(status_code=400, detail="Invalid UUID format")
    async with request.app.state.cache_lock:
        report_generator = request.app.state.report_generators[str(body.user_id)][0]
        request.app.state.report_generators[str(body.user_id)][1] = datetime.now() + timedelta(seconds=request.app.state.EXPIRY_SECONDS)
    
    report_generator.chat_history.clear()
    
    return True