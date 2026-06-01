"""Web-started Codex login task management."""

import asyncio
import os
import time
from collections import deque
from pathlib import Path
from typing import Optional

from account_manager import account_dir, validate_account_name
from codex_cli import CODEX_CLI_MISSING_MESSAGE, find_codex_cli


class LoginTask:
    def __init__(
        self,
        name: str,
        target_dir: Path,
        codex_cli: str,
        *,
        force_relogin: bool = False,
    ):
        self.name = name
        self.target_dir = target_dir
        self.codex_cli = codex_cli
        self.force_relogin = force_relogin
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.error: Optional[str] = None
        self.backup_path: Optional[Path] = None
        self.restored_backup = False
        self.process: Optional[asyncio.subprocess.Process] = None
        self._readers: list[asyncio.Task] = []
        self._logs = deque(maxlen=120)

    @property
    def auth_path(self) -> Path:
        return self.target_dir / "auth.json"

    def append_log(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        self.updated_at = time.time()
        self._logs.append(line)

    async def start(self) -> None:
        self.target_dir.mkdir(parents=True, exist_ok=True)
        if self.force_relogin and self.auth_path.exists():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self.backup_path = self.target_dir / f"auth.json.relogin-backup-{stamp}"
            self.auth_path.replace(self.backup_path)
            self.append_log(f"existing auth.json backed up to {self.backup_path.name}.")
        env = {**os.environ, "CODEX_HOME": str(self.target_dir)}
        self.process = await asyncio.create_subprocess_exec(
            self.codex_cli,
            "login",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        self.append_log("codex login started; complete the browser sign-in to finish.")
        if self.process.stdout:
            self._readers.append(asyncio.create_task(self._read_output(self.process.stdout)))

    async def _read_output(self, stream: asyncio.StreamReader) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            self.append_log(line.decode(errors="replace"))

    async def stop(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        for reader in self._readers:
            reader.cancel()
        if self._readers:
            await asyncio.gather(*self._readers, return_exceptions=True)
        self.error = "login task stopped"
        self._restore_backup_if_needed()
        self.append_log("login task stopped.")

    async def status(self) -> dict:
        returncode = None
        if self.process:
            returncode = self.process.returncode
            if returncode is None:
                returncode = self.process.returncode

        has_auth = self.auth_path.exists()
        if self.error:
            state = "error"
        elif has_auth:
            state = "success"
        elif self.process and self.process.returncode is not None:
            state = "error" if self.process.returncode else "waiting_for_auth"
            if state == "error" and not self.error:
                self.error = f"codex login exited with code {self.process.returncode}"
                self._restore_backup_if_needed()
        else:
            state = "running"

        return {
            "name": self.name,
            "state": state,
            "has_auth": has_auth,
            "returncode": returncode,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "logs": list(self._logs),
            "account_dir": str(self.target_dir),
            "force_relogin": self.force_relogin,
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "restored_backup": self.restored_backup,
        }

    def _restore_backup_if_needed(self) -> None:
        if self.restored_backup or self.auth_path.exists() or not self.backup_path:
            return
        if not self.backup_path.exists():
            return
        self.backup_path.replace(self.auth_path)
        self.restored_backup = True
        self.append_log("previous auth.json restored.")


class LoginManager:
    def __init__(self):
        self._tasks: dict[str, LoginTask] = {}

    async def start(self, name: str, *, force_relogin: bool = False) -> dict:
        safe_name = validate_account_name(name)
        target_dir = account_dir(safe_name)
        auth_path = target_dir / "auth.json"
        if auth_path.exists() and not force_relogin:
            raise ValueError("account already has auth.json")

        existing = self._tasks.get(safe_name)
        if existing:
            status = await existing.status()
            if status["state"] in {"running", "waiting_for_auth"}:
                return status

        codex_cli = find_codex_cli()
        if not codex_cli:
            raise FileNotFoundError(CODEX_CLI_MISSING_MESSAGE)

        task = LoginTask(
            safe_name,
            target_dir,
            codex_cli,
            force_relogin=force_relogin,
        )
        self._tasks[safe_name] = task
        await task.start()
        return await task.status()

    async def status(self, name: str) -> dict:
        safe_name = validate_account_name(name)
        task = self._tasks.get(safe_name)
        if task:
            return await task.status()
        target_dir = account_dir(safe_name)
        return {
            "name": safe_name,
            "state": "success" if (target_dir / "auth.json").exists() else "not_started",
            "has_auth": (target_dir / "auth.json").exists(),
            "returncode": None,
            "error": None,
            "created_at": None,
            "updated_at": None,
            "logs": [],
            "account_dir": str(target_dir),
        }

    async def stop(self, name: str) -> dict:
        safe_name = validate_account_name(name)
        task = self._tasks.get(safe_name)
        if not task:
            return await self.status(safe_name)
        await task.stop()
        return await task.status()

    async def cleanup(self) -> None:
        await asyncio.gather(
            *(task.stop() for task in self._tasks.values()),
            return_exceptions=True,
        )
