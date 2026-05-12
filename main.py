import json
import uuid
import traceback
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from chat import generate_reply

from sqlalchemy.orm import Session
from database import get_db, Base, engine, SessionLocal
import models

from models import Chat, Message
import crud
from crud import (
    fetch_recent_chat,
    get_memory,
    upsert_memory
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Digital Companion API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

app.mount("/icons", StaticFiles(directory="icons"), name="icons")


# ----------------------------
# Helpers
# ----------------------------
def now_utc_iso() -> str:
    return datetime.utcnow().isoformat()


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


def build_from_messages(messages: List[Message]) -> List[Dict[str, str]]:
    """
    把数据库里的 Message 列表，转成你 generate_reply / stream_reply (LLM理解的结构）
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


class MemoryUpdateRequest(BaseModel):
    category: str
    content: str


class MemoryItem(BaseModel):
    id: Optional[int] = None
    category: str
    content: str


class MemoryBulkRequest(BaseModel):
    memories: List[MemoryItem]


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


@app.post("/chat")
def chat_api(req: ChatRequest):
    user_msg = req.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    db: Session = SessionLocal()

    try:
        # 找 chat
        chat_obj = (
            db.query(Chat)
            .filter(Chat.session_id == req.session_id, Chat.chat_id == req.chat_id)
            .first()
        )
        if not chat_obj:
            raise HTTPException(status_code=404, detail="chat not found")

        # 读历史
        old_messages = (
            db.query(Message)
            .filter(Message.chat_id == req.chat_id)
            .order_by(Message.created_at.asc())
            .all()
        )

        chat_history = build_from_messages(old_messages)

        # 生成完整回复
        reply = generate_reply(
            user_msg=user_msg,
            chat_history=chat_history,
            db=db,
            image_path=req.image_path
        )

        # 存 user
        db.add(Message(
            chat_id=req.chat_id,
            role="user",
            content=user_msg,
            created_at=datetime.utcnow()
        ))

        # 👉 存 assistant
        db.add(Message(
            chat_id=req.chat_id,
            role="assistant",
            content=reply,
            created_at=datetime.utcnow()
        ))

        # 👉 更新 chat
        if len(old_messages) == 0:
            chat_obj.title = user_msg[:20] or "新对话"

        chat_obj.updated_at = datetime.utcnow()

        db.commit()

        return {
            "reply": reply
        }

    except Exception as e:
        db.rollback()

        print("🔥 ERROR:", e)
        traceback.print_exc()

        raise HTTPException(status_code=500, detail=str(e))

    finally:
        db.close()


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

    return {
        "chats": [
            {
                "chat_id": c.chat_id,
                "title": c.title,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in data
        ]
    }


@app.get("/memory")
def get_memory_api():
    db = SessionLocal()
    try:
        from models import Memory

        memories = db.query(Memory).all()

        return {
            "memories": [
                {
                    "id": m.id,
                    "category": m.category,
                    "content": m.content
                }
                for m in memories
            ]
        }
    finally:
        db.close()


@app.post("/memory/update")
def update_memory_api(req: MemoryUpdateRequest):
    db: Session = SessionLocal()

    try:
        upsert_memory(db, req.category, req.content)
        return {"status": "ok"}
    except Exception as e:
        import traceback
        db.rollback()

        print("MEMORY ERROR:", e)
        traceback.print_exc()

        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.post("/memory/bulk_update")
def bulk_update_memory(req: MemoryBulkRequest):
    db = SessionLocal()
    try:
        from models import Memory

        # 先清空（简单粗暴但稳定）
        db.query(Memory).delete()

        for item in req.memories:
            mem = Memory(
                category=item.category,
                content=item.content
            )
            db.add(mem)

        db.commit()
        return {"status": "ok"}

    except Exception as e:
        import traceback
        db.rollback()
        print("BULK ERROR:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        db.close()


@app.delete("/delete-chat")
def delete_chat(session_id: str, chat_id: str, db: Session = Depends(get_db)):
    chat = get_chat_or_404_db(db, session_id, chat_id)

    db.delete(chat)
    db.commit()

    return {"status": "ok"}


@app.post("/rename-chat")
def rename_chat(session_id: str, chat_id: str, title: str, db: Session = Depends(get_db)):
    chat = get_chat_or_404_db(db, session_id, chat_id)

    chat.title = title.strip() or "New chat"
    chat.updated_at = datetime.utcnow()

    db.commit()

    return {"status": "ok"}


@app.delete("/delete-message-pair")
def delete_message_pair(
    session_id: str,
    chat_id: str,
    index: int,
    db: Session = Depends(get_db)
):
    # 找 chat（防止乱删）
    chat = get_chat_or_404_db(db, session_id, chat_id)

    # 按时间顺序拿所有 message
    messages = (
        db.query(Message)
        .filter(Message.chat_id == chat_id)
        .order_by(Message.created_at.asc())
        .all()
    )

    # ❗安全检查
    if index < 0 or index >= len(messages):
        raise HTTPException(status_code=400, detail="invalid index")

    # 删除 user + assistant（两条）
    to_delete = messages[index:index+2]

    for m in to_delete:
        db.delete(m)

    db.commit()

    return {"status": "ok"}


@app.get("/manifest.json")
async def manifest():
    return FileResponse("manifest.json")
