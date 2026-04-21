import json
from pathlib import Path

from app.models import PreferencesPayload, ToolSection


ROOT_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT_DIR / "backend" / "data"
CONFIG_PATH = CONFIG_DIR / "tool_preferences.json"

DEFAULT_SECTIONS = [
    ToolSection(key="all", label="All Tools"),
    ToolSection(key="favorites", label="Favorites"),
    ToolSection(key="mapping", label="Mapping"),
    ToolSection(key="network", label="Network"),
    ToolSection(key="perception", label="Perception"),
    ToolSection(key="other", label="Other"),
]


def load_preferences() -> PreferencesPayload:
    if not CONFIG_PATH.exists():
        return PreferencesPayload(sections=DEFAULT_SECTIONS)

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload = PreferencesPayload(**data)
    if not any(section.key == "all" for section in payload.sections):
        payload.sections = [DEFAULT_SECTIONS[0], *payload.sections]
    if not any(section.key == "favorites" for section in payload.sections):
        payload.sections = [DEFAULT_SECTIONS[0], DEFAULT_SECTIONS[1], *[section for section in payload.sections if section.key != "all"]]
    return payload


def save_preferences(payload: PreferencesPayload) -> PreferencesPayload:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    sections = payload.sections
    if not any(section.key == "all" for section in sections):
        sections = [DEFAULT_SECTIONS[0], *sections]
    if not any(section.key == "favorites" for section in sections):
        sections = [DEFAULT_SECTIONS[0], DEFAULT_SECTIONS[1], *[section for section in sections if section.key != "all"]]

    normalized = PreferencesPayload(
        sections=sections,
        section_assignments=payload.section_assignments,
        favorite_keys=payload.favorite_keys,
    )
    CONFIG_PATH.write_text(
        normalized.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return normalized
