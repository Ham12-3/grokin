"""Docker provider for local dev: one container per user from `infra/computer`.

- Named volumes hold `/workspace` and the browser profile, so files and logins survive a
  restart or a rebuilt container.
- Only the control port is published, and only on 127.0.0.1 of this machine. The live screen
  and the browser are reached through the control server, behind its token.
- CPU, memory and process limits apply. Capabilities are dropped except the few `start.sh`
  needs to lock down the network before it drops to an unprivileged user.
"""

import asyncio
import time
import uuid
from typing import Any

import docker
import structlog
from docker.errors import DockerException, ImageNotFound, NotFound

from crew.computer.control import ControlBackedProvider
from crew.computer.provider import (
    ComputerError,
    ComputerHandle,
    ComputerState,
    control_token,
)
from crew.config import Settings

log = structlog.get_logger(__name__)

CONTROL_PORT = "7000/tcp"
START_TIMEOUT_SECONDS = 90
PORT_WAIT_SECONDS = 15
NOT_AVAILABLE = "Docker is not running on this server, so the computer cannot start."


class DockerProvider(ControlBackedProvider):
    name = "docker"

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._client: Any = None

    def _docker(self) -> Any:
        if self._client is None:
            try:
                self._client = docker.from_env()
            except DockerException as error:
                raise ComputerError(NOT_AVAILABLE) from error
        return self._client

    @staticmethod
    def _name(user_id: uuid.UUID) -> str:
        return f"crew-computer-{user_id}"

    def _create(self, user_id: uuid.UUID) -> Any:
        settings = self._settings
        try:
            return self._docker().containers.create(
                settings.computer_image,
                name=self._name(user_id),
                detach=True,
                environment={"CONTROL_TOKEN": control_token(settings, user_id)},
                volumes={
                    f"crew-workspace-{user_id}": {"bind": "/workspace", "mode": "rw"},
                    f"crew-profile-{user_id}": {"bind": "/home/crew/.config", "mode": "rw"},
                },
                # Reachable from this machine only; never from the network.
                ports={CONTROL_PORT: ("127.0.0.1", None)},
                mem_limit=settings.computer_memory,
                nano_cpus=int(settings.computer_cpus * 1_000_000_000),
                pids_limit=settings.computer_pids_limit,
                shm_size="1g",
                cap_drop=["ALL"],
                cap_add=["NET_ADMIN", "SETUID", "SETGID", "SETPCAP", "CHOWN", "DAC_OVERRIDE"],
                labels={"crew.user": str(user_id), "crew.role": "computer"},
            )
        except ImageNotFound as error:
            raise ComputerError(
                f"The computer image {settings.computer_image} is not built yet. "
                "Run `make computer-image` on the server."
            ) from error

    def _base_url(self, container: Any) -> str | None:
        # Docker publishes the port a moment after the container starts.
        deadline = time.monotonic() + PORT_WAIT_SECONDS
        while True:
            container.reload()
            bindings = (container.attrs["NetworkSettings"]["Ports"] or {}).get(CONTROL_PORT)
            if bindings:
                return f"http://127.0.0.1:{bindings[0]['HostPort']}"
            if container.status == "exited" or time.monotonic() > deadline:
                return None
            time.sleep(0.2)

    def _start_sync(self, user_id: uuid.UUID, recreate: bool) -> str:
        """Blocking Docker calls: runs in a thread."""
        client = self._docker()
        try:
            try:
                container = client.containers.get(self._name(user_id))
                if recreate:
                    container.remove(force=True)
                    container = self._create(user_id)
            except NotFound:
                container = self._create(user_id)
            if container.status != "running":
                container.start()
            base_url = self._base_url(container)
        except ComputerError:
            raise
        except DockerException as error:
            log.warning("computer.docker_failed", error=type(error).__name__)
            raise ComputerError(NOT_AVAILABLE) from error
        if base_url is None:
            raise ComputerError("Your computer started without its control port.")
        return base_url

    async def _wait_healthy(self, base_url: str) -> None:
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if await self.healthy(base_url):
                return
            await asyncio.sleep(0.5)
        raise ComputerError("Your computer did not start in time. Try again.")

    async def ensure(self, user_id: uuid.UUID) -> ComputerHandle:
        token = control_token(self._settings, user_id)
        base_url = await asyncio.to_thread(self._start_sync, user_id, False)
        await self._wait_healthy(base_url)
        handle = ComputerHandle(user_id, base_url, token)
        if not await self.token_accepted(handle):
            # The container was made with another secret. Rebuild it; the volumes stay.
            log.info("computer.recreate", reason="token mismatch")
            base_url = await asyncio.to_thread(self._start_sync, user_id, True)
            await self._wait_healthy(base_url)
            handle = ComputerHandle(user_id, base_url, token)
        return handle

    def _stop_sync(self, user_id: uuid.UUID) -> None:
        try:
            self._docker().containers.get(self._name(user_id)).stop(timeout=10)
        except NotFound:
            return
        except DockerException as error:
            raise ComputerError(NOT_AVAILABLE) from error

    async def stop(self, user_id: uuid.UUID) -> None:
        await asyncio.to_thread(self._stop_sync, user_id)

    def _state_sync(self, user_id: uuid.UUID) -> ComputerState:
        try:
            container = self._docker().containers.get(self._name(user_id))
        except NotFound:
            return "missing"
        except DockerException as error:
            raise ComputerError(NOT_AVAILABLE) from error
        return "running" if container.status == "running" else "stopped"

    async def state(self, user_id: uuid.UUID) -> ComputerState:
        return await asyncio.to_thread(self._state_sync, user_id)

    def _destroy_sync(self, user_id: uuid.UUID) -> None:
        """Removes the container AND its volumes. For tests and account deletion only."""
        client = self._docker()
        try:
            client.containers.get(self._name(user_id)).remove(force=True)
        except NotFound:
            pass
        for volume in (f"crew-workspace-{user_id}", f"crew-profile-{user_id}"):
            try:
                client.volumes.get(volume).remove(force=True)
            except NotFound:
                pass

    async def destroy(self, user_id: uuid.UUID) -> None:
        await asyncio.to_thread(self._destroy_sync, user_id)
