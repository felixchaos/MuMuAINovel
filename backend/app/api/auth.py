"""
认证 API - LinuxDO OAuth2 登录 + 本地账户登录 + 邮箱验证码注册/登录
"""
from fastapi import APIRouter, HTTPException, Response, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
import hashlib
import secrets
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.oauth_service import LinuxDOOAuthService
from app.user_manager import user_manager, User as UserDTO
from app.user_password import password_manager
from app.logger import get_logger
from app.config import settings
from app.database import get_engine
from app.models.user import User as UserModel
from app.models.settings import Settings as SettingsModel
from app.services.email_service import email_service
from app.security import create_session_token

# 中国时区 UTC+8
CHINA_TZ = timezone(timedelta(hours=8))


def get_china_now():
    """获取中国当前时间"""
    return datetime.now(CHINA_TZ)


logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])

# OAuth2 服务实例
oauth_service = LinuxDOOAuthService()

# State 临时存储（生产环境应使用 Redis）
_state_storage = {}

# 邮箱验证码临时存储（生产环境应使用 Redis）
_email_verification_storage = {}
MAX_VERIFICATION_ATTEMPTS = 5

EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AuthUrlResponse(BaseModel):
    auth_url: str
    state: str


class LocalLoginRequest(BaseModel):
    """本地登录请求"""
    username: str
    password: str


class EmailLoginRequest(BaseModel):
    """邮箱验证码登录请求"""
    email: str
    code: str


class EmailSendCodeRequest(BaseModel):
    """邮箱验证码发送请求"""
    email: str
    scene: str = "register"


class EmailRegisterRequest(BaseModel):
    """邮箱注册请求"""
    email: str
    code: str
    password: str
    display_name: Optional[str] = None


class EmailResetPasswordRequest(BaseModel):
    """邮箱重置密码请求"""
    email: str
    code: str
    new_password: str


class LocalLoginResponse(BaseModel):
    """登录响应"""
    success: bool
    message: str
    user: Optional[dict] = None


class SetPasswordRequest(BaseModel):
    """设置密码请求"""
    password: str


class SetPasswordResponse(BaseModel):
    """设置密码响应"""
    success: bool
    message: str


class PasswordStatusResponse(BaseModel):
    """密码状态响应"""
    has_password: bool
    has_custom_password: bool
    username: Optional[str] = None
    default_password: Optional[str] = None


async def _get_global_session() -> AsyncSession:
    """获取全局数据库会话"""
    engine = await get_engine("_global_users_")
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return session_maker()


async def _get_auth_runtime_settings() -> dict:
    """获取认证相关运行时配置，优先读取管理员系统设置，其次回退到 .env"""
    runtime = {
        "email_auth_enabled": settings.EMAIL_AUTH_ENABLED,
        "email_register_enabled": settings.EMAIL_REGISTER_ENABLED,
        "verification_code_ttl_minutes": settings.EMAIL_VERIFICATION_CODE_TTL_MINUTES,
        "verification_resend_interval_seconds": settings.EMAIL_VERIFICATION_RESEND_INTERVAL_SECONDS,
        "smtp_host": settings.SMTP_HOST,
        "smtp_port": settings.SMTP_PORT,
        "smtp_username": settings.SMTP_USERNAME,
        "smtp_password": settings.SMTP_PASSWORD,
        "smtp_use_tls": settings.SMTP_USE_TLS,
        "smtp_use_ssl": settings.SMTP_USE_SSL,
        "smtp_from_email": settings.SMTP_FROM_EMAIL,
        "smtp_from_name": settings.SMTP_FROM_NAME,
    }

    async with await _get_global_session() as session:
        result = await session.execute(
            select(SettingsModel)
            .join(UserModel, UserModel.user_id == SettingsModel.user_id)
            .where(UserModel.is_admin == True)
            .order_by(SettingsModel.updated_at.desc())
            .limit(1)
        )
        admin_settings = result.scalar_one_or_none()

        if admin_settings:
            runtime.update({
                "email_auth_enabled": admin_settings.email_auth_enabled,
                "email_register_enabled": admin_settings.email_register_enabled,
                "verification_code_ttl_minutes": admin_settings.verification_code_ttl_minutes,
                "verification_resend_interval_seconds": admin_settings.verification_resend_interval_seconds,
                "smtp_host": admin_settings.smtp_host,
                "smtp_port": admin_settings.smtp_port,
                "smtp_username": admin_settings.smtp_username,
                "smtp_password": admin_settings.smtp_password,
                "smtp_use_tls": admin_settings.smtp_use_tls,
                "smtp_use_ssl": admin_settings.smtp_use_ssl,
                "smtp_from_email": admin_settings.smtp_from_email,
                "smtp_from_name": admin_settings.smtp_from_name,
            })

    return runtime


async def _find_user_by_email(email: str) -> Optional[UserDTO]:
    """按邮箱查找用户。邮箱用户的 username 字段即邮箱地址。"""
    normalized_email = email.strip().lower()
    async with await _get_global_session() as session:
        result = await session.execute(
            select(UserModel).where(UserModel.username == normalized_email)
        )
        user = result.scalar_one_or_none()
        if not user:
            return None
        return UserDTO(**user.to_dict())


async def _create_email_user(email: str, display_name: Optional[str]) -> UserDTO:
    """创建邮箱注册用户"""
    normalized_email = email.strip().lower()
    final_display_name = (display_name or normalized_email.split("@")[0]).strip()
    if not final_display_name:
        final_display_name = normalized_email.split("@")[0]

    user_id = f"email_{hashlib.md5(normalized_email.encode()).hexdigest()[:16]}"

    async with await _get_global_session() as session:
        existing = await session.execute(
            select(UserModel).where(UserModel.user_id == user_id)
        )
        user = existing.scalar_one_or_none()

        if user:
            raise HTTPException(status_code=400, detail="该邮箱已注册")

        user = UserModel(
            user_id=user_id,
            username=normalized_email,
            display_name=final_display_name,
            avatar_url=None,
            trust_level=1,
            is_admin=False,
            linuxdo_id=user_id,
            created_at=datetime.now(),
            last_login=datetime.now(),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        return UserDTO(**user.to_dict())


async def _touch_user_last_login(user_id: str):
    """更新最后登录时间"""
    async with await _get_global_session() as session:
        result = await session.execute(
            select(UserModel).where(UserModel.user_id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return

        user.last_login = datetime.now()
        await session.commit()


def _validate_email(email: str) -> str:
    normalized_email = email.strip().lower()
    if not normalized_email or len(normalized_email) > 255 or not EMAIL_REGEX.match(normalized_email):
        raise HTTPException(status_code=400, detail="请输入有效的邮箱地址")
    return normalized_email


def _validate_password(password: str):
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少为6个字符")


def _is_session_cookie_secure() -> bool:
    """判断会话 Cookie 是否启用 Secure 标记。"""
    if settings.SESSION_COOKIE_SECURE is not None:
        return settings.SESSION_COOKIE_SECURE
    return not settings.debug


def _set_login_cookies(response: Response, user_id: str):
    """设置登录 Cookie"""
    max_age = settings.SESSION_EXPIRE_MINUTES * 60
    session_token = create_session_token(user_id, max_age)
    cookie_secure = _is_session_cookie_secure()
    response.set_cookie(
        key="session_token",
        value=session_token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=cookie_secure,
    )

    china_now = get_china_now()
    expire_time = china_now + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)
    expire_at = int(expire_time.timestamp())

    response.set_cookie(
        key="session_expire_at",
        value=str(expire_at),
        max_age=max_age,
        httponly=False,
        samesite="lax",
        secure=cookie_secure,
    )


def _generate_verification_code() -> str:
    return f"{secrets.randbelow(1000000):06d}"


def _build_verification_mail_content(scene: str, code: str, ttl_minutes: int) -> tuple[str, str, str]:
    scene_title_map = {
        "register": "邮箱注册验证码",
        "login": "邮箱登录验证码",
        "reset_password": "重置密码验证码",
    }
    scene_desc_map = {
        "register": "欢迎注册 MuMuAINovel。",
        "login": "你正在使用邮箱验证码登录 MuMuAINovel。",
        "reset_password": "你正在重置 MuMuAINovel 账号密码。",
    }

    scene_title = scene_title_map.get(scene, "邮箱验证码")
    scene_desc = scene_desc_map.get(scene, "你正在进行邮箱身份验证。")
    subject = f"MuMuAINovel {scene_title}"
    text_body = (
        f"{scene_desc}\n\n"
        f"你的验证码是：{code}\n"
        f"有效期：{ttl_minutes} 分钟\n\n"
        f"如果这不是你的操作，请忽略本邮件。"
    )
    html_body = f"""
    <div style="font-family: Arial, PingFang SC, Microsoft YaHei, sans-serif; line-height: 1.8; color: #1f2937;">
      <h2 style="margin-bottom: 16px;">MuMuAINovel {scene_title}</h2>
      <p>{scene_desc}</p>
      <p>你的验证码为：</p>
      <div style="display: inline-block; padding: 10px 18px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; font-size: 28px; font-weight: 700; letter-spacing: 4px; color: #2563eb;">
        {code}
      </div>
      <p style="margin-top: 16px;">有效期：{ttl_minutes} 分钟</p>
      <p>如果这不是你的操作，请忽略本邮件。</p>
    </div>
    """
    return subject, text_body, html_body


def _get_verification_storage_key(scene: str, email: str) -> str:
    return f"{scene}:{email}"


def _validate_verification_scene(scene: str) -> str:
    normalized_scene = scene.strip().lower()
    allowed_scenes = {"register", "login", "reset_password"}
    if normalized_scene not in allowed_scenes:
        raise HTTPException(status_code=400, detail="不支持的验证码场景")
    return normalized_scene


@router.get("/config")
async def get_auth_config(response: Response):
    """获取认证配置信息"""
    runtime = await _get_auth_runtime_settings()
    response.headers["Cache-Control"] = "no-store"
    return {
        "local_auth_enabled": settings.LOCAL_AUTH_ENABLED,
        "linuxdo_enabled": bool(settings.LINUXDO_CLIENT_ID and settings.LINUXDO_CLIENT_SECRET),
        "email_auth_enabled": runtime["email_auth_enabled"],
        "email_register_enabled": runtime["email_register_enabled"],
    }


@router.post("/local/login", response_model=LocalLoginResponse)
async def local_login(request: LocalLoginRequest, response: Response):
    """本地账户登录（支持.env配置的管理员账号和Linux DO授权后绑定的账号）"""
    if not settings.LOCAL_AUTH_ENABLED:
        raise HTTPException(status_code=403, detail="本地账户登录未启用")

    logger.info(f"[本地登录] 尝试登录用户名: {request.username}")

    all_users = await user_manager.get_all_users()
    target_user = None

    for user in all_users:
        password_username = await password_manager.get_username(user.user_id)
        if user.username == request.username or password_username == request.username:
            target_user = user
            logger.info(f"[本地登录] 找到 Linux DO 授权用户: {user.user_id}")
            break

    if target_user:
        if not await password_manager.has_password(target_user.user_id):
            logger.warning(f"[本地登录] 用户 {target_user.user_id} 没有设置密码")
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        if not await password_manager.verify_password(target_user.user_id, request.password):
            logger.warning(f"[本地登录] 用户 {target_user.user_id} 密码验证失败")
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        logger.info(f"[本地登录] Linux DO 授权用户 {target_user.user_id} 登录成功")
        user = target_user
    else:
        logger.info(f"[本地登录] 未找到 Linux DO 用户，检查 .env 管理员账号")

        if not settings.LOCAL_AUTH_USERNAME or not settings.LOCAL_AUTH_PASSWORD:
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        user_id = f"local_{hashlib.md5(request.username.encode()).hexdigest()[:16]}"
        user = await user_manager.get_user(user_id)

        if not user:
            if request.username != settings.LOCAL_AUTH_USERNAME or request.password != settings.LOCAL_AUTH_PASSWORD:
                raise HTTPException(status_code=401, detail="用户名或密码错误")

            user = await user_manager.create_or_update_from_linuxdo(
                linuxdo_id=user_id,
                username=request.username,
                display_name=settings.LOCAL_AUTH_DISPLAY_NAME,
                avatar_url=None,
                trust_level=9
            )

            await password_manager.set_password(user.user_id, request.username, request.password)
            logger.info(f"[本地登录] 管理员用户 {user.user_id} 初始密码已设置到数据库")
        else:
            if not await password_manager.verify_password(user.user_id, request.password):
                raise HTTPException(status_code=401, detail="用户名或密码错误")

            logger.info(f"[本地登录] 管理员用户 {user.user_id} 登录成功")

    _set_login_cookies(response, user.user_id)
    logger.info(f"✅ [登录] 用户 {user.user_id} 登录成功，会话有效期 {settings.SESSION_EXPIRE_MINUTES} 分钟")

    return LocalLoginResponse(
        success=True,
        message="登录成功",
        user=user.dict()
    )


@router.post("/email/send-code")
async def send_email_verification_code(request: EmailSendCodeRequest):
    """发送邮箱验证码（注册 / 登录 / 重置密码）"""
    runtime = await _get_auth_runtime_settings()
    if not runtime["email_auth_enabled"]:
        raise HTTPException(status_code=403, detail="邮箱认证未启用")

    email = _validate_email(request.email)
    scene = _validate_verification_scene(request.scene)
    existing_user = await _find_user_by_email(email)

    if scene == "register":
        if not runtime["email_register_enabled"]:
            raise HTTPException(status_code=403, detail="新用户注册未启用")
        if existing_user:
            raise HTTPException(status_code=400, detail="该邮箱已注册")
    else:
        if not existing_user:
            raise HTTPException(status_code=404, detail="该邮箱尚未注册")

    if not runtime["smtp_host"] or not runtime["smtp_username"] or not runtime["smtp_password"]:
        raise HTTPException(status_code=400, detail="系统 SMTP 未配置完整，暂无法发送验证码")

    now = get_china_now()
    storage_key = _get_verification_storage_key(scene, email)
    cached = _email_verification_storage.get(storage_key)
    resend_interval = runtime["verification_resend_interval_seconds"]
    ttl_minutes = runtime["verification_code_ttl_minutes"]

    if cached and cached["last_sent_at"] + timedelta(seconds=resend_interval) > now:
        remain_seconds = int((cached["last_sent_at"] + timedelta(seconds=resend_interval) - now).total_seconds())
        raise HTTPException(status_code=429, detail=f"验证码发送过于频繁，请 {remain_seconds} 秒后重试")

    code = _generate_verification_code()
    expires_at = now + timedelta(minutes=ttl_minutes)
    subject, text_body, html_body = _build_verification_mail_content(scene, code, ttl_minutes)
    from_email = runtime["smtp_from_email"] or runtime["smtp_username"]

    await email_service.send_mail(
        host=runtime["smtp_host"],
        port=runtime["smtp_port"],
        username=runtime["smtp_username"],
        password=runtime["smtp_password"],
        use_tls=runtime["smtp_use_tls"],
        use_ssl=runtime["smtp_use_ssl"],
        from_email=from_email,
        from_name=runtime["smtp_from_name"],
        to_email=email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )

    _email_verification_storage[storage_key] = {
        "code": code,
        "expires_at": expires_at,
        "last_sent_at": now,
        "attempts": 0,
    }

    logger.info(f"[邮箱验证码] 场景={scene} 已发送到 {email}")
    return {
        "success": True,
        "message": "验证码已发送，请检查邮箱",
        "expire_in_seconds": ttl_minutes * 60,
        "resend_interval_seconds": resend_interval,
    }


@router.post("/email/register", response_model=LocalLoginResponse)
async def email_register(request: EmailRegisterRequest, response: Response):
    """邮箱验证码注册并自动登录"""
    runtime = await _get_auth_runtime_settings()
    if not runtime["email_auth_enabled"]:
        raise HTTPException(status_code=403, detail="邮箱认证未启用")
    if not runtime["email_register_enabled"]:
        raise HTTPException(status_code=403, detail="新用户注册未启用")

    email = _validate_email(request.email)
    code = request.code.strip()
    _validate_password(request.password)

    if len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=400, detail="请输入6位数字验证码")

    cached = _email_verification_storage.get(_get_verification_storage_key("register", email))
    if not cached:
        raise HTTPException(status_code=400, detail="请先发送验证码")

    now = get_china_now()
    if cached["expires_at"] < now:
        _email_verification_storage.pop(_get_verification_storage_key("register", email), None)
        raise HTTPException(status_code=400, detail="验证码已过期，请重新发送")

    if cached["code"] != code:
        cached["attempts"] = cached.get("attempts", 0) + 1
        if cached["attempts"] >= MAX_VERIFICATION_ATTEMPTS:
            _email_verification_storage.pop(_get_verification_storage_key("register", email), None)
            raise HTTPException(status_code=429, detail="验证码错误次数过多，请重新发送")
        raise HTTPException(status_code=400, detail="验证码错误")

    existing_user = await _find_user_by_email(email)
    if existing_user:
        _email_verification_storage.pop(_get_verification_storage_key("register", email), None)
        raise HTTPException(status_code=400, detail="该邮箱已注册")

    user = await _create_email_user(email, request.display_name)
    await password_manager.set_password(user.user_id, email, request.password)
    _email_verification_storage.pop(_get_verification_storage_key("register", email), None)

    _set_login_cookies(response, user.user_id)
    logger.info(f"✅ [邮箱注册] 用户 {user.user_id} 注册并登录成功")

    return LocalLoginResponse(
        success=True,
        message="注册成功",
        user=user.dict()
    )


@router.post("/email/login", response_model=LocalLoginResponse)
async def email_login(request: EmailLoginRequest, response: Response):
    """邮箱验证码登录"""
    runtime = await _get_auth_runtime_settings()
    if not runtime["email_auth_enabled"]:
        raise HTTPException(status_code=403, detail="邮箱认证未启用")

    email = _validate_email(request.email)
    code = request.code.strip()
    user = await _find_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="该邮箱尚未注册")

    if len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=400, detail="请输入6位数字验证码")

    storage_key = _get_verification_storage_key("login", email)
    cached = _email_verification_storage.get(storage_key)
    if not cached:
        raise HTTPException(status_code=400, detail="请先发送登录验证码")

    now = get_china_now()
    if cached["expires_at"] < now:
        _email_verification_storage.pop(storage_key, None)
        raise HTTPException(status_code=400, detail="登录验证码已过期，请重新发送")

    if cached["code"] != code:
        cached["attempts"] = cached.get("attempts", 0) + 1
        if cached["attempts"] >= MAX_VERIFICATION_ATTEMPTS:
            _email_verification_storage.pop(storage_key, None)
            raise HTTPException(status_code=429, detail="验证码错误次数过多，请重新发送")
        raise HTTPException(status_code=400, detail="登录验证码错误")

    _email_verification_storage.pop(storage_key, None)
    await _touch_user_last_login(user.user_id)
    latest_user = await user_manager.get_user(user.user_id)
    if latest_user:
        user = latest_user

    _set_login_cookies(response, user.user_id)
    logger.info(f"✅ [邮箱登录] 用户 {user.user_id} 登录成功")

    return LocalLoginResponse(
        success=True,
        message="登录成功",
        user=user.dict()
    )


@router.post("/email/reset-password")
async def email_reset_password(request: EmailResetPasswordRequest):
    """通过邮箱验证码重置密码"""
    runtime = await _get_auth_runtime_settings()
    if not runtime["email_auth_enabled"]:
        raise HTTPException(status_code=403, detail="邮箱认证未启用")

    email = _validate_email(request.email)
    code = request.code.strip()
    _validate_password(request.new_password)

    user = await _find_user_by_email(email)
    if not user:
        raise HTTPException(status_code=404, detail="该邮箱尚未注册")

    if len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=400, detail="请输入6位数字验证码")

    storage_key = _get_verification_storage_key("reset_password", email)
    cached = _email_verification_storage.get(storage_key)
    if not cached:
        raise HTTPException(status_code=400, detail="请先发送重置密码验证码")

    now = get_china_now()
    if cached["expires_at"] < now:
        _email_verification_storage.pop(storage_key, None)
        raise HTTPException(status_code=400, detail="重置密码验证码已过期，请重新发送")

    if cached["code"] != code:
        cached["attempts"] = cached.get("attempts", 0) + 1
        if cached["attempts"] >= MAX_VERIFICATION_ATTEMPTS:
            _email_verification_storage.pop(storage_key, None)
            raise HTTPException(status_code=429, detail="验证码错误次数过多，请重新发送")
        raise HTTPException(status_code=400, detail="重置密码验证码错误")

    await password_manager.set_password(user.user_id, email, request.new_password)
    _email_verification_storage.pop(storage_key, None)
    logger.info(f"✅ [邮箱重置密码] 用户 {user.user_id} 重置密码成功")

    return {
        "success": True,
        "message": "密码重置成功，请使用新验证码重新登录",
    }


@router.get("/linuxdo/url", response_model=AuthUrlResponse)
async def get_linuxdo_auth_url():
    """获取 LinuxDO 授权 URL"""
    state = oauth_service.generate_state()
    auth_url = oauth_service.get_authorization_url(state)

    _state_storage[state] = True

    return AuthUrlResponse(auth_url=auth_url, state=state)


async def _handle_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    response: Response = None
):
    """
    LinuxDO OAuth2 回调处理

    成功后重定向到前端首页，并设置 user_id Cookie
    """
    if error:
        raise HTTPException(status_code=400, detail=f"授权失败: {error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="缺少 code 或 state 参数")

    if state not in _state_storage:
        raise HTTPException(status_code=400, detail="无效的 state 参数")

    del _state_storage[state]

    token_data = await oauth_service.get_access_token(code)
    if not token_data or "access_token" not in token_data:
        raise HTTPException(status_code=400, detail="获取访问令牌失败")

    access_token = token_data["access_token"]

    user_info = await oauth_service.get_user_info(access_token)
    if not user_info:
        raise HTTPException(status_code=400, detail="获取用户信息失败")

    linuxdo_id = str(user_info.get("id"))
    username = user_info.get("username", "")
    display_name = user_info.get("name", username)
    avatar_url = user_info.get("avatar_url")
    trust_level = user_info.get("trust_level", 0)
    user_id = f"linuxdo_{linuxdo_id}"
    existing_user = await user_manager.get_user(user_id)
    is_initial_admin = settings.INITIAL_ADMIN_LINUXDO_ID and linuxdo_id == settings.INITIAL_ADMIN_LINUXDO_ID

    if not existing_user and not is_initial_admin:
        runtime = await _get_auth_runtime_settings()
        if not runtime["email_register_enabled"]:
            logger.warning(f"[OAuth登录] 新用户注册已关闭，拒绝 LinuxDO 用户创建: {linuxdo_id}")
            raise HTTPException(status_code=403, detail="新用户注册未启用，请联系管理员")

    user = await user_manager.create_or_update_from_linuxdo(
        linuxdo_id=linuxdo_id,
        username=username,
        display_name=display_name,
        avatar_url=avatar_url,
        trust_level=trust_level
    )

    is_first_login = not await password_manager.has_password(user.user_id)
    if is_first_login:
        logger.info(f"用户 {user.user_id} ({username}) 首次登录，需要初始化密码")

    frontend_url = settings.FRONTEND_URL.rstrip('/')
    redirect_url = f"{frontend_url}/auth/callback"
    logger.info(f"OAuth回调成功，重定向到前端: {redirect_url}")
    redirect_response = RedirectResponse(url=redirect_url)

    _set_login_cookies(redirect_response, user.user_id)
    logger.info(f"✅ [OAuth登录] 用户 {user.user_id} 登录成功，会话有效期 {settings.SESSION_EXPIRE_MINUTES} 分钟")

    if is_first_login:
        redirect_response.set_cookie(
            key="first_login",
            value="true",
            max_age=300,
            httponly=False,
            samesite="lax",
            secure=_is_session_cookie_secure(),
        )
        logger.info(f"✅ [OAuth登录] 用户 {user.user_id} 首次登录，已设置 first_login 标记")

    return redirect_response


@router.get("/linuxdo/callback")
async def linuxdo_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    response: Response = None
):
    """LinuxDO OAuth2 回调处理（标准路径）"""
    return await _handle_callback(code, state, error, response)


@router.get("/callback")
async def callback_alias(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    response: Response = None
):
    """LinuxDO OAuth2 回调处理（兼容路径）"""
    return await _handle_callback(code, state, error, response)


@router.post("/refresh")
async def refresh_session(request: Request, response: Response):
    """刷新会话 - 延长登录状态"""
    if not hasattr(request.state, "user") or not request.state.user:
        raise HTTPException(status_code=401, detail="未登录，无法刷新会话")

    user = request.state.user

    session_expire_at = request.cookies.get("session_expire_at")
    if session_expire_at:
        try:
            expire_timestamp = int(session_expire_at)
            current_timestamp = int(get_china_now().timestamp())
            remaining_minutes = (expire_timestamp - current_timestamp) / 60

            if remaining_minutes > settings.SESSION_REFRESH_THRESHOLD_MINUTES:
                logger.info(f"⏱️ [刷新会话] 用户 {user.user_id} 会话仍有效，剩余 {int(remaining_minutes)} 分钟")
                return {
                    "message": "会话仍然有效，无需刷新",
                    "remaining_minutes": int(remaining_minutes),
                    "expire_at": expire_timestamp
                }
        except (ValueError, TypeError):
            pass

    _set_login_cookies(response, user.user_id)

    china_now = get_china_now()
    expire_time = china_now + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)
    expire_at = int(expire_time.timestamp())

    logger.info(f"[刷新会话] 用户: {user.user_id}")
    logger.info(f"[刷新会话] 中国当前时间: {china_now.strftime('%Y-%m-%d %H:%M:%S')} (UTC+8)")
    logger.info(f"[刷新会话] 中国过期时间: {expire_time.strftime('%Y-%m-%d %H:%M:%S')} (UTC+8)")
    logger.info(f"[刷新会话] 过期时间戳 (秒): {expire_at}")
    logger.info(f"[刷新会话] Cookie max_age (秒): {settings.SESSION_EXPIRE_MINUTES * 60}")

    logger.info(f"用户 {user.user_id} 刷新会话成功")
    return {
        "message": "会话刷新成功",
        "expire_at": expire_at,
        "remaining_minutes": settings.SESSION_EXPIRE_MINUTES
    }


@router.post("/logout")
async def logout(request: Request, response: Response):
    """退出登录"""
    user_id = getattr(request.state, 'user_id', None)
    if user_id:
        logger.info(f"🚪 [退出] 用户 {user_id} 退出登录")

    response.delete_cookie("user_id")
    response.delete_cookie("session_token")
    response.delete_cookie("session_expire_at")
    return {"message": "退出登录成功"}


@router.get("/user")
async def get_current_user(request: Request):
    """获取当前登录用户信息"""
    if not hasattr(request.state, "user") or not request.state.user:
        raise HTTPException(status_code=401, detail="未登录")

    return request.state.user.dict()


@router.get("/password/status", response_model=PasswordStatusResponse)
async def get_password_status(request: Request):
    """获取当前用户的密码状态"""
    if not hasattr(request.state, "user") or not request.state.user:
        raise HTTPException(status_code=401, detail="未登录")

    user = request.state.user
    has_password = await password_manager.has_password(user.user_id)
    has_custom = await password_manager.has_custom_password(user.user_id)
    username = await password_manager.get_username(user.user_id)

    default_password = None

    return PasswordStatusResponse(
        has_password=has_password,
        has_custom_password=has_custom,
        username=username or user.username,
        default_password=default_password
    )


@router.post("/password/set", response_model=SetPasswordResponse)
async def set_user_password(request: Request, password_req: SetPasswordRequest):
    """设置当前用户的密码"""
    if not hasattr(request.state, "user") or not request.state.user:
        raise HTTPException(status_code=401, detail="未登录")

    user = request.state.user
    _validate_password(password_req.password)

    await password_manager.set_password(user.user_id, user.username, password_req.password)
    logger.info(f"用户 {user.user_id} ({user.username}) 设置了自定义密码")

    return SetPasswordResponse(
        success=True,
        message="密码设置成功"
    )


@router.post("/password/initialize", response_model=SetPasswordResponse)
async def initialize_user_password(request: Request, password_req: SetPasswordRequest):
    """
    初始化首次登录用户的密码

    用于首次通过 Linux DO 授权登录的用户，可以选择设置自定义密码或使用默认密码
    """
    if not hasattr(request.state, "user") or not request.state.user:
        raise HTTPException(status_code=401, detail="未登录")

    user = request.state.user

    if await password_manager.has_password(user.user_id):
        raise HTTPException(status_code=400, detail="密码已经初始化，请使用密码修改功能")

    _validate_password(password_req.password)

    await password_manager.set_password(user.user_id, user.username, password_req.password)
    logger.info(f"用户 {user.user_id} ({user.username}) 初始化密码成功")

    return SetPasswordResponse(
        success=True,
        message="密码初始化成功"
    )


@router.post("/bind/login", response_model=LocalLoginResponse)
async def bind_account_login(request: LocalLoginRequest, response: Response):
    """使用绑定的账号密码登录（LinuxDO授权后绑定的账号）"""
    all_users = await user_manager.get_all_users()
    target_user = None

    logger.info(f"[绑定账号登录] 尝试登录用户名: {request.username}")
    logger.info(f"[绑定账号登录] 当前共有 {len(all_users)} 个用户")

    for user in all_users:
        password_username = await password_manager.get_username(user.user_id)
        logger.info(f"[绑定账号登录] 检查用户 {user.user_id}: users.username={user.username}, passwords.username={password_username}")

        if user.username == request.username or password_username == request.username:
            target_user = user
            logger.info(f"[绑定账号登录] 找到匹配用户: {user.user_id}")
            break

    if not target_user:
        logger.warning(f"[绑定账号登录] 用户名 {request.username} 未找到")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    has_pwd = await password_manager.has_password(target_user.user_id)
    if not has_pwd:
        logger.warning(f"[绑定账号登录] 用户 {target_user.user_id} 没有设置密码")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    is_valid = await password_manager.verify_password(target_user.user_id, request.password)
    logger.info(f"[绑定账号登录] 用户 {target_user.user_id} 密码验证结果: {is_valid}")

    if not is_valid:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    _set_login_cookies(response, target_user.user_id)
    logger.info(f"✅ [绑定账号登录] 用户 {target_user.user_id} ({request.username}) 登录成功，会话有效期 {settings.SESSION_EXPIRE_MINUTES} 分钟")

    return LocalLoginResponse(
        success=True,
        message="登录成功",
        user=target_user.dict()
    )
