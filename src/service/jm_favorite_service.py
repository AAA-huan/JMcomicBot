"""JM 账号临时会话与单向收藏导入，不保存账号密码或 Cookie。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Event, RLock, Thread
from typing import Callable, Dict, Iterator, List, Optional, Protocol, Set, Tuple, cast
from uuid import uuid4

from jmcomic import JmOption

from src.database.models import utc_now
from src.database.repositories.jm_favorite_repository import (
    JmFavoriteRepository,
    import_view,
)

from .web_auth_service import AuthenticatedSession


class FavoritePage(Protocol):
    """仅使用收藏接口中明确存在的字段。"""

    total: int

    def iter_id_title(self) -> Iterator[Tuple[str, str]]:
        """遍历漫画编号和标题。"""
        raise NotImplementedError

    def iter_folder_id_name(self) -> Iterator[Tuple[str, str]]:
        """遍历收藏夹编号和名称。"""
        raise NotImplementedError


class FavoriteClient(Protocol):
    """可替换为真实 jmcomic 客户端或不联网的测试客户端。"""

    def login(self, username: str, password: str) -> object:
        """登录失败由客户端抛出异常。"""
        raise NotImplementedError

    def favorite_folder(self) -> FavoritePage:
        """读取全部收藏第一页及收藏夹目录。"""
        raise NotImplementedError

    def favorite_folder_gen(self, folder_id: str) -> Iterator[FavoritePage]:
        """分页读取指定收藏夹。"""
        raise NotImplementedError


def create_favorite_client() -> FavoriteClient:
    """独立客户端不共享机器人 Cookie，也不执行用户下载插件。"""
    return cast(
        FavoriteClient, JmOption.default().new_jm_client(impl="api", cache=False)
    )


class JmFavoriteError(Exception):
    """稳定的中文业务错误，禁止透传可能包含凭据的第三方异常文本。"""

    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class AccountSession:
    """与 WebUI 当前会话绑定，服务重启后自动失效。"""

    admin_id: int
    username: str
    client: FavoriteClient
    expires_at: datetime
    folders: Dict[str, str]
    total: int


class JmFavoriteService:
    """串行后台导入；分页错误保留已完成结果并明确标记失败。"""

    def __init__(
        self,
        repository: JmFavoriteRepository,
        client_factory: Callable[[], FavoriteClient] = create_favorite_client,
    ) -> None:
        self.repository = repository
        self.client_factory = client_factory
        self._sessions: Dict[str, AccountSession] = {}
        self._connecting: Dict[str, str] = {}
        self._lock = RLock()
        self._stop = Event()
        self._worker: Optional[Thread] = None
        self._active: Optional[Tuple[int, str, str]] = None
        self.repository.recover_interrupted()

    def cleanup_expired(self) -> None:
        """由应用生命周期定期清理，未再访问的账号会话也会及时释放。"""
        with self._lock:
            self._sessions = {
                key: value
                for key, value in self._sessions.items()
                if value.expires_at > utc_now()
            }

    def account_status(self, authenticated: AuthenticatedSession) -> Dict[str, object]:
        """账号会话仅当前 WebUI 会话可见，导入记录按管理员隔离。"""
        self.cleanup_expired()
        with self._lock:
            account = self._sessions.get(authenticated.session_id)
            if account is None or account.admin_id != authenticated.admin_id:
                return {"connected": False}
            return {
                "connected": True,
                "username": account.username,
                "expires_at": account.expires_at,
                "total": account.total,
                "folders": [
                    {"id": key, "name": name} for key, name in account.folders.items()
                ],
            }

    def login(
        self, authenticated: AuthenticatedSession, username: str, password: str
    ) -> Dict[str, object]:
        """不保留密码，不把上游登录响应（含 Cookie 等）返回前端。"""
        username = username.strip()
        if not username:
            raise JmFavoriteError("JM_INVALID_USERNAME", "JM 用户名不能为空", 400)
        key = authenticated.session_id
        attempt_id = str(uuid4())
        with self._lock:
            if key in self._connecting or (
                self._active is not None and self._active[2] == key
            ):
                raise JmFavoriteError("JM_BUSY", "当前会话正在登录或导入，请等待完成")
            self._connecting[key] = attempt_id
            self._sessions.pop(key, None)
        try:
            client = self.client_factory()
            client.login(username, password)
            page = client.favorite_folder()
            folders = {
                str(folder_id): str(name)
                for folder_id, name in page.iter_folder_id_name()
            }
            folders["0"] = "全部收藏"
            expires_at = min(
                authenticated.expires_at, utc_now() + timedelta(minutes=30)
            )
            with self._lock:
                if self._stop.is_set() or self._connecting.get(key) != attempt_id:
                    raise JmFavoriteError("JM_SESSION_CLOSED", "登录已取消，请重新登录")
                self._sessions[key] = AccountSession(
                    authenticated.admin_id,
                    username,
                    client,
                    expires_at,
                    folders,
                    int(page.total),
                )
        except JmFavoriteError:
            raise
        # 网络和登录接口的异常可能包含原始响应，只暴露异常类型，不记录秘密。
        except Exception as error:  # pylint: disable=broad-exception-caught
            raise JmFavoriteError(
                "JM_LOGIN_FAILED",
                f"JM 登录或收藏夹读取失败（{type(error).__name__}），请检查账号及部署网络。",
                502,
            ) from None
        finally:
            with self._lock:
                if self._connecting.get(key) == attempt_id:
                    self._connecting.pop(key)
        return self.account_status(authenticated)

    def logout(self, session_id: str) -> None:
        """释放当前账号会话；正在导入的任务在下一页前中断。"""
        with self._lock:
            self._sessions.pop(session_id, None)
            self._connecting.pop(session_id, None)

    def logout_all(self) -> None:
        """WebUI 修改密码时清理全部 JM 账号会话。"""
        with self._lock:
            self._sessions.clear()
            self._connecting.clear()

    def start_import(
        self, authenticated: AuthenticatedSession, folder_ids: List[str]
    ) -> Dict[str, object]:
        """禁止同一服务同时发起多个导入，确保客户端会话和分页计数一致。"""
        self.cleanup_expired()
        with self._lock:
            if self._stop.is_set():
                raise JmFavoriteError("JM_SERVICE_STOPPED", "服务正在停止")
            account = self._sessions.get(authenticated.session_id)
            if account is None or account.admin_id != authenticated.admin_id:
                raise JmFavoriteError(
                    "JM_LOGIN_REQUIRED", "JM 账号未登录或已过期，请重新登录"
                )
            if self._active is not None:
                raise JmFavoriteError("JM_IMPORT_RUNNING", "已有收藏导入任务正在执行")
            chosen = list(dict.fromkeys(folder_ids))
            if not chosen or any(
                folder_id not in account.folders for folder_id in chosen
            ):
                raise JmFavoriteError("JM_INVALID_FOLDER", "请选择有效的收藏夹", 400)
            if "0" in chosen:
                # 全部收藏页包含未归入自建收藏夹的漫画，再遍历各夹保留成员关系。
                chosen = ["0"] + [
                    folder_id for folder_id in account.folders if folder_id != "0"
                ]
            job = self.repository.create_import(
                authenticated.admin_id, str(uuid4()), account.username, chosen
            )
            self._active = (authenticated.admin_id, job.id, authenticated.session_id)
            self._worker = Thread(
                target=self._run_import,
                args=(authenticated.session_id, account, job.id, chosen),
                daemon=True,
                name="jm-favorite-import",
            )
            self._worker.start()
            return import_view(job)

    def _ensure_active(self, session_id: str, account: AccountSession) -> None:
        with self._lock:
            if (
                self._stop.is_set()
                or self._sessions.get(session_id) is not account
                or account.expires_at <= utc_now()
            ):
                raise JmFavoriteError(
                    "JM_IMPORT_INTERRUPTED",
                    "账号会话已结束，导入中断；已导入的漫画保留，请重新登录并导入。",
                )

    def _run_import(
        self,
        session_id: str,
        account: AccountSession,
        job_id: str,
        folder_ids: List[str],
    ) -> None:
        seen: Set[str] = set()
        try:
            for folder_id in folder_ids:
                iterator = account.client.favorite_folder_gen(folder_id=folder_id)
                while True:
                    # 在下一次联网请求前检查会话，退出账号后不继续翻页。
                    self._ensure_active(session_id, account)
                    try:
                        page = next(iterator)
                    except StopIteration:
                        break
                    self._ensure_active(session_id, account)
                    items = [
                        (str(manga_id), str(title))
                        for manga_id, title in page.iter_id_title()
                    ]
                    if any(
                        not manga_id.isascii()
                        or not manga_id.isdecimal()
                        or len(manga_id) > 32
                        or len(title) > 255
                        for manga_id, title in items
                    ):
                        raise JmFavoriteError(
                            "JM_INVALID_PAGE",
                            "收藏页返回了无效漫画编号或标题，导入已停止。",
                            502,
                        )
                    self.repository.save_page(
                        account.admin_id,
                        job_id,
                        folder_id,
                        account.folders[folder_id],
                        items,
                        seen,
                    )
            self._ensure_active(session_id, account)
            self.repository.finish(account.admin_id, job_id, "succeeded")
        except JmFavoriteError as error:
            self.repository.finish(
                account.admin_id,
                job_id,
                "interrupted" if error.code == "JM_IMPORT_INTERRUPTED" else "failed",
                str(error),
            )
        # 后台任务必须写入失败终态；不透传第三方异常正文以免泄露账号会话。
        except Exception as error:  # pylint: disable=broad-exception-caught
            self.repository.finish(
                account.admin_id,
                job_id,
                "failed",
                f"收藏导入失败（{type(error).__name__}），已完成页保留，可重新导入。",
            )
        finally:
            with self._lock:
                self._active = None

    def shutdown(self) -> None:
        """应用停止时中断任务，网络请求线程不阻塞进程退出。"""
        self._stop.set()
        with self._lock:
            self._sessions.clear()
            self._connecting.clear()
            if self._active is not None:
                admin_id, job_id, _session_id = self._active
                self.repository.finish(
                    admin_id,
                    job_id,
                    "interrupted",
                    "服务停止，已完成页保留，请重新登录并导入。",
                )
