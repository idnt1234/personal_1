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

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import get_db, Base, engine
import models
import crud

from database import SessionLocal
from models import Chat, Message
from datetime import datetime


Base.metadata.create_all(bind=engine)


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
def now_utc_iso() -> str:
    return datetime.utcnow().isoformat()


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


def generate_chat_id_from_db(db: Session, session_id: str) -> str:
    existing_ids = (
        db.query(Chat.chat_id)
        .filter(Chat.session_id == session_id)
        .all()
    )

    numbers = []
    for (chat_id,) in existing_ids:
        if chat_id.startswith("chat_"):
            suffix = chat_id.replace("chat_", "")
            if suffix.isdigit():
                numbers.append(int(suffix))

    next_number = max(numbers, default=0) + 1
    return f"chat_{next_number:03d}"


def build_chat_history_from_messages(messages: List[Message]) -> List[Dict[str, str]]:
    """
    把数据库里的 Message 列表，转成你 generate_reply / stream_reply
    需要的 chat_history 格式：
    [
        {"user": "...", "assistant": "..."},
        ...
    ]
    """
    chat_history = []
    i = 0

    while i < len(messages) - 1:
        user_item = messages[i]
        assistant_item = messages[i + 1]

        if user_item.role == "user" and assistant_item.role == "assistant":
            chat_history.append({
                "user": user_item.content,
                "assistant": assistant_item.content
            })
            i += 2
        else:
            i += 1

    return chat_history


def get_chat_or_404_db(db: Session, session_id: str, chat_id: str) -> Chat:
    chat = (
        db.query(Chat)
        .filter(Chat.session_id == session_id, Chat.chat_id == chat_id)
        .first()
    )
    if not chat:
        raise HTTPException(status_code=404, detail="chat not found")
    return chat


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


@app.get("/history")
def history(session_id: str, chat_id: str, db: Session = Depends(get_db)):
    chat = (
        db.query(Chat)
        .filter(Chat.session_id == session_id, Chat.chat_id == chat_id)
        .first()
    )
    if not chat:
        raise HTTPException(status_code=404, detail="chat not found")

    messages = (
        db.query(Message)
        .filter(Message.chat_id == chat_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    return [
        {
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


@app.post("/new-chat")
def new_chat(req: NewChatRequest, db: Session = Depends(get_db)):
    title = (req.title or "新对话").strip() or "新对话"
    timestamp = datetime.utcnow()

    chat_id = generate_chat_id_from_db(db, req.session_id)

    chat = Chat(
        session_id=req.session_id,
        chat_id=chat_id,
        title=title,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)

    return {
        "chat_id": chat.chat_id,
        "title": chat.title,
        "created_at": chat.created_at.isoformat() if chat.created_at else None,
        "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
    }


@app.post("/chat/stream")
def chat_stream_api(req: ChatRequest):
    user_msg = req.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    db: Session = SessionLocal()

    chat_obj = (
        db.query(Chat)
        .filter(Chat.session_id == req.session_id, Chat.chat_id == req.chat_id)
        .first()
    )
    if not chat_obj:
        db.close()
        raise HTTPException(status_code=404, detail="chat not found")

    # 读出历史消息，给模型用
    old_messages = (
        db.query(Message)
        .filter(Message.chat_id == req.chat_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    chat_history = [
        {"role": m.role, "text": m.content}
        for m in old_messages
    ]

    def event_generator():
        full_reply = ""
        try:
            # 先把用户消息存进去
            db.add(Message(
                chat_id=req.chat_id,
                role="user",
                content=user_msg,
                created_at=datetime.utcnow()
            ))
            db.commit()

            # 流式生成回复
            for chunk in stream_reply(
                user_msg=user_msg,
                chat_history=chat_history,
                image_path=req.image_path
            ):
                full_reply += chunk
                yield chunk

            # 把助手回复存进去
            db.add(Message(
                chat_id=req.chat_id,
                role="assistant",
                content=full_reply,
                created_at=datetime.utcnow()
            ))

            # 第一次发消息时，顺手设置标题
            if len(old_messages) == 0:
                chat_obj.title = user_msg[:20] or "新对话"

            chat_obj.updated_at = datetime.utcnow()
            db.commit()

        except Exception as e:
            db.rollback()
            yield f"\n[ERROR] {type(e).__name__}: {e}"
        finally:
            db.close()

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
        "preview_url": f"{url}/uploads/{filename}"
    }


@app.get("/chats")
def chats(session_id: str, db: Session = Depends(get_db)):
    data = crud.get_chats_by_session(db, session_id)
    return [
        {
            "chat_id": c.chat_id,
            "title": c.title,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in data
    ]
