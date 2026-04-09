# summary.py
import json
import mimetypes
import base64
from pathlib import Path
from typing import Optional

from openai import OpenAI


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


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


def extract_memory_from_turn(
    client: OpenAI,
    model_name: str,
    prompts_dir: Path,
    user_msg: str,
    assistant_msg: str
) -> dict:
    summary_prompt = read_text(prompts_dir / "summary_prompt.txt")

    response = client.responses.create(
        model=model_name,
        instructions=summary_prompt,
        input=f"""User message:
{user_msg}

Assistant message:
{assistant_msg}
"""
    )

    raw = response.output_text.strip()

    try:
        data = json.loads(raw)
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

    return data if isinstance(data, dict) else {
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
""".strip()


def generate_image_summary(
    client: OpenAI,
    model_name: str,
    user_msg: str,
    image_path: Optional[str] = None
) -> str:
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
        model=model_name,
        instructions=instructions,
        input=input_items
    )

    return response.output_text.strip()
