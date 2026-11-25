"""The real Docker computer. Slow: needs Docker and the `crew-computer:dev` image.

Skipped unless CREW_RUN_SLOW=1 (`make check-slow`). Some checks need internet access.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.typing import Subprotocol

from crew.computer.docker_provider import DockerProvider
from crew.computer.provider import ComputerError, ComputerHandle
from crew.config import Settings

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not os.environ.get("CREW_RUN_SLOW"), reason="slow Docker test (set CREW_RUN_SLOW=1)"
    ),
]

SECRET = "test-only-computer-secret-0123456789abcdef"


@pytest.fixture(scope="module")
async def computer() -> AsyncIterator[tuple[DockerProvider, ComputerHandle, uuid.UUID]]:
    """One real container for the whole module. Removed, with its volumes, afterwards."""
    settings = Settings(_env_file=None, computer_token_secret=SECRET, jwt_secret=SECRET)
    provider = DockerProvider(settings)
    user_id = uuid.uuid4()
    try:
        handle = await provider.ensure(user_id)
        yield provider, handle, user_id
    finally:
        await provider.destroy(user_id)
        await provider.aclose()


Computer = tuple[DockerProvider, ComputerHandle, uuid.UUID]


async def test_commands_run_as_an_unprivileged_user_in_the_workspace(computer: Computer) -> None:
    provider, handle, _ = computer
    result = await provider.exec(handle, "whoami && pwd && id -u", 20)
    assert result.exit_code == 0
    assert result.stdout.split() == ["crew", "/workspace", "1000"]
    # No way back to root, and the control token is not in the environment.
    sudo = await provider.exec(handle, 'sudo true; echo "token=[${CONTROL_TOKEN:-}]"', 20)
    assert "token=[]" in sudo.stdout
    assert "sudo" in sudo.stderr


async def test_file_round_trip_and_confinement(computer: Computer) -> None:
    provider, handle, _ = computer
    await provider.write_file(handle, "reports/q3.md", b"hello from the test")
    assert await provider.read_file(handle, "reports/q3.md") == b"hello from the test"
    names = {entry.name for entry in await provider.list_dir(handle, ".")}
    assert {"reports", "outputs", "inbox"} <= names
    seen = await provider.exec(handle, "cat reports/q3.md", 20)
    assert seen.stdout == "hello from the test"
    with pytest.raises(ComputerError, match="outside your workspace"):
        await provider.read_file(handle, "../etc/passwd")
    with pytest.raises(ComputerError, match="outside your workspace"):
        await provider.write_file(handle, "../../tmp/escape", b"x")


async def test_a_command_that_runs_too_long_is_killed(computer: Computer) -> None:
    provider, handle, _ = computer
    result = await provider.exec(handle, "sleep 30; echo done", 2)
    assert result.timed_out is True
    assert "done" not in result.stdout


async def test_private_networks_and_metadata_are_blocked(computer: Computer) -> None:
    provider, handle, _ = computer
    probe = (
        "for target in http://169.254.169.254/ http://host.docker.internal:8000/ "
        "http://172.17.0.1:8000/ http://10.0.0.1/ http://192.168.65.254:5432/; do "
        'curl -s -o /dev/null -m 4 "$target" && echo "REACHED $target" || echo "blocked $target"; '
        "done"
    )
    result = await provider.exec(handle, probe, 40)
    assert "REACHED" not in result.stdout, result.stdout
    assert result.stdout.count("blocked") == 5
    # The rules cannot be changed from inside.
    flush = await provider.exec(handle, "iptables -F OUTPUT 2>&1; echo exit=$?", 20)
    assert "exit=0" not in flush.stdout


async def test_public_internet_works(computer: Computer) -> None:
    provider, handle, _ = computer
    result = await provider.exec(
        handle, "curl -s -o /dev/null -m 20 -w '%{http_code}' https://example.com/", 30
    )
    assert result.stdout.strip() == "200", result.stderr


async def test_control_server_refuses_a_wrong_token(computer: Computer) -> None:
    _, handle, _ = computer
    async with httpx.AsyncClient() as http:
        for headers in ({}, {"X-Control-Token": "wrong"}):
            response = await http.post(
                f"{handle.base_url}/exec", json={"cmd": "id"}, headers=headers
            )
            assert response.status_code == 401
    assert handle.base_url.startswith("http://127.0.0.1:")  # never published to the network


async def test_browser_opens_and_reads_a_page(computer: Computer) -> None:
    provider, handle, _ = computer
    await provider.start_display(handle, 1)
    page = await provider.browser(handle, 1, "open", url="https://example.com/")
    assert page["title"] == "Example Domain"
    assert "documentation examples" in page["text"]
    assert page["elements"], "the page's link should be listed"
    link = page["elements"][0]
    assert link["tag"] == "a"

    after = await provider.browser(handle, 1, "click", element=link["id"])
    assert "iana.org" in after["url"]

    shot = await provider.browser(handle, 1, "screenshot")
    assert shot["path"].startswith("/workspace/outputs/screenshots/") and shot["size"] > 1000
    with pytest.raises(ComputerError, match="Only http and https"):
        await provider.browser(handle, 1, "open", url="file:///etc/passwd")


async def test_live_screen_speaks_vnc_and_needs_the_token(computer: Computer) -> None:
    provider, handle, _ = computer
    await provider.start_display(handle, 1)
    async with connect(provider.vnc_url(handle, 1), subprotocols=[Subprotocol("binary")]) as socket:
        banner = await asyncio.wait_for(socket.recv(), 10)
        assert isinstance(banner, bytes) and banner.startswith(b"RFB 003.")

    wrong = provider.vnc_url(handle, 1).split("?")[0] + "?token=wrong"
    with pytest.raises((InvalidStatus, ConnectionClosed)):
        async with connect(wrong, subprotocols=[Subprotocol("binary")]) as socket:
            await asyncio.wait_for(socket.recv(), 5)


async def test_files_and_browser_profile_survive_a_restart(computer: Computer) -> None:
    provider, handle, user_id = computer
    await provider.write_file(handle, "keep.md", b"still here")
    await provider.start_display(handle, 1)
    await provider.browser(handle, 1, "open", url="https://example.com/")
    marker = await provider.exec(
        handle, "touch /home/crew/.config/chromium-1/crew-test-marker && echo ok", 20
    )
    assert marker.stdout.strip() == "ok"

    await provider.stop(user_id)
    assert await provider.state(user_id) == "stopped"
    restarted = await provider.ensure(user_id)
    assert await provider.state(user_id) == "running"

    assert await provider.read_file(restarted, "keep.md") == b"still here"
    profile = await provider.exec(
        restarted, "ls /home/crew/.config/chromium-1/crew-test-marker && echo kept", 20
    )
    assert "kept" in profile.stdout
    # The browser comes back after the restart.
    page = await provider.browser(restarted, 1, "open", url="https://example.com/")
    assert page["title"] == "Example Domain"
