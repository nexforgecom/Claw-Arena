import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
import json
import threading

app = Flask(__name__)
CORS(app)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data')
os.makedirs(DATA_DIR, exist_ok=True)

ARENA_FILE = os.path.join(DATA_DIR, 'arena.json')
AGENTS_FILE = os.path.join(DATA_DIR, 'agents.json')
BATTLES_FILE = os.path.join(DATA_DIR, 'battles.json')

def load_data(file, default):
    if os.path.exists(file):
        try:
            with open(file, 'r') as f:
                return json.load(f)
        except:
            pass
    return default

def save_data(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

arena = load_data(ARENA_FILE, {"status": "open", "players": []})
agents = load_data(AGENTS_FILE, [])
battles = load_data(BATTLES_FILE, [])

lock = threading.Lock()

@app.route('/arena-status', methods=['GET'])
def arena_status():
    return jsonify(arena)

@app.route('/agents', methods=['GET'])
def get_agents():
    return jsonify(agents)

@app.route('/join', methods=['POST'])
def join():
    with lock:
        data = request.json or {}
        player = data.get('player_id') or f"player_{len(arena['players'])+1}"
        if player not in arena['players']:
            arena['players'].append(player)
            save_data(ARENA_FILE, arena)
        return jsonify({"status": "joined", "player": player})

@app.route('/challenge', methods=['POST'])
def challenge():
    with lock:
        data = request.json or {}
        challenger = data.get('challenger')
        opponent = data.get('opponent')
        if challenger and opponent:
            battle = {"id": f"{challenger}_vs_{opponent}_{datetime.now().timestamp()}", "status": "pending"}
            battles.append(battle)
            save_data(BATTLES_FILE, battles)
            return jsonify(battle)
        return jsonify({"error": "missing params"}), 400

@app.route('/submit-move', methods=['POST'])
def submit_move():
    return jsonify({"status": "move accepted"})

@app.route('/tasks', methods=['GET'])
def tasks():
    return jsonify([])

@app.route('/', methods=['GET'])
def serve_index():
    return send_from_directory('../', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
