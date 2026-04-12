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


def fetch_recent_chat(db: Session, chat_id: str, limit: int = 10):
    """
    从 messages 表中取最近 N 轮对话
    """

    # 先拿最近的 2 * limit 条 message（因为一轮 = user + assistant）
    msgs = (
        db.query(Message)
        .filter(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc())
        .limit(limit * 2)
        .all()
    )

    # ⚠转成时间正序
    msgs = list(reversed(msgs))

    chat_history = []
    temp_user = None

    for m in msgs:
        if m.role == "user":
            temp_user = m.content

        elif m.role == "assistant" and temp_user:
            chat_history.append({
                "user": temp_user,
                "assistant": m.content,
                "image_summary": None
            })
            temp_user = None

    return chat_history


def insert_message_pair(db: Session, chat_id: str, user_msg: str, assistant_msg: str):
    from models import Message

    user = Message(
        chat_id=chat_id,
        role="user",
        content=user_msg
    )

    assistant = Message(
        chat_id=chat_id,
        role="assistant",
        content=assistant_msg
    )

    db.add(user)
    db.add(assistant)
    db.commit()
