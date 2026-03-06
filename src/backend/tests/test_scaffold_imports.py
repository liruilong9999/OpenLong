from app.channel.manager import ChannelManager
from app.self_evolution.engine import SelfEvolutionEngine


def test_reserved_modules_available() -> None:
    manager = ChannelManager()
    engine = SelfEvolutionEngine()

    assert manager.list_channels() == []
    assert engine.propose_update_plan("main")
