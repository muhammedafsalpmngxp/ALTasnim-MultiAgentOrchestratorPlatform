import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from api.core.auth import hash_password
from api.core.deps import AdminUser, AuthUser
from api.routes.projects import _ts

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"


class UpdateUserRequest(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None


@router.get("/users")
async def list_users(user: AdminUser):
    try:
        from api.db.services.user_service import UserService
        users = UserService.query()
        return [
            {
                "id": str(u.id),
                "username": u.nickname,
                "email": u.email,
                "role": getattr(u, "role", "user"),
                "status": u.status,
                "created_at": _ts(u.create_time),
            }
            for u in users
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(req: CreateUserRequest, user: AdminUser):
    try:
        from api.db.services.user_service import UserService
        existing = UserService.query(nickname=req.username)
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")
        new_user = UserService.save(**{
            "id": str(uuid.uuid4()).replace("-", ""),
            "nickname": req.username,
            "email": req.email,
            "password": hash_password(req.password),
            "role": req.role,
            "status": "1",
        })
        return {"id": str(new_user.id), "username": req.username, "email": req.email, "role": req.role}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}")
async def get_user(user_id: str, current_user: AuthUser):
    if not current_user.is_admin and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        from api.db.services.user_service import UserService
        ok, u = UserService.get_by_id(user_id)
        if not ok or not u:
            raise HTTPException(status_code=404, detail="User not found")
        return {"id": str(u.id), "username": u.nickname, "email": u.email, "role": getattr(u, "role", "user")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{user_id}")
async def update_user(user_id: str, req: UpdateUserRequest, current_user: AuthUser):
    if not current_user.is_admin and current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        from api.db.services.user_service import UserService
        updates = req.model_dump(exclude_none=True)
        if "password" in updates:
            updates["password"] = hash_password(updates["password"])
        UserService.update_by_id(user_id, updates)
        return {"message": "User updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, current_user: AdminUser):
    if user_id == "admin" or user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete this user")
    try:
        from api.db.services.user_service import UserService
        ok, u = UserService.get_by_id(user_id)
        if not ok or not u:
            raise HTTPException(status_code=404, detail="User not found")
        UserService.delete_by_id(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
