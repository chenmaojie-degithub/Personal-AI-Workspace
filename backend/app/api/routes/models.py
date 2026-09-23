from fastapi import APIRouter

from app.providers.registry import get_model, models

router = APIRouter(tags=["models"])


@router.get("/models")
def list_models() -> dict:
    available = [item for item in models() if item.available]
    try:
        default_id = get_model().id
    except RuntimeError:
        default_id = available[0].id if available else None
    return {
        "default_model_id": default_id,
        "models": [
            {"model_id": item.id, "provider": item.provider, "model": item.model,
             "supports_tools": item.supports_tools}
            for item in available
        ],
    }
