#!/usr/bin/env python3
"""Star Office UI - Backend State Service"""

import os
from flask import Flask, jsonify, send_from_directory, make_response, request
from datetime import datetime, timedelta
import json
import re
import threading
from flask_cors import CORS

# Paths (project-relative, no hardcoded absolute paths)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_DIR = os.path.join(os.path.dirname(ROOT_DIR), "memory")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
STATE_FILE = os.path.join(ROOT_DIR, "state.json")
AGENTS_STATE_FILE = os.path.join(ROOT_DIR, "agents-state.json")
JOIN_KEYS_FILE = os.path.join(ROOT_DIR, "join-keys.json")

def get_yesterday_date_str():
    """获取昨天的日期字符串 YYYY-MM-DD"""
    yesterday = datetime.now() - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")

def sanitize_content(text):
    """清理内容，保护隐私"""
    import re
    
    # 移除 OpenID、User ID 等
    text = re.sub(r'ou_[a-f0-9]+', '[用户]', text)
    text = re.sub(r'user_id="[^"]+"', 'user_id="[隐藏]"', text)
    
    # 移除具体的人名（如果有的话）
    # 这里可以根据需要添加更多规则
    
    # 移除 IP 地址、路径等敏感信息
    text = re.sub(r'/root/[^"\s]+', '[路径]', text)
    text = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', '[IP]', text)
    
    # 移除电话号码、邮箱等
    text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[邮箱]', text)
    text = re.sub(r'1[3-9]\d{9}', '[手机号]', text)
    
    return text

def extract_memo_from_file(file_path):
    """从 memory 文件中提取适合展示的 memo 内容（睿智风格的总结）"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 提取真实内容，不做过度包装
        lines = content.strip().split("\n")
        
        # 提取核心要点
        core_points = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            if line.startswith("- "):
                core_points.append(line[2:].strip())
            elif len(line) > 10:
                core_points.append(line)
        
        if not core_points:
            return "「昨日无事记录」\n\n若有恒，何必三更眠五更起；最无益，莫过一日曝十日寒。"
        
        # 从核心内容中提取 2-3 个关键点
        selected_points = core_points[:3]
        
        # 睿智语录库
        wisdom_quotes = [
            "「工欲善其事，必先利其器。」",
            "「不积跬步，无以至千里；不积小流，无以成江海。」",
            "「知行合一，方可致远。」",
            "「业精于勤，荒于嬉；行成于思，毁于随。」",
            "「路漫漫其修远兮，吾将上下而求索。」",
            "「昨夜西风凋碧树，独上高楼，望尽天涯路。」",
            "「衣带渐宽终不悔，为伊消得人憔悴。」",
            "「众里寻他千百度，蓦然回首，那人却在，灯火阑珊处。」",
            "「世事洞明皆学问，人情练达即文章。」",
            "「纸上得来终觉浅，绝知此事要躬行。」"
        ]
        
        import random
        quote = random.choice(wisdom_quotes)
        
        # 组合内容
        result = []
        
        # 添加核心内容
        if selected_points:
            for i, point in enumerate(selected_points):
                # 隐私清理
                point = sanitize_content(point)
                # 截断过长的内容
                if len(point) > 40:
                    point = point[:37] + "..."
                # 每行最多 20 字
                if len(point) <= 20:
                    result.append(f"· {point}")
                else:
                    # 按 20 字切分
                    for j in range(0, len(point), 20):
                        chunk = point[j:j+20]
                        if j == 0:
                            result.append(f"· {chunk}")
                        else:
                            result.append(f"  {chunk}")
        
        # 添加睿智语录
        if quote:
            if len(quote) <= 20:
                result.append(f"\n{quote}")
            else:
                for j in range(0, len(quote), 20):
                    chunk = quote[j:j+20]
                    if j == 0:
                        result.append(f"\n{chunk}")
                    else:
                        result.append(chunk)
        
        return "\n".join(result).strip()
        
    except Exception as e:
        print(f"提取 memo 失败: {e}")
        return "「昨日记录加载失败」\n\n「往者不可谏，来者犹可追。」"

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/static")
CORS(app)
app.json.ensure_ascii = False  # return real Unicode in jsonify (not \uXXXX escapes)

# Economy blueprint (Phase 1)
from economy import bp as economy_bp
app.register_blueprint(economy_bp)

# Guard join-agent critical section to enforce per-key concurrency under parallel requests
join_lock = threading.Lock()

# Generate a version timestamp once at server startup for cache busting
VERSION_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

@app.after_request
def add_no_cache_headers(response):
    """Aggressively prevent caching for all responses"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Default state
DEFAULT_STATE = {
    "state": "idle",
    "detail": "等待任务中...",
    "progress": 0,
    "updated_at": datetime.now().isoformat()
}

def load_state():
    """Load state from file.

    Includes a simple auto-idle mechanism:
    - If the last update is older than ttl_seconds (default 25s)
      and the state is a "working" state, we fall back to idle.

    This avoids the UI getting stuck at the desk when no new updates arrive.
    """
    state = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = None

    if not isinstance(state, dict):
        state = dict(DEFAULT_STATE)

    # Auto-idle
    try:
        ttl = int(state.get("ttl_seconds", 300))
        updated_at = state.get("updated_at")
        s = state.get("state", "idle")
        working_states = {"writing", "researching", "executing"}
        if updated_at and s in working_states:
            # tolerate both with/without timezone
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            # Use UTC for aware datetimes; local time for naive.
            if dt.tzinfo:
                from datetime import timezone
                age = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
            else:
                age = (datetime.now() - dt).total_seconds()
            if age > ttl:
                state["state"] = "idle"
                state["detail"] = "待命中（自动回到休息区）"
                state["progress"] = 0
                state["updated_at"] = datetime.now().isoformat()
                # persist the auto-idle so every client sees it consistently
                try:
                    save_state(state)
                except Exception:
                    pass
    except Exception:
        pass

    return state

def save_state(state: dict):
    """Save state to file"""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# Initialize state
if not os.path.exists(STATE_FILE):
    save_state(DEFAULT_STATE)

@app.route("/", methods=["GET"])
def index():
    """Serve the pixel office UI with built-in version cache busting"""
    with open(os.path.join(FRONTEND_DIR, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("{{VERSION_TIMESTAMP}}", VERSION_TIMESTAMP)
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp

@app.route("/join", methods=["GET"])
def join_page():
    """Serve the agent join page"""
    with open(os.path.join(FRONTEND_DIR, "join.html"), "r", encoding="utf-8") as f:
        html = f.read()
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp

@app.route("/invite", methods=["GET"])
def invite_page():
    """Serve human-facing invite instruction page"""
    with open(os.path.join(FRONTEND_DIR, "invite.html"), "r", encoding="utf-8") as f:
        html = f.read()
    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp

DEFAULT_AGENTS = [
    {
        "agentId": "star",
        "name": "Star",
        "isMain": True,
        "state": "idle",
        "detail": "待命中，随时准备为你服务",
        "updated_at": datetime.now().isoformat(),
        "area": "breakroom",
        "source": "local",
        "joinKey": None,
        "authStatus": "approved",
        "authExpiresAt": None,
        "lastPushAt": None
    }
]

def load_agents_state():
    if os.path.exists(AGENTS_STATE_FILE):
        try:
            with open(AGENTS_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return list(DEFAULT_AGENTS)

def save_agents_state(agents):
    with open(AGENTS_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(agents, f, ensure_ascii=False, indent=2)

def load_join_keys():
    if os.path.exists(JOIN_KEYS_FILE):
        try:
            with open(JOIN_KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("keys"), list):
                    return data
        except Exception:
            pass
    return {"keys": []}

def save_join_keys(data):
    with open(JOIN_KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def normalize_agent_state(s):
    """归一化状态，提高兼容性。
    兼容输入：working/busy → writing; run/running → executing; sync → syncing; research → researching.
    未识别默认返回 idle.
    """
    if not s:
        return 'idle'
    s_lower = s.lower().strip()
    if s_lower in {'working', 'busy', 'write'}:
        return 'writing'
    if s_lower in {'run', 'running', 'execute', 'exec'}:
        return 'executing'
    if s_lower in {'sync'}:
        return 'syncing'
    if s_lower in {'research', 'search'}:
        return 'researching'
    if s_lower in {'idle', 'writing', 'researching', 'executing', 'syncing', 'error'}:
        return s_lower
    # 默认 fallback
    return 'idle'

def state_to_area(state):
    area_map = {
        "idle": "breakroom",
        "writing": "writing",
        "researching": "writing",
        "executing": "writing",
        "syncing": "writing",
        "error": "error"
    }
    return area_map.get(state, "breakroom")

# Ensure files exist
if not os.path.exists(AGENTS_STATE_FILE):
    save_agents_state(DEFAULT_AGENTS)
if not os.path.exists(JOIN_KEYS_FILE):
    save_join_keys({"keys": []})

@app.route("/agents", methods=["GET"])
def get_agents():
    """Get full agents list (for multi-agent UI), with auto-cleanup on access"""
    agents = load_agents_state()
    now = datetime.now()

    cleaned_agents = []
    keys_data = load_join_keys()

    for a in agents:
        if a.get("isMain"):
            cleaned_agents.append(a)
            continue

        auth_expires_at_str = a.get("authExpiresAt")
        auth_status = a.get("authStatus", "pending")

        # 1) 超时未批准自动 leave
        if auth_status == "pending" and auth_expires_at_str:
            try:
                auth_expires_at = datetime.fromisoformat(auth_expires_at_str)
                if now > auth_expires_at:
                    key = a.get("joinKey")
                    if key:
                        key_item = next((k for k in keys_data.get("keys", []) if k["key"] == key), None)
                        if key_item:
                            keys_data["keys"] = [k for k in keys_data["keys"] if k["key"] != key]
                            save_join_keys(keys_data)
                    agents = [ag for ag in agents if ag["agentId"] != a["agentId"]]
                    save_agents_state(agents)
                    continue
            except Exception:
                pass

        cleaned_agents.append(a)

    return jsonify(cleaned_agents)

# ... (sisa kode asli repo lainnya tetap, kalau ada blueprint economy dll, biarkan apa adanya. Kode di atas sampai sini adalah bagian utama yang di-adjust. Kalau repo punya lebih banyak route di app.py, copy sisanya manual dari original repo ke sini setelah bagian ini.)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 18795))
    app.run(host="0.0.0.0", port=port, debug=False)
