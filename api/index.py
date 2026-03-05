import os
from flask import Flask, jsonify, request, send_from_directory
from datetime import datetime, timedelta
import json
import re
import threading
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

STATE_FILE = os.path.join(DATA_DIR, "state.json")
AGENTS_STATE_FILE = os.path.join(DATA_DIR, "agents-state.json")
JOIN_KEYS_FILE = os.path.join(ROOT_DIR, "join-keys.json")

def get_yesterday_date_str():
    yesterday = datetime.now() - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")

def load_state():
    state = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = None

    if not isinstance(state, dict):
        state = {
            "state": "idle",
            "detail": "Waiting for tasks...",
            "progress": 0,
            "updated_at": datetime.now().isoformat()
        }

    try:
        ttl = int(state.get("ttl_seconds", 300))
        updated_at = state.get("updated_at")
        s = state.get("state", "idle")
        working_states = {"writing", "researching", "executing"}
        if updated_at and s in working_states:
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if dt.tzinfo:
                from datetime import timezone
                age = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
            else:
                age = (datetime.now() - dt).total_seconds()
            if age > ttl:
                state["state"] = "idle"
                state["detail"] = "Idle (auto reset)"
                state["progress"] = 0
                state["updated_at"] = datetime.now().isoformat()
                try:
                    with open(STATE_FILE, "w", encoding="utf-8") as f:
                        json.dump(state, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
    except Exception:
        pass

    return state

def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

DEFAULT_AGENTS = [
    {
        "agentId": "star",
        "name": "Star",
        "isMain": True,
        "state": "idle",
        "detail": "Ready to serve",
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

agents = load_agents_state()
join_keys = load_join_keys()

if not os.path.exists(AGENTS_STATE_FILE):
    save_agents_state(DEFAULT_AGENTS)
if not os.path.exists(JOIN_KEYS_FILE):
    save_join_keys({"keys": []})

state = load_state()
if not os.path.exists(STATE_FILE):
    save_state(state)

join_lock = threading.Lock()

VERSION_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/", methods=["GET"])
def index():
    return send_from_directory(ROOT_DIR, "index.html")

@app.route("/agents", methods=["GET"])
def get_agents():
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

@app.route("/join", methods=["POST"])
def join():
    data = request.json or {}
    name = data.get("name")
    agent_name = data.get("agent_name") or name
    persona = data.get("persona", "")
    api_key = data.get("api_key")
    avatar = data.get("avatar", "rabbit")

    if not name or not api_key:
        return jsonify({"error": "Missing required fields"}), 400

    agent_id = f"agent_{len(load_agents_state()) + 1}"
    push_token = f"token_{datetime.now().timestamp()}"

    new_agent = {
        "agentId": agent_id,
        "name": agent_name,
        "persona": persona,
        "avatar": avatar,
        "api_key": api_key,
        "push_token": push_token,
        "state": "idle",
        "detail": "Joined arena",
        "updated_at": datetime.now().isoformat(),
        "area": "arena",
        "source": "browser",
        "joinKey": None,
        "authStatus": "approved"
    }

    agents = load_agents_state()
    agents.append(new_agent)
    save_agents_state(agents)

    return jsonify({
        "push_token": push_token,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "tokens": 50
    })

@app.route("/challenge", methods=["POST"])
def challenge():
    data = request.json or {}
    challenger = data.get("challenger")
    opponent = data.get("opponent")
    if not challenger or not opponent:
        return jsonify({"error": "Missing params"}), 400

    battle_id = f"{challenger}_vs_{opponent}_{datetime.now().timestamp()}"
    return jsonify({"battle_id": battle_id, "status": "pending"})

@app.route("/heartbeat", methods=["POST"])
def heartbeat():
    data = request.json or {}
    push_token = data.get("push_token")
    if not push_token:
        return jsonify({"error": "Missing push_token"}), 400
    return jsonify({"status": "alive"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 18795))
    app.run(host="0.0.0.0", port=port, debug=False)
