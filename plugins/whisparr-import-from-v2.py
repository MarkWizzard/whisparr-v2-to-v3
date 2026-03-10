#!/usr/bin/env python3
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from stashapi import log as stash_log
from stashapi.stashapp import StashInterface

PLUGIN_AUTHOR = "MarkWizzard"
PROCESSING_DIR = Path("/processing")
STASHED_DIR = Path("/stashed")

logger = logging.getLogger("whisparr-import")

class WhisparrPlugin:
    def __init__(self, stash_data: dict, whisparr_url: str, whisparr_key: str, monitored: bool = True):
        self.stash_data = stash_data
        self.whisparr_url = whisparr_url
        self.whisparr_key = whisparr_key
        self.monitored = monitored
        self.stash_conn = StashInterface(stash_data["server_connection"])

    def move_file_to_stashed(self, path: Path) -> Optional[Path]:
        target = STASHED_DIR / path.name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            path.replace(target)
            logger.info("Moved %s → %s", path, target)
            return target
        except Exception as e:
            logger.exception("Failed to move %s: %s", path, e)
            return None

    def process_scene(self, scene_id: int):
        try:
            scene_data = self.stash_conn.find_scene(scene_id)
            if not scene_data:
                logger.warning("Scene ID %s not found in Stash", scene_id)
                return
        except Exception as e:
            logger.exception("Failed to fetch scene: %s", e)
            return

        stash_files = scene_data.get("files", [])
        stashed_files = []

        for f in stash_files:
            path_str = f.get("path")
            if not path_str:
                continue
            src_path = Path(path_str)
            if src_path.exists() and src_path.is_file():
                moved = self.move_file_to_stashed(src_path)
                if moved:
                    stashed_files.append(moved)

        if stashed_files:
            self.add_scene_to_whisparr(scene_data)

    def add_scene_to_whisparr(self, scene_data: dict):
        stash_id = scene_data.get("stash_ids", [{}])[0].get("stash_id")
        if not stash_id:
            logger.warning("No StashID found, skipping Whisparr import")
            return
        payload = {
            "title": scene_data.get("title"),
            "foreignId": stash_id,
            "stashId": stash_id,
            "monitored": self.monitored,
            "rootFolderPath": str(STASHED_DIR),
            "addOptions": {"monitor": "movieOnly" if self.monitored else "none", "searchForMovie": False}
        }
        try:
            resp = requests.post(f"{self.whisparr_url}/api/v3/movie",
                                 json=payload,
                                 headers={"X-Api-Key": self.whisparr_key})
            if resp.status_code in (200, 201):
                logger.info("Scene '%s' added to Whisparr", scene_data.get("title"))
            else:
                logger.error("Failed to add to Whisparr: %s %s", resp.status_code, resp.text)
        except Exception as e:
            logger.exception("Whisparr API request failed: %s", e)

def main():
    # Read hook data from Stash
    try:
        raw_data = sys.stdin.read()
        stash_data = json.loads(raw_data) if raw_data.strip() else {}
    except Exception as e:
        stash_log.error("Failed to read Stash hook data: %s", e)
        return

    # Load plugin settings
    whisparr_url = stash_data.get("WHISPARR_URL", "")
    whisparr_key = stash_data.get("WHISPARR_KEY", "")
    monitored = stash_data.get("MONITORED", True)

    plugin = WhisparrPlugin(stash_data, whisparr_url, whisparr_key, monitored)

    # Determine scene ID from hook
    args = stash_data.get("args", {})
    hook_context = args.get("hookContext", {})
    scene_id = hook_context.get("id")

    if scene_id:
        plugin.process_scene(scene_id)
    else:
        # Optional manual run: process all files in /processing with matching StashID
        for file_path in PROCESSING_DIR.glob("*"):
            if file_path.is_file():
                # Optional: detect StashID from filename or metadata (implement your logic)
                logger.info("Processing file manually: %s", file_path)
                plugin.move_file_to_stashed(file_path)

if __name__ == "__main__":
    main()
