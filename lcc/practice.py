"""
practice.py
-----------
Flask Blueprint providing practice log API endpoints for the LCC API.

Routes
------
POST /practice/add       Save a combined pre/post match practice entry.
GET  /practice/          Return all entries, newest first (optional ?player= filter).
DELETE /practice/<id>    Delete a single entry by its string _id.
"""
import re
from datetime import datetime, timezone
from bson import ObjectId
from bson.errors import InvalidId
from flask import request, jsonify, Blueprint
from .mongo_connection import MongoConnection

bp = Blueprint('practice', __name__, url_prefix='/practice')

_db = MongoConnection()
_col = _db.get_practice_collection()


def _serialize(doc):
    """Convert a MongoDB document to a JSON-safe dict."""
    doc['_id'] = str(doc['_id'])
    return doc


# ---------------------------------------------------------------------------
# POST /practice/add
# ---------------------------------------------------------------------------
@bp.route('/add', methods=['POST'])
def add_entry():
    """
    Save a new practice log entry.

    Expected JSON body (all optional except playerName):
    {
        "playerName":         str,
        "gameMode":           str,   # solo | duo | flex | normal
        "role":               str,   # TOP | JUNGLE | MID | BOTTOM | SUPPORT
        "myChampion":         str,   # DDragon champion id
        "opponentChampion":   str,
        "goal":               str,
        "win":                bool,
        "lesson":             str,
        "focus":              int,   # 1-5
        "performance":        int,
        "mental":             int
    }
    """
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'message': 'Invalid or missing JSON body.'}), 400

    player_name = (data.get('playerName') or '').strip()
    if not player_name:
        return jsonify({'message': 'playerName is required.'}), 400

    entry = {
        'playerName':       player_name,
        'gameMode':         data.get('gameMode', ''),
        'role':             data.get('role', ''),
        'myChampion':       data.get('myChampion', ''),
        'opponentChampion': data.get('opponentChampion', ''),
        'goal':             (data.get('goal') or '').strip(),
        'matchId':          (data.get('matchId') or '').strip(),
        'win':              bool(data.get('win')),
        'lesson':           (data.get('lesson') or '').strip(),
        'focus':            int(data.get('focus', 3)),
        'performance':      int(data.get('performance', 3)),
        'mental':           int(data.get('mental', 3)),
        'submittedAt':      datetime.now(timezone.utc).isoformat(),
    }

    result = _col.insert_one(entry)
    entry['_id'] = str(result.inserted_id)
    return jsonify({'message': 'Practice entry saved.', 'entry': entry}), 200


# ---------------------------------------------------------------------------
# GET /practice/
# ---------------------------------------------------------------------------
@bp.route('/', methods=['GET'])
def get_entries():
    """
    Return all practice entries sorted newest first.

    Optional query params:
      ?summoner=<name>   Case-insensitive filter by summonerName.
      ?limit=<n>         Max results to return (default 50).
    """
    query = {}
    player = request.args.get('player', '').strip()
    if player:
        query['playerName'] = {'$regex': f'^{re.escape(player)}$', '$options': 'i'}

    limit = int(request.args.get('limit', 50))
    docs = list(
        _col.find(query, {'_id': 1, 'playerName': 1, 'gameMode': 1,
                          'role': 1, 'myChampion': 1, 'opponentChampion': 1,
                          'goal': 1, 'matchId': 1, 'win': 1, 'lesson': 1, 'focus': 1,
                          'performance': 1, 'mental': 1, 'submittedAt': 1})
        .sort('submittedAt', -1)
        .limit(limit)
    )
    return jsonify([_serialize(d) for d in docs]), 200


# ---------------------------------------------------------------------------
# DELETE /practice/<id>
# ---------------------------------------------------------------------------
@bp.route('/<entry_id>', methods=['DELETE'])
def delete_entry(entry_id):
    """Delete a practice entry by its _id."""
    try:
        oid = ObjectId(entry_id)
    except InvalidId:
        return jsonify({'message': 'Invalid entry id.'}), 400

    result = _col.delete_one({'_id': oid})
    if result.deleted_count == 0:
        return jsonify({'message': 'Entry not found.'}), 404
    return jsonify({'message': 'Entry deleted.'}), 200
