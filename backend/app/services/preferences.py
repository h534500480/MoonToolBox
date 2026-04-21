import json
from pathlib import Path

from app.models import PreferencesPayload, ToolSection


ROOT_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT_DIR / "backend" / "data"
CONFIG_PATH = CONFIG_DIR / "tool_preferences.json"

DEFAULT_SECTIONS = [
    ToolSection(key="all", label="全部工具"),
    ToolSection(key="favorites", label="收藏夹"),
    ToolSection(key="mapping", label="地图处理"),
    ToolSection(key="network", label="网络工具"),
    ToolSection(key="perception", label="感知工具"),
    ToolSection(key="entertainment", label="娱乐分区"),
    ToolSection(key="other", label="其他工具"),
]

FIXED_SECTION_LABELS = {section.key: section.label for section in DEFAULT_SECTIONS}


def _normalize_sections(sections):
    custom_sections = []
    section_map = {}
    for section in sections:
        if section.key in section_map:
            continue
        if section.key in FIXED_SECTION_LABELS:
            section_map[section.key] = ToolSection(key=section.key, label=FIXED_SECTION_LABELS[section.key])
        else:
            custom_sections.append(section)

    normalized = []
    for default_section in DEFAULT_SECTIONS:
        normalized.append(section_map.get(default_section.key, default_section))
    normalized.extend(custom_sections)
    return normalized


def load_preferences() -> PreferencesPayload:
    if not CONFIG_PATH.exists():
        return PreferencesPayload(sections=DEFAULT_SECTIONS)

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload = PreferencesPayload(**data)
    payload.sections = _normalize_sections(payload.sections)
    return payload


def save_preferences(payload: PreferencesPayload) -> PreferencesPayload:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    sections = _normalize_sections(payload.sections)

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
