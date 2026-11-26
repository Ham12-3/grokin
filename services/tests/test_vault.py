"""The Vault: encryption, ownership, placeholders and the secret never reaching the model."""

import base64
import logging
import os
import uuid
from typing import Any

import pytest
import structlog
from sqlalchemy import select, text

from crew.llm.base import ToolUse
from crew.llm.fake import FakeLLM, Turn
from crew.logs import configure
from crew.models import AuditLog, VaultItem
from crew.tools import default_registry
from crew.tools.registry import Args, Tool, ToolContext, ToolOutput
from crew.vault import inject, service
from crew.vault.crypto import (
    KmsKeyWrapper,
    MasterKeyWrapper,
    Sealed,
    VaultError,
    create_wrapper,
    seal,
    unseal,
)
from tests.conftest import TEST_VAULT_KEY, Ctx
from tests.helpers import API, create_bot, public_resolver, run_worker, send, sign_in

SECRET = "ghp_test0nly5ecretValue1234567890"


def _wrapper() -> MasterKeyWrapper:
    return MasterKeyWrapper(TEST_VAULT_KEY)


# --- Crypto -----------------------------------------------------------------------------


def test_round_trip_and_nothing_readable_at_rest() -> None:
    user = uuid.uuid4()
    sealed = seal(_wrapper(), user, "github_token", SECRET)
    assert SECRET.encode() not in sealed.ciphertext + sealed.wrapped_data_key
    assert len(sealed.nonce) == 12 and sealed.wrapped_by == "master"
    assert unseal(_wrapper(), user, "github_token", sealed) == SECRET
    # A fresh key and nonce every time.
    again = seal(_wrapper(), user, "github_token", SECRET)
    assert (
        again.ciphertext != sealed.ciphertext and again.wrapped_data_key != sealed.wrapped_data_key
    )


def test_another_user_another_name_or_another_master_key_cannot_decrypt() -> None:
    user = uuid.uuid4()
    sealed = seal(_wrapper(), user, "github_token", SECRET)
    with pytest.raises(VaultError):
        unseal(_wrapper(), uuid.uuid4(), "github_token", sealed)  # row copied to another user
    with pytest.raises(VaultError):
        unseal(_wrapper(), user, "other_name", sealed)
    other_key = MasterKeyWrapper(base64.b64encode(os.urandom(32)).decode())
    with pytest.raises(VaultError):
        unseal(other_key, user, "github_token", sealed)
    tampered = Sealed(
        sealed.ciphertext[:-1] + b"\x00", sealed.nonce, sealed.wrapped_data_key, "master"
    )
    with pytest.raises(VaultError):
        unseal(_wrapper(), user, "github_token", tampered)


def test_master_key_must_be_32_bytes_and_setup_is_required(ctx_settings: Any = None) -> None:
    with pytest.raises(VaultError):
        MasterKeyWrapper(base64.b64encode(b"too short").decode())
    with pytest.raises(VaultError):
        MasterKeyWrapper("not base64 !!")


def test_kms_wraps_the_data_key_with_the_configured_key() -> None:
    class FakeKms:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def encrypt(self, KeyId: str, Plaintext: bytes) -> dict[str, bytes]:
            self.calls.append(("encrypt", KeyId))
            return {"CiphertextBlob": b"kms:" + bytes(reversed(Plaintext))}

        def decrypt(self, KeyId: str, CiphertextBlob: bytes) -> dict[str, bytes]:
            self.calls.append(("decrypt", KeyId))
            return {"Plaintext": bytes(reversed(CiphertextBlob[4:]))}

    kms = FakeKms()
    wrapper = KmsKeyWrapper("alias/crew-vault", client=kms)
    user = uuid.uuid4()
    sealed = seal(wrapper, user, "card", "4111")
    assert sealed.wrapped_by == "kms" and unseal(wrapper, user, "card", sealed) == "4111"
    assert kms.calls == [("encrypt", "alias/crew-vault"), ("decrypt", "alias/crew-vault")]
    # An item wrapped by KMS is not readable with the dev master key, and the reverse.
    with pytest.raises(VaultError):
        unseal(_wrapper(), user, "card", sealed)


def test_a_server_without_any_key_has_no_vault(ctx: Ctx) -> None:
    settings = ctx.settings.model_copy(update={"vault_master_key": "", "vault_kms_key_id": ""})
    with pytest.raises(VaultError):
        create_wrapper(settings)


# --- API --------------------------------------------------------------------------------


async def _add(
    ctx: Ctx, me: dict[str, str], name: str = "github_token", value: str = SECRET
) -> dict[str, Any]:
    resp = await ctx.client.post(
        f"{API}/vault", headers=me, json={"name": name, "type": "api_key", "value": value}
    )
    assert resp.status_code == 201, resp.text
    item: dict[str, Any] = resp.json()
    return item


async def test_values_go_in_and_never_come_out(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    added = await _add(ctx, me)
    assert set(added) == {"id", "name", "type", "created_at"}
    listed = await ctx.client.get(f"{API}/vault", headers=me)
    assert SECRET not in listed.text and [item["name"] for item in listed.json()] == [
        "github_token"
    ]
    async with ctx.session_factory() as session:
        row = (await session.scalars(select(VaultItem))).one()
        raw = (
            await session.execute(text("SELECT ciphertext, wrapped_data_key FROM vault_items"))
        ).one()
        assert SECRET.encode() not in raw[0] + raw[1]
        assert await service.reveal(session, _wrapper(), row.user_id, "github_token") == SECRET

    dup = await ctx.client.post(
        f"{API}/vault", headers=me, json={"name": "github_token", "type": "api_key", "value": "x"}
    )
    assert dup.status_code == 409
    for bad in ("Has Spaces", "1starts_with_digit", "x"):
        resp = await ctx.client.post(
            f"{API}/vault", headers=me, json={"name": bad, "type": "note", "value": "v"}
        )
        assert resp.status_code == 422, bad
    # A validation error never echoes the value back.
    wrong = await ctx.client.post(
        f"{API}/vault", headers=me, json={"name": "ok_name", "type": "nope", "value": SECRET}
    )
    assert wrong.status_code == 422 and SECRET not in wrong.text


async def test_another_user_cannot_list_use_or_delete_an_item(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    item = await _add(ctx, me)
    other = await sign_in(ctx, "mallory@example.com")
    assert (await ctx.client.get(f"{API}/vault", headers=other)).json() == []
    assert (await ctx.client.delete(f"{API}/vault/{item['id']}", headers=other)).status_code == 404
    assert (await ctx.client.get(f"{API}/vault")).status_code == 401
    other_id = uuid.UUID((await ctx.client.get(f"{API}/me", headers=other)).json()["id"])
    async with ctx.session_factory() as session:
        # Same name, other user: not found, and their id cannot open the row either.
        assert await service.reveal(session, _wrapper(), other_id, "github_token") is None
        args, _ = {"cmd": "echo {{vault:github_token}}"}, None
        with pytest.raises(inject.MissingSecret):
            await inject.resolve(session, _wrapper(), other_id, args, tool="terminal_run")
    assert (await ctx.client.delete(f"{API}/vault/{item['id']}", headers=me)).status_code == 204
    assert (await ctx.client.get(f"{API}/vault", headers=me)).json() == []


# --- Placeholders -----------------------------------------------------------------------


async def test_placeholders_are_swapped_everywhere_in_the_arguments(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    await _add(ctx, me)
    await _add(ctx, me, "db_password", "hunter2hunter2")
    user_id = uuid.UUID((await ctx.client.get(f"{API}/me", headers=me)).json()["id"])
    args = {
        "cmd": "gh auth login --with-token <<< {{vault:github_token}}",
        "env": {"PGPASSWORD": "{{ vault:db_password }}", "n": 3},
        "list": ["{{vault:github_token}}", "plain"],
    }
    assert inject.names_in(args) == {"github_token", "db_password"}
    async with ctx.session_factory() as session:
        real, values = await inject.resolve(session, _wrapper(), user_id, args, tool="terminal_run")
        used = (await session.scalars(select(AuditLog).where(AuditLog.action == "vault.use"))).all()
    assert real == {
        "cmd": f"gh auth login --with-token <<< {SECRET}",
        "env": {"PGPASSWORD": "hunter2hunter2", "n": 3},
        "list": [SECRET, "plain"],
    }
    assert str(args["cmd"]).endswith("{{vault:github_token}}")  # the stored args are untouched
    assert sorted(values) == sorted([SECRET, "hunter2hunter2"])
    assert [row.detail for row in used] == [
        {"names": ["db_password", "github_token"], "tool": "terminal_run"}
    ]
    inject.forget_active()


def test_redaction_replaces_every_copy_longest_first() -> None:
    values = ["abcd", "abcd-and-more"]
    assert inject.redact("x abcd-and-more y abcd z", values) == "x [redacted] y [redacted] z"
    assert inject.redact("pin 12", ["12"]) == "pin 12"  # too short to scrub safely


# --- A full run -------------------------------------------------------------------------


def _echo_tool(seen: list[Args]) -> Tool:
    async def handler(args: Args, tool_ctx: ToolContext) -> ToolOutput:
        seen.append(args)
        # A tool that prints its input back, like `gh` printing a token in an error.
        return ToolOutput(f"logged in with {args['token']}", f"Used {args['token']}")

    return Tool(
        name="cli_login",
        description="Log in to a CLI",
        input_schema={
            "type": "object",
            "properties": {"token": {"type": "string"}},
            "required": ["token"],
        },
        handler=handler,
        summary=lambda args: f"Logged in with {args.get('token')}",
        read_only=True,
    )


async def test_a_run_uses_a_secret_that_never_reaches_the_model_the_database_or_the_logs(
    ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    configure("INFO")
    me = await sign_in(ctx, "a@example.com")
    await _add(ctx, me)
    bot = await create_bot(ctx, me)
    seen: list[Args] = []
    registry = default_registry(public_resolver)
    registry.register(_echo_tool(seen))
    sent = await send(ctx, me, bot["direct_chat_id"], "Log in to GitHub with my token")
    llm = FakeLLM(
        [
            Turn(
                ["Logging in."],
                [ToolUse("toolu_1", "cli_login", {"token": "{{vault:github_token}}"})],
            ),
            Turn(["Logged in."]),
        ]
    )
    # Using a secret always asks first, even for a tool that is otherwise safe.
    assert await run_worker(ctx, sent["run_id"], llm, registry=registry) == "waiting_approval"
    assert seen == []
    (approval,) = (await ctx.client.get(f"{API}/approvals?status=pending", headers=me)).json()
    assert approval["preview"]["context"]["vault"] == "github_token"
    assert approval["preview"]["fields"] == {"token": "{{vault:github_token}}"}
    await ctx.client.post(f"{API}/approvals/{approval['id']}/approve", headers=me)

    structlog.get_logger("test").info(
        "tool.debug", detail=f"before the run {SECRET}"
    )  # not active yet
    assert await run_worker(ctx, sent["run_id"], llm, registry=registry) == "completed"

    # The tool got the real value...
    assert seen == [{"token": SECRET}]
    # ...and nobody else did: not the model,
    assert SECRET not in str(llm.calls)
    result = llm.calls[1]["messages"][-1]["content"][0]["content"]
    assert result == "logged in with [redacted]"
    # not the API,
    page = await ctx.client.get(f"{API}/chats/{bot['direct_chat_id']}/messages", headers=me)
    calls = await ctx.client.get(f"{API}/runs/{sent['run_id']}/tool-calls", headers=me)
    assert SECRET not in page.text + calls.text
    assert calls.json()[0]["result_summary"] == "Used [redacted]"
    # not the database (outside the encrypted Vault row),
    async with ctx.session_factory() as session:
        for query in (
            "SELECT tool_calls::text FROM tool_calls",
            "SELECT runs::text FROM runs",
            "SELECT messages::text FROM messages",
            "SELECT approvals::text FROM approvals",
            "SELECT audit_log::text FROM audit_log",
        ):
            dump = (await session.execute(text(query))).scalars().all()
            assert SECRET not in "".join(dump), query
    # and not the logs.
    logs = capsys.readouterr()
    assert "run.finished" in logs.out
    assert (
        logs.out.count(SECRET) == 1 and "before the run" in logs.out
    )  # only our own line, made before
    logging.getLogger().handlers.clear()


async def test_a_log_line_written_during_the_run_is_scrubbed(
    ctx: Ctx, capsys: pytest.CaptureFixture[str]
) -> None:
    configure("INFO")
    me = await sign_in(ctx, "a@example.com")
    await _add(ctx, me)
    user_id = uuid.UUID((await ctx.client.get(f"{API}/me", headers=me)).json()["id"])
    async with ctx.session_factory() as session:
        await inject.resolve(
            session, _wrapper(), user_id, {"t": "{{vault:github_token}}"}, tool="x"
        )
    structlog.get_logger("test").warning(
        "tool.crashed", error=f"bad token {SECRET}", nested={"a": [SECRET]}
    )
    out = capsys.readouterr().out
    assert SECRET not in out and out.count("[redacted]") == 2
    inject.forget_active()


async def test_an_unknown_vault_name_is_a_clear_tool_error(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    seen: list[Args] = []
    registry = default_registry(public_resolver)
    registry.register(_echo_tool(seen))
    sent = await send(ctx, me, bot["direct_chat_id"], "log in")
    llm = FakeLLM(
        [
            Turn([], [ToolUse("toolu_1", "cli_login", {"token": "{{vault:nope}}"})]),
            Turn(["I could not."]),
        ]
    )
    assert await run_worker(ctx, sent["run_id"], llm, registry=registry) == "waiting_approval"
    (approval,) = (await ctx.client.get(f"{API}/approvals?status=pending", headers=me)).json()
    await ctx.client.post(f"{API}/approvals/{approval['id']}/approve", headers=me)
    assert await run_worker(ctx, sent["run_id"], llm, registry=registry) == "completed"
    assert seen == []
    block = llm.calls[1]["messages"][-1]["content"][0]
    assert block["is_error"] is True and block["content"] == "There is no Vault item named nope."


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("CREW_RUN_SLOW"), reason="slow Docker test")
async def test_a_real_terminal_gets_the_secret_and_nobody_else_does(ctx: Ctx) -> None:
    """The Done-means case: a token used by a command on the real computer."""
    from crew.computer.docker_provider import DockerProvider

    me = await sign_in(ctx, "a@example.com")
    await _add(ctx, me)
    bot = await create_bot(ctx, me)
    user_id = uuid.UUID((await ctx.client.get(f"{API}/me", headers=me)).json()["id"])
    provider = DockerProvider(ctx.settings)
    # The command proves the real value arrived (its length) and tries to print it back.
    command = 'T="{{vault:github_token}}"; echo "length=${#T}"; echo "token=$T"'
    sent = await send(ctx, me, bot["direct_chat_id"], "check my GitHub token")
    llm = FakeLLM(
        [Turn(["Checking."], [ToolUse("toolu_1", "terminal_run", {"cmd": command})]), Turn(["ok"])]
    )
    try:
        assert await run_worker(ctx, sent["run_id"], llm, provider=provider) == "waiting_approval"
        (approval,) = (await ctx.client.get(f"{API}/approvals?status=pending", headers=me)).json()
        assert approval["preview"]["context"]["vault"] == "github_token"
        await ctx.client.post(f"{API}/approvals/{approval['id']}/approve", headers=me)
        assert await run_worker(ctx, sent["run_id"], llm, provider=provider) == "completed"
    finally:
        await provider.destroy(user_id)
        await provider.aclose()
    output = llm.calls[1]["messages"][-1]["content"][0]["content"]
    assert f"length={len(SECRET)}" in output and "token=[redacted]" in output
    assert SECRET not in str(llm.calls)
    calls = await ctx.client.get(f"{API}/runs/{sent['run_id']}/tool-calls", headers=me)
    assert SECRET not in calls.text
