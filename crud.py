# 放增删改查函数

from sqlalchemy.orm import Session
from models import Chat, Message
from typing import Optional


def create_chat(db: Session, session_id: str, chat_id: str, title: Optional[str] = None):
    chat = Chat(session_id=session_id, chat_id=chat_id, title=title)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


def add_message(db: Session, chat_id: str, role: str, content: str):
    msg = Message(chat_id=chat_id, role=role, content=content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_messages_by_chat(db: Session, chat_id: str):
    return (
        db.query(Message)
        .filter(Message.chat_id == chat_id)
        .order_by(Message.created_at.asc())
        .all()
    )


def get_chats_by_session(db: Session, session_id: str):
    return (
        db.query(Chat)
        .filter(Chat.session_id == session_id)
        .order_by(Chat.updated_at.desc())
        .all()
    )
