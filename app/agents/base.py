"""Clase base de agentes: identidad, skills declaradas y bitácora compartida."""
from __future__ import annotations

from typing import Callable, List

from ..config import Settings

LogFn = Callable[[str, str, str, dict], None]


class Agent:
    name: str = "agent"
    title: str = "Agente"
    mission: str = ""
    skills: List[str] = []          # coincide con /skills/<skill>/SKILL.md

    def __init__(self, settings: Settings, log_fn: LogFn):
        self.settings = settings
        self._log = log_fn

    def log(self, msg: str, level: str = "info", **data) -> None:
        self._log(self.name, level, msg, data)

    def describe(self) -> dict:
        return {"name": self.name, "title": self.title, "mission": self.mission, "skills": self.skills}
