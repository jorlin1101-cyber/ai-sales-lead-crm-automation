import socket

import pytest
from pytest_socket import SocketConnectBlockedError


def test_external_network_is_blocked() -> None:
    with pytest.warns(UserWarning, match="A test tried to use socket"):
        with pytest.raises(SocketConnectBlockedError):
            socket.create_connection(("192.0.2.1", 80), timeout=0.01)
