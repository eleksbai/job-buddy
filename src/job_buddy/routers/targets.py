from fastapi import APIRouter, Depends, Response, status

from job_buddy.deps import get_target_service
from job_buddy.modules.targets import TargetProfileCreate, TargetProfileRead, TargetProfileService, TargetProfileUpdate

router = APIRouter(prefix="/targets", tags=["targets"])


@router.get("", response_model=list[TargetProfileRead], operation_id="list_targets")
async def list_targets(service: TargetProfileService = Depends(get_target_service)) -> list[TargetProfileRead]:
    return [TargetProfileRead(**item.model_dump()) for item in await service.list_targets()]


@router.post("", response_model=TargetProfileRead, status_code=status.HTTP_201_CREATED, operation_id="create_target")
async def create_target(
    payload: TargetProfileCreate,
    service: TargetProfileService = Depends(get_target_service),
) -> TargetProfileRead:
    target = await service.create_target(payload)
    return TargetProfileRead(**target.model_dump())


@router.get("/{target_id}", response_model=TargetProfileRead, operation_id="get_target")
async def get_target(target_id: str, service: TargetProfileService = Depends(get_target_service)) -> TargetProfileRead:
    target = await service.get_target(target_id)
    return TargetProfileRead(**target.model_dump())


@router.put("/{target_id}", response_model=TargetProfileRead, operation_id="update_target")
async def update_target(
    target_id: str,
    payload: TargetProfileUpdate,
    service: TargetProfileService = Depends(get_target_service),
) -> TargetProfileRead:
    target = await service.update_target(target_id, payload)
    return TargetProfileRead(**target.model_dump())


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="delete_target")
async def delete_target(target_id: str, service: TargetProfileService = Depends(get_target_service)) -> Response:
    await service.delete_target(target_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
