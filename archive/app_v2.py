import streamlit as st
from chat import stream_reply, generate_image_summary
import uuid
import json
import os

# ----------------------------
# 配置
# ----------------------------
CHAT_FILE = "../chats.json"
UPLOAD_DIR = "../uploads"

# 确保上传目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ----------------------------
# 读写本地 JSON
# ----------------------------
def load_chats():
    if os.path.exists(CHAT_FILE):
        try:
            with open(CHAT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_chats(chats, current_chat_id):
    data = {
        "current_chat_id": current_chat_id,
        "chats": chats
    }
    with open(CHAT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ----------------------------
# 保存上传图片到本地
# ----------------------------
def save_uploaded_image(uploaded_file):
    if uploaded_file is None:
        return None

    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if not ext:
        ext = ".png"

    filename = f"{uuid.uuid4()}{ext}"
    save_path = os.path.join(UPLOAD_DIR, filename)

    with open(save_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    return save_path

# ----------------------------
# 页面设置
# ----------------------------
st.set_page_config(page_title="Digital Companion", page_icon="💬", layout="wide")
st.title("💬 Digital Companion")

# ----------------------------
# 初始化 session state
# ----------------------------
if "chats" not in st.session_state or "current_chat_id" not in st.session_state:
    saved_data = load_chats()

    if saved_data and "chats" in saved_data and saved_data["chats"]:
        st.session_state.chats = saved_data["chats"]
        st.session_state.current_chat_id = saved_data.get(
            "current_chat_id",
            list(saved_data["chats"].keys())[0]
        )
    else:
        first_chat_id = str(uuid.uuid4())
        st.session_state.chats = {
            first_chat_id: {
                "title": "New Chat",
                "messages": []
            }
        }
        st.session_state.current_chat_id = first_chat_id
        save_chats(st.session_state.chats, st.session_state.current_chat_id)

if "show_uploader" not in st.session_state:
    st.session_state.show_uploader = False

if "pending_image" not in st.session_state:
    st.session_state.pending_image = None

if "pending_image_name" not in st.session_state:
    st.session_state.pending_image_name = None

# ----------------------------
# helper
# ----------------------------
def build_chat_history(messages):
    history = []
    for i in range(0, len(messages) - 1, 2):
        if (
            i + 1 < len(messages)
            and messages[i]["role"] == "user"
            and messages[i + 1]["role"] == "assistant"
        ):
            history.append({
                "user": messages[i]["content"],
                "assistant": messages[i + 1]["content"],
                "image_summary": messages[i].get("image_summary", "")
            })
    return history

def create_new_chat():
    new_chat_id = str(uuid.uuid4())
    st.session_state.chats[new_chat_id] = {
        "title": "New Chat",
        "messages": []
    }
    st.session_state.current_chat_id = new_chat_id
    st.session_state.pending_image = None
    st.session_state.pending_image_name = None
    st.session_state.show_uploader = False
    save_chats(st.session_state.chats, st.session_state.current_chat_id)

def switch_chat(chat_id):
    st.session_state.current_chat_id = chat_id
    st.session_state.pending_image = None
    st.session_state.pending_image_name = None
    st.session_state.show_uploader = False
    save_chats(st.session_state.chats, st.session_state.current_chat_id)

# ----------------------------
# 左边栏：聊天记录
# ----------------------------
with st.sidebar:
    st.subheader("History Chats")

    if st.button("+ New Chat", use_container_width=True):
        create_new_chat()
        st.rerun()

    st.divider()

    for chat_id, chat_data in reversed(list(st.session_state.chats.items())):
        title = chat_data["title"]
        if st.button(title, key=f"chat_{chat_id}", use_container_width=True):
            switch_chat(chat_id)
            st.rerun()

# ----------------------------
# 当前聊天
# ----------------------------
current_chat = st.session_state.chats[st.session_state.current_chat_id]
messages = current_chat["messages"]

# ----------------------------
# 渲染历史消息（支持图片）
# ----------------------------
for msg in messages:
    with st.chat_message(msg["role"]):
        if msg.get("content"):
            st.markdown(msg["content"])

        if msg.get("image_path"):
            image_path = msg["image_path"]
            if os.path.exists(image_path):
                st.image(image_path, width=220)
            else:
                st.caption("⚠图片文件不存在或已丢失")

st.divider()

# ----------------------------
# 上传区（由 + 按钮控制展开）
# ----------------------------
if st.session_state.show_uploader:
    uploaded_file = st.file_uploader(
        "选择一张图片",
        type=["png", "jpg", "jpeg", "webp"],
        key="image_uploader"
    )

    if uploaded_file is not None:
        st.session_state.pending_image = uploaded_file
        st.session_state.pending_image_name = uploaded_file.name

    if st.session_state.pending_image is not None:
        st.image(
            st.session_state.pending_image,
            caption=f"待发送图片：{st.session_state.pending_image_name}",
            width=220
        )

        if st.button("移除这张图片"):
            st.session_state.pending_image = None
            st.session_state.pending_image_name = None
            st.rerun()

# ----------------------------
# 底部输入区：+ 按钮 + 文本框 + 发送
# ----------------------------
with st.form("bottom_input_form", clear_on_submit=True):
    col1, col2, col3 = st.columns([1, 8, 1])

    with col1:
        plus_clicked = st.form_submit_button("＋", use_container_width=True)

    with col2:
        prompt = st.text_input(
            "输入消息",
            placeholder="和你的数字伙伴聊点什么…",
            label_visibility="collapsed"
        )

    with col3:
        send_clicked = st.form_submit_button("发送", use_container_width=True)

# 点 +：切换上传区显示状态
if plus_clicked:
    st.session_state.show_uploader = not st.session_state.show_uploader
    st.rerun()

# ----------------------------
# 点发送
# ----------------------------
if send_clicked and prompt.strip():
    text = prompt.strip()

    # 如果有待发送图片，先保存到本地
    saved_image_path = None
    if st.session_state.pending_image is not None:
        saved_image_path = save_uploaded_image(st.session_state.pending_image)

    # 用户消息：这次把 image_path 也存进去
    user_message = {
        "role": "user",
        "content": text,
        "image_path": saved_image_path,
        "image_summary": ""
    }
    messages.append(user_message)

    # 自动更新标题
    if current_chat["title"] == "新聊天":
        current_chat["title"] = text[:20] + ("..." if len(text) > 20 else "")

    save_chats(st.session_state.chats, st.session_state.current_chat_id)

    # 当前这一轮显示 user 气泡：文本 + 图片
    with st.chat_message("user"):
        st.markdown(text)
        if saved_image_path and os.path.exists(saved_image_path):
            st.image(saved_image_path, width=220)

    # 构造文本历史（暂时不把图片传给模型）
    chat_history = build_chat_history(messages[:-1])

    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_text = ""

        try:
            for delta in stream_reply(text, chat_history, image_path=saved_image_path):
                full_text += delta
                placeholder.markdown(full_text + "▌")
            placeholder.markdown(full_text)
        except Exception as e:
            full_text = f"连接 API 失败：{e}"
            placeholder.markdown(full_text)

    messages.append({
        "role": "assistant",
        "content": full_text
    })

    if saved_image_path:
        try:
            image_summary = generate_image_summary(text, saved_image_path)
            user_message["image_summary"] = image_summary
        except Exception as e:
            print(f"生成图片摘要失败：{e}")
            user_message["image_summary"] = ""

    save_chats(st.session_state.chats, st.session_state.current_chat_id)

    # 清空临时图片
    st.session_state.pending_image = None
    st.session_state.pending_image_name = None
    st.session_state.show_uploader = False

    st.rerun()