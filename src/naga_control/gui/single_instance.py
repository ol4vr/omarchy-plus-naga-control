"""Reuse the existing GUI without duplicating its tray process on Linux."""

import os

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QWidget


def _request_existing(name: str) -> bool:
    socket = QLocalSocket()
    socket.setSocketOptions(QLocalSocket.SocketOption.AbstractNamespaceOption)
    socket.connectToServer(name)
    if not socket.waitForConnected(250):
        return False
    socket.disconnectFromServer()
    return True


class GuiInstance(QObject):
    """Own one per-user abstract socket for the lifetime of the GUI."""

    def __init__(self, show_server: QLocalServer, probe_server: QLocalServer) -> None:
        super().__init__()
        self._show_server = show_server
        self._probe_server = probe_server
        show_server.setParent(self)
        probe_server.setParent(self)
        self._window: QWidget | None = None
        show_server.newConnection.connect(self._receive_show)
        probe_server.newConnection.connect(self._receive_probe)

    @classmethod
    def start(
        cls, name: str | None = None, *, activate_existing: bool = True
    ) -> "GuiInstance | None":
        name = name or f"org.nagacontrol.NagaControl-gui-{os.getuid()}"
        probe_name = f"{name}-probe"
        target = name if activate_existing else probe_name
        if _request_existing(target):
            return None
        show_server = QLocalServer()
        show_server.setSocketOptions(QLocalServer.SocketOption.AbstractNamespaceOption)
        if not show_server.listen(name):
            if _request_existing(target):
                return None
            raise RuntimeError(
                f"could not establish the Naga Control GUI instance: {show_server.errorString()}"
            )
        probe_server = QLocalServer()
        probe_server.setSocketOptions(QLocalServer.SocketOption.AbstractNamespaceOption)
        if probe_server.listen(probe_name):
            return cls(show_server, probe_server)
        show_server.close()
        if _request_existing(target):
            return None
        raise RuntimeError(
            f"could not establish the Naga Control GUI probe: {probe_server.errorString()}"
        )

    def set_window(self, window: QWidget) -> None:
        self._window = window

    def close(self) -> None:
        self._probe_server.close()
        self._show_server.close()

    def _receive_show(self) -> None:
        while self._show_server.hasPendingConnections():
            socket = self._show_server.nextPendingConnection()
            socket.deleteLater()
            if self._window is not None:
                if self._window.isMinimized():
                    self._window.showNormal()
                elif not self._window.isVisible():
                    self._window.show()
                self._window.raise_()
                self._window.activateWindow()

    def _receive_probe(self) -> None:
        while self._probe_server.hasPendingConnections():
            self._probe_server.nextPendingConnection().deleteLater()
