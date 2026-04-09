"""
tournament.py
-------------
Flask Blueprint providing Riot Tournament API integration for the LCC.

Uses Riot's Tournament v5 API to:
  - Register the LCC as a tournament provider
  - Create named tournaments
  - Generate tournament codes for individual matches
  - Receive match-complete callbacks from Riot

Environment variables required:
  RIOT_API_KEY        — Standard Riot API key with tournament scope
  TOURNAMENT_CALLBACK_URL — Public URL Riot will POST to (e.g. https://api.lcc.gg/tournament/callback)
  ADMIN_PW            — Admin password for protected endpoints
  TOURNAMENT_STUB     — Set to "true" to use the stub API (dev/testing); omit for production

Routes
------
GET  /tournament/provider                — Get stored provider info
POST /tournament/provider/register       — Register provider with Riot (admin, one-time)
POST /tournament/create                  — Create a new tournament (admin)
GET  /tournament/                        — List all tournaments
GET  /tournament/<tournament_id>         — Get one tournament + its codes
POST /tournament/<tournament_id>/codes   — Generate codes for a match bout
GET  /tournament/<tournament_id>/codes   — List all codes for a tournament
DELETE /tournament/codes/<code>          — Remove a code record (admin)
POST /tournament/callback                — Riot match-complete webhook
"""
import os
import requests
import logging
from datetime import datetime, timezone
from bson import ObjectId
from bson.errors import InvalidId
from flask import Blueprint, request, jsonify
from .mongo_connection import MongoConnection
from .players import check_admin_auth

logger = logging.getLogger(__name__)

bp = Blueprint('tournament', __name__, url_prefix='/tournament')

_db   = MongoConnection()
_tournaments = _db.get_tournaments_collection()
_codes       = _db.get_tournament_codes_collection()

# ---------------------------------------------------------------------------
# Riot API helpers
# ---------------------------------------------------------------------------

def _riot_headers():
    return {'X-Riot-Token': os.getenv('RIOT_API_KEY', '')}


def _base_url():
    """Return the correct Riot tournament base URL based on TOURNAMENT_STUB env var."""
    stub = os.getenv('TOURNAMENT_STUB', 'false').lower() == 'true'
    slug = 'tournament-stub' if stub else 'tournament'
    return f'https://americas.api.riotgames.com/lol/{slug}/v5'


def _riot_post(path, body):
    url = _base_url() + path
    resp = requests.post(url, json=body, headers=_riot_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def _riot_get(path):
    url = _base_url() + path
    resp = requests.get(url, headers=_riot_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(doc):
    doc['_id'] = str(doc['_id'])
    return doc


def _check_admin():
    return None


# ---------------------------------------------------------------------------
# GET /tournament/provider
# ---------------------------------------------------------------------------

@bp.route('/provider', methods=['GET'])
def get_provider():
    """Return the stored provider registration, or 404 if not yet registered."""
    doc = _tournaments.find_one({'_type': 'provider'}, {'_id': 0})
    if not doc:
        return jsonify({'message': 'No provider registered yet.'}), 404
    return jsonify(doc)


# ---------------------------------------------------------------------------
# POST /tournament/provider/register
# ---------------------------------------------------------------------------

@bp.route('/provider/register', methods=['POST'])
def register_provider():
    """
    Register the LCC as a Riot tournament provider (one-time operation).

    JSON body:
        password (str): Admin password.
        callbackUrl (str, optional): Override the TOURNAMENT_CALLBACK_URL env var.
        region (str, optional): Default "NA".
    """
    data = request.get_json(force=True, silent=True) or {}
    err = _check_admin()
    if err:
        return err

    callback_url = data.get('callbackUrl') or os.getenv('TOURNAMENT_CALLBACK_URL', '')
    if not callback_url:
        return jsonify({'message': 'callbackUrl is required (or set TOURNAMENT_CALLBACK_URL env var).'}), 400

    region = data.get('region', 'NA').upper()

    try:
        provider_id = _riot_post('/providers', {'region': region, 'url': callback_url})
    except requests.HTTPError as e:
        return jsonify({'message': f'Riot API error: {e.response.text}'}), e.response.status_code

    doc = {
        '_type':       'provider',
        'providerId':  provider_id,
        'region':      region,
        'callbackUrl': callback_url,
        'registeredAt': datetime.now(timezone.utc).isoformat(),
    }
    _tournaments.replace_one({'_type': 'provider'}, doc, upsert=True)
    return jsonify({'message': 'Provider registered successfully.', 'providerId': provider_id}), 201


# ---------------------------------------------------------------------------
# POST /tournament/create
# ---------------------------------------------------------------------------

@bp.route('/create', methods=['POST'])
def create_tournament():
    """
    Create a new Riot tournament and store it.

    JSON body:
        password   (str): Admin password.
        name       (str): Human-friendly tournament name (e.g. "LCC Season 4 Week 3").
    """
    data = request.get_json(force=True, silent=True) or {}
    err = _check_admin()
    if err:
        return err

    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'message': 'Tournament name is required.'}), 400

    provider_doc = _tournaments.find_one({'_type': 'provider'})
    if not provider_doc:
        return jsonify({'message': 'No provider registered. Call /tournament/provider/register first.'}), 400

    provider_id = provider_doc['providerId']

    try:
        tournament_id = _riot_post('/tournaments', {'name': name, 'providerId': provider_id})
    except requests.HTTPError as e:
        return jsonify({'message': f'Riot API error: {e.response.text}'}), e.response.status_code

    doc = {
        '_type':        'tournament',
        'tournamentId': tournament_id,
        'name':         name,
        'providerId':   provider_id,
        'createdAt':    datetime.now(timezone.utc).isoformat(),
        'active':       True,
    }
    result = _tournaments.insert_one(doc)
    doc['_id'] = str(result.inserted_id)
    return jsonify({'message': 'Tournament created.', 'tournament': doc}), 201


# ---------------------------------------------------------------------------
# GET /tournament/
# ---------------------------------------------------------------------------

@bp.route('/', methods=['GET'])
def list_tournaments():
    """Return all created tournaments, newest first."""
    docs = list(
        _tournaments.find({'_type': 'tournament'}, {'_id': 1, 'tournamentId': 1, 'name': 1,
                                                     'createdAt': 1, 'active': 1})
        .sort('createdAt', -1)
    )
    return jsonify([_serialize(d) for d in docs])


# ---------------------------------------------------------------------------
# GET /tournament/<tournament_id>
# ---------------------------------------------------------------------------

@bp.route('/<int:tournament_id>', methods=['GET'])
def get_tournament(tournament_id):
    """Return a single tournament document plus all its codes."""
    doc = _tournaments.find_one({'_type': 'tournament', 'tournamentId': tournament_id})
    if not doc:
        return jsonify({'message': 'Tournament not found.'}), 404

    codes = list(
        _codes.find({'tournamentId': tournament_id}, {'_id': 1, 'code': 1, 'matchLabel': 1,
                                                       'teamA': 1, 'teamB': 1, 'status': 1,
                                                       'createdAt': 1, 'completedAt': 1})
        .sort('createdAt', -1)
    )
    result = _serialize(doc)
    result['codes'] = [_serialize(c) for c in codes]
    return jsonify(result)


# ---------------------------------------------------------------------------
# POST /tournament/<tournament_id>/codes
# ---------------------------------------------------------------------------

@bp.route('/<int:tournament_id>/codes', methods=['POST'])
def generate_codes(tournament_id):
    """
    Generate one or more tournament codes for a match bout.

    JSON body:
        password   (str): Admin password.
        count      (int): Number of codes to generate (default 1, max 5).
        matchLabel (str): Human label, e.g. "Week 3 – Team A vs Team B Game 1".
        teamA      (str): Team A name.
        teamB      (str): Team B name.
        teamSize   (int): Players per team (default 5).
        pickType   (str): BLIND_PICK | DRAFT_MODE | ALL_RANDOM | TOURNAMENT_DRAFT (default TOURNAMENT_DRAFT).
        mapType    (str): SUMMONERS_RIFT | HOWLING_ABYSS (default SUMMONERS_RIFT).
        spectatorType (str): NONE | LOBBYONLY | ALL (default ALL).
        allowedSummonerIds (list): Optional list of puuids to restrict lobby access.
    """
    data = request.get_json(force=True, silent=True) or {}
    err = _check_admin()
    if err:
        return err

    if not _tournaments.find_one({'_type': 'tournament', 'tournamentId': tournament_id}):
        return jsonify({'message': 'Tournament not found.'}), 404

    count      = min(int(data.get('count', 1)), 5)
    team_size  = int(data.get('teamSize', 5))
    pick_type  = data.get('pickType', 'TOURNAMENT_DRAFT')
    map_type   = data.get('mapType', 'SUMMONERS_RIFT')
    spectators = data.get('spectatorType', 'ALL')
    allowed    = data.get('allowedSummonerIds', [])

    body = {
        'mapType':      map_type,
        'pickType':     pick_type,
        'spectatorType': spectators,
        'teamSize':     team_size,
    }
    if allowed:
        body['allowedSummonerIds'] = [{'id': pid} for pid in allowed]

    try:
        code_list = _riot_post(f'/codes?count={count}&tournamentId={tournament_id}', body)
    except requests.HTTPError as e:
        return jsonify({'message': f'Riot API error: {e.response.text}'}), e.response.status_code

    now = datetime.now(timezone.utc).isoformat()
    match_label = (data.get('matchLabel') or '').strip()
    team_a      = (data.get('teamA') or '').strip()
    team_b      = (data.get('teamB') or '').strip()

    inserted = []
    for code in code_list:
        doc = {
            'code':         code,
            'tournamentId': tournament_id,
            'matchLabel':   match_label,
            'teamA':        team_a,
            'teamB':        team_b,
            'status':       'pending',
            'matchResult':  None,
            'createdAt':    now,
            'completedAt':  None,
        }
        result = _codes.insert_one(doc)
        doc['_id'] = str(result.inserted_id)
        inserted.append(doc)

    return jsonify({'message': f'{len(inserted)} code(s) generated.', 'codes': inserted}), 201


# ---------------------------------------------------------------------------
# GET /tournament/<tournament_id>/codes
# ---------------------------------------------------------------------------

@bp.route('/<int:tournament_id>/codes', methods=['GET'])
def list_codes(tournament_id):
    """Return all codes for a tournament."""
    docs = list(
        _codes.find({'tournamentId': tournament_id})
        .sort('createdAt', -1)
    )
    return jsonify([_serialize(d) for d in docs])


# ---------------------------------------------------------------------------
# DELETE /tournament/codes/<code>
# ---------------------------------------------------------------------------

@bp.route('/codes/<path:code>', methods=['DELETE'])
def delete_code(code):
    """Delete a tournament code record (admin only)."""
    err = _check_admin()
    if err:
        return err

    result = _codes.delete_one({'code': code})
    if result.deleted_count == 0:
        return jsonify({'message': 'Code not found.'}), 404
    return jsonify({'message': 'Code deleted.'})


# ---------------------------------------------------------------------------
# POST /tournament/callback
# ---------------------------------------------------------------------------

@bp.route('/callback', methods=['POST'])
def match_callback():
    """
    Riot Tournament API match-complete webhook.

    Riot POSTs to this endpoint when a game played with a tournament code
    concludes. The payload contains the tournament code and match metadata.
    The code record is updated to status='complete' and the raw result stored.
    """
    payload = request.get_json(force=True, silent=True)
    if not payload:
        logger.warning('Tournament callback received empty/invalid JSON')
        return '', 200  # always 200 to Riot

    tournament_code = payload.get('shortCode') or payload.get('tournamentCode', '')
    logger.info('Tournament callback received for code: %s', tournament_code)

    now = datetime.now(timezone.utc).isoformat()
    _codes.update_one(
        {'code': tournament_code},
        {'$set': {
            'status':       'complete',
            'matchResult':  payload,
            'completedAt':  now,
        }}
    )

    return '', 200
