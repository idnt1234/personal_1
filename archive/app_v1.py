import streamlit as st
from chat import stream_reply

# ----------------------------
# 页面设置
# ----------------------------
st.set_page_config(page_title="Digital Companion", page_icon="💬")
st.title("💬 Digital Companion")

# ----------------------------
# Session state 初始化
# ----------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "edit_index" not in st.session_state:
    st.session_state.edit_index = None

if "input_box" not in st.session_state:
    st.session_state.input_box = ""

# ----------------------------
# 渲染历史聊天
# ----------------------------
for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        if msg["role"] == "user":
            btn_key = f"edit_{i}_{hash(msg['content'])}"
            if st.button("✏️ 编辑", key=btn_key):
                st.session_state.edit_index = i
                st.session_state.input_box = msg["content"]
                st.rerun()

# ----------------------------
# 输入区域（用 form 包起来）
# ----------------------------
with st.form("chat_form", clear_on_submit=False):
    user_input = st.text_area(
        "和你的数字伙伴聊点什么…",
        key="input_box",
        height=120,
        placeholder="可以慢慢写，Shift+Enter 换行"
    )
    send = st.form_submit_button("发送", use_container_width=True)

# ----------------------------
# 发送消息
# ----------------------------
if send and user_input.strip():
    message = user_input.strip()

    # 编辑模式
    if st.session_state.edit_index is not None:
        edit_i = st.session_state.edit_index
        st.session_state.messages[edit_i]["content"] = message

        # 删除这条用户消息之后的所有内容，重新生成
        st.session_state.messages = st.session_state.messages[:edit_i + 1]
        st.session_state.edit_index = None
    else:
        st.session_state.messages.append({"role": "user", "content": message})

    # 构造 chat_history（只取完整 user-assistant 配对）
    chat_history = []
    msgs = st.session_state.messages[:-1]  # 排除最新用户消息
    for j in range(0, len(msgs) - 1, 2):
        if msgs[j]["role"] == "user" and msgs[j + 1]["role"] == "assistant":
            chat_history.append({
                "user": msgs[j]["content"],
                "assistant": msgs[j + 1]["content"]
            })

    # 流式显示 assistant 回复
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_text = ""

        try:
            for delta in stream_reply(message, chat_history):
                full_text += delta
                placeholder.markdown(full_text + "▌")
            placeholder.markdown(full_text)
        except Exception as e:
            full_text = f"连接 API 失败：{e}"
            placeholder.markdown(full_text)

    # 保存 assistant 消息
    st.session_state.messages.append({"role": "assistant", "content": full_text})

    # 清空输入框
    st.session_state.clear_input = True

    # 重新运行，让输入框出现在最底部
    st.rerun()