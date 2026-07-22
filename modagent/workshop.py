import json
import os
import re
import shutil
import zipfile

from .config import CONFIG_DIR

WORKSHOP_DIR = os.path.join(CONFIG_DIR, "workshop")

TEXT_EXTENSIONS = {".json", ".yaml", ".yml", ".ini", ".cfg", ".xml", ".lua", ".reds", ".txt", ".md", ".py", ".js", ".ts", ".toml"}


def list_files(mod_id: str, game_root: str = "") -> dict:
    from . import db
    mod = db.get_mod(mod_id)
    if not mod:
        return {"error": f"Mod {mod_id} 未找到"}

    files = json.loads(mod.files_installed) if isinstance(mod.files_installed, str) else (mod.files_installed or [])
    readme = ""
    file_list = []

    for f in files:
        ext = os.path.splitext(f)[1].lower()
        is_text = ext in TEXT_EXTENSIONS
        size_kb = round(os.path.getsize(f) / 1024, 1) if os.path.exists(f) else 0
        entry = {"path": f, "ext": ext, "type": "text" if is_text else "binary", "size_kb": size_kb}
        file_list.append(entry)

        bn = os.path.basename(f).lower()
        if bn in ("readme.txt", "readme.md", "readme", "install.txt", "readme.html"):
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as rf:
                    readme = rf.read()[:2000]
            except Exception:
                pass

    file_list.sort(key=lambda x: (x["type"] == "binary", x["path"].lower()))

    return {
        "mod_id": mod_id,
        "mod_name": mod.name,
        "game_root": game_root,
        "readme": readme,
        "files": file_list,
        "editable_count": sum(1 for f in file_list if f["type"] == "text"),
    }


def read_file(mod_id: str, file_path: str, max_chars: int = 3000) -> dict:
    from . import db
    mod = db.get_mod(mod_id)
    if not mod:
        return {"error": f"Mod {mod_id} 未找到"}

    files = json.loads(mod.files_installed) if isinstance(mod.files_installed, str) else (mod.files_installed or [])
    if file_path not in files:
        return {"error": f"文件 {file_path} 不在此 Mod 中"}

    if not os.path.exists(file_path):
        return {"error": f"文件不存在: {file_path}"}

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in TEXT_EXTENSIONS:
        return {"error": f"不支持编辑二进制文件 ({ext})，只支持: {', '.join(sorted(TEXT_EXTENSIONS))}"}

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return {"error": f"读取失败: {e}"}

    truncated = len(content) > max_chars
    return {
        "path": file_path,
        "content": content[:max_chars] if truncated else content,
        "total_chars": len(content),
        "truncated": truncated,
    }


def write_file(mod_id: str, file_path: str, new_content: str, game_root: str, game_slug: str) -> dict:
    from . import db, snapshot

    mod = db.get_mod(mod_id)
    if not mod:
        return {"error": f"Mod {mod_id} 未找到"}

    files = json.loads(mod.files_installed) if isinstance(mod.files_installed, str) else (mod.files_installed or [])
    if file_path not in files:
        return {"error": f"文件 {file_path} 不在此 Mod 中"}

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in TEXT_EXTENSIONS:
        return {"error": f"不支持编辑二进制文件 ({ext})"}

    real_file = os.path.realpath(file_path)
    real_root = os.path.realpath(game_root)
    try:
        if os.path.commonpath([real_root, real_file]) != real_root:
            return {"error": "拒绝写入游戏目录外的文件"}
    except ValueError:
        return {"error": "路径越界"}

    if not os.path.exists(os.path.dirname(file_path)):
        return {"error": f"目标目录不存在"}

    snap_id = snapshot.snapshot_create(game_root, game_slug, trigger_mod_name=f"修改 {mod.name}")

    backup_path = file_path + ".modagent_bak"
    try:
        shutil.copy2(file_path, backup_path)
    except Exception as e:
        return {"error": f"备份失败: {e}"}

    if ext in (".json",):
        try:
            json.loads(new_content)
        except json.JSONDecodeError as e:
            return {"error": f"JSON 语法错误: {e}"}
    elif ext in (".yaml", ".yml"):
        try:
            import yaml
            yaml.safe_load(new_content)
        except ImportError:
            pass
        except Exception as e:
            return {"error": f"YAML 语法错误: {e}"}

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        return {"error": f"写入失败: {e}"}

    return {
        "ok": True,
        "snapshot_id": snap_id,
        "backup_path": backup_path,
        "file": file_path,
        "chars_written": len(new_content),
    }


def build_zip(workshop_name: str, game_slug: str) -> dict:
    workshop_path = os.path.join(WORKSHOP_DIR, workshop_name)
    if not os.path.isdir(workshop_path):
        return {"error": f"工作目录不存在: {workshop_path}"}

    from .downloader import DOWNLOADS_DIR
    downloads_dir = DOWNLOADS_DIR
    zip_name = f"{workshop_name}.zip"
    zip_path = os.path.join(downloads_dir, game_slug, zip_name)
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(workshop_path):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, workshop_path)
                zf.write(full, rel)

    return {
        "workshop_name": workshop_name,
        "zip_path": zip_path,
        "ready_to_install": True,
    }
