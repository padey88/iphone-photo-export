"""Filtering / classification logic for the export GUI.

Pure functions over inventory dicts so they can be unit-tested without a device.

Inventory item: {path, name, size, mtime, ext, is_video}
After classify(): + {kind, date, exported, mb, stem, dir}
Kinds: photo, live (still of a Live Photo), live_mov (its motion clip),
       screenshot, recording (screen recording), video
"""
from __future__ import annotations

import posixpath
from datetime import datetime, time

IMAGE_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".tif", ".tiff", ".dng"}
VIDEO_EXT = {".mov", ".mp4", ".m4v", ".avi"}


def classify(items: list[dict], exported_index: dict[str, int] | None = None) -> list[dict]:
    """Annotate items with kind/date/exported and link Live Photo pairs."""
    exported_index = exported_index or {}
    stems: dict[tuple[str, str], dict[str, str]] = {}
    for it in items:
        stem = posixpath.splitext(it["name"])[0]
        d = posixpath.dirname(it["path"])
        stems.setdefault((d, stem), {})[it["ext"]] = it["path"]

    out = []
    for it in items:
        ext = it["ext"]
        name = it["name"]
        stem = posixpath.splitext(name)[0]
        d = posixpath.dirname(it["path"])
        siblings = stems.get((d, stem), {})
        has_mov = any(e in VIDEO_EXT for e in siblings)
        has_img = any(e in IMAGE_EXT for e in siblings)

        if ext in VIDEO_EXT:
            if name.upper().startswith("RPREPLAY_FINAL"):
                kind = "recording"
            elif has_img:
                kind = "live_mov"
            else:
                kind = "video"
        elif ext == ".png":
            kind = "screenshot"
        elif has_mov:
            kind = "live"
        else:
            kind = "photo"

        out.append({
            **it,
            "stem": stem,
            "dir": d,
            "kind": kind,
            "date": datetime.fromtimestamp(it["mtime"]).strftime("%Y-%m-%d %H:%M"),
            "day": datetime.fromtimestamp(it["mtime"]).strftime("%Y-%m-%d"),
            "exported": it["path"] in exported_index,
            "mb": round(it["size"] / 1e6, 2),
        })
    return out


def _parse_date(s: str, end: bool = False) -> float:
    dt = datetime.strptime(s, "%Y-%m-%d")
    if end:
        dt = datetime.combine(dt.date(), time(23, 59, 59))
    return dt.timestamp()


def apply_filters(items: list[dict], spec: dict) -> list[dict]:
    """spec keys: date_mode(all|older|newer|between), date, date_from, date_to,
    kinds(list), min_mb, max_mb, exported(any|no|yes), q, keep_pairs(bool)."""
    mode = spec.get("date_mode", "all")
    kinds = spec.get("kinds") or []
    min_mb = spec.get("min_mb")
    max_mb = spec.get("max_mb")
    exp = spec.get("exported", "any")
    q = (spec.get("q") or "").strip().lower()

    lo = hi = None
    if mode == "older" and spec.get("date"):
        hi = _parse_date(spec["date"])
    elif mode == "newer" and spec.get("date"):
        lo = _parse_date(spec["date"])
    elif mode == "between":
        if spec.get("date_from"):
            lo = _parse_date(spec["date_from"])
        if spec.get("date_to"):
            hi = _parse_date(spec["date_to"], end=True)

    picked = []
    for it in items:
        t = it["mtime"]
        if lo is not None and t < lo:
            continue
        if hi is not None and t > hi:
            continue
        if kinds and it["kind"] not in kinds:
            continue
        if min_mb is not None and it["mb"] < float(min_mb):
            continue
        if max_mb is not None and it["mb"] > float(max_mb):
            continue
        if exp == "no" and it["exported"]:
            continue
        if exp == "yes" and not it["exported"]:
            continue
        if q and q not in it["name"].lower():
            continue
        picked.append(it)

    if spec.get("keep_pairs", True):
        picked = _attach_pairs(picked, items)
    return picked


def _attach_pairs(picked: list[dict], everything: list[dict]) -> list[dict]:
    """Re-add Live Photo motion clips whose still matched the filter (and vice versa)."""
    by_key = {(i["dir"], i["stem"], i["ext"]): i for i in everything}
    have = {i["path"] for i in picked}
    additions: dict[str, dict] = {}
    for it in picked:
        if it["kind"] not in ("live", "live_mov"):
            continue
        for ext in (IMAGE_EXT | VIDEO_EXT):
            sib = by_key.get((it["dir"], it["stem"], ext))
            if sib and sib["path"] not in have:
                additions[sib["path"]] = {**sib, "pair_auto": True}
    out = list(picked) + list(additions.values())
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def summarize(items: list[dict]) -> dict:
    total = sum(i["size"] for i in items)
    counts: dict[str, int] = {}
    for i in items:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
    return {
        "count": len(items),
        "bytes": total,
        "mb": round(total / 1e6, 1),
        "gb": round(total / 1e9, 2),
        "by_kind": counts,
        "exported": sum(1 for i in items if i["exported"]),
    }


def suggest_presets(today: datetime | None = None) -> list[dict]:
    """Date presets offered in the UI."""
    today = today or datetime.now()
    y = today.year
    return [
        {"id": "older_jan1", "label": f"Older than 1 Jan {y}",
         "spec": {"date_mode": "older", "date": f"{y}-01-01"}},
        {"id": "older_last_year", "label": f"Older than 1 Jan {y - 1}",
         "spec": {"date_mode": "older", "date": f"{y - 1}-01-01"}},
        {"id": "last_30", "label": "Last 30 days",
         "spec": {"date_mode": "newer",
                  "date": (today.replace(hour=0, minute=0, second=0)).strftime("%Y-%m-%d")}},
        {"id": "not_exported", "label": "Not yet exported",
         "spec": {"date_mode": "all", "exported": "no"}},
        {"id": "big_videos", "label": "Videos over 100 MB",
         "spec": {"date_mode": "all", "kinds": ["video", "live_mov", "recording"], "min_mb": 100}},
        {"id": "all", "label": "Everything", "spec": {"date_mode": "all"}},
    ]
