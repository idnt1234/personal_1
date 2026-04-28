const SESSION_ID = "digital-companion-main";
const API_BASE = "https://personal1-e9lq.onrender.com";

const chatBox = document.getElementById("chatBox");
const messageInput = document.getElementById("messageInput");
const sendButton = document.getElementById("sendButton");
const newChatButton = document.getElementById("newChatButton");
const chatList = document.getElementById("chatList");
const chatTitle = document.getElementById("chatTitle");

const imageInput = document.getElementById("imageInput");

const menuButton = document.getElementById("menuButton");
const sidebar = document.querySelector(".sidebar");

const overlay = document.querySelector(".overlay");

const actionMenu = document.getElementById("actionMenu");

let currentActionChatId = null;
let currentChatId = null;
let messages = [];
let chatListData = [];
let uploadedImagePath = null;

window.addEventListener("load", () => {
    messageInput.style.height = "auto";
    messageInput.style.height = messageInput.scrollHeight + "px";
});

function scrollToBottom() {
    chatBox.scrollTop = chatBox.scrollHeight;
}

function createMessageElement(role, text, image) {
    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${role}`;

    // 如果有图片，先加图片
    if (image) {
        const img = document.createElement("img");
        img.src = API_BASE + image;  // 或直接用你的路径
        img.style.maxWidth = "160px";
        img.style.borderRadius = "10px";
        img.style.display = "block";
        img.style.marginBottom = text ? "6px" : "0";

        msgDiv.appendChild(img);
    }

    // 再加文字
    if (text) {
        const textNode = document.createElement("div");
        textNode.innerHTML = marked.parse(text);
        msgDiv.appendChild(textNode);
    }

    return msgDiv;
}

function renderMessages() {
    chatBox.innerHTML = "";
    messages.forEach((msg, index) => {
    const msgDiv = createMessageElement(msg.role, msg.text, msg.image);

    // 👉 如果是 user，加删除按钮
    if (msg.role === "user") {
        const wrapper = document.createElement("div");
        wrapper.style.display = "flex";
        wrapper.style.flexDirection = "column";

        wrapper.appendChild(msgDiv);

        const actions = document.createElement("div");
        actions.style.marginTop = "4px";
        actions.style.display = "flex";
        actions.style.justifyContent = "flex-end";

        const deleteBtn = document.createElement("button");
        deleteBtn.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-trash2-icon lucide-trash-2"><path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
        `;
        deleteBtn.style.border = "none";
        deleteBtn.style.background = "transparent";
        deleteBtn.style.cursor = "pointer";

        deleteBtn.onclick = () => {
            deleteMessagePair(index);
        };

        actions.appendChild(deleteBtn);
        wrapper.appendChild(actions);

        chatBox.appendChild(wrapper);
    } else {
        chatBox.appendChild(msgDiv);
    }
});
    scrollToBottom();
}

function renderChatList() {
    chatList.innerHTML = "";

    for (const item of chatListData) {
        const div = document.createElement("div");
        div.className = "chat-item";
        if (item.chat_id === currentChatId) {
            div.classList.add("active");
        }

        const content = document.createElement("div");
        content.className = "chat-item-content";

        const title = document.createElement("div");
        title.className = "chat-item-title";
        title.textContent = item.title || "New chat";
        title.addEventListener("dblclick", async (e) => {
            e.stopPropagation();

            const newName = prompt("Rename chat", item.title || "");

            if (!newName) return;

            await renameChat(item.chat_id, newName);
        });

        const time = document.createElement("div");
        time.className = "chat-item-time";
        time.textContent = item.updated_at
            ? item.updated_at.split("T")[0]
            : "";

        // 拼左侧
        content.appendChild(title);
        content.appendChild(time);

        // delete 按钮
        const delBtn = document.createElement("button");
        delBtn.className = "chat-delete";
        delBtn.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-trash-icon lucide-trash"><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
        `;

        // ❗关键：阻止冒泡
        delBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            deleteChat(item.chat_id);
        });

        div.appendChild(content);
        div.appendChild(delBtn);

        chatList.appendChild(div);

        // 手机上
        let pressTimer = null;
        let isLongPress = false;

        div.addEventListener("touchstart", (e) => {
            isLongPress = false;

            const touch = e.touches[0];

            pressTimer = setTimeout(() => {
                isLongPress = true;
                showActionMenu(item.chat_id, touch.clientX, touch.clientY);
            }, 700);
        });

        div.addEventListener("touchend", () => {
            clearTimeout(pressTimer);

            if (!isLongPress) {
                openChat(item.chat_id);
            }
        });

        div.addEventListener("touchmove", () => {
            clearTimeout(pressTimer);
        });

        // 👉 只给桌面
        if (!('ontouchstart' in window)) {
            div.addEventListener("click", () => {
                openChat(item.chat_id);
            });
        }
    }
}

function setLoading(isLoading) {
    sendButton.disabled = isLoading;
    newChatButton.disabled = isLoading;
    messageInput.disabled = isLoading;
    imageInput.disabled = isLoading;
}

function clearImage() {
    uploadedImagePath = null;
    imageInput.value = "";
}

function resizeTextarea() {
    messageInput.style.height = "auto";
    messageInput.style.height = messageInput.scrollHeight + "px";
}

function showActionMenu(chatId, x, y) {
    currentActionChatId = chatId;

    actionMenu.style.left = x + "px";
    actionMenu.style.top = y + "px";
    actionMenu.style.display = "block";
}

async function deleteMessagePair(index) {
    const res = await fetch(
        `${API_BASE}/delete-message-pair?session_id=${SESSION_ID}&chat_id=${currentChatId}&index=${index}`,
        {
            method: "DELETE"
        }
    );

    if (!res.ok) {
        alert("删除失败");
        return;
    }

    await openChat(currentChatId); // 🔥 重新拉最新数据
}

async function loadChatList() {
    const response = await fetch(
        `${API_BASE}/chats?session_id=${encodeURIComponent(SESSION_ID)}`,
        {
            headers: {
                "ngrok-skip-browser-warning": "1"
            }
        }
    );
    if (!response.ok) {
        throw new Error(`加载聊天列表失败: HTTP ${response.status}`);
    }

    const data = await response.json();
    chatListData = data.chats || [];
    renderChatList();
    return chatListData;
}

async function openChat(chatId) {
    const response = await fetch(
        `${API_BASE}/history?session_id=${encodeURIComponent(SESSION_ID)}&chat_id=${encodeURIComponent(chatId)}`,
        {
            headers: {
                "ngrok-skip-browser-warning": "1"
            }
        }
    );

    if (!response.ok) {
        throw new Error(`加载聊天记录失败: HTTP ${response.status}`);
    }

    const data = await response.json();

    currentChatId = chatId;
    messages = data.map(m => ({
        role: m.role,
        text: m.content
    }));
    chatTitle.textContent = data.title || "💬 Digital Companion";

    renderMessages();
    renderChatList();
}

async function createNewChat() {
    const response = await fetch(`${API_BASE}/new-chat`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "ngrok-skip-browser-warning": "1"
        },
        body: JSON.stringify({
            session_id: SESSION_ID
        })
    });

    if (!response.ok) {
        throw new Error(`新建聊天失败: HTTP ${response.status}`);
    }

    const data = await response.json();
    await loadChatList();
    await openChat(data.chat_id);
}

async function sendMessage() {
    const message = messageInput.value.trim();
    const imageToSend = uploadedImagePath;

    if (!message) return;

    if (!currentChatId) {
        await createNewChat();
    }

    // 先显示用户消息
    messages.push({
        role: "user",
        text: message,
        image: imageToSend
    });
    renderMessages();

    clearImage();
    messageInput.value = "";
    resizeTextarea();

    messageInput.focus();

    messageInput.value = "";
    setLoading(true);

    // 预留 assistant 气泡
    const assistantMsgDiv = createMessageElement("assistant", "...");
    chatBox.appendChild(assistantMsgDiv);
    scrollToBottom();

    try {
        const response = await fetch(`${API_BASE}/chat`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                message: message,
                session_id: SESSION_ID,
                chat_id: currentChatId,
                image_path: imageToSend
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        // ✅ 非流式：直接拿完整结果
        const data = await response.json();
        const fullReply = data.reply || "";

        // 👉 更新 UI
        assistantMsgDiv.innerHTML = marked.parse(fullReply);

        // 👉 存到本地 messages
        messages.push({
            role: "assistant",
            text: fullReply
        });

        scrollToBottom();

        // 👉 只更新左边列表（不要 reload 当前聊天）
        await loadChatList();

    } catch (error) {
        console.error("请求失败:", error);
        assistantMsgDiv.textContent = `请求失败：${error.message}`;
    } finally {
        setLoading(false);
        messageInput.focus();
        scrollToBottom();
    }

    console.log("发送时 image_path =", uploadedImagePath);
}

async function uploadImage(file) {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch(`${API_BASE}/upload-image`, {
        method: "POST",
        headers: {
            "ngrok-skip-browser-warning": "1"
        },
        body: formData
    });

    if (!res.ok) {
        throw new Error(`图片上传失败: HTTP ${res.status}`);
    }

    const data = await res.json();
    uploadedImagePath = data.image_path;

    document.getElementById("removeImageButton").addEventListener("click", clearImage);
}

async function deleteChat(chatId) {
    await fetch(`${API_BASE}/delete-chat?session_id=${SESSION_ID}&chat_id=${chatId}`, {
        method: "DELETE"
    });

    await loadChatList();

    if (chatId === currentChatId) {
        if (chatListData.length > 0) {
            await openChat(chatListData[0].chat_id);
        } else {
            await createNewChat();
        }
    }
}

async function renameChat(chatId, newTitle) {
    const res = await fetch(
        `${API_BASE}/rename-chat?session_id=${SESSION_ID}&chat_id=${chatId}&title=${encodeURIComponent(newTitle)}`,
        {
            method: "POST"
        }
    );

    if (!res.ok) {
        alert("重命名失败");
        return;
    }

    await loadChatList();
}

addButton.addEventListener("click", () => {
    imageInput.click();
});

sendButton.addEventListener("click", () => {
    console.log("clicked");
    sendMessage();
});

newChatButton.addEventListener("click", async () => {
    try {
        setLoading(true);
        await createNewChat();
        messageInput.focus();
    } catch (error) {
        console.error("新建聊天失败:", error);
        alert(`新建聊天失败：${error.message}`);
    } finally {
        setLoading(false);
    }
});

messageInput.addEventListener("keydown", function (event) {
    const isMobile = /Mobi|Android|iPhone/i.test(navigator.userAgent);

    if (event.key === "Enter" && !event.shiftKey && !isMobile) {
        event.preventDefault();
        sendMessage();
    }
});

messageInput.addEventListener("input", resizeTextarea, () => {
    messageInput.style.height = "auto";
    messageInput.style.height = messageInput.scrollHeight + "px";
});

const inputBar = document.querySelector(".input-bar");

inputBar.addEventListener("dragover", (e) => {
    e.preventDefault();
    inputBar.style.background = "#eef2f7";
});

inputBar.addEventListener("dragleave", () => {
    inputBar.style.background = "#f8fafc";
});

inputBar.addEventListener("drop", async (e) => {
    e.preventDefault();
    inputBar.style.background = "#f8fafc";

    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith("image/")) {
        await uploadImage(file);
    }
});

imageInput.addEventListener("change", async () => {
    if (imageInput.files[0]) {
        try {
            await uploadImage(imageInput.files[0]);
        } catch (error) {
            console.error(error);
            alert(error.message);
        }
    }
});

window.addEventListener("load", async () => {
    try {
        await loadChatList();

        if (chatListData.length > 0) {
            await openChat(chatListData[0].chat_id);
        } else {
            await createNewChat();
        }
    } catch (error) {
        console.error("初始化失败:", error);
        chatTitle.textContent = "💬 Digital Companion";
        chatBox.innerHTML = "";
        chatBox.appendChild(createMessageElement("assistant", `初始化失败：${error.message}`));
    }
});

menuButton.addEventListener("click", () => {
    sidebar.classList.toggle("open");
    overlay.classList.toggle("show");
});

document.addEventListener("click", (e) => {
    if (!sidebar.contains(e.target) && !menuButton.contains(e.target)) {
        sidebar.classList.remove("open");
    }
});

document.getElementById("memoryButton").onclick = () => {
    window.location.href = "/memory.html";
};

overlay.addEventListener("click", () => {
    sidebar.classList.remove("open");
    overlay.classList.remove("show");
});

actionMenu.addEventListener("click", async (e) => {
    const action = e.target.dataset.action;

    if (!action) return;

    if (action === "rename") {
        const newName = prompt("New name:");
        if (newName) await renameChat(currentActionChatId, newName);
    }

    if (action === "delete") {
        if (confirm("Delete chat?")) {
            await deleteChat(currentActionChatId);
        }
    }

    actionMenu.style.display = "none";
});

document.addEventListener("click", () => {
    actionMenu.style.display = "none";
});
