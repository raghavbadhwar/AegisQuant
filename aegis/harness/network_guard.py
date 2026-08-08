"""Best-effort in-process network denial for deterministic replay providers."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch


class NetworkAccessDenied(RuntimeError):
    pass


def _denied(*args: object, **kwargs: object) -> None:
    del args, kwargs
    raise NetworkAccessDenied("network access is forbidden in replay")


@contextmanager
def deny_network_io() -> Iterator[None]:
    """Deny Python socket creation during the enclosed replay operation."""
    with (
        patch.object(socket, "socket", _denied),
        patch.object(socket, "create_connection", _denied),
    ):
        yield
