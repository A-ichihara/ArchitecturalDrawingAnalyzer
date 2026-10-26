"""
core.rooms.review_store
部屋の確認・修正内容を DXF とは別ファイル（サイドカー）に保存する。

保存先は DXF と同じフォルダの `<図面名>.rooms.json`。
DXF 自体は書き換えない（非破壊）ため、元の図面が変わることはない。
部屋 ID は検出順に付けられるため、同じ図面・同じ検出方法であれば
再検出しても一致する。検出方法が変わって ID が一致しなくなった
保存内容は無視され、読み込みを妨げない。
"""
import json
import logging
import os
from typing import Dict, List, Set

from core.models.room import (
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_REJECTED,
    REVIEW_STATUS_TO_CONFIRM,
    Room,
)

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
_VALID_STATUSES = {
    REVIEW_STATUS_TO_CONFIRM,
    REVIEW_STATUS_CONFIRMED,
    REVIEW_STATUS_REJECTED,
}


def sidecar_path(dxf_path: str) -> str:
    """DXF に対応する保存ファイルのパスを返す。"""
    return os.path.splitext(dxf_path)[0] + ".rooms.json"


def save_reviews(dxf_path: str, rooms: List[Room], touched_ids: Set[str]) -> str:
    """ユーザーが触った部屋の確認内容を保存する。

    保存対象は、名前を編集したか状態を変更した部屋だけ。
    自動で関連付けられた部屋名は保存しない（図面の文字が変わった
    ときに古い名前が残るのを防ぐため）。
    """
    path = sidecar_path(dxf_path)
    entries = {}
    for room in rooms:
        if room.room_id not in touched_ids:
            continue
        entry = {}
        if room.room_name:
            entry["room_name"] = room.room_name
        if room.review_status != REVIEW_STATUS_TO_CONFIRM:
            entry["review_status"] = room.review_status
        if entry:
            entries[room.room_id] = entry

    data = {
        "version": FORMAT_VERSION,
        "drawing": os.path.basename(dxf_path),
        "rooms": entries,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("部屋の確認内容を保存しました: %s（%d 件）", path, len(entries))
    return path


def load_reviews(dxf_path: str) -> Dict[str, dict]:
    """保存された確認内容を読み込む。ファイルが無い・壊れている場合は空を返す。"""
    path = sidecar_path(dxf_path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("部屋の確認内容を読み込めませんでした（%s）: %s", path, exc)
        return {}
    rooms = data.get("rooms") if isinstance(data, dict) else None
    if not isinstance(rooms, dict):
        logger.warning("部屋の確認内容の形式が不正です: %s", path)
        return {}
    return rooms


def apply_reviews(rooms: List[Room], reviews: Dict[str, dict]) -> int:
    """保存された確認内容を検出直後の部屋一覧へ適用する。

    保存された部屋 ID と一致する部屋だけを対象とし、不明な状態値や
    空の部屋名は無視する。適用した件数を返す。
    """
    applied = 0
    by_id = {room.room_id: room for room in rooms}
    for room_id, entry in reviews.items():
        room = by_id.get(room_id)
        if room is None or not isinstance(entry, dict):
            continue
        name = entry.get("room_name")
        if isinstance(name, str) and name:
            room.room_name = name
        status = entry.get("review_status")
        if status in _VALID_STATUSES:
            room.review_status = status
        applied += 1
    if applied:
        logger.info("保存された部屋の確認内容を適用しました: %d 件", applied)
    return applied
