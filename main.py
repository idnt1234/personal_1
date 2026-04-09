import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from chat import generate_reply, stream_reply


app = FastAPI(title="Digital Companion API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "https://personal2-iota.vercel.app",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

CHAT_STORE_PATH = Path(__file__).parent / "data" / "chats.json"
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# ----------------------------
# Helpers
# ----------------------------
def now_iso() -> str:
    return datetime.now().isoformat()


def load_chats() -> dict:
    if not CHAT_STORE_PATH.exists():
        return {}
    with CHAT_STORE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_chats(chats: dict):
    CHAT_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CHAT_STORE_PATH.open("w", encoding="utf-8") as f:
        json.dump(chats, f, ensure_ascii=False, indent=2)


def ensure_session(chats: dict, session_id: str):
    if session_id not in chats:
        chats[session_id] = {}


def generate_chat_id(session_chats: dict) -> str:
    existing_ids = session_chats.keys()
    numbers = []
    for chat_id in existing_ids:
        if chat_id.startswith("chat_"):
            suffix = chat_id.replace("chat_", "")
            if suffix.isdigit():
                numbers.append(int(suffix))
    next_number = max(numbers, default=0) + 1
    return f"chat_{next_number:03d}"


def build_chat_history(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    chat_history = []
    for i in range(0, len(messages) - 1, 2):
        user_item = messages[i]
        assistant_item = messages[i + 1]
        if user_item["role"] == "user" and assistant_item["role"] == "assistant":
            chat_history.append({
                "user": user_item["text"],
                "assistant": assistant_item["text"]
            })
    return chat_history


def get_chat_or_404(chats: dict, session_id: str, chat_id: str) -> dict:
    ensure_session(chats, session_id)
    session_chats = chats[session_id]
    if chat_id not in session_chats:
        raise HTTPException(status_code=404, detail="chat not found")
    return session_chats[chat_id]


# ----------------------------
# Request models
# ----------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: str
    chat_id: str
    image_path: Optional[str] = None


class NewChatRequest(BaseModel):
    session_id: str
    title: Optional[str] = None


# ----------------------------
# Routes
# ----------------------------
@app.get("/")
def root():
    return {"message": "Digital Companion API is running."}


@app.get("/chats")
def get_chats(session_id: str = Query(...)):
    chats = load_chats()
    ensure_session(chats, session_id)

    session_chats = chats[session_id]
    result = []
    for chat_id, chat_obj in session_chats.items():
        result.append({
            "chat_id": chat_id,
            "title": chat_obj.get("title", "新对话"),
            "created_at": chat_obj.get("created_at"),
            "updated_at": chat_obj.get("updated_at"),
        })

    result.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return {"chats": result}


@app.get("/history")
def get_history(session_id: str = Query(...), chat_id: str = Query(...)):
    chats = load_chats()
    chat_obj = get_chat_or_404(chats, session_id, chat_id)
    return {
        "chat_id": chat_id,
        "title": chat_obj.get("title", "新对话"),
        "messages": chat_obj.get("messages", [])
    }


@app.post("/new-chat")
def new_chat(req: NewChatRequest):
    chats = load_chats()
    ensure_session(chats, req.session_id)

    session_chats = chats[req.session_id]
    chat_id = generate_chat_id(session_chats)

    title = (req.title or "新对话").strip() or "新对话"
    timestamp = now_iso()

    session_chats[chat_id] = {
        "title": title,
        "created_at": timestamp,
        "updated_at": timestamp,
        "messages": []
    }

    save_chats(chats)

    return {
        "chat_id": chat_id,
        "title": title,
        "created_at": timestamp,
        "updated_at": timestamp
    }


@app.post("/chat")
def chat_api(req: ChatRequest):
    user_msg = req.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    try:
        chats = load_chats()
        chat_obj = get_chat_or_404(chats, req.session_id, req.chat_id)

        messages = chat_obj.get("messages", [])
        chat_history = build_chat_history(messages)

        reply = generate_reply(
            user_msg=user_msg,
            chat_history=chat_history,
            image_path=req.image_path
        )

        messages.append({"role": "user", "text": user_msg})
        messages.append({"role": "assistant", "text": reply})

        if not messages[:-2]:
            chat_obj["title"] = user_msg[:20] or "新对话"

        chat_obj["messages"] = messages
        chat_obj["updated_at"] = now_iso()

        save_chats(chats)

        return {
            "reply": reply,
            "chat_id": req.chat_id,
            "title": chat_obj["title"]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.post("/chat/stream")
def chat_stream_api(req: ChatRequest):
    user_msg = req.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    chats = load_chats()
    chat_obj = get_chat_or_404(chats, req.session_id, req.chat_id)

    messages = chat_obj.get("messages", [])
    chat_history = build_chat_history(messages)

    def event_generator():
        full_reply = ""
        try:
            for chunk in stream_reply(
                user_msg=user_msg,
                chat_history=chat_history,
                image_path=req.image_path
            ):
                full_reply += chunk
                yield chunk

            messages.append({"role": "user", "text": user_msg})
            messages.append({"role": "assistant", "text": full_reply})

            if not messages[:-2]:
                chat_obj["title"] = user_msg[:20] or "新对话"

            chat_obj["messages"] = messages
            chat_obj["updated_at"] = now_iso()
            save_chats(chats)

        except Exception as e:
            yield f"\n[ERROR] {type(e).__name__}: {e}"

    return StreamingResponse(event_generator(), media_type="text/plain; charset=utf-8")


@app.post("/upload-image")
async def upload_image(request: Request, file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="only image files are allowed")

    suffix = Path(file.filename).suffix or ".png"
    filename = f"{uuid.uuid4().hex}{suffix}"
    save_path = UPLOAD_DIR / filename

    content = await file.read()
    save_path.write_bytes(content)

    url = str(request.base_url).rstrip("/")
    return {
        "image_path": str(save_path),
        "preview_url": f"https://valeria-xxx.ngrok-free.dev/uploads/{filename}"
    }
