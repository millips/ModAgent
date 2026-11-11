"""Pure prompt entry point; old templates remain available for offline audits."""
from . import config
from .orchestration.prompting import build_core_prompt


def build_prompt(cfg):
    return build_core_prompt(cfg, custom_style=config.load_prompt())
