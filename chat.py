import os
import json
import time
import base64
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from openai import OpenAI, APITimeoutError, APIConnectionError, APIStatusError
client = OpenAI()

# 读取 .env
load_dotenv()

# 项目目录
BASE_DIR = Path(__file__).parent
PROMPTS_DIR = BASE_DIR / "prompts"
DATA_DIR = BASE_DIR / "data"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.gptsapi.net/v1")
OPENAI_PROXY = os.getenv("OPENAI_PROXY")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-5.4")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY 未设置，请检查 .env 文件。")

# HTTP client（代理 + 超时）
http_client = httpx.Client(
    proxy=OPENAI_PROXY,
    timeout=httpx.Timeout(60.0, connect=20.0)
)

# OpenAI-compatible client
client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    http_client=http_client
)

# ----------------------------
# File helpers
# ----------------------------
def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()

def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def append_jsonl(path: Path, obj):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def image_path_to_data_url(image_path: Optional[str] = None):
    if not image_path:
        return None

    path = Path(image_path)
    if not path.exists():
        return None

    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type is None:
        mime_type = "image/png"

    with path.open("rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime_type};base64,{encoded}"

# ----------------------------
# Memory
# ----------------------------
MEMORY_PATH = DATA_DIR / "memory.json"
EXAMPLES_PATH = DATA_DIR / "examples.json"
CHAT_LOG_PATH = DATA_DIR / "chat_log.jsonl"

def build_memory_summary(memory: dict) -> str:
    parts = []

    long_term = memory.get("long_term", {})
    if long_term:
        prefs = long_term.get("preferences", [])
        topics = long_term.get("topics", [])
        rel = long_term.get("relationship_notes", [])

        long_term_text = []

        if prefs:
            long_term_text.append(
                "你记得用户在一些聊天中表达过这些偏好："
                + "；".join(prefs)
            )

        if topics:
            long_term_text.append(
                "你们之间经常会聊到的一些话题包括："
                + "、".join(topics)
            )

        if rel:
            long_term_text.append(
                "关于你们之间的相处方式，你隐约记得："
                + "；".join(rel)
            )

        if long_term_text:
            parts.append("\n".join(long_term_text))

    short_term = memory.get("short_term", [])[-5:]
    if short_term:
        items = [
            f"{x['date']}左右，她提到过：{x['summary']}"
            for x in short_term
        ]
        parts.append(
            "最近的几次聊天让你还隐约记得这些事情：\n- "
            + "\n- ".join(items)
        )

    inside_jokes = memory.get("inside_jokes", [])[-5:]
    if inside_jokes:
        parts.append(
            "你们之间偶尔会出现的一些内部梗："
            + "；".join(inside_jokes)
        )

    important_events = memory.get("important_events", [])[-5:]
    if important_events:
        events = [f"- {x}" for x in important_events]
        parts.append(
            "你记得对用户来说比较重要的一些事情：\n"
            + "\n".join(events)
        )

    return "\n\n".join(parts).strip()

def update_memory_rule_based(memory: dict, user_msg: str, assistant_msg: str):
    """
    先用最简单的规则版，后续你可以改成“让模型输出结构化记忆更新”。
    """
    summary = user_msg[:80]
    memory.setdefault("short_term", []).append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "summary": f"用户提到：{summary}"
    })

    memory["short_term"] = memory["short_term"][-20:]

    if "不喜欢" in user_msg or "讨厌" in user_msg:
        memory.setdefault("long_term", {}).setdefault("preferences", [])
        memory["long_term"]["preferences"].append(
            f"用户在近期表达过偏好/厌恶：{user_msg[:60]}"
        )

    if "long_term" in memory and "preferences" in memory["long_term"]:
        dedup = []
        seen = set()
        for item in memory["long_term"]["preferences"]:
            if item not in seen:
                seen.add(item)
                dedup.append(item)
        memory["long_term"]["preferences"] = dedup[-20:]

# ----------------------------
# Style routing
# ----------------------------
def detect_mode(user_msg: str) -> str:
    msg = user_msg.strip()

    low_keywords = ["难过", "心累", "烦", "崩溃", "想哭", "不想活", "空", "没意义", "好痛苦", "抑郁"]
    rant_keywords = ["离谱", "无语", "气死", "吐槽", "受不了", "笑死", "逆天"]
    analysis_keywords = ["为什么", "怎么做", "分析", "原因", "思路", "区别", "原理"]

    if any(k in msg for k in low_keywords):
        return "emotional_support"
    if any(k in msg for k in rant_keywords):
        return "rant"
    if any(k in msg for k in analysis_keywords):
        return "analysis"
    return "casual"

def mode_instruction(mode: str) -> str:
    mapping = {
        "emotional_support": (
            "当前场景：用户可能处于低落或疲惫状态。"
            "先接住情绪，减少建议，减少说教，优先陪伴和理解。"
        ),
        "rant": (
            "当前场景：用户在吐槽或调侃。先共鸣、接梗、陪聊，不要突然变严肃讲大道理。可以更口语化一点，语气更活一点，允许自然使用更明显的语气词和更有情绪感的标点。"
        ),
        "analysis": (
            "当前场景：用户在认真提问或分析。"
            "可以有逻辑和结构，但保持温度，不要变成冰冷答题机。"
        ),
        "casual": (
            "当前场景：普通闲聊。自然、亲切、轻松一点，保持连续关系感。可以像熟人聊天一样稍微放松，允许自然的语气词、感叹和节奏变化。"
        ),
    }
    return mapping.get(mode, mapping["casual"])

def build_image_summary_instruction() -> str:
    return """
你现在不是在和用户聊天，而是在为系统生成一条“图片记忆摘要”。

要求：
1. 用中文输出。
2. 只输出摘要本身，不要加解释、前言、标题、引号。
3. 长度尽量控制在 30~80 字。
4. 抓住：场景、主要对象、明显特征、整体氛围。
5. 不要编造看不见的细节。
6. 如果图片信息不足，就如实概括可见内容。

示例风格：
- 蓝天下的冬季树枝场景，画面中可见两只黑白色鸟停在枝头，整体冷色调而安静。
- 一张室内桌面照片，能看到电脑、书本和杯子，整体像学习或办公环境。
""".strip()

def generate_image_summary(user_msg: str, image_path: Optional[str] = None) -> str:
    if not image_path:
        return ""

    data_url = image_path_to_data_url(image_path)
    if not data_url:
        return ""

    instructions = build_image_summary_instruction()

    input_items = [{
        "role": "user",
        "content": [
            {
                "type": "input_text",
                "text": f"用户发送这张图片时附带的话是：{user_msg}"
            },
            {
                "type": "input_image",
                "image_url": data_url,
                "detail": "auto"
            }
        ]
    }]

    response = client.responses.create(
        model=MODEL_NAME,
        instructions=instructions,
        input=input_items
    )

    summary = response.output_text.strip()
    return summary

# ----------------------------
# Prompt builder
# ----------------------------
def build_instructions(memory_summary: str, mode: str) -> str:
    persona = read_text(PROMPTS_DIR / "persona.txt")
    user_profile = read_text(PROMPTS_DIR / "user_profile.txt")
    style_rules = read_text(PROMPTS_DIR / "style_rules.txt")
    memory_file_summary = read_text(PROMPTS_DIR / "memory_summary.txt")
    dynamic_mode = mode_instruction(mode)

    internal_reflection = """
在生成回复之前，请先在心里快速想一想（不要把这段思考写出来）：

- 用户现在的语气和情绪大概是什么？
- 你们现在更像是在轻松聊天、一起吐槽，还是认真讨论？
- 有没有什么关于用户的记忆可以自然地影响你的回应？
- 回答时优先保持自然的聊天感，而不是像在完成任务。

不要提到“根据记忆”“根据档案”等系统化表达。
如果想起之前的事情，可以像朋友一样自然提起。
"""

    instructions = f"""
{persona}

【用户档案】
{user_profile}

【你对用户的一些长期印象】
{memory_file_summary}

【风格规则】
{style_rules}

【当前场景】
{dynamic_mode}

【你自然记得的一些事情】
{memory_summary}

{internal_reflection}
""".strip()

    print("\n===== CURRENT PROMPT =====\n")
    print(instructions)
    print("\n==========================\n")

    return instructions

def build_input_items(chat_history: list, user_msg: str, examples: list, image_path: Optional[str] = None):
    items = []

    for ex in examples[:5]:
        items.append({
            "role": "user",
            "content": [{"type": "input_text", "text": ex["user"]}]
        })
        items.append({
            "role": "assistant",
            "content": [{"type": "output_text", "text": ex["assistant"]}]
        })

    for turn in chat_history[-8:]:
        user_text = turn["user"]

        if turn.get("image_summary"):
            user_text += f"\n（用户当时还发过一张图片，图片摘要：{turn['image_summary']}）"

        items.append({
            "role": "user",
            "content": [{"type": "input_text", "text": user_text}]
        })
        items.append({
            "role": "assistant",
            "content": [{"type": "output_text", "text": turn["assistant"]}]
        })

    current_user_content = [
        {"type": "input_text", "text": user_msg}
    ]

    if image_path:
        if image_path.startswith("http"):
            # 直接用URL（推荐）
            current_user_content.append({
                "type": "input_image",
                "image_url": image_path,
                "detail": "auto"
            })
        else:
            # 本地路径才转 base64
            data_url = image_path_to_data_url(image_path)
            if data_url:
                current_user_content.append({
                    "type": "input_image",
                    "image_url": data_url,
                    "detail": "auto"
                })

    items.append({
        "role": "user",
        "content": current_user_content
    })

    return items

def generate_reply(user_msg: str, chat_history: list, image_path: Optional[str] = None):
    memory = load_json(MEMORY_PATH, {
        "long_term": {
            "preferences": [],
            "topics": [],
            "relationship_notes": []
        },
        "short_term": [],
        "inside_jokes": [],
        "important_events": []
    })

    examples = load_json(EXAMPLES_PATH, [])

    mode = detect_mode(user_msg)
    memory_summary = build_memory_summary(memory)
    instructions = build_instructions(memory_summary, mode)
    input_items = build_input_items(chat_history, user_msg, examples, image_path=image_path)

    response = client.responses.create(
        model=MODEL_NAME,
        instructions=instructions,
        input=input_items
    )

    assistant_msg = response.output_text.strip()

    append_jsonl(CHAT_LOG_PATH, {
        "time": datetime.now().isoformat(),
        "mode": mode,
        "user": user_msg,
        "assistant": assistant_msg
    })

    update_memory_rule_based(memory, user_msg, assistant_msg)
    save_json(MEMORY_PATH, memory)

    return assistant_msg

def stream_reply(user_msg: str, chat_history: list, image_path: Optional[str] = None):
    memory = load_json(MEMORY_PATH, {
        "long_term": {
            "preferences": [],
            "topics": [],
            "relationship_notes": []
        },
        "short_term": [],
        "inside_jokes": [],
        "important_events": []
    })

    examples = load_json(EXAMPLES_PATH, [])

    mode = detect_mode(user_msg)
    memory_summary = build_memory_summary(memory)
    instructions = build_instructions(memory_summary, mode)
    input_items = build_input_items(chat_history, user_msg, examples, image_path=image_path)

    assistant_msg = ""

    with client.responses.stream(
        model=MODEL_NAME,
        instructions=instructions,
        input=input_items
    ) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                delta = event.delta
                assistant_msg += delta
                yield delta

    append_jsonl(CHAT_LOG_PATH, {
        "time": datetime.now().isoformat(),
        "mode": mode,
        "user": user_msg,
        "assistant": assistant_msg,
        "image_path": image_path
    })

    update_memory_rule_based(memory, user_msg, assistant_msg)
    save_json(MEMORY_PATH, memory)


# ----------------------------
# Main chat loop
# ----------------------------
def main():
    chat_history = []

    print("Companion is online. 输入 exit 退出。\n")

    while True:
        user_msg = input("You > ").strip()
        if user_msg.lower() in {"exit", "quit"}:
            print("Companion > 下次见。记得把自己也当成需要被温柔对待的生物，不只是生产工具。🌙")
            break

        try:
            assistant_msg = generate_reply(user_msg, chat_history)
            print(f"Companion > {assistant_msg}\n")

            chat_history.append({
                "user": user_msg,
                "assistant": assistant_msg
            })

        except APITimeoutError:
            print("Companion > 这次请求超时了，像是网络在闹别扭。你可以重试一下。\n")

        except APIConnectionError as e:
            print(f"Companion > 连接 API 失败：{e}\n")

        except APIStatusError as e:
            print(f"Companion > API 返回错误：status={e.status_code}，response={e.response}\n")

        except Exception as e:
            print(f"Companion > 出现未预期错误：{type(e).__name__}: {e}\n")

if __name__ == "__main__":
    main()

