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

# 读取 .env
load_dotenv()

# 项目目录
BASE_DIR = Path(__file__).parent
PROMPTS_DIR = BASE_DIR / "prompts"
DATA_DIR = BASE_DIR / "data"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.gptsapi.net/v1")
# OPENAI_PROXY = os.getenv("OPENAI_PROXY")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-5.4")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY 未设置，请检查 .env 文件。")

# HTTP client（代理 + 超时）
"""
http_client = httpx.Client(
    proxy=OPENAI_PROXY,
    timeout=httpx.Timeout(60.0, connect=20.0)
)
"""

# OpenAI-compatible client
client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
    # http_client=http_client
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

from memory import (
    default_memory,
    load_json,
    save_json,
    build_memory_summary,
    update_memory_from_extraction,
)

from summary import (
    extract_memory_from_turn,
    generate_image_summary,
)

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

def prepare_reply_context(user_msg: str, chat_history: list, image_path: Optional[str] = None):
    memory = load_json(MEMORY_PATH, default_memory())
    examples = load_json(EXAMPLES_PATH, [])

    mode = detect_mode(user_msg)
    memory_summary = build_memory_summary(memory)
    instructions = build_instructions(memory_summary, mode)
    input_items = build_input_items(chat_history, user_msg, examples, image_path=image_path)

    return memory, mode, instructions, input_items


def finalize_reply_turn(
    memory: dict,
    user_msg: str,
    assistant_msg: str,
    mode: str,
    image_path: Optional[str] = None
):
    append_jsonl(CHAT_LOG_PATH, {
        "time": datetime.now().isoformat(),
        "mode": mode,
        "user": user_msg,
        "assistant": assistant_msg,
        "image_path": image_path
    })

    extracted = extract_memory_from_turn(client, MODEL_NAME, PROMPTS_DIR, user_msg, assistant_msg)
    update_memory_from_extraction(memory, extracted)
    save_json(MEMORY_PATH, memory)
    
def generate_reply(user_msg: str, chat_history: list, image_path: Optional[str] = None):
    memory, mode, instructions, input_items = prepare_reply_context(
        user_msg=user_msg,
        chat_history=chat_history,
        image_path=image_path
    )

    response = client.responses.create(
        model=MODEL_NAME,
        instructions=instructions,
        input=input_items
    )

    assistant_msg = response.output_text.strip()
    finalize_reply_turn(
        memory=memory,
        user_msg=user_msg,
        assistant_msg=assistant_msg,
        mode=mode,
        image_path=image_path
    )
    return assistant_msg


def stream_reply(user_msg: str, chat_history: list, image_path: Optional[str] = None):
    memory, mode, instructions, input_items = prepare_reply_context(
        user_msg=user_msg,
        chat_history=chat_history,
        image_path=image_path
    )

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

    finalize_reply_turn(
        memory=memory,
        user_msg=user_msg,
        assistant_msg=assistant_msg,
        mode=mode,
        image_path=image_path
    )

def extract_memory_from_turn(user_msg: str, assistant_msg: str) -> dict:
    summary_prompt = read_text(PROMPTS_DIR / "summary_prompt.txt")

    input_text = f"""
User message:
{user_msg}

Assistant message:
{assistant_msg}
""".strip()

    response = client.responses.create(
        model=MODEL_NAME,
        instructions=summary_prompt,
        input=input_text
    )

    raw = response.output_text.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "should_store": False,
            "short_term_summary": "",
            "preferences": [],
            "topics": [],
            "relationship_notes": [],
            "inside_jokes": [],
            "important_events": [],
            "emotion_tone": "",
            "confidence": 0.0
        }

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
