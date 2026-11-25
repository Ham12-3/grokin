"""Cloud computer providers behind one ComputerProvider interface."""

from crew.computer.provider import ComputerProvider
from crew.config import Settings


def create_provider(settings: Settings) -> ComputerProvider:
    if settings.computer_provider == "docker":
        from crew.computer.docker_provider import DockerProvider

        return DockerProvider(settings)
    if settings.computer_provider == "e2b":
        from crew.computer.e2b_provider import E2BProvider

        return E2BProvider(settings)
    from crew.computer.local_provider import LocalProvider

    return LocalProvider(settings)


__all__ = ["ComputerProvider", "create_provider"]
