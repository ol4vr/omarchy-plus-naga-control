"""Bind Qt object lifetime to the otherwise Qt-free service model."""

from collections.abc import Callable

from PySide6.QtCore import QObject

from naga_control.gui.models import ServiceModel


def subscribe_model(owner: QObject, model: ServiceModel, listener: Callable[[], None]) -> None:
    """Remove a model listener before its owning Qt object becomes invalid."""
    unsubscribe = model.add_listener(listener)
    owner.destroyed.connect(unsubscribe)
