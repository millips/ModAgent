import json
import os
from dataclasses import dataclass, asdict

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".modagent")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PROMPT_FILE = os.path.join(CONFIG_DIR, "prompt.md")


@dataclass
class Config:
    nexus_api_key: str = ""
    game_name: str = "Skyrim Special Edition"
    game_slug: str = "skyrimspecialedition"
    game_id: int = 1704
    game_root: str = ""
    mod_loader: str = ""
    chrome_cdp_port: int = 18888
    llm_api_key: str = ""
    llm_endpoint: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-v4-pro"
    tier: str = "free"
    tavily_api_key: str = ""
    workshop_dir: str = ""
    dev_mode: bool = False          # 开发者模式:开启后记录 trace 并暴露 /debug 端点


def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load() -> Config:
    if not os.path.exists(CONFIG_FILE):
        return Config()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    filtered = {k: v for k, v in data.items() if k in Config.__dataclass_fields__}
    return Config(**filtered)


def save(cfg: Config):
    ensure_config_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2, ensure_ascii=False)


def load_prompt() -> str:
    if os.path.exists(PROMPT_FILE):
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def save_prompt(text: str):
    ensure_config_dir()
    with open(PROMPT_FILE, "w", encoding="utf-8") as f:
        f.write(text)


class Tier:
    FREE = "free"
    PRO = "pro"
    SUPER = "super"

    FEATURES = {
        FREE: ["search", "download", "install", "rollback"],
        PRO: ["search", "download", "install", "rollback", "patch", "builtin_llm"],
        SUPER: ["search", "download", "install", "rollback", "patch", "builtin_llm", "vibe_coding", "persona"],
    }

    @classmethod
    def can(cls, tier: str, feature: str) -> bool:
        return feature in cls.FEATURES.get(tier, cls.FEATURES[cls.FREE])
