from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from api.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=settings.JWT_EXPIRY_HOURS)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Authenticate against .env credentials or DB users."""
    # Phase 1: .env admin credentials
    if username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD:
        return {
            "id": "admin",
            "username": settings.ADMIN_USERNAME,
            "email": settings.ADMIN_EMAIL,
            "role": "admin",
            "tenant_id": "default",
        }

    # Phase 2: DB users (when DB is configured)
    try:
        from api.db.services.user_service import UserService
        users = UserService.query(nickname=username)
        if users:
            user = users[0]
            if verify_password(password, user.password):
                return {
                    "id": str(user.id),
                    "username": user.nickname,
                    "email": user.email,
                    "role": getattr(user, "role", "user"),
                    "tenant_id": str(getattr(user, "tenant_id", "default")),
                }
    except Exception:
        pass

    return None
