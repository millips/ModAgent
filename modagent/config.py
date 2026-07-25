import json
import os
import hashlib
from dataclasses import dataclass, asdict, field

CONFIG_DIR = os.path.abspath(os.environ.get(
    "MODAGENT_DATA_DIR", os.path.join(os.path.expanduser("~"), ".modagent")))
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PROMPT_FILE = os.path.join(CONFIG_DIR, "prompt.md")


def current_edition() -> str:
    value = (os.environ.get("MODAGENT_EDITION") or "free").strip().lower()
    return value if value in {"free", "subscription"} else "free"


def current_channel() -> str:
    value = (os.environ.get("MODAGENT_CHANNEL") or "stable").strip().lower()
    return value if value in {"stable", "beta"} else "stable"


def make_game_instance_id(game_root: str) -> str:
    """Return a stable local-install identity, separate from catalogue slugs."""
    if not game_root:
        return ""
    normalized = os.path.normcase(os.path.realpath(os.path.abspath(
        os.path.expandvars(os.path.expanduser(game_root))
    )))
    digest = hashlib.sha256(normalized.encode("utf-8", errors="surrogatepass")).hexdigest()
    return f"gi_{digest[:20]}"


def game_storage_id(cfg, requested: str = "") -> str:
    """Resolve legacy catalogue-slug callers to the selected install instance."""
    requested = str(requested or "")
    instance_id = str(getattr(cfg, "game_instance_id", "") or "")
    catalogue_slug = str(getattr(cfg, "game_slug", "") or "")
    if instance_id and (not requested or requested in {catalogue_slug, instance_id}):
        return instance_id
    return requested or catalogue_slug


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
    game_instance_id: str = ""
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
    if cfg.game_root and not cfg.game_instance_id:
        cfg.game_instance_id = make_game_instance_id(cfg.game_root)
    normalized_manual_games = []
    for entry in cfg.manual_games or []:
        normalized = dict(entry)
        path = str(normalized.get("path") or normalized.get("game_root") or "")
        if path and not normalized.get("game_instance_id"):
            normalized["game_instance_id"] = make_game_instance_id(path)
        normalized_manual_games.append(normalized)
    cfg.manual_games = normalized_manual_games
    if cfg.game_instance_id and cfg.game_slug:
        roots = dict(cfg.manual_mod_dirs or {})
        if cfg.game_instance_id not in roots and cfg.game_slug in roots:
            roots[cfg.game_instance_id] = list(roots[cfg.game_slug])
        cfg.manual_mod_dirs = roots
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

    CORE_FEATURES = ["search", "download", "install", "rollback"]
    FEATURES = {
        FREE: CORE_FEATURES,
        PRO: CORE_FEATURES + [
            "patch",
            "structured_recommendations",
            "subscription_experience",
        ],
        # Reserved internal tier. It does not represent a separately shipped
        # product and must not be advertised as an available edition.
        SUPER: CORE_FEATURES + [
            "patch",
            "structured_recommendations",
            "subscription_experience",
        ],
    }

    @classmethod
    def can(cls, tier: str, feature: str) -> bool:
        return feature in cls.FEATURES.get(tier, cls.FEATURES[cls.FREE])
