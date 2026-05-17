from fastapi import APIRouter, Depends, Query, status

from job_buddy.deps import get_conversation_service
from job_buddy.modules.conversations import (
    ChatHistoryResponse,
    ConversationRecordRead,
    ConversationService,
    ConversationSyncResponse,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationRecordRead], operation_id="list_conversations")
async def list_conversations(
    service: ConversationService = Depends(get_conversation_service),
) -> list[ConversationRecordRead]:
    conversations = await service.list_conversations()
    return [ConversationRecordRead(**item.model_dump()) for item in conversations]


@router.post("/sync", response_model=ConversationSyncResponse, status_code=status.HTTP_202_ACCEPTED, operation_id="sync_conversations")
async def sync_conversations(
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationSyncResponse:
    count = await service.sync_conversations()
    return ConversationSyncResponse(count=count)


@router.get("/{job_id}/messages", response_model=ChatHistoryResponse, operation_id="get_chat_history")
async def get_chat_history(
    job_id: int,
    page: int = Query(default=1, ge=1),
    count: int = Query(default=20, le=100),
    service: ConversationService = Depends(get_conversation_service),
) -> ChatHistoryResponse:
    return await service.get_chat_history(job_id=job_id, page=page, count=count)
