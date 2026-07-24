import json
import os
from dataclasses import dataclass, asdict, field

CONFIG_DIR = os.path.abspath(os.environ.get(
    "MODAGENT_DATA_DIR", os.path.join(os.path.expanduser("~"), ".modagent")))
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PROMPT_FILE = os.path.join(CONFIG_DIR, "prompt.md")


def current_edition() -> str:
    value = (os.environ.get("MODAGENT_EDITION") or "free").strip().lower()
    return value if value in {"free", "subscription"} else "free"


def entitlement_tier() -> str:
    """Return the capability tier owned by the signed desktop edition."""
    return "pro" if current_edition() == "subscription" else "free"


def edition_data_dir(*parts: str) -> str:
    return os.path.join(CONFIG_DIR, "editions", current_edition(), *parts)


@dataclass
class Config:
    nexus_api_key: str = ""
    game_name: str = ""
    game_slug: str = ""
    game_id: int = 0
    game_root: str = ""
    mod_loader: str = ""
    chrome_cdp_port: int = 18888
    llm_api_key: str = ""
    llm_endpoint: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-v4-pro"
    tier: str = "free"
    tavily_api_key: str = ""
    workshop_dir: str = ""
    recommendation_limit: int = 10
    manual_games: list[dict] = field(default_factory=list)
    # Per-game Vortex/MO2/Fluffy/custom mod roots.
    manual_mod_dirs: dict[str, list[str]] = field(default_factory=dict)
    dev_mode: bool = False          # 开发者模式:开启后记录 trace 并暴露 /debug 端点


def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


_SECRET_ENV = {
    "nexus_api_key": "MODAGENT_NEXUS_API_KEY",
    "llm_api_key": "MODAGENT_LLM_API_KEY",
    "tavily_api_key": "MODAGENT_TAVILY_API_KEY",
}


def load() -> Config:
    data = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    filtered = {k: v for k, v in data.items() if k in Config.__dataclass_fields__}
    cfg = Config(**filtered)
    try:
        cfg.recommendation_limit = max(2, min(int(cfg.recommendation_limit), 20))
    except (TypeError, ValueError):
        cfg.recommendation_limit = 10
    # Edition is authoritative: stale config cannot downgrade Pro or unlock free.
    cfg.tier = entitlement_tier()
    for field, env_name in _SECRET_ENV.items():
        value = os.environ.get(env_name)
        if value:
            setattr(cfg, field, value)
    return cfg


def save(cfg: Config):
    ensure_config_dir()
    data = asdict(cfg)
    data["tier"] = entitlement_tier()
    if os.environ.get("MODAGENT_SECURE_SECRETS") == "1":
        for field in _SECRET_ENV:
            data.pop(field, None)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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
