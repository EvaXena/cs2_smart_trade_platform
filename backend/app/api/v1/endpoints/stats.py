from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_stats():
    return {"message": "Stats endpoint"}
