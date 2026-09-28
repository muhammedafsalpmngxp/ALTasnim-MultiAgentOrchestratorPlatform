from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from api.core.auth import authenticate_user, create_access_token, hash_password
from api.core.deps import AuthUser

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = create_access_token({
        "sub": user["id"],
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "tenant_id": user["tenant_id"],
    })
    return LoginResponse(access_token=token, user=user)


@router.post("/auth/logout")
async def logout(user: AuthUser):
    # JWT is stateless — client discards token
    # For DB users: could invalidate token in DB
    return {"message": "Logged out successfully"}


@router.get("/auth/me")
async def me(user: AuthUser):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "tenant_id": user.tenant_id,
    }


@router.put("/auth/password")
async def change_password(req: ChangePasswordRequest, user: AuthUser):
    verified = authenticate_user(user.username, req.current_password)
    if not verified:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    try:
        from api.db.services.user_service import UserService
        db_users = UserService.query(nickname=user.username)
        if db_users:
            UserService.update_by_id(db_users[0].id, {"password": hash_password(req.new_password)})
        return {"message": "Password changed successfully"}
    except Exception:
        raise HTTPException(status_code=400, detail="Cannot change .env admin password via API — update .env directly")
