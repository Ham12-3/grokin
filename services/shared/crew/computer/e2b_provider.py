"""E2B provider for production. NOT BUILT YET: this is the shape it has to fill.

TODO (when an E2B account is available):
- `ensure`: create a desktop sandbox from a template built from `infra/computer` (or resume
  the paused one stored in `computers.external_id`), pass CONTROL_TOKEN, and return a handle
  whose `base_url` is the sandbox's control-server address.
- `stop`: pause the sandbox so the disk and the browser profile persist.
- `state`: map the sandbox state to running / stopped / missing.
- Everything else comes from `ControlBackedProvider`, as long as the sandbox runs the same
  control server on port 7000.
- Network rules: confirm E2B blocks private ranges and metadata addresses, or keep the
  iptables rules from `start.sh`.
"""

import uuid

from crew.computer.control import ControlBackedProvider
from crew.computer.provider import ComputerError, ComputerHandle, ComputerState
from crew.config import Settings

NOT_BUILT = "The E2B computer provider is not built yet. Set COMPUTER_PROVIDER=docker."


class E2BProvider(ControlBackedProvider):
    name = "e2b"

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

    async def ensure(self, user_id: uuid.UUID) -> ComputerHandle:
        raise ComputerError(NOT_BUILT)

    async def stop(self, user_id: uuid.UUID) -> None:
        raise ComputerError(NOT_BUILT)

    async def state(self, user_id: uuid.UUID) -> ComputerState:
        return "missing"
