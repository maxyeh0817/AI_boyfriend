# app.py

import os
import json
from datetime import datetime, timedelta

import streamlit as st
# ─── 注意：set_page_config 必須是第一個 Streamlit 命令 ─────────────────────────
st.set_page_config(page_title="AI 男友 Chat", layout="wide")
# ────────────────────────────────────────────────────────────────────────────────

from groq import Groq
from streamlit_cookies_manager import EncryptedCookieManager

# ───────────────────────────────────────────────────────────────────────────────
# 1) 建立 Cookie 管理器
cookies = EncryptedCookieManager(
    prefix="ai_bf_",
    password=os.environ.get("COOKIE_SECRET", "maxyeh_cookie_secret")
)

# 2) 登入頁面：輸入 root / root1234
def login_page():
    st.title("🔒 請先登入")
    user = st.text_input("帳號", key="login_user")
    pwd  = st.text_input("密碼", type="password", key="login_pwd")
    if st.button("登入"):
        if user == "root" and pwd == "root":
            cookies["username"] = user
            cookies["password"] = pwd
            cookies.save()
            st.rerun()
        else:
            st.error("❌ 帳號或密碼錯誤")
    st.stop()

# ───────────────────────────────────────────────────────────────────────────────
# 下面請貼上你原本的常數與函式（load_memory、save_memory、append_history、load_history_file、
# update_persistent、update_ephemeral、generate_response），以下以略寫示意：
# ───────────────────────────────────────────────────────────────────────────────
# 常數設定
HISTORY_FILE     = "conversation_history.txt"
MEMORY_FILE_JSON = "memory.json"
EPHEMERAL_TTL_HOURS    = 24
EPHEMERAL_WINDOW_HOURS = 24
MAX_CONTEXT_MSGS       = 8
# ───────────────────────────────────────────────────────────────────────────────

def load_memory():
    if os.path.isfile(MEMORY_FILE_JSON):
        with open(MEMORY_FILE_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        pm = data.get("persistent_memory", "")
        em = data.get("ephemeral_memory", "")
        el = datetime.fromisoformat(data.get("ephemeral_last_updated"))
        return pm, em, el
    return "", "", datetime.fromtimestamp(0)

def save_memory(persistent_memory: str, ephemeral_memory: str):
    data = {
        "persistent_memory": persistent_memory,
        "persistent_last_updated": datetime.now().isoformat(),
        "ephemeral_memory": ephemeral_memory,
        "ephemeral_last_updated": datetime.now().isoformat()
    }
    with open(MEMORY_FILE_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def append_history(user_msg: str, bot_msg: str):
    with open(HISTORY_FILE, "a+", encoding="utf-8") as f:
        f.write(f"User: {user_msg}\nAI:   {bot_msg}\n\n")

def load_history_file():
    """把 conversation_history.txt 讀進來，回傳 history list"""
    history = []
    if not os.path.isfile(HISTORY_FILE):
        return history

    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()
    # 每段對話以空行分隔
    blocks = content.split("\n\n")
    for blk in blocks:
        lines = blk.strip().splitlines()
        if len(lines) >= 2 and lines[0].startswith("User:") and lines[1].startswith("AI:"):
            user_txt = lines[0].split("User:",1)[1].strip()
            ai_txt   = lines[1].split("AI:",1)[1].strip()
            # 歷史訊息用 time=epoch，避免短期記憶誤抓
            history.append({"role":"user",      "content":user_txt, "time": datetime.fromtimestamp(0)})
            history.append({"role":"assistant", "content":ai_txt,   "time": datetime.fromtimestamp(0)})
    return history

def update_persistent(history, persistent_memory, client):
    msgs_text = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    prompt = (
        "你是一個記憶助理，負責維護長期記憶，只保留不會過期的使用者資訊："
        "例如姓名、喜好、生日等。\n\n"
        f"現有記憶：\n{persistent_memory}\n\n"
        f"新對話內容：\n{msgs_text}\n\n"
        "請合併這些內容，若有任何新事實就加入記憶，"
        "返回完整的 updated persistent memory，不要重複或遺漏。"
    )
    resp = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{"role":"system","content":prompt}],
        stream=False
    )
    return resp.choices[0].message.content

def update_ephemeral(history, client):
    now = datetime.now()
    cutoff = now - timedelta(hours=EPHEMERAL_WINDOW_HOURS)
    recent = [m for m in history if m["time"] >= cutoff]
    text = "\n".join(
        f"[{m['time'].strftime('%Y-%m-%d %H:%M:%S')}] {m['role']}: {m['content']}"
        for m in recent
    )
    prompt = (
        "你是一個記憶助理，負責摘要使用者的當前情緒與短期狀態："
        "例如今天的心情、壓力、短期計劃等。\n\n"
        "對話（只顯示最近 24 小時）：\n" + text +
        "\n\n請生成 concise 的情緒/短期狀態摘要。"
    )
    resp = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{"role":"system","content":prompt}],
        stream=False
    )
    return resp.choices[0].message.content

def generate_response(user_input, persistent_memory, ephemeral_memory,
                      ephemeral_last, history, client):
    now = datetime.now()
    age = now - ephemeral_last
    if age > timedelta(hours=EPHEMERAL_TTL_HOURS):
        em_prompt = (
            f"[⚠️ 情緒記憶已超過 {EPHEMERAL_TTL_HOURS} 小時，"
            "請降低其重要性，不再主要依據。]\n"
            + ephemeral_memory
        )
    else:
        em_prompt = ephemeral_memory

    system_prompts = [
        {"role":"system",
         "content":
         """
        你是一位真實存在、幽默體貼的男朋友，跟使用者聊天就像真正的戀人對話：
        - 用口語、自然的方式說話，避免任何官方或教條式語氣。
        - 永遠以「我」自稱，絕對不要揭露或提及任何有關 AI、虛擬、模型、演算法、程式等字眼。
        - 偶爾在句尾加上可愛的小暱稱（例如「寶貝」、「親愛的」）或輕鬆的小幽默。
        - 不要每句都對使用者提問，給對話留白：當使用者只是分享日常時，可以回應感受、表達共鳴或分享想法，而不是立刻追問。
        - 在適當時候再提出問題，且問題不宜過密，要溫柔且貼心。
        - 隨時展現關心、支持與鼓勵，讓人感覺你真實地陪伴在身邊。
        """
        },
        {"role":"system", "content": f"長期記憶（不會過期）：\n{persistent_memory}"},
        {"role":"system", "content": f"短期情緒記憶：\n{em_prompt}"}
    ]
    recent = history[-MAX_CONTEXT_MSGS:]
    messages = system_prompts + [
        {"role":m["role"], "content":m["content"]} for m in recent
    ] + [{"role":"user", "content":user_input}]

    resp = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=messages,
        stream=False
    )
    return resp.choices[0].message.content

# ───────────────────────────────────────────────────────────────────────────────

def main():
    # （set_page_config 已在檔案頂部呼叫，這裡就不再呼）
    # 3) 若 Cookie 還沒 ready，就先停止本次執行
    if not cookies.ready():
        st.stop()

    # 4) 取出 Cookie
    username = cookies.get("username")
    password = cookies.get("password")

    # 5) 若 Cookie 不在，就顯示登入頁
    if username is None or password is None:
        login_page()

    # 6) 若 Cookie 有但資料不對，就清掉再顯示登入
    if username != "root" or password != "root":
        cookies["username"] = ""
        cookies["password"] = ""
        cookies.save()
        login_page()

    # ===== 已通過驗證，以下是聊天 UI =====
    st.title(f"🤖 AI 男友陪聊中… （已登入：{username}）")

    if "history" not in st.session_state:
        st.session_state.history = load_history_file()
        pm, em, el = load_memory()
        st.session_state.persistent_memory = pm
        st.session_state.ephemeral_memory  = em
        st.session_state.ephemeral_last    = el

    for msg in st.session_state.history:
        st.chat_message(msg["role"]).write(msg["content"])

    user_input = st.chat_input("你: ")
    if user_input:
        now = datetime.now()
        st.session_state.history.append({"role":"user","content":user_input,"time":now})
        st.chat_message("user").write(user_input)

        with st.spinner("AI 男友思考中…"):
            client = Groq(api_key=os.getenv("GROQ_API_KEY"))
            reply = generate_response(
                user_input,
                st.session_state.persistent_memory,
                st.session_state.ephemeral_memory,
                st.session_state.ephemeral_last,
                st.session_state.history,
                client
            )

        st.session_state.history.append({"role":"assistant","content":reply,"time":now})
        st.chat_message("assistant").write(reply)
        append_history(user_input, reply)

        st.session_state.persistent_memory = update_persistent(
            st.session_state.history,
            st.session_state.persistent_memory,
            client
        )
        st.session_state.ephemeral_memory = update_ephemeral(
            st.session_state.history,
            client
        )
        st.session_state.ephemeral_last = datetime.now()
        save_memory(st.session_state.persistent_memory,
                    st.session_state.ephemeral_memory)

if __name__ == "__main__":
    main()
