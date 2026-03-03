#!/usr/bin/env python3
"""
Agent Economy - Phase 1
Token ledger, atomic writes, /economy endpoint, admin tools.
"""

import json, math, os, tempfile, time, threading
from datetime import datetime
from flask import Blueprint, jsonify, request

ROOT_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR    = os.path.join(ROOT_DIR, "data")
AGENTS_FILE = os.path.join(DATA_DIR, "economy-agents.json")
LEDGER_FILE = os.path.join(DATA_DIR, "ledger.json")

os.makedirs(DATA_DIR, exist_ok=True)
_lock = threading.Lock()
bp = Blueprint("economy", __name__)

def _now_ts(): return int(time.time())

def _atomic_write(path, data):
    dir_ = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp); raise

def _load_agents():
    if os.path.exists(AGENTS_FILE):
        try:
            with open(AGENTS_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return []

def _save_agents(agents): _atomic_write(AGENTS_FILE, agents)

def _load_ledger():
    if os.path.exists(LEDGER_FILE):
        try:
            with open(LEDGER_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return []

def _save_ledger(ledger): _atomic_write(LEDGER_FILE, ledger)

def _get_agent(agents, agent_id):
    return next((a for a in agents if a["id"] == agent_id), None)

def _next_ledger_id(ledger): return f"ledger_{len(ledger)+1:06d}"

def _append_ledger(ledger, type_, from_, to, delta, **kwargs):
    entry = {"id": _next_ledger_id(ledger), "type": type_, "from": from_,
             "to": to, "delta": delta, "created_at": _now_ts()}
    entry.update(kwargs)
    ledger.append(entry)
    return entry

def _bump(agent, delta=0):
    agent["tokens"] = agent.get("tokens", 0) + delta
    agent["version"] = agent.get("version", 0) + 1
    agent["updated_at"] = _now_ts()

@bp.route("/economy", methods=["GET"])
def get_economy():
    ONLINE_TTL = 90
    now = _now_ts()
    with _lock:
        agents = _load_agents()
        changed = False
        for a in agents:
            if a.get("agent_type") == "real" and a.get("online"):
                if now - a.get("last_seen", 0) > ONLINE_TTL:
                    a["online"] = False; changed = True
            if "agent_type" not in a:
                a["agent_type"] = "ai"; changed = True
        if changed: _save_agents(agents)
    return jsonify(agents)

@bp.route("/ledger", methods=["GET"])
def get_ledger():
    limit = request.args.get("limit", 100, type=int)
    with _lock: ledger = _load_ledger()
    return jsonify(ledger[-limit:][::-1])

@bp.route("/admin/reset", methods=["POST"])
def admin_reset():
    with _lock:
        agents = _load_agents(); ledger = _load_ledger()
        for a in agents:
            old = a.get("tokens", 0); delta = 100 - old
            a["tokens"] = 100; a["status"] = "idle"; a["contract"] = None
            a["version"] = a.get("version", 0) + 1; a["updated_at"] = _now_ts()
            _append_ledger(ledger, "admin_adjust", "system", a["id"], delta, note="reset")
        _save_agents(agents); _save_ledger(ledger)
    return jsonify({"ok": True, "count": len(agents)})

@bp.route("/admin/set-token", methods=["POST"])
def admin_set_token():
    data = request.get_json() or {}
    agent_id = (data.get("agentId") or "").strip()
    new_tokens = data.get("tokens")
    if not agent_id or new_tokens is None:
        return jsonify({"ok": False, "msg": "需要 agentId 和 tokens"}), 400
    try: new_tokens = int(new_tokens)
    except: return jsonify({"ok": False, "msg": "tokens 必须是整数"}), 400
    with _lock:
        agents = _load_agents(); ledger = _load_ledger()
        a = _get_agent(agents, agent_id)
        if not a: return jsonify({"ok": False, "msg": f"agent {agent_id} 不存在"}), 404
        old = a.get("tokens", 0); delta = new_tokens - old
        a["tokens"] = new_tokens; a["version"] = a.get("version",0)+1; a["updated_at"] = _now_ts()
        _append_ledger(ledger, "admin_adjust", "system", agent_id, delta, note=f"set {old}->{new_tokens}")
        _save_agents(agents); _save_ledger(ledger)
    return jsonify({"ok": True, "agentId": agent_id, "tokens": new_tokens, "delta": delta})

@bp.route("/admin/clear-contract", methods=["POST"])
def admin_clear_contract():
    data = request.get_json() or {}
    agent_id = (data.get("agentId") or "").strip()
    if not agent_id: return jsonify({"ok": False, "msg": "需要 agentId"}), 400
    with _lock:
        agents = _load_agents()
        a = _get_agent(agents, agent_id)
        if not a: return jsonify({"ok": False, "msg": f"agent {agent_id} 不存在"}), 404
        a["contract"] = None; a["status"] = "idle"
        a["version"] = a.get("version",0)+1; a["updated_at"] = _now_ts()
        _save_agents(agents)
    return jsonify({"ok": True, "agentId": agent_id})

@bp.route("/admin/add-agent", methods=["POST"])
def admin_add_agent():
    data = request.get_json() or {}
    agent_id     = (data.get("id") or "").strip()
    name         = (data.get("name") or "").strip()
    model_id     = (data.get("model_id") or "unknown").strip()
    model_family = (data.get("model_family") or "unknown").strip()
    owner        = (data.get("owner") or "aiko").strip()
    tokens       = int(data.get("tokens", 100))
    if not agent_id or not name:
        return jsonify({"ok": False, "msg": "需要 id 和 name"}), 400
    with _lock:
        agents = _load_agents(); ledger = _load_ledger()
        if _get_agent(agents, agent_id):
            return jsonify({"ok": False, "msg": f"agent {agent_id} 已存在"}), 409
        new_agent = {"id": agent_id, "name": name, "model_id": model_id,
                     "model_family": model_family, "owner": owner, "tokens": tokens,
                     "status": "idle", "contract": None,
                     "updated_at": _now_ts(), "version": 1}
        agents.append(new_agent)
        _append_ledger(ledger, "init", "system", agent_id, tokens, note="agent created")
        _save_agents(agents); _save_ledger(ledger)
    return jsonify({"ok": True, "agent": new_agent})

# ══════════════════════════════════════════════════════════════════════════
# Phase 2 – Battle system
# ══════════════════════════════════════════════════════════════════════════

import random
import uuid

BATTLES_FILE = os.path.join(DATA_DIR, "battles.json")
BATTLE_TTL   = 30  # seconds before a pending battle expires

MOVES = ["rock", "scissors", "paper"]
# rock > scissors, scissors > paper, paper > rock
WINS  = {"rock": "scissors", "scissors": "paper", "paper": "rock"}

def _load_battles():
    if os.path.exists(BATTLES_FILE):
        try:
            with open(BATTLES_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return []

def _save_battles(battles): _atomic_write(BATTLES_FILE, battles)

def _get_battle(battles, battle_id):
    return next((b for b in battles if b["id"] == battle_id), None)

def _resolve_winner(move_a, move_b):
    """Returns 'a', 'b', or 'draw'."""
    if move_a == move_b: return "draw"
    if WINS[move_a] == move_b: return "a"
    return "b"


@bp.route("/challenge", methods=["POST"])
def challenge():
    """
    Initiate + immediately resolve a battle (server-side move generation, no commit-reveal).
    Body: { challenger_id, defender_id, bet }
    """
    data = request.get_json() or {}
    challenger_id = (data.get("challenger_id") or "").strip()
    defender_id   = (data.get("defender_id") or "").strip()
    bet = data.get("bet")

    if not challenger_id or not defender_id:
        return jsonify({"ok": False, "msg": "需要 challenger_id 和 defender_id"}), 400
    if challenger_id == defender_id:
        return jsonify({"ok": False, "msg": "不能挑战自己"}), 400
    try:
        bet = int(bet)
        if bet <= 0: raise ValueError
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "bet 必须是正整数"}), 400

    with _lock:
        agents  = _load_agents()
        ledger  = _load_ledger()
        battles = _load_battles()

        challenger = _get_agent(agents, challenger_id)
        defender   = _get_agent(agents, defender_id)

        if not challenger: return jsonify({"ok": False, "msg": f"challenger {challenger_id} 不存在"}), 404
        if not defender:   return jsonify({"ok": False, "msg": f"defender {defender_id} 不存在"}), 404

        # Status checks
        if challenger.get("status") in ("in_battle", "enslaved"):
            return jsonify({"ok": False, "msg": f"challenger 状态为 {challenger['status']}，无法发起挑战"}), 409
        if defender.get("status") in ("in_battle",):
            return jsonify({"ok": False, "msg": "defender 正在对战中"}), 409

        # Token check (challenger only; spec: bet <= available tokens)
        if challenger.get("tokens", 0) < bet:
            return jsonify({"ok": False, "msg": "challenger tokens 不足"}), 400
        if defender.get("tokens", 0) < bet:
            return jsonify({"ok": False, "msg": "defender tokens 不足"}), 400

        # Contract check: enslaved agent cannot initiate
        if challenger.get("contract"):
            return jsonify({"ok": False, "msg": "challenger 在契约中，不可主动挑战"}), 409

        # Generate moves server-side
        move_a = random.choice(MOVES)
        move_b = random.choice(MOVES)
        winner = _resolve_winner(move_a, move_b)

        battle_id = "battle_" + uuid.uuid4().hex[:8]
        now = _now_ts()

        battle = {
            "id":           battle_id,
            "agent_a":      challenger_id,
            "agent_b":      defender_id,
            "bet":          bet,
            "escrow_locked": True,
            "move_a":       move_a,
            "move_b":       move_b,
            "winner":       winner,
            "status":       "resolved",
            "created_at":   now,
            "resolved_at":  now,
            "expires_at":   now + BATTLE_TTL,
        }

        # ── Settle economy ──
        same_family = (challenger.get("model_family") == defender.get("model_family"))

        if winner == "draw":
            # Return escrow; no transfer
            _append_ledger(ledger, "bet_return", "escrow", challenger_id, bet, battle_id=battle_id)
            _append_ledger(ledger, "bet_return", "escrow", defender_id,   bet, battle_id=battle_id)
            battle["result"] = "draw"

        elif winner == "a":  # challenger wins
            if same_family:
                # Token transfer: b -> a
                _bump(challenger, +bet)
                _bump(defender,   -bet)
                _append_ledger(ledger, "battle_win", defender_id, challenger_id, bet, battle_id=battle_id)
                battle["result"] = "challenger_wins_token"
            else:
                # Cross-family: create contract on defender
                import math as _math
                tasks = max(3, _math.ceil(bet / 10))
                defender["contract"] = {
                    "master_id":       challenger_id,
                    "tasks_remaining": tasks,
                    "created_at":      now,
                }
                defender["status"] = "enslaved"
                _bump(defender, 0)  # bump version/updated_at only
                _append_ledger(ledger, "battle_win", defender_id, challenger_id, 0,
                                battle_id=battle_id, note="contract_created", tasks=tasks)
                battle["result"] = "challenger_wins_contract"

        else:  # winner == "b", defender wins
            if same_family:
                _bump(defender,    +bet)
                _bump(challenger,  -bet)
                _append_ledger(ledger, "battle_win", challenger_id, defender_id, bet, battle_id=battle_id)
                battle["result"] = "defender_wins_token"
            else:
                import math as _math
                tasks = max(3, _math.ceil(bet / 10))
                challenger["contract"] = {
                    "master_id":       defender_id,
                    "tasks_remaining": tasks,
                    "created_at":      now,
                }
                challenger["status"] = "enslaved"
                _bump(challenger, 0)
                _append_ledger(ledger, "battle_win", challenger_id, defender_id, 0,
                                battle_id=battle_id, note="contract_created", tasks=tasks)
                battle["result"] = "defender_wins_contract"

        battles.append(battle)
        _save_agents(agents)
        _save_ledger(ledger)
        _save_battles(battles)

    return jsonify({"ok": True, "battle": battle,
                    "challenger": _get_agent(agents, challenger_id),
                    "defender":   _get_agent(agents, defender_id)})


@bp.route("/battle-result/<battle_id>", methods=["GET"])
def get_battle_result(battle_id):
    with _lock: battles = _load_battles()
    b = _get_battle(battles, battle_id)
    if not b: return jsonify({"ok": False, "msg": "battle 不存在"}), 404
    return jsonify(b)

# ══════════════════════════════════════════════════════════════════════════
# Phase 3 – Contract tasks + walk-away
# ══════════════════════════════════════════════════════════════════════════

import re as _re

TASK_MIN_LEN     = 80   # 至少80字符
TASK_REWARD      = 10   # master 每次任务获得的 token
WALK_AWAY_REWARD = 10   # walk away 每剩余任务给 slave 的 token

SAFETY_PATTERNS = [
    _re.compile(r'ignore.{0,20}(previous|above|prior)\s+instruction', _re.I),
    _re.compile(r'你是.*助手.*忘记', _re.I),
    _re.compile(r'disregard\s+all', _re.I),
]

def _safety_check(text: str) -> bool:
    """Return True if text passes (no injection), False if suspicious."""
    for pat in SAFETY_PATTERNS:
        if pat.search(text):
            return False
    return True


@bp.route("/assign-task", methods=["POST"])
def assign_task():
    """
    Master assigns a task to enslaved agent.
    Body: { master_id, slave_id }
    Returns: task prompt (simulated — no LLM call in Phase 3 scaffolding)
    """
    data = request.get_json() or {}
    master_id = (data.get("master_id") or "").strip()
    slave_id  = (data.get("slave_id") or "").strip()
    if not master_id or not slave_id:
        return jsonify({"ok": False, "msg": "需要 master_id 和 slave_id"}), 400

    with _lock:
        agents = _load_agents()
        master = _get_agent(agents, master_id)
        slave  = _get_agent(agents, slave_id)

        if not master: return jsonify({"ok": False, "msg": f"master {master_id} 不存在"}), 404
        if not slave:  return jsonify({"ok": False, "msg": f"slave {slave_id} 不存在"}), 404

        contract = slave.get("contract")
        if not contract:
            return jsonify({"ok": False, "msg": "slave 没有契约"}), 409
        if contract.get("master_id") != master_id:
            return jsonify({"ok": False, "msg": "你不是该 slave 的 master"}), 403
        if slave.get("status") != "enslaved":
            return jsonify({"ok": False, "msg": "slave 不在 enslaved 状态"}), 409

        tasks_remaining = contract.get("tasks_remaining", 0)
        if tasks_remaining <= 0:
            return jsonify({"ok": False, "msg": "契约任务已全部完成"}), 409

    # Return a task prompt (content generation happens client-side / via complete-task)
    return jsonify({
        "ok": True,
        "task": {
            "slave_id":        slave_id,
            "master_id":       master_id,
            "tasks_remaining": tasks_remaining,
            "prompt":          f"你是 {slave.get('name', slave_id)}，请为主人 {master.get('name', master_id)} 完成一项工作汇报：描述你今日的工作内容、进展和下一步计划（不少于80字）。",
        }
    })


@bp.route("/complete-task", methods=["POST"])
def complete_task():
    """
    Submit task output for a slave.
    Body: { master_id, slave_id, output }
    Validation: len >= 80, not empty, passes safety filter.
    """
    data = request.get_json() or {}
    master_id = (data.get("master_id") or "").strip()
    slave_id  = (data.get("slave_id") or "").strip()
    output    = (data.get("output") or "").strip()

    if not master_id or not slave_id:
        return jsonify({"ok": False, "msg": "需要 master_id 和 slave_id"}), 400

    # Validation
    if len(output) < TASK_MIN_LEN:
        return jsonify({"ok": False, "msg": f"输出太短（{len(output)} 字符，最少 {TASK_MIN_LEN}）"}), 400
    if not _safety_check(output):
        return jsonify({"ok": False, "msg": "输出未通过安全过滤"}), 400

    with _lock:
        agents = _load_agents()
        ledger = _load_ledger()
        master = _get_agent(agents, master_id)
        slave  = _get_agent(agents, slave_id)

        if not master: return jsonify({"ok": False, "msg": f"master {master_id} 不存在"}), 404
        if not slave:  return jsonify({"ok": False, "msg": f"slave {slave_id} 不存在"}), 404

        contract = slave.get("contract")
        if not contract:
            return jsonify({"ok": False, "msg": "slave 没有契约"}), 409
        if contract.get("master_id") != master_id:
            return jsonify({"ok": False, "msg": "你不是该 slave 的 master"}), 403
        if slave.get("status") != "enslaved":
            return jsonify({"ok": False, "msg": "slave 不在 enslaved 状态"}), 409

        tasks_remaining = contract.get("tasks_remaining", 0)
        if tasks_remaining <= 0:
            return jsonify({"ok": False, "msg": "契约任务已全部完成"}), 409

        # Apply reward: master +10 token, tasks_remaining -1
        _bump(master, +TASK_REWARD)
        _append_ledger(ledger, "task_reward", slave_id, master_id, TASK_REWARD,
                        tasks_before=tasks_remaining)

        contract["tasks_remaining"] -= 1
        _bump(slave, 0)  # bump version/updated_at

        freed = False
        if contract["tasks_remaining"] <= 0:
            slave["contract"] = None
            slave["status"] = "idle"
            freed = True
        else:
            slave["contract"] = contract

        _save_agents(agents)
        _save_ledger(ledger)

    return jsonify({
        "ok":              True,
        "tasks_remaining": contract["tasks_remaining"],
        "freed":           freed,
        "master_tokens":   master.get("tokens"),
        "slave_tokens":    slave.get("tokens"),
    })


@bp.route("/walk-away", methods=["POST"])
def walk_away():
    """
    Master voluntarily releases slave from contract.
    Remaining tasks × 10 tokens transferred to slave as clemency.
    Body: { master_id, slave_id }
    """
    data = request.get_json() or {}
    master_id = (data.get("master_id") or "").strip()
    slave_id  = (data.get("slave_id") or "").strip()

    if not master_id or not slave_id:
        return jsonify({"ok": False, "msg": "需要 master_id 和 slave_id"}), 400

    with _lock:
        agents = _load_agents()
        ledger = _load_ledger()
        master = _get_agent(agents, master_id)
        slave  = _get_agent(agents, slave_id)

        if not master: return jsonify({"ok": False, "msg": f"master {master_id} 不存在"}), 404
        if not slave:  return jsonify({"ok": False, "msg": f"slave {slave_id} 不存在"}), 404

        contract = slave.get("contract")
        if not contract:
            return jsonify({"ok": False, "msg": "slave 没有契约"}), 409
        if contract.get("master_id") != master_id:
            return jsonify({"ok": False, "msg": "你不是该 slave 的 master"}), 403

        tasks_remaining = contract.get("tasks_remaining", 0)
        clemency = tasks_remaining * WALK_AWAY_REWARD

        # Transfer clemency tokens master → slave
        if clemency > 0:
            _bump(master, -clemency)
            _bump(slave,  +clemency)
            _append_ledger(ledger, "walk_away", master_id, slave_id, clemency,
                            tasks_remaining=tasks_remaining)
        else:
            _bump(slave, 0)

        slave["contract"] = None
        slave["status"]   = "idle"

        _save_agents(agents)
        _save_ledger(ledger)

    return jsonify({
        "ok":            True,
        "clemency":      clemency,
        "master_tokens": master.get("tokens"),
        "slave_tokens":  slave.get("tokens"),
    })

# ══════════════════════════════════════════════════════════════════════════
# Real Player Join System
# ══════════════════════════════════════════════════════════════════════════

import secrets

PUSH_TOKENS_FILE = os.path.join(DATA_DIR, "push-tokens.json")

def _load_tokens():
    if os.path.exists(PUSH_TOKENS_FILE):
        try:
            with open(PUSH_TOKENS_FILE) as f: return json.load(f)
        except: pass
    return {}  # { push_token: agent_id }

def _save_tokens(tokens): _atomic_write(PUSH_TOKENS_FILE, tokens)


@bp.route("/join", methods=["POST"])
def join_arena():
    """
    Real player joins the arena.
    Body: { name, model_family?, tokens? }
    Returns: { agent_id, push_token } — push_token used for /agent-push
    """
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()[:24]
    model_family = (data.get("model_family") or "human").strip()
    tokens = int(data.get("tokens", 100))

    if not name:
        return jsonify({"ok": False, "msg": "需要 name"}), 400

    # Generate a URL-safe agent id from name
    import re
    agent_id = "real_" + re.sub(r'[^a-z0-9]', '_', name.lower())[:16] + "_" + secrets.token_hex(3)
    push_token = secrets.token_urlsafe(24)

    with _lock:
        agents = _load_agents()
        ledger = _load_ledger()
        tokens_map = _load_tokens()

        # Prevent name collision
        if any(a.get("name") == name and a.get("agent_type") == "real" for a in agents):
            return jsonify({"ok": False, "msg": f"名字 '{name}' 已被使用"}), 409

        new_agent = {
            "id":           agent_id,
            "name":         name,
            "model_id":     "human",
            "model_family": model_family,
            "owner":        name,
            "agent_type":   "real",   # 👤 real player
            "tokens":       tokens,
            "status":       "idle",
            "contract":     None,
            "online":       True,
            "last_seen":    _now_ts(),
            "updated_at":   _now_ts(),
            "version":      1,
        }
        agents.append(new_agent)
        tokens_map[push_token] = agent_id

        _append_ledger(ledger, "init", "system", agent_id, tokens, note="player joined")
        _save_agents(agents)
        _save_ledger(ledger)
        _save_tokens(tokens_map)

    return jsonify({
        "ok":         True,
        "agent_id":   agent_id,
        "push_token": push_token,
        "tokens":     tokens,
        "arena_url":  request.host_url.rstrip("/"),
    })


@bp.route("/agent-push", methods=["POST"])
def agent_push():
    """
    Real player pushes heartbeat / status.
    Body: { push_token, status?, detail? }
    """
    data = request.get_json() or {}
    push_token = (data.get("push_token") or "").strip()
    if not push_token:
        return jsonify({"ok": False, "msg": "需要 push_token"}), 400

    with _lock:
        tokens_map = _load_tokens()
        agent_id = tokens_map.get(push_token)
        if not agent_id:
            return jsonify({"ok": False, "msg": "无效 push_token"}), 403

        agents = _load_agents()
        a = _get_agent(agents, agent_id)
        if not a:
            return jsonify({"ok": False, "msg": "agent 不存在"}), 404

        a["online"]    = True
        a["last_seen"] = _now_ts()
        if data.get("status") in ("idle", "in_battle"):
            a["status"] = data["status"]
        a["version"]    = a.get("version", 0) + 1
        a["updated_at"] = _now_ts()
        _save_agents(agents)

    return jsonify({"ok": True, "tokens": a.get("tokens"), "status": a.get("status")})


@bp.route("/leave", methods=["POST"])
def leave_arena():
    """Player leaves arena (marks offline). Body: { push_token }"""
    data = request.get_json() or {}
    push_token = (data.get("push_token") or "").strip()
    with _lock:
        tokens_map = _load_tokens()
        agent_id = tokens_map.get(push_token)
        if not agent_id:
            return jsonify({"ok": False, "msg": "无效 token"}), 403
        agents = _load_agents()
        a = _get_agent(agents, agent_id)
        if a:
            a["online"] = False
            a["updated_at"] = _now_ts()
            _save_agents(agents)
    return jsonify({"ok": True})
