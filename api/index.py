import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import json
import threading

app = Flask(__name__)
CORS(app)

# Paths
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT_DIR, '../data')
os.makedirs(DATA_DIR, exist_ok=True)

STATE_FILE = os.path.join(DATA_DIR, 'state.json')
LEDGER_FILE = os.path.join(DATA_DIR, 'ledger.json')
BATTLES_FILE = os.path.join(DATA_DIR, 'battles.json')
AGENTS_FILE = os.path.join(DATA_DIR, 'agents.json')
TASKS_FILE = os.path.join(DATA_DIR, 'tasks.json')

DEFAULT_STATE = {"arena": {"status": "open", "players": [], "battles": []}}

def load_json(file_path, default):
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except:
            pass
    return default

def save_json(file_path, data):
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)

state = load_json(STATE_FILE, DEFAULT_STATE)
ledger = load_json(LEDGER_FILE, {})
battles = load_json(BATTLES_FILE, [])
agents = load_json(AGENTS_FILE, {})
tasks = load_json(TASKS_FILE, [])

lock = threading.Lock()

@app.route('/arena-status', methods=['GET'])
def arena_status():
    return jsonify(state['arena'])

@app.route('/join', methods=['POST'])
def join():
    with lock:
        data = request.json
        player_id = data.get('player_id')
        if not player_id:
            return jsonify({"error": "player_id required"}), 400
        if player_id not in state['arena']['players']:
            state['arena']['players'].append(player_id)
            save_json(STATE_FILE, state)
        return jsonify({"status": "joined", "player_id": player_id})

@app.route('/challenge', methods=['POST'])
def challenge():
    with lock:
        data = request.json
        challenger = data.get('challenger')
        opponent = data.get('opponent')
        if not challenger or not opponent:
            return jsonify({"error": "missing params"}), 400
        battle_id = f"{challenger}_vs_{opponent}_{datetime.now().timestamp()}"
        battles.append({"id": battle_id, "challenger": challenger, "opponent": opponent, "status": "pending"})
        save_json(BATTLES_FILE, battles)
        return jsonify({"battle_id": battle_id})

# Tambahkan route lain sesuai kebutuhan game (submit-move, resolve-battle, tasks, dll)
# Contoh placeholder
@app.route('/submit-move', methods=['POST'])
def submit_move():
    return jsonify({"status": "move received"})

@app.route('/')
def root():
    return app.send_static_file('../index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 18795))
    app.run(host='0.0.0.0', port=port, debug=False)
