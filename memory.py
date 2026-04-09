# memory.py
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def default_memory() -> dict:
    return {
        "long_term": {
            "preferences": [],
            "topics": [],
            "relationship_notes": []
        },
        "short_term": [],
        "inside_jokes": [],
        "important_events": []
    }


def load_json(path: Path, default: Any):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def dedupe_keep_order(items: List[str], limit: Optional[int] = None) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    if limit is not None:
        return out[-limit:]
    return out


def build_memory_summary(memory: dict) -> str:
    parts = []

    long_term = memory.get("long_term", {}) or {}
    preferences = dedupe_keep_order(long_term.get("preferences", []), limit=10)
    topics = dedupe_keep_order(long_term.get("topics", []), limit=10)
    relationship_notes = dedupe_keep_order(long_term.get("relationship_notes", []), limit=10)

    if preferences:
        parts.append("你隐约记得用户的一些长期偏好和厌恶：" + "；".join(preferences))

    if topics:
        parts.append("你们经常会聊到的话题包括：" + "、".join(topics))

    if relationship_notes:
        parts.append("关于你和用户的相处方式，你记得这些印象：" + "；".join(relationship_notes))

    short_term = memory.get("short_term", []) or []
    short_term = short_term[-5:]
    if short_term:
        lines = []
        for item in short_term:
            date = item.get("date", "")
            summary = item.get("summary", "")
            if summary:
                if date:
                    lines.append(f"{date}附近，她提到：{summary}")
                else:
                    lines.append(f"她最近提到：{summary}")
        if lines:
            parts.append("最近的聊天余温：\n- " + "\n- ".join(lines))

    inside_jokes = dedupe_keep_order(memory.get("inside_jokes", []), limit=5)
    if inside_jokes:
        parts.append("你们之间偶尔会出现的内部梗：" + "；".join(inside_jokes))

    important_events = dedupe_keep_order(memory.get("important_events", []), limit=5)
    if important_events:
        parts.append("你记得对用户来说比较重要的事情：\n- " + "\n- ".join(important_events))

    return "\n\n".join(parts).strip()


def update_memory_from_extraction(memory: dict, extracted: dict):
    """
    extracted 由 summary.py 产出，必须尽量保持结构化。
    """
    short_term_summary = (extracted.get("short_term_summary") or "").strip()
    if short_term_summary:
        memory.setdefault("short_term", []).append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "summary": short_term_summary
        })
        memory["short_term"] = memory["short_term"][-20:]

    if not extracted.get("should_store", False):
        return memory

    memory.setdefault("long_term", {})
    for key in ["preferences", "topics", "relationship_notes"]:
        memory["long_term"].setdefault(key, [])

    memory.setdefault("inside_jokes", [])
    memory.setdefault("important_events", [])

    for item in extracted.get("preferences", []):
        if item and item not in memory["long_term"]["preferences"]:
            memory["long_term"]["preferences"].append(item)

    for item in extracted.get("topics", []):
        if item and item not in memory["long_term"]["topics"]:
            memory["long_term"]["topics"].append(item)

    for item in extracted.get("relationship_notes", []):
        if item and item not in memory["long_term"]["relationship_notes"]:
            memory["long_term"]["relationship_notes"].append(item)

    for item in extracted.get("inside_jokes", []):
        if item and item not in memory["inside_jokes"]:
            memory["inside_jokes"].append(item)

    for item in extracted.get("important_events", []):
        if item and item not in memory["important_events"]:
            memory["important_events"].append(item)

    memory["long_term"]["preferences"] = memory["long_term"]["preferences"][-20:]
    memory["long_term"]["topics"] = memory["long_term"]["topics"][-20:]
    memory["long_term"]["relationship_notes"] = memory["long_term"]["relationship_notes"][-20:]
    memory["inside_jokes"] = memory["inside_jokes"][-20:]
    memory["important_events"] = memory["important_events"][-20:]

    return memory
