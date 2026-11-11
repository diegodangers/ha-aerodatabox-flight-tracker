"""Offline SkyLedger domain migration. Run ONLY while Home Assistant Core is stopped.

Dry-run by default. --apply creates a full backup of affected storage files
before changing config entry domains and entity-registry platforms.
"""
from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timezone

OLD = "aerodatabox_flights"
NEW = "skyledger"
FILES = ("core.config_entries", "core.entity_registry", OLD + ".history")

def plan(config: Path):
    storage = config / ".storage"
    sources = {name: storage / name for name in FILES}
    if not all(p.is_file() for p in sources.values()):
        raise ValueError("Missing required Home Assistant storage file")
    docs = {name: json.loads(p.read_text(encoding="utf-8")) for name, p in sources.items()}
    entries = docs["core.config_entries"].get("data", {}).get("entries", [])
    legacy = [e for e in entries if e.get("domain") == OLD]
    if len(legacy) != 1 or any(e.get("domain") == NEW for e in entries):
        raise ValueError("Expected exactly one legacy config entry and no SkyLedger entry")
    entry = legacy[0]
    if not isinstance(entry.get("data"), dict) or not entry["data"].get("api_key"):
        raise ValueError("Legacy configuration is missing its API key")
    entities = docs["core.entity_registry"].get("data", {}).get("entities", [])
    affected = [e for e in entities if e.get("platform") == OLD and e.get("config_entry_id") == entry["entry_id"]]
    other = [e for e in entities if e.get("platform") == OLD and e.get("config_entry_id") != entry["entry_id"]]
    if other:
        raise ValueError("Found legacy entities belonging to other config entries")
    history = docs[OLD + ".history"].get("data", {}).get("flights")
    if not isinstance(history, dict) or any(not isinstance(v, dict) or v.get("id") != k for k, v in history.items()):
        raise ValueError("Invalid legacy history")
    if (storage / (NEW + ".history")).exists():
        raise ValueError("SkyLedger history already exists; refusing overwrite")
    updated = copy.deepcopy(docs)
    match = next(e for e in updated["core.config_entries"]["data"]["entries"] if e["entry_id"] == entry["entry_id"])
    match["domain"] = NEW
    match["title"] = "SkyLedger"
    for e in updated["core.entity_registry"]["data"]["entities"]:
        if e.get("platform") == OLD and e.get("config_entry_id") == entry["entry_id"]:
            e["platform"] = NEW
    new_history = copy.deepcopy(updated[OLD + ".history"])
    new_history["key"] = NEW + ".history"
    return sources, updated, new_history, len(affected), len(history), entry["entry_id"]

def write_atomic(path: Path, doc: dict):
    fd, tmp = tempfile.mkstemp(prefix=".skyledger-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(doc, out, ensure_ascii=False, separators=(",", ":"))
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=Path("/config"))
    ap.add_argument("--apply", action="store_true", help="Requires Home Assistant Core to be stopped")
    args = ap.parse_args()
    sources, updated, new_history, entities, flights, entry_id = plan(args.config)
    print(f"Config entry: {entry_id}; entity registrations: {entities}; saved flights: {flights}")
    print("Entity IDs and unique IDs will remain unchanged. API key will not be printed.")
    if not args.apply:
        print("DRY RUN ONLY. No files changed.")
        return
    print("WARNING: Home Assistant Core MUST be stopped. Continuing assumes it is stopped.")
    backup = args.config / (".skyledger-migration-backup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup.mkdir(mode=0o700)
    for name, path in sources.items():
        shutil.copy2(path, backup / name)
    target = args.config / ".storage" / (NEW + ".history")
    try:
        write_atomic(target, new_history)
        write_atomic(sources["core.config_entries"], updated["core.config_entries"])
        write_atomic(sources["core.entity_registry"], updated["core.entity_registry"])
    except Exception:
        for name in ("core.config_entries", "core.entity_registry"):
            shutil.copy2(backup / name, sources[name])
        if target.exists():
            target.unlink()
        raise
    print(f"Migrated. Backup retained at {backup}")

if __name__ == "__main__":
    main()
