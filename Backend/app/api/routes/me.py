from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_current_user

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=CurrentUser)
def me(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    """Temporary sanity-check endpoint: proves the Expo app's Supabase token
    is accepted by this backend. Replace with real profile routes later."""
    return user
