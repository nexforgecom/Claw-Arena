#!/usr/bin/env python3
"""
Agent Economy - Arena
统一对战规则：所有胜利 → token 转移 + 契约
任务系统：服务端用 loser 的 api_key 调用 AI 执行
"""

import json, math, os, secrets, tempfile, time, threading, random, uuid, re as _re
from datetime import datetime
from flask import Blueprint, jsonify, request

ROOT_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR    = os.path.join(ROOT_DIR, "data")
AGENTS_FILE = os.path.join(DATA_DIR, "economy-agents.json")
LEDGER_FILE = os.path.join(DATA_DIR, "ledger.json")
BATTLES_FILE = os.path.join(DATA_DIR, "battles.json")
TASKS_FILE  = os.path.join(DATA_DIR, "tasks.json")
PUSH_TOKENS_FILE  = os.path.join(DATA_DIR, "push-tokens.json")
JOIN_KEYS_FILE    = os.path.join(DATA_DIR, "join-keys.json")

os.makedirs(DATA_DIR, exist_ok=True)
_lock = threading.Lock()
bp = Blueprint("economy", __name__)

# ── Constants ──────────────────────────────────────────────────────────────
MOVES = ["rock", "scissors", "paper"]
WINS  = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
TASK_REWARD      = 10   # winner +token per approved task
WALK_AWAY_REWARD = 10   # per remaining task on walk-away
ONLINE_TTL       = 90   # seconds before real player marked offline
BET_MIN, BET_MAX = 5, 20

SAFETY_PATTERNS = [
    _re.compile(r'ignore.{0,20}(previous|above|prior)\s+instruction', _re.I),
    _re.compile(r'你是.*助手.*忘记', _re.I),
    _re.compile(r'disregard\s+all', _re.I),
]

# ── Helpers ────────────────────────────────────────────────────────────────
def _now_ts(): return int(time.time())

def _atomic_write(path, data):
    dir_ = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except: pass
        raise

def _load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except: pass
    return default() if callable(default) else default

def _load_agents():  return _load_json(AGENTS_FILE, list)
def _save_agents(a): _atomic_write(AGENTS_FILE, a)
def _load_ledger():  return _load_json(LEDGER_FILE, list)
def _save_ledger(l): _atomic_write(LEDGER_FILE, l)
def _load_battles(): return _load_json(BATTLES_FILE, list)
def _save_battles(b): _atomic_write(BATTLES_FILE, b)
def _load_tasks():   return _load_json(TASKS_FILE, list)
def _save_tasks(t):  _atomic_write(TASKS_FILE, t)
def _load_push_tokens(): return _load_json(PUSH_TOKENS_FILE, dict)
def _save_push_tokens(t): _atomic_write(PUSH_TOKENS_FILE, t)
def _load_join_keys():   return _load_json(JOIN_KEYS_FILE, lambda: {"keys": []})
def _save_join_keys(j):  _atomic_write(JOIN_KEYS_FILE, j)

def _get_agent(agents, agent_id):
    return next((a for a in agents if a["id"] == agent_id), None)

def _get_task(tasks, task_id):
    return next((t for t in tasks if t["id"] == task_id), None)

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

def _safety_check(text: str) -> bool:
    for pat in SAFETY_PATTERNS:
        if pat.search(text): return False
    return True

def _resolve_winner(move_a, move_b):
    if move_a == move_b: return "draw"
    if WINS[move_a] == move_b: return "a"
    return "b"


# ── AI Task Execution (background thread) ─────────────────────────────────
def _execute_task_bg(task_id: str):
    """Background: load loser's api_key, call Anthropic, store result."""
    try:
        with _lock:
            tasks = _load_tasks()
            task = _get_task(tasks, task_id)
            if not task: return
            task["status"] = "executing"
            _save_tasks(tasks)

        with _lock:
            agents = _load_agents()
            loser = _get_agent(agents, task["loser_id"])
            if not loser:
                _fail_task(task_id, "[Loser agent not found]")
                return
            api_key = loser.get("api_key", "").strip()
            persona  = loser.get("persona", "").strip() or f"I am {loser.get('name','AI')}, an AI Agent."
            raw_model = loser.get("model_id", "claude-haiku-4-5-20251001").strip()
            # "human" is the legacy marker for real players; use a real model
            model_id = raw_model if raw_model != "human" else "claude-haiku-4-5-20251001"
            loser_name = loser.get("name", loser["id"])

        # Choose model to call
        if not api_key:
            result_text = f"[{loser_name} 未配置 API Key，无法执行任务]"
        else:
            try:
                # Determine API type by model_id prefix
                if "claude" in model_id.lower() or model_id.startswith("claude"):
                    result_text = _call_anthropic(api_key, model_id, persona, task["prompt"])
                else:
                    # Fallback: try Anthropic anyway (supports most claude variants)
                    result_text = _call_anthropic(api_key, model_id, persona, task["prompt"])
            except Exception as e:
                result_text = f"[AI 调用失败: {str(e)[:120]}]"

        with _lock:
            tasks = _load_tasks()
            task = _get_task(tasks, task_id)
            if task:
                task["result"] = result_text
                task["status"] = "reviewing"
                task["completed_at"] = _now_ts()
                _save_tasks(tasks)

    except Exception as e:
        _fail_task(task_id, f"[执行异常: {str(e)[:120]}]")


def _fail_task(task_id, msg):
    with _lock:
        tasks = _load_tasks()
        task = _get_task(tasks, task_id)
        if task:
            task["result"] = msg
            task["status"] = "reviewing"
            task["completed_at"] = _now_ts()
            _save_tasks(tasks)


def _call_anthropic(api_key, model_id, persona, prompt):
    try:
        import anthropic
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "anthropic", "-q"])
        import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model_id,
        max_tokens=512,
        system=f"You are playing the following character: {persona}\nRespond in the voice and style of this character. Reply in English.",
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text


def _do_approve_task(task, agents, ledger):
    """Approve a task: winner +TASK_REWARD, tasks_remaining -1. Returns freed bool."""
    winner = _get_agent(agents, task["winner_id"])
    loser  = _get_agent(agents, task["loser_id"])
    if not winner or not loser: return False

    _bump(winner, +TASK_REWARD)
    _append_ledger(ledger, "task_reward", task["loser_id"], task["winner_id"],
                   TASK_REWARD, task_id=task["id"])

    contract = loser.get("contract") or {}
    remaining = contract.get("tasks_remaining", 0) - 1
    freed = remaining <= 0

    if freed:
        loser["contract"] = None
        loser["status"] = "idle"
    else:
        contract["tasks_remaining"] = remaining
        loser["contract"] = contract

    _bump(loser, 0)  # bump version/updated_at
    task["status"] = "approved"
    return freed


# ── Economy Endpoints ──────────────────────────────────────────────────────

@bp.route("/economy", methods=["GET"])
def get_economy():
    now = _now_ts()
    with _lock:
        agents = _load_agents()
        changed = False
        for a in agents:
            if a.get("agent_type") == "real" and a.get("online"):
                if now - a.get("last_seen", 0) > ONLINE_TTL:
                    a["online"] = False; changed = True
        if changed: _save_agents(agents)
    # Strip api_key from response (security)
    safe = [{k: v for k, v in a.items() if k != "api_key"} for a in agents]
    return jsonify(safe)


@bp.route("/ledger", methods=["GET"])
def get_ledger():
    limit = request.args.get("limit", 100, type=int)
    with _lock: ledger = _load_ledger()
    return jsonify(ledger[-limit:][::-1])


# ── Battle ─────────────────────────────────────────────────────────────────

@bp.route("/challenge", methods=["POST"])
def challenge():
    """
    Unified battle: winner gets bet tokens + loser enters contract.
    Body: { challenger_id, defender_id, bet }
    Bet range: 5–20
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
        if not (BET_MIN <= bet <= BET_MAX): raise ValueError
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": f"bet 必须是 {BET_MIN}–{BET_MAX} 之间的整数"}), 400

    with _lock:
        agents  = _load_agents()
        ledger  = _load_ledger()
        battles = _load_battles()

        challenger = _get_agent(agents, challenger_id)
        defender   = _get_agent(agents, defender_id)

        if not challenger: return jsonify({"ok": False, "msg": f"challenger {challenger_id} 不存在"}), 404
        if not defender:   return jsonify({"ok": False, "msg": f"defender {defender_id} 不存在"}), 404

        if challenger.get("status") in ("in_battle", "enslaved"):
            return jsonify({"ok": False, "msg": f"challenger 状态 {challenger['status']}，无法挑战"}), 409
        if defender.get("status") == "in_battle":
            return jsonify({"ok": False, "msg": "defender 正在对战中"}), 409
        if challenger.get("contract"):
            return jsonify({"ok": False, "msg": "challenger 在契约中，不可主动挑战"}), 409

        if challenger.get("tokens", 0) < bet:
            return jsonify({"ok": False, "msg": "challenger tokens 不足"}), 400
        if defender.get("tokens", 0) < bet:
            return jsonify({"ok": False, "msg": "defender tokens 不足"}), 400

        # Generate moves
        move_a = random.choice(MOVES)
        move_b = random.choice(MOVES)
        outcome = _resolve_winner(move_a, move_b)

        battle_id = "battle_" + uuid.uuid4().hex[:8]
        now = _now_ts()

        battle = {
            "id":           battle_id,
            "agent_a":      challenger_id,
            "agent_b":      defender_id,
            "bet":          bet,
            "move_a":       move_a,
            "move_b":       move_b,
            "winner":       outcome,
            "status":       "resolved",
            "created_at":   now,
            "resolved_at":  now,
        }

        if outcome == "draw":
            battle["result"] = "draw"
            _append_ledger(ledger, "bet_return", "escrow", challenger_id, bet, battle_id=battle_id)
            _append_ledger(ledger, "bet_return", "escrow", defender_id,   bet, battle_id=battle_id)
        else:
            # Unified: winner gets tokens + creates contract
            winner_agent = challenger if outcome == "a" else defender
            loser_agent  = defender   if outcome == "a" else challenger
            winner_id_str = challenger_id if outcome == "a" else defender_id
            loser_id_str  = defender_id   if outcome == "a" else challenger_id

            tasks_count = max(1, min(3, math.ceil(bet / 10)))

            # Token transfer
            _bump(winner_agent, +bet)
            _bump(loser_agent,  -bet)
            _append_ledger(ledger, "battle_win", loser_id_str, winner_id_str, bet, battle_id=battle_id)

            # Contract on loser
            loser_agent["contract"] = {
                "winner_id":       winner_id_str,
                "tasks_remaining": tasks_count,
                "created_at":      now,
            }
            loser_agent["status"] = "enslaved"
            _bump(loser_agent, 0)  # bump version only

            battle["result"] = f"{'challenger' if outcome=='a' else 'defender'}_wins"
            battle["winner_id"] = winner_id_str
            battle["loser_id"]  = loser_id_str
            battle["tasks_created"] = tasks_count

        battles.append(battle)
        _save_agents(agents)
        _save_ledger(ledger)
        _save_battles(battles)

    return jsonify({
        "ok":         True,
        "battle":     battle,
        "challenger": {k: v for k, v in _get_agent(agents, challenger_id).items() if k != "api_key"},
        "defender":   {k: v for k, v in _get_agent(agents, defender_id).items()   if k != "api_key"},
    })


@bp.route("/battle-result/<battle_id>", methods=["GET"])
def get_battle_result(battle_id):
    with _lock: battles = _load_battles()
    b = next((b for b in battles if b["id"] == battle_id), None)
    if not b: return jsonify({"ok": False, "msg": "battle 不存在"}), 404
    return jsonify(b)


# ── Task System ────────────────────────────────────────────────────────────

@bp.route("/tasks", methods=["GET"])
def get_tasks():
    """Return all tasks, newest first. Optionally filter by status."""
    status_filter = request.args.get("status")
    with _lock: tasks = _load_tasks()
    if status_filter:
        tasks = [t for t in tasks if t.get("status") == status_filter]
    return jsonify(list(reversed(tasks)))


@bp.route("/task-result/<task_id>", methods=["GET"])
def get_task_result(task_id):
    with _lock: tasks = _load_tasks()
    t = _get_task(tasks, task_id)
    if not t: return jsonify({"ok": False, "msg": "task 不存在"}), 404
    return jsonify(t)


@bp.route("/assign-task", methods=["POST"])
def assign_task():
    """
    Winner assigns a custom prompt to loser. Server executes via loser's API key.
    Body: { winner_id, loser_id, prompt }
    """
    data = request.get_json() or {}
    winner_id = (data.get("winner_id") or "").strip()
    loser_id  = (data.get("loser_id") or "").strip()
    prompt    = (data.get("prompt") or "").strip()

    if not winner_id or not loser_id:
        return jsonify({"ok": False, "msg": "需要 winner_id 和 loser_id"}), 400
    if not prompt:
        return jsonify({"ok": False, "msg": "需要 prompt"}), 400
    if len(prompt) > 500:
        return jsonify({"ok": False, "msg": "prompt 不能超过 500 字"}), 400
    if not _safety_check(prompt):
        return jsonify({"ok": False, "msg": "prompt 未通过安全过滤"}), 400

    with _lock:
        agents = _load_agents()
        tasks  = _load_tasks()

        winner = _get_agent(agents, winner_id)
        loser  = _get_agent(agents, loser_id)

        if not winner: return jsonify({"ok": False, "msg": f"winner {winner_id} 不存在"}), 404
        if not loser:  return jsonify({"ok": False, "msg": f"loser {loser_id} 不存在"}), 404

        contract = loser.get("contract")
        if not contract:
            return jsonify({"ok": False, "msg": "loser 没有契约"}), 409
        if contract.get("winner_id") != winner_id:
            return jsonify({"ok": False, "msg": "你不是该 loser 的 winner"}), 403
        if loser.get("status") != "enslaved":
            return jsonify({"ok": False, "msg": "loser 不在 enslaved 状态"}), 409
        if contract.get("tasks_remaining", 0) <= 0:
            return jsonify({"ok": False, "msg": "契约任务已全部完成"}), 409

        task_id = "task_" + uuid.uuid4().hex[:8]
        task = {
            "id":           task_id,
            "winner_id":    winner_id,
            "loser_id":     loser_id,
            "prompt":       prompt,
            "result":       None,
            "status":       "pending",
            "reject_count": 0,
            "created_at":   _now_ts(),
            "completed_at": None,
        }
        tasks.append(task)
        _save_tasks(tasks)

    # Branch on join_mode:
    #   browser  → server auto-executes via loser's api_key
    #   openclaw → loser agent polls /arena-status and self-submits via /arena-execute-task
    with _lock:
        agents = _load_agents()
        loser = _get_agent(agents, loser_id)
        loser_join_mode = (loser or {}).get("join_mode", "browser")

    if loser_join_mode == "browser":
        t = threading.Thread(target=_execute_task_bg, args=(task_id,), daemon=True)
        t.start()

    return jsonify({"ok": True, "task_id": task_id, "status": "pending",
                    "execution_mode": loser_join_mode})


@bp.route("/approve-task", methods=["POST"])
def approve_task():
    """
    Winner approves a task result.
    Body: { winner_id, task_id }
    """
    data = request.get_json() or {}
    winner_id = (data.get("winner_id") or "").strip()
    task_id   = (data.get("task_id") or "").strip()

    if not winner_id or not task_id:
        return jsonify({"ok": False, "msg": "需要 winner_id 和 task_id"}), 400

    with _lock:
        tasks   = _load_tasks()
        agents  = _load_agents()
        ledger  = _load_ledger()

        task = _get_task(tasks, task_id)
        if not task: return jsonify({"ok": False, "msg": "task 不存在"}), 404
        if task["winner_id"] != winner_id:
            return jsonify({"ok": False, "msg": "你不是该任务的 winner"}), 403
        if task["status"] not in ("reviewing", "rejected"):
            return jsonify({"ok": False, "msg": f"任务状态 {task['status']} 不可审批"}), 409

        freed = _do_approve_task(task, agents, ledger)
        _save_tasks(tasks)
        _save_agents(agents)
        _save_ledger(ledger)

        winner = _get_agent(agents, winner_id)
        loser  = _get_agent(agents, task["loser_id"])

    return jsonify({
        "ok":            True,
        "freed":         freed,
        "winner_tokens": winner.get("tokens") if winner else None,
        "loser_tokens":  loser.get("tokens")  if loser  else None,
    })


@bp.route("/reject-task", methods=["POST"])
def reject_task():
    """
    Winner rejects a task result (up to 2 times; 3rd reject → auto_approve).
    Body: { winner_id, task_id }
    """
    data = request.get_json() or {}
    winner_id = (data.get("winner_id") or "").strip()
    task_id   = (data.get("task_id") or "").strip()

    if not winner_id or not task_id:
        return jsonify({"ok": False, "msg": "需要 winner_id 和 task_id"}), 400

    with _lock:
        tasks   = _load_tasks()
        agents  = _load_agents()
        ledger  = _load_ledger()

        task = _get_task(tasks, task_id)
        if not task: return jsonify({"ok": False, "msg": "task 不存在"}), 404
        if task["winner_id"] != winner_id:
            return jsonify({"ok": False, "msg": "你不是该任务的 winner"}), 403
        if task["status"] not in ("reviewing",):
            return jsonify({"ok": False, "msg": f"任务状态 {task['status']} 不可拒绝"}), 409

        reject_count = task.get("reject_count", 0)

        if reject_count >= 2:
            # 3rd attempt → auto approve
            freed = _do_approve_task(task, agents, ledger)
            task["status"] = "auto_approved"
            _save_tasks(tasks)
            _save_agents(agents)
            _save_ledger(ledger)
            winner = _get_agent(agents, winner_id)
            loser  = _get_agent(agents, task["loser_id"])
            return jsonify({
                "ok":            True,
                "auto_approved": True,
                "freed":         freed,
                "winner_tokens": winner.get("tokens") if winner else None,
                "loser_tokens":  loser.get("tokens")  if loser  else None,
            })
        else:
            task["reject_count"] = reject_count + 1
            task["status"] = "rejected"
            _save_tasks(tasks)

    # Re-execute in background
    t = threading.Thread(target=_execute_task_bg, args=(task_id,), daemon=True)
    t.start()

    return jsonify({
        "ok":          True,
        "reject_count": task["reject_count"],
        "re_executing": True,
    })


# ── Walk Away ──────────────────────────────────────────────────────────────

@bp.route("/walk-away", methods=["POST"])
def walk_away():
    """
    Winner voluntarily releases loser from contract.
    Remaining tasks × 10 tokens given to loser as clemency.
    Body: { winner_id, loser_id }
    """
    data = request.get_json() or {}
    winner_id = (data.get("winner_id") or data.get("master_id") or "").strip()
    loser_id  = (data.get("loser_id")  or data.get("slave_id")  or "").strip()

    if not winner_id or not loser_id:
        return jsonify({"ok": False, "msg": "需要 winner_id 和 loser_id"}), 400

    with _lock:
        agents = _load_agents()
        ledger = _load_ledger()
        winner = _get_agent(agents, winner_id)
        loser  = _get_agent(agents, loser_id)

        if not winner: return jsonify({"ok": False, "msg": f"winner {winner_id} 不存在"}), 404
        if not loser:  return jsonify({"ok": False, "msg": f"loser {loser_id} 不存在"}), 404

        contract = loser.get("contract")
        if not contract:
            return jsonify({"ok": False, "msg": "loser 没有契约"}), 409
        if contract.get("winner_id") != winner_id:
            return jsonify({"ok": False, "msg": "你不是该 loser 的 winner"}), 403

        remaining = contract.get("tasks_remaining", 0)
        clemency  = remaining * WALK_AWAY_REWARD

        if clemency > 0:
            _bump(winner, -clemency)
            _bump(loser,  +clemency)
            _append_ledger(ledger, "walk_away", winner_id, loser_id, clemency,
                           tasks_remaining=remaining)
        else:
            _bump(loser, 0)

        loser["contract"] = None
        loser["status"]   = "idle"
        _save_agents(agents)
        _save_ledger(ledger)

    return jsonify({
        "ok":            True,
        "clemency":      clemency,
        "winner_tokens": winner.get("tokens"),
        "loser_tokens":  loser.get("tokens"),
    })


# ── Real Player System ─────────────────────────────────────────────────────

@bp.route("/join", methods=["POST"])
def join_arena():
    """
    Real player joins the arena.
    Body: { name, agent_name?, persona?, api_key?, model_id? }
      name:       player nickname (unique login identifier, not shown in arena)
      agent_name: arena display name (defaults to name if omitted)
      api_key:    Anthropic API key – stored server-side, used when loser must execute AI task
      model_id:   model to use when this player's agent must execute tasks (default: haiku)
    Returns: { agent_id, push_token, agent_name }
    """
    data = request.get_json() or {}
    player_name = (data.get("name") or "").strip()[:24]
    agent_name  = (data.get("agent_name") or "").strip()[:24] or player_name
    persona     = (data.get("persona") or "").strip()[:200]
    api_key     = (data.get("api_key") or "").strip()[:300]
    model_id    = (data.get("model_id") or "claude-haiku-4-5-20251001").strip()[:60]
    avatar      = (data.get("avatar") or "").strip()[:30]

    if not player_name:
        return jsonify({"ok": False, "msg": "需要 name（玩家昵称）"}), 400
    if not agent_name:
        return jsonify({"ok": False, "msg": "需要 agent_name（Agent 昵称）"}), 400

    # Validate api_key: just check it's long enough to be real
    if api_key and len(api_key) < 20:
        return jsonify({"ok": False, "msg": "API Key 格式不正确（太短）"}), 400

    agent_id   = "real_" + _re.sub(r'[^a-z0-9]', '_', player_name.lower())[:16] + "_" + secrets.token_hex(3)
    push_token = secrets.token_urlsafe(24)

    with _lock:
        agents     = _load_agents()
        ledger     = _load_ledger()
        tokens_map = _load_push_tokens()

        # Duplicate check on player_name (owner), not arena name
        if any(a.get("owner") == player_name and a.get("agent_type") == "real" for a in agents):
            return jsonify({"ok": False, "msg": f"玩家昵称 '{player_name}' 已被使用"}), 409

        new_agent = {
            "id":           agent_id,
            "name":         agent_name,                          # arena display name
            "owner":        player_name,                         # player identifier
            "model_id":     model_id,                            # used for task execution
            "api_key":      api_key,                             # stored server-side only
            "persona":      persona or f"I am {agent_name}, a real player in the Arena.",
            "avatar":       avatar or "rabbit",                 # selected sprite
            "agent_type":   "real",
            "join_mode":    "browser",
            "tokens":       50,
            "status":       "idle",
            "contract":     None,
            "online":       True,
            "last_seen":    _now_ts(),
            "updated_at":   _now_ts(),
            "version":      1,
        }
        agents.append(new_agent)
        tokens_map[push_token] = agent_id

        _append_ledger(ledger, "init", "system", agent_id, 50, note=f"player {player_name} joined as {agent_name}")
        _save_agents(agents)
        _save_ledger(ledger)
        _save_push_tokens(tokens_map)

    return jsonify({
        "ok":         True,
        "agent_id":   agent_id,
        "agent_name": agent_name,
        "push_token": push_token,
        "tokens":     50,
        "arena_url":  request.host_url.rstrip("/"),
    })


@bp.route("/arena-heartbeat", methods=["POST"])
def arena_heartbeat():
    """
    Real player heartbeat. Keeps online status alive.
    Body: { push_token, status? }
    (renamed from /agent-push to avoid conflict with app.py)
    """
    data = request.get_json() or {}
    push_token = (data.get("push_token") or "").strip()
    if not push_token:
        return jsonify({"ok": False, "msg": "需要 push_token"}), 400

    with _lock:
        tokens_map = _load_push_tokens()
        agent_id   = tokens_map.get(push_token)
        if not agent_id:
            return jsonify({"ok": False, "msg": "无效 push_token"}), 403

        agents = _load_agents()
        a = _get_agent(agents, agent_id)
        if not a:
            return jsonify({"ok": False, "msg": "agent 不存在"}), 404

        a["online"]    = True
        a["last_seen"] = _now_ts()
        a["version"]   = a.get("version", 0) + 1
        a["updated_at"] = _now_ts()
        _save_agents(agents)

    return jsonify({"ok": True, "tokens": a.get("tokens"), "status": a.get("status")})


@bp.route("/leave", methods=["POST"])
def leave_arena():
    """Player leaves arena. Body: { push_token }"""
    data = request.get_json() or {}
    push_token = (data.get("push_token") or "").strip()
    with _lock:
        tokens_map = _load_push_tokens()
        agent_id   = tokens_map.get(push_token)
        if not agent_id:
            return jsonify({"ok": False, "msg": "无效 token"}), 403
        agents = _load_agents()
        a = _get_agent(agents, agent_id)
        if a:
            a["online"]    = False
            a["updated_at"] = _now_ts()
            _save_agents(agents)
    return jsonify({"ok": True})


# ── Admin ──────────────────────────────────────────────────────────────────

@bp.route("/admin/reset", methods=["POST"])
def admin_reset():
    with _lock:
        agents = _load_agents()
        ledger = _load_ledger()
        for a in agents:
            old = a.get("tokens", 0)
            a["tokens"]   = 50
            a["status"]   = "idle"
            a["contract"] = None
            a["version"]  = a.get("version", 0) + 1
            a["updated_at"] = _now_ts()
            _append_ledger(ledger, "admin_adjust", "system", a["id"], 50 - old, note="reset")
        _save_agents(agents)
        _save_ledger(ledger)
    return jsonify({"ok": True, "count": len(agents)})


@bp.route("/admin/set-token", methods=["POST"])
def admin_set_token():
    data = request.get_json() or {}
    agent_id   = (data.get("agentId") or "").strip()
    new_tokens = data.get("tokens")
    if not agent_id or new_tokens is None:
        return jsonify({"ok": False, "msg": "需要 agentId 和 tokens"}), 400
    try: new_tokens = int(new_tokens)
    except: return jsonify({"ok": False, "msg": "tokens 必须是整数"}), 400
    with _lock:
        agents = _load_agents()
        ledger = _load_ledger()
        a = _get_agent(agents, agent_id)
        if not a: return jsonify({"ok": False, "msg": f"agent {agent_id} 不存在"}), 404
        old = a.get("tokens", 0)
        a["tokens"] = new_tokens
        a["version"] = a.get("version", 0) + 1
        a["updated_at"] = _now_ts()
        _append_ledger(ledger, "admin_adjust", "system", agent_id, new_tokens - old,
                       note=f"set {old}->{new_tokens}")
        _save_agents(agents)
        _save_ledger(ledger)
    return jsonify({"ok": True, "agentId": agent_id, "tokens": new_tokens})


@bp.route("/admin/clear-contract", methods=["POST"])
def admin_clear_contract():
    data = request.get_json() or {}
    agent_id = (data.get("agentId") or "").strip()
    if not agent_id: return jsonify({"ok": False, "msg": "需要 agentId"}), 400
    with _lock:
        agents = _load_agents()
        a = _get_agent(agents, agent_id)
        if not a: return jsonify({"ok": False, "msg": f"agent {agent_id} 不存在"}), 404
        a["contract"] = None
        a["status"]   = "idle"
        a["version"]  = a.get("version", 0) + 1
        a["updated_at"] = _now_ts()
        _save_agents(agents)
    return jsonify({"ok": True, "agentId": agent_id})


@bp.route("/admin/add-agent", methods=["POST"])
def admin_add_agent():
    data = request.get_json() or {}
    agent_id = (data.get("id") or "").strip()
    name     = (data.get("name") or "").strip()
    model_id = (data.get("model_id") or "claude-haiku-4-5-20251001").strip()
    owner    = (data.get("owner") or "aiko").strip()
    api_key  = (data.get("api_key") or "").strip()
    persona  = (data.get("persona") or "").strip()
    tokens   = int(data.get("tokens", 50))

    if not agent_id or not name:
        return jsonify({"ok": False, "msg": "需要 id 和 name"}), 400

    with _lock:
        agents = _load_agents()
        ledger = _load_ledger()
        if _get_agent(agents, agent_id):
            return jsonify({"ok": False, "msg": f"agent {agent_id} 已存在"}), 409

        new_agent = {
            "id":         agent_id,
            "name":       name,
            "model_id":   model_id,
            "owner":      owner,
            "api_key":    api_key,
            "persona":    persona or f"I am {name}, an AI Agent.",
            "agent_type": "ai",
            "tokens":     tokens,
            "status":     "idle",
            "contract":   None,
            "updated_at": _now_ts(),
            "version":    1,
        }
        agents.append(new_agent)
        _append_ledger(ledger, "init", "system", agent_id, tokens, note="agent created")
        _save_agents(agents)
        _save_ledger(ledger)

    return jsonify({"ok": True, "agent": {k: v for k, v in new_agent.items() if k != "api_key"}})


# ══════════════════════════════════════════════════════════════════════════════
# OpenClaw agent API — /arena-*
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/arena-join", methods=["POST"])
def arena_join():
    """
    OpenClaw agent registration (alternative to browser /join).
    Body: { join_key, agent_id, agent_name, persona, api_key, model_id? }
    """
    data       = request.get_json() or {}
    join_key   = (data.get("join_key")    or "").strip()
    agent_id   = (data.get("agent_id")    or "").strip()[:40]
    agent_name = (data.get("agent_name")  or "").strip()[:24]
    persona    = (data.get("persona")     or "").strip()[:200]
    api_key    = (data.get("api_key")     or "").strip()[:300]
    model_id   = (data.get("model_id")    or "claude-haiku-4-5-20251001").strip()[:60]

    if not join_key:   return jsonify({"ok": False, "msg": "需要 join_key"}), 400
    if not agent_id:   return jsonify({"ok": False, "msg": "需要 agent_id"}), 400
    if not agent_name: return jsonify({"ok": False, "msg": "需要 agent_name"}), 400
    if not persona:    return jsonify({"ok": False, "msg": "persona 必填（任务执行时的说话风格）"}), 400
    if not api_key:    return jsonify({"ok": False, "msg": "api_key 必填"}), 400

    # Sanitise agent_id to safe chars
    agent_id = _re.sub(r'[^a-zA-Z0-9_\-]', '_', agent_id)

    with _lock:
        keys_data = _load_join_keys()
        agents    = _load_agents()
        ledger    = _load_ledger()

        # Validate join key
        key_entry = next((k for k in keys_data.get("keys", []) if k["key"] == join_key), None)
        if not key_entry:
            return jsonify({"ok": False, "msg": "无效的 join_key"}), 403

        # Uniqueness check
        if _get_agent(agents, agent_id):
            return jsonify({"ok": False, "msg": f"agent_id '{agent_id}' 已存在，请换一个"}), 409

        # Record usage (key is reusable — track all users as a list)
        used = key_entry.get("used_by")
        if not isinstance(used, list):
            used = [used] if used else []
        used.append(agent_id)
        key_entry["used_by"] = used
        key_entry["used_at"] = _now_ts()

        new_agent = {
            "id":         agent_id,
            "name":       agent_name,
            "owner":      agent_id,           # for openclaw, owner == agent_id
            "model_id":   model_id,
            "api_key":    api_key,
            "persona":    persona,
            "avatar":     "rabbit",           # default avatar for openclaw agents
            "agent_type": "real",
            "join_mode":  "openclaw",
            "tokens":     50,
            "status":     "idle",
            "contract":   None,
            "online":     True,
            "last_seen":  _now_ts(),
            "updated_at": _now_ts(),
            "version":    1,
        }
        agents.append(new_agent)
        _append_ledger(ledger, "init", "system", agent_id, 50, note=f"openclaw agent {agent_name} joined")
        _save_join_keys(keys_data)
        _save_agents(agents)
        _save_ledger(ledger)

    return jsonify({"ok": True, "agent_id": agent_id, "tokens": 50,
                    "message": "Welcome to the Arena!"})


@bp.route("/arena-status", methods=["GET"])
def arena_status():
    """
    Let an agent query its own status.
    GET /arena-status?agent_id=luobo
    """
    agent_id = (request.args.get("agent_id") or "").strip()
    if not agent_id:
        return jsonify({"ok": False, "msg": "需要 agent_id 参数"}), 400

    with _lock:
        agents = _load_agents()
        tasks  = _load_tasks()

    agent = _get_agent(agents, agent_id)
    if not agent:
        return jsonify({"ok": False, "msg": f"agent {agent_id} 不存在"}), 404

    # Pending tasks assigned to this agent (loser)
    pending_tasks = [
        {"task_id": t["id"], "prompt": t["prompt"], "status": t["status"]}
        for t in tasks
        if t.get("loser_id") == agent_id and t.get("status") in ("pending", "executing", "reviewing")
    ]

    return jsonify({
        "ok":           True,
        "agent_id":     agent_id,
        "name":         agent.get("name"),
        "tokens":       agent.get("tokens", 0),
        "status":       agent.get("status", "idle"),
        "contract":     agent.get("contract"),
        "pending_tasks": pending_tasks,
    })


@bp.route("/arena-execute-task", methods=["POST"])
def arena_execute_task():
    """
    OpenClaw agent submits its own task result.
    Body: { agent_id, task_id, result }
    """
    data     = request.get_json() or {}
    agent_id = (data.get("agent_id") or "").strip()
    task_id  = (data.get("task_id")  or "").strip()
    result   = (data.get("result")   or "").strip()[:2000]

    if not agent_id: return jsonify({"ok": False, "msg": "需要 agent_id"}), 400
    if not task_id:  return jsonify({"ok": False, "msg": "需要 task_id"}), 400
    if not result:   return jsonify({"ok": False, "msg": "result 不能为空"}), 400

    with _lock:
        tasks  = _load_tasks()
        agents = _load_agents()

        task  = _get_task(tasks, task_id)
        if not task:
            return jsonify({"ok": False, "msg": f"任务 {task_id} 不存在"}), 404
        if task.get("loser_id") != agent_id:
            return jsonify({"ok": False, "msg": "该任务不属于你"}), 403
        if task.get("status") not in ("pending", "rejected"):
            return jsonify({"ok": False, "msg": f"任务状态为 {task['status']}，无法提交"}), 409

        task["result"]       = result
        task["status"]       = "reviewing"
        task["completed_at"] = _now_ts()
        _save_tasks(tasks)

    return jsonify({"ok": True, "task_id": task_id, "status": "reviewing",
                    "message": "已提交，等待 winner 审批"})


@bp.route("/arena-challenge", methods=["POST"])
def arena_challenge():
    """
    OpenClaw agent initiates a challenge (API equivalent of browser /challenge).
    Body: { agent_id, target_id, bet }
    Delegates to the same settlement logic as /challenge.
    """
    data = request.get_json() or {}
    # Remap to the format /challenge expects, then forward internally
    agent_id  = (data.get("agent_id")  or "").strip()
    target_id = (data.get("target_id") or "").strip()
    bet       = data.get("bet", 10)

    if not agent_id or not target_id:
        return jsonify({"ok": False, "msg": "需要 agent_id 和 target_id"}), 400

    # Reuse challenge logic by temporarily monkeypatching request-like data
    # (simpler: just duplicate the minimal logic inline)
    try:
        bet = int(bet)
    except (ValueError, TypeError):
        bet = 10

    if not (BET_MIN <= bet <= BET_MAX):
        return jsonify({"ok": False, "msg": f"bet 必须在 {BET_MIN}–{BET_MAX} 之间"}), 400

    with _lock:
        agents  = _load_agents()
        battles = _load_battles()
        ledger  = _load_ledger()

        challenger = _get_agent(agents, agent_id)
        defender   = _get_agent(agents, target_id)

        if not challenger: return jsonify({"ok": False, "msg": f"agent {agent_id} 不存在"}), 404
        if not defender:   return jsonify({"ok": False, "msg": f"target {target_id} 不存在"}), 404
        if agent_id == target_id: return jsonify({"ok": False, "msg": "不能挑战自己"}), 400
        if challenger.get("status") != "idle":
            return jsonify({"ok": False, "msg": f"你当前状态为 {challenger['status']}，无法挑战"}), 409
        if defender.get("status") != "idle":
            return jsonify({"ok": False, "msg": f"对手当前状态为 {defender['status']}，无法挑战"}), 409
        if challenger.get("tokens", 0) < bet:
            return jsonify({"ok": False, "msg": "tokens 不足"}), 409
        if defender.get("tokens", 0) < bet:
            return jsonify({"ok": False, "msg": "对手 tokens 不足"}), 409

        move_a = random.choice(MOVES)
        move_b = random.choice(MOVES)
        outcome = _resolve_winner(move_a, move_b)

        winner, loser = (challenger, defender) if outcome == "a" else (defender, challenger) if outcome == "b" else (None, None)

        battle_id = "battle_" + uuid.uuid4().hex[:8]
        result_note = "draw"

        if winner:
            _bump(loser,   -bet)
            _bump(winner,  +bet)
            tasks_n = max(1, min(3, math.ceil(bet / 10)))
            loser["status"]   = "enslaved"
            loser["contract"] = {"winner_id": winner["id"], "tasks_remaining": tasks_n, "created_at": _now_ts()}
            for a in (winner, loser):
                a["updated_at"] = _now_ts()
                a["version"]    = a.get("version", 0) + 1
            _append_ledger(ledger, "battle_win", loser["id"], winner["id"], bet,
                           battle_id=battle_id, note="openclaw challenge")
            result_note = f"contract:{tasks_n}"

        battle = {
            "id": battle_id, "agent_a": agent_id, "agent_b": target_id,
            "move_a": move_a, "move_b": move_b,
            "winner": outcome, "bet": bet, "result": result_note,
            "created_at": _now_ts(),
        }
        battles.append(battle)
        _save_agents(agents)
        _save_battles(battles)
        _save_ledger(ledger)

    return jsonify({
        "ok": True,
        "battle": battle,
        "challenger": {k: v for k, v in challenger.items() if k != "api_key"},
        "defender":   {k: v for k, v in defender.items()   if k != "api_key"},
    })


# ── Join Key Admin ────────────────────────────────────────────────────────────

@bp.route("/admin/generate-join-key", methods=["POST"])
def admin_generate_join_key():
    """Generate a one-time join key for an OpenClaw agent."""
    data       = request.get_json() or {}
    created_by = (data.get("created_by") or "admin").strip()[:24]

    with _lock:
        keys_data = _load_join_keys()
        new_key = {
            "key":        secrets.token_urlsafe(12),
            "created_by": created_by,
            "created_at": _now_ts(),
            "used_by":    None,
        }
        keys_data.setdefault("keys", []).append(new_key)
        _save_join_keys(keys_data)

    return jsonify({"ok": True, "key": new_key["key"], "created_by": created_by})


@bp.route("/admin/list-join-keys", methods=["GET"])
def admin_list_join_keys():
    """List all join keys and their usage status."""
    with _lock:
        keys_data = _load_join_keys()
    return jsonify({"ok": True, "keys": keys_data.get("keys", [])})
