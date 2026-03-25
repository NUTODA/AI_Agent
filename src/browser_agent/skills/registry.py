"""Registry for runtime skills."""

from __future__ import annotations

from dataclasses import dataclass, field

from browser_agent.skills.base import BaseSkill
from browser_agent.skills.dialog import InspectDialogSkill
from browser_agent.skills.file_handling import UploadFileSkill
from browser_agent.skills.interaction import (
    ClickElementSkill,
    PressKeySkill,
    SelectOptionSkill,
    TypeTextSkill,
)
from browser_agent.skills.navigation import NavigateSkill, ScrollViewportSkill
from browser_agent.skills.observation import (
    ExtractPageTextSkill,
    GetInteractiveElementsSkill,
    ObservePageSkill,
    WaitForElementSkill,
)
from browser_agent.skills.reporting import FinishTaskSkill
from browser_agent.skills.safety import RequestConfirmationSkill


@dataclass(slots=True)
class SkillRegistry:
    """Simple in-memory registry keyed by skill name."""

    _skills: dict[str, BaseSkill] = field(default_factory=dict)

    def register(self, skill: BaseSkill) -> None:
        """Register a skill instance by name."""

        if skill.name in self._skills:
            raise ValueError(f"Skill `{skill.name}` is already registered.")
        self._skills[skill.name] = skill

    def get(self, name: str) -> BaseSkill:
        """Return a registered skill or raise a clear error."""

        try:
            return self._skills[name]
        except KeyError as exc:
            raise KeyError(f"Skill `{name}` is not registered.") from exc

    def list_names(self) -> list[str]:
        """Return registered skill names in sorted order."""

        return sorted(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills


def build_default_registry() -> SkillRegistry:
    """Bootstrap the MVP runtime skill set."""

    registry = SkillRegistry()
    for skill in (
        # Observation skills
        ObservePageSkill(),
        GetInteractiveElementsSkill(),
        ExtractPageTextSkill(),
        WaitForElementSkill(),
        # Navigation skills
        NavigateSkill(),
        ScrollViewportSkill(),
        # Interaction skills
        ClickElementSkill(),
        TypeTextSkill(),
        SelectOptionSkill(),
        PressKeySkill(),
        # File handling skills
        UploadFileSkill(),
        # Dialog skills
        InspectDialogSkill(),
        # Safety and reporting skills
        RequestConfirmationSkill(),
        FinishTaskSkill(),
    ):
        registry.register(skill)
    return registry
