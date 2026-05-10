from .california import CaliforniaEngine
from ..registry import StateEngineRegistry


def register_overrides(engines: StateEngineRegistry) -> None:
    engines.register("CA", CaliforniaEngine)


__all__ = ["CaliforniaEngine", "register_overrides"]
