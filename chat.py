import os
import json
import base64
import mimetypes
import time
from dotenv import load_dotenv
from pathlib import Path
from typing import Optional

from openai import OpenAI, APITimeoutError, APIConnectionError, APIStatusError

from sqlalchemy.orm import Session
from crud import fetch_recent_chat, get_memory

from database import SessionLocal


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


def load_json(path: Path, default=None):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("⚠JSON load error:", e)
        return default


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
    return f"当前对话氛围偏向：{mode}。自然调整语气即可，不需要刻意切换表达模式。"


def build_internal_reflection():
    return """
在生成回复之前，请先在心里快速想一想（不要写出来）：

- 只专注用户刚刚说的话本身
- 不要总结，不要规划对话方向
- 不要刻意“回应情绪”或“引导对话”
- 像自然聊天一样接住当前这一句

不要提到“根据记忆”等系统表达。
""".strip()


def build_instructions(memory_summary: str) -> str:
    blocks = [
        build_persona_block(),
        build_user_block(),
        build_style_block(),
        build_memory_block(memory_summary),
        build_internal_reflection()
    ]

    instructions = "\n\n".join(blocks)

    return instructions


def build_input_items(chat_history: list, examples: list, user_msg: str, image_path: Optional[str] = None):
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

    memory_text = get_memory(db)

    instructions = build_instructions(memory_text)
    input_items = build_input_items(chat_history, examples, user_msg, image_path=image_path)

    return instructions, input_items


def generate_reply(user_msg, chat_history, db, image_path=None):
    instructions, input_items = prepare_reply_context(
        user_msg=user_msg,
        chat_history=chat_history,
        db=db,
        image_path=image_path
    )

    response = call_model_with_retry(
        model=MODEL_NAME,
        instructions=instructions,
        input=input_items
    )

    return response.output_text.strip()


def call_model_with_retry(**kwargs):
    for i in range(3):
        try:
            return client.responses.create(**kwargs)

        except APIStatusError as e:
            if e.status_code == 504:
                wait = 2 * (i + 1)
                print(f"504 retry {i+1}, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise

    raise Exception("Model failed after retries")


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
