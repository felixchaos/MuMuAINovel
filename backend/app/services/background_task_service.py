"""后台任务管理服务 - 管理长时间运行的AI生成任务"""
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, update
from app.database import get_engine
from app.models.background_task import BackgroundTask
from app.logger import get_logger

logger = get_logger(__name__)


class TaskProgressTracker:
    """后台任务进度追踪器（替代SSE的WizardProgressTracker）"""

    def __init__(self, task_id: str, user_id: str, task_name: str = "任务"):
        self.task_id = task_id
        self.user_id = user_id
        self.task_name = task_name
        self.current_progress = 0
        self._last_generating_progress = 20

    async def _update_task(self, **kwargs):
        """更新任务状态到数据库"""
        try:
            engine = await get_engine(self.user_id)
            AsyncSessionLocal = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(BackgroundTask).where(BackgroundTask.id == self.task_id)
                )
                task = result.scalar_one_or_none()
                if task:
                    for key, value in kwargs.items():
                        setattr(task, key, value)
                    task.updated_at = datetime.now()
                    await session.commit()
        except Exception as e:
            logger.error(f"❌ 更新任务进度失败: {e}")

    async def start(self, message: str = None):
        self.current_progress = 0
        msg = message or f"开始生成{self.task_name}..."
        await self._update_task(
            status="running", progress=0, status_message=msg,
            started_at=datetime.now(),
            progress_details={"stage": "init", "message": msg}
        )

    async def loading(self, message: str = None, sub_progress: float = 0.5):
        progress = 5 + int(10 * sub_progress)
        self.current_progress = progress
        msg = message or "加载数据中..."
        await self._update_task(
            progress=progress, status_message=msg,
            progress_details={"stage": "loading", "message": msg}
        )

    async def preparing(self, message: str = None):
        self.current_progress = 17
        msg = message or "准备AI提示词..."
        await self._update_task(
            progress=17, status_message=msg,
            progress_details={"stage": "preparing", "message": msg}
        )

    async def generating(self, current_chars: int = 0, estimated_total: int = 5000,
                         message: str = None, retry_count: int = 0, max_retries: int = 3):
        sub_progress = min(current_chars / max(estimated_total, 1), 1.0)
        progress = 20 + int(65 * sub_progress)
        if progress < self._last_generating_progress:
            progress = self._last_generating_progress
        else:
            self._last_generating_progress = progress
        self.current_progress = progress

        retry_suffix = f" (重试 {retry_count}/{max_retries})" if retry_count > 0 else ""
        msg = message or f"生成{self.task_name}中... ({current_chars}字符){retry_suffix}"
        await self._update_task(
            progress=progress, status_message=msg,
            progress_details={"stage": "generating", "message": msg, "current_chars": current_chars}
        )

    async def parsing(self, message: str = None):
        self.current_progress = 88
        msg = message or f"解析{self.task_name}数据..."
        await self._update_task(
            progress=88, status_message=msg,
            progress_details={"stage": "parsing", "message": msg}
        )

    async def saving(self, message: str = None, sub_progress: float = 0.5):
        progress = 92 + int(6 * sub_progress)
        self.current_progress = progress
        msg = message or f"保存{self.task_name}到数据库..."
        await self._update_task(
            progress=progress, status_message=msg,
            progress_details={"stage": "saving", "message": msg}
        )

    async def complete(self, message: str = None):
        self.current_progress = 100
        msg = message or f"{self.task_name}生成完成!"
        await self._update_task(
            status="completed", progress=100, status_message=msg,
            completed_at=datetime.now(),
            progress_details={"stage": "complete", "message": msg}
        )

    async def error(self, error_message: str):
        await self._update_task(
            status="failed", error_message=error_message,
            status_message=f"失败: {error_message}",
            completed_at=datetime.now(),
            progress_details={"stage": "error", "message": error_message}
        )

    async def warning(self, message: str):
        await self._update_task(
            status_message=f"⚠️ {message}",
            progress_details={"stage": "warning", "message": message}
        )

    async def retry(self, retry_count: int, max_retries: int, reason: str = "准备重试"):
        msg = f"⚠️ {reason}... ({retry_count}/{max_retries})"
        await self._update_task(
            status_message=msg, retry_count=retry_count,
            progress_details={"stage": "retry", "message": msg, "retry_count": retry_count}
        )

    def reset_generating_progress(self):
        self._last_generating_progress = 20

    async def check_cancelled(self) -> bool:
        """检查任务是否被取消"""
        try:
            engine = await get_engine(self.user_id)
            AsyncSessionLocal = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(BackgroundTask.cancel_requested)
                    .where(BackgroundTask.id == self.task_id)
                )
                cancelled = result.scalar_one_or_none()
                return bool(cancelled)
        except Exception:
            return False


class BackgroundTaskService:
    """后台任务管理服务（按用户排队：同用户任务逐个执行，不同用户可并发）"""

    def __init__(self):
        self._user_queues: Dict[str, asyncio.Queue] = {}   # user_id -> Queue
        self._user_workers: Dict[str, bool] = {}            # user_id -> worker是否运行中

    def _ensure_user_queue(self, user_id: str) -> asyncio.Queue:
        """确保指定用户的队列已初始化"""
        if user_id not in self._user_queues:
            self._user_queues[user_id] = asyncio.Queue()
        return self._user_queues[user_id]

    async def _start_user_worker(self, user_id: str):
        """启动指定用户的工作协程"""
        if self._user_workers.get(user_id, False):
            return
        self._user_workers[user_id] = True
        asyncio.create_task(self._user_worker_loop(user_id))
        logger.info(f"📋 用户 {user_id[:8]} 的任务队列工作协程已启动")

    async def _user_worker_loop(self, user_id: str):
        """从指定用户的队列中逐个取出任务并执行"""
        queue = self._user_queues[user_id]
        try:
            while True:
                try:
                    task_item = await queue.get()
                    task_id = task_item["task_id"]
                    task_func = task_item["task_func"]
                    args = task_item["args"]
                    kwargs = task_item["kwargs"]

                    logger.info(f"🔄 [用户{user_id[:8]}] 队列开始执行任务: {task_id[:8]} (队列剩余: {queue.qsize()})")

                    try:
                        if await self._is_task_cancelled_before_start(task_id, user_id):
                            logger.info(f"🚫 [用户{user_id[:8]}] 任务已在排队时取消，跳过执行: {task_id[:8]}")
                            continue
                        await task_func(task_id, args["user_id"], *args["extra_args"], **kwargs)
                    except Exception as e:
                        logger.error(f"❌ 后台任务 {task_id[:8]} 异常: {e}", exc_info=True)
                        # 确保任务状态更新为失败
                        try:
                            engine = await get_engine(user_id)
                            AsyncSessionLocal = async_sessionmaker(
                                engine, class_=AsyncSession, expire_on_commit=False
                            )
                            async with AsyncSessionLocal() as session:
                                result = await session.execute(
                                    select(BackgroundTask).where(BackgroundTask.id == task_id)
                                )
                                task = result.scalar_one_or_none()
                                if task and task.status == "running":
                                    task.status = "failed"
                                    task.error_message = str(e)
                                    task.status_message = f"任务失败: {str(e)}"
                                    task.completed_at = datetime.now()
                                    await session.commit()
                        except Exception as update_err:
                            logger.error(f"❌ 更新失败任务状态失败: {update_err}")
                    finally:
                        queue.task_done()
                        logger.info(f"✅ [用户{user_id[:8]}] 队列任务完成: {task_id[:8]} (队列剩余: {queue.qsize()})")

                except Exception as e:
                    logger.error(f"❌ [用户{user_id[:8]}] 队列工作循环异常: {e}", exc_info=True)
        finally:
            # 工作协程退出时清理标记
            self._user_workers.pop(user_id, None)
            logger.info(f"📋 用户 {user_id[:8]} 的工作协程已退出")

    @staticmethod
    async def create_task(
        user_id: str,
        project_id: str,
        task_type: str,
        task_input: Dict[str, Any] = None,
        db: AsyncSession = None
    ) -> BackgroundTask:
        """创建后台任务记录"""
        task = BackgroundTask(
            user_id=user_id,
            project_id=project_id,
            task_type=task_type,
            task_input=task_input or {},
            status="pending",
            progress=0,
            status_message="任务已创建，等待执行..."
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        logger.info(f"📋 创建后台任务: {task.id[:8]} type={task_type} project={project_id[:8]}")
        return task

    @staticmethod
    async def get_task(task_id: str, user_id: str, db: AsyncSession) -> Optional[BackgroundTask]:
        """获取任务详情"""
        result = await db.execute(
            select(BackgroundTask).where(
                BackgroundTask.id == task_id,
                BackgroundTask.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_project_tasks(
        project_id: str, user_id: str, db: AsyncSession,
        task_type: str = None, limit: int = 20
    ) -> list:
        """获取项目的任务列表"""
        query = (
            select(BackgroundTask)
            .where(
                BackgroundTask.project_id == project_id,
                BackgroundTask.user_id == user_id
            )
            .order_by(BackgroundTask.created_at.desc())
        )
        if task_type:
            query = query.where(BackgroundTask.task_type == task_type)
        query = query.limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    @staticmethod
    async def cancel_task(task_id: str, user_id: str, db: AsyncSession) -> bool:
        """请求取消任务"""
        result = await db.execute(
            select(BackgroundTask).where(
                BackgroundTask.id == task_id,
                BackgroundTask.user_id == user_id
            )
        )
        task = result.scalar_one_or_none()
        if not task:
            return False
        if task.status not in ("pending", "running"):
            return False
        task.cancel_requested = True
        task.status = "cancelled"
        task.status_message = "任务已取消"
        task.completed_at = datetime.now()
        await db.commit()
        logger.info(f"🚫 取消任务: {task_id[:8]}")
        return True

    @staticmethod
    async def cleanup_old_tasks(user_id: str, db: AsyncSession, days: int = 7):
        """清理旧任务记录"""
        from sqlalchemy import delete as sql_delete
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)
        result = await db.execute(
            sql_delete(BackgroundTask).where(
                BackgroundTask.user_id == user_id,
                BackgroundTask.status.in_(["completed", "failed", "cancelled"]),
                BackgroundTask.completed_at < cutoff
            )
        )
        if result.rowcount > 0:
            await db.commit()
            logger.info(f"🧹 清理用户 {user_id[:8]} 的 {result.rowcount} 条旧任务记录")

    async def spawn_background_task(
        self,
        task_id: str,
        user_id: str,
        task_func: Callable[..., Awaitable],
        *args,
        **kwargs
    ):
        """
        将任务加入该用户的队列排队执行（同一用户FIFO，不同用户可并发）
        
        Args:
            task_id: 任务ID
            user_id: 用户ID
            task_func: 异步任务函数
            *args, **kwargs: 传递给task_func的参数
        """
        # 确保该用户的队列和工作协程已启动
        queue = self._ensure_user_queue(user_id)
        await self._start_user_worker(user_id)

        # 将任务放入该用户的队列
        await queue.put({
            "task_id": task_id,
            "task_func": task_func,
            "args": {"user_id": user_id, "extra_args": args},
            "kwargs": kwargs,
        })
        queue_size = queue.qsize()
        logger.info(f"📥 任务已加入用户 {user_id[:8]} 的队列: {task_id[:8]} (当前队列长度: {queue_size})")

        # 更新任务状态，显示排队位置
        try:
            engine = await get_engine(user_id)
            AsyncSessionLocal = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(BackgroundTask).where(BackgroundTask.id == task_id)
                )
                task = result.scalar_one_or_none()
                if task and task.status == "pending":
                    if queue_size > 0:
                        task.status_message = f"排队中，前方还有 {queue_size} 个任务等待..."
                    else:
                        task.status_message = "即将开始执行..."
                    task.progress_details = {"stage": "queued", "queue_size": queue_size}
                    task.updated_at = datetime.now()
                    await session.commit()
        except Exception as e:
            logger.error(f"更新队列位置信息失败: {e}")

    def get_queue_size(self, user_id: str = None) -> int:
        """获取队列中等待的任务数量"""
        if user_id:
            queue = self._user_queues.get(user_id)
            return queue.qsize() if queue else 0
        # 所有用户队列总数
        return sum(q.qsize() for q in self._user_queues.values())

    def get_all_queue_info(self) -> Dict[str, int]:
        """获取所有用户的队列信息"""
        return {
            uid: q.qsize() for uid, q in self._user_queues.items() if q.qsize() > 0
        }

    @staticmethod
    async def _is_task_cancelled_before_start(task_id: str, user_id: str) -> bool:
        """避免排队中已取消的任务被 worker 重新拉起。"""
        try:
            engine = await get_engine(user_id)
            AsyncSessionLocal = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(BackgroundTask.status, BackgroundTask.cancel_requested)
                    .where(BackgroundTask.id == task_id)
                )
                row = result.one_or_none()
                if not row:
                    return True
                status, cancel_requested = row
                return status == "cancelled" or bool(cancel_requested)
        except Exception as e:
            logger.error(f"检查任务取消状态失败: {e}")
            return False


# 全局单例
background_task_service = BackgroundTaskService()
