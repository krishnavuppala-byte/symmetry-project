from fastapi import APIRouter, HTTPException, Query

from app.models.diff import DiffResponse
from app.services.diff_service import compute_diff

router = APIRouter(prefix="/symmetry/v1/wiki", tags=["revision-diff"])


@router.get("/diff", response_model=DiffResponse)
def get_revision_diff(
    title: str = Query(..., description="Wikipedia article title"),
    lang: str = Query("en", description="Wikipedia language code"),
    revid_a: int = Query(..., description="First revision ID"),
    revid_b: int = Query(..., description="Second revision ID"),
):
    try:
        return compute_diff(title, lang, revid_a, revid_b)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))