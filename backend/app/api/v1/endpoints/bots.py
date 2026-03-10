from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_bots():
    return {"message": "Bots endpoint"}
