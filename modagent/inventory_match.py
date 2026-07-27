"""Conservative matching between upstream candidates and installed mods."""
from __future__ import annotations

from difflib import SequenceMatcher
import json
import os
import re

from . import db
from .source_alignment import normalize_name


_FAMILY_QUALIFIERS = {
    "better", "best", "continued", "continuation", "fixed", "fix",
    "updated", "update", "cosmetic", "comestic", "edition", "redux", "mod",
}
_FAMILY_ALIASES = {
    "team": "shared",
}


def functional_family_name(value: str) -> str:
    """Return a conservative family key for obvious alternative implementations."""
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
    tokens = re.findall(r"[a-z0-9]+", expanded.casefold())
    tokens = [
        _FAMILY_ALIASES.get(token, token)
        for token in tokens
        if token not in _FAMILY_QUALIFIERS
    ]
    # A one-word family such as "map" or "jump" is too generic to be safe.
    if len(tokens) < 2:
        return ""
    return "".join(tokens)


def find_installed_duplicate(
    game_slug: str,
    source: str,
    source_key: str,
    target_name: str = "",
    installed_mods=None,
):
    """Return an installed mod only for an exact identity or strict name match."""
    try:
        direct = db.get_mod(str(source_key), game_slug) or db.get_mod_by_source(
            game_slug, source, str(source_key)
        )
    except Exception:
        direct = None
    if direct or not target_name:
        return direct

    target = normalize_name(target_name)
    if len(target) < 5:
        return None
    if installed_mods is None:
        try:
            installed_mods = db.get_installed_mods(game_slug)
        except Exception:
            return None

    best = None
    best_score = 0.0
    for mod in installed_mods:
        raw_aliases = {str(getattr(mod, "name", "") or "")}
        try:
            files = getattr(mod, "files_installed", "[]")
            files = json.loads(files) if isinstance(files, str) else (files or [])
        except (TypeError, ValueError, json.JSONDecodeError):
            files = []
        for path in files[:200]:
            value = str(path or "").rstrip("\\/")
            if not value:
                continue
            raw_aliases.add(os.path.splitext(os.path.basename(value))[0])
            raw_aliases.add(os.path.basename(os.path.dirname(value)))

        aliases = {normalize_name(value) for value in raw_aliases}
        aliases.discard("")
        # ModAgent/Nexus archives are commonly installed below a namespace
        # such as ``39_MoneyValueTracker``.  The leading stable Nexus ID is
        # packaging metadata, not part of the Mod name.
        if source == "nexus" and str(source_key).isdigit():
            prefix = str(source_key)
            aliases.update(
                alias[len(prefix):]
                for alias in tuple(aliases)
                if alias.startswith(prefix) and len(alias) > len(prefix) + 3
            )

        score = 0.0
        for candidate in aliases:
            candidate_score = (
                1.0 if candidate == target
                else SequenceMatcher(None, candidate, target).ratio()
            )
            if min(len(candidate), len(target)) >= 8 and (
                candidate in target or target in candidate
            ):
                candidate_score = max(candidate_score, .97)
            score = max(score, candidate_score)
        if score > best_score:
            best, best_score = mod, score
    return best if best_score >= .96 else None


def find_installed_functional_equivalent(
    target_name: str,
    installed_mods,
):
    """Find an obvious same-purpose alternative without claiming exact identity."""
    target_family = functional_family_name(target_name)
    if len(target_family) < 8:
        return None
    matches = []
    for mod in installed_mods or []:
        installed_name = getattr(mod, "name", "")
        if normalize_name(installed_name) == normalize_name(target_name):
            continue
        if functional_family_name(installed_name) == target_family:
            matches.append(mod)
    return matches[0] if len(matches) == 1 else None
