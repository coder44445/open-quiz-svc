from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.game_service import GameService

router = APIRouter(prefix="/api/game", tags=["game"])

class CreateRoomResponse(BaseModel):
    room_id: str

@router.post("/create", response_model=CreateRoomResponse)
async def create_room():
    """
    Generate a unique, human-readable room ID securely and create a new game session.
    """
    service = GameService()
    try:
        room_id = await service.create_unique_session()
        return CreateRoomResponse(room_id=room_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
