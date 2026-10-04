from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GameState:
    grid: list
    sietch: tuple
    x: int
    y: int
    hp: int
    water: int
    spice: int = 0
    form: str = "human"
    turn: int = 0
    worms: list = field(default_factory=list)  # [(x, y)]
    abilities: set = field(default_factory=set)
    flags: dict = field(default_factory=dict)
    done: bool = False
    ending: str | None = None
    log: list = field(default_factory=list)

    @property
    def at_sietch(self) -> bool:
        return (self.x, self.y) == tuple(self.sietch)
