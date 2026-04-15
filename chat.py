import os
import json
import base64
import mimetypes
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path
from typing import Optional

from openai import OpenAI, APITimeoutError, APIConnectionError, APIStatusError

from sqlalchemy.orm import Session
from crud import fetch_recent_chat, insert_message_pair, get_memory

from database import get_db, Base, engine, SessionLocal
# 读取 .env
from models import Memory


load_dotenv()

# 项目目录
BASE_DIR = Path(__file__).parent
PROMPTS_DIR = BASE_DIR / "prompts"
DATA_DIR = BASE_DIR / "data"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.gptsapi.net/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-5.4")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY 未设置，请检查 .env 文件。")


# OpenAI-compatible client
client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL
)


# ----------------------------
# File helpers
# ----------------------------
def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


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
EXAMPLES_PATH = DATA_DIR / "examples.json"


# ----------------------------
# Style routing
# ----------------------------
def detect_mode_llm(user_msg: str) -> str:
    prompt = f"""
请判断下面这句话更接近哪种对话场景：

可选类别：
- emotional_support（情绪低落/需要安慰）
- rant（吐槽/发泄）
- analysis（认真提问/分析）
- casual（普通聊天）

只返回类别名称，不要解释。

用户输入：
{user_msg}
"""

    response = client.responses.create(
        model=MODEL_NAME,
        input=prompt
    )

    mode = response.output_text.strip()

    # 防御：防止模型乱输出
    if mode not in {"emotional_support", "rant", "analysis", "casual"}:
        return "casual"

    return mode


def detect_mode(user_msg: str) -> str:
    msg = user_msg.strip()

    if any(k in msg for k in ["难过", "崩溃"]):
        return "emotional_support"

    if any(k in msg for k in ["离谱", "无语"]):
        return "rant"

    # 不确定 → 用 LLM
    return detect_mode_llm(user_msg)


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
def build_persona_block():
    return read_text(PROMPTS_DIR / "persona.txt")


def build_user_block():
    user_profile = read_text(PROMPTS_DIR / "user_profile.txt")
    return f"【用户档案】\n{user_profile}"


def build_memory_block(memory_summary: str):
    return f"【你自然记得的一些事情】\n{memory_summary}"


def build_style_block():
    style_rules = read_text(PROMPTS_DIR / "style_rules.txt")
    return f"【风格规则】\n{style_rules}"


def build_mode_block(mode: str):
    return f"【当前场景】\n{mode_instruction(mode)}"


def build_internal_reflection():
    return """
在生成回复之前，请先在心里快速想一想（不要写出来）：

- 用户现在的语气和情绪？
- 当前是闲聊、吐槽还是分析？
- 有没有可以自然提起的记忆？
- 优先保持自然聊天感

不要提到“根据记忆”等系统表达。
""".strip()


def build_instructions(memory_summary: str, mode: str) -> str:
    blocks = [
        build_persona_block(),
        build_user_block(),
        build_style_block(),
        build_mode_block(mode),
        build_memory_block(memory_summary),
        build_internal_reflection()
    ]

    instructions = "\n\n".join(blocks)

    return instructions


def build_input_items(chat_history: list, user_msg: str, examples: list, image_path: Optional[str] = None):
    items = []

    for ex in examples:
        items.append({
            "role": "user",
            "content": [{"type": "input_text", "text": ex["user"]}]
        })
        items.append({
            "role": "assistant",
            "content": [{"type": "output_text", "text": ex["assistant"]}]
        })

    for turn in chat_history:
        user_text = turn["user"]

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


def prepare_reply_context(user_msg, chat_history, db, image_path=None):
    examples = load_json(EXAMPLES_PATH, [])

    mode = detect_mode(user_msg)
    memory_text = get_memory(db)

    instructions = build_instructions(memory_text, mode)
    input_items = build_input_items(chat_history, user_msg, examples, image_path=image_path)

    return mode, instructions, input_items


def generate_reply(user_msg, chat_history, db, image_path=None):
    mode, instructions, input_items = prepare_reply_context(
        user_msg=user_msg,
        chat_history=chat_history,
        db=db,
        image_path=image_path
    )

    response = client.responses.create(
        model=MODEL_NAME,
        instructions=instructions,
        input=input_items
    )

    return response.output_text.strip()


# ----------------------------
# Main chat loop
# ----------------------------
def main():
    print("Companion is online. 输入 exit 退出。\n")

    import uuid
    chat_id = str(uuid.uuid4())

    while True:
        user_msg = input("You > ").strip()

        if user_msg.lower() in {"exit", "quit"}:
            print("Companion > 下次见。记得把自己也当成需要被温柔对待的生物，不只是生产工具🌙")
            break

        db = SessionLocal()

        try:
            chat_history = fetch_recent_chat(db, chat_id)
            assistant_msg = generate_reply(user_msg, chat_history, db)
            print(f"Companion > {assistant_msg}\n")

        except APITimeoutError:
            print("Companion > 请求超时了\n")

        except APIConnectionError as e:
            print(f"Companion > API连接失败：{e}\n")

        except APIStatusError as e:
            print(f"Companion > API错误：{e}\n")

        except Exception as e:
            print(f"Companion > 未知错误：{type(e).__name__}: {e}\n")

        finally:
            db.close()


if __name__ == "__main__":
    main()
