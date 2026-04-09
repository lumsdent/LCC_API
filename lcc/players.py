"""
players.py
----------
Flask Blueprint providing all player-related API endpoints for the LCC API.

Includes routes for adding, retrieving, and refreshing players, paginated match
history, per-champion stats, and helpers for Riot API and DDragon data access.
"""
from datetime import timedelta, datetime
import os
import requests
from flask import request, jsonify, Blueprint
from .mongo_connection import MongoConnection
from .process_match_reports import get_champion_mastery

bp = Blueprint('players', __name__, url_prefix='/players')

DDRAGON_BASE_URL = 'https://ddragon.leagueoflegends.com/cdn/latest'

# Two accounts belonging to the same person — merge the old one into the canonical one.
_MERGE_OLD_PUUID = 'OMb9S_LJfcHcmNf2EeoK6oKVZPN_ilQ_atdZLBHcS-1cNv38UZObF9COSP54dJn9eD4-mP23xpHUug'
_MERGE_NEW_PUUID = '2_h_CpcRsZypWQHR66PnB_DU1rHiQYz8AmRETV54QFVuZuwX9Ly_ys7R3SOh7fFo9U1CZ9VlPv50Aw'


def _merge_duplicate_players(player_list):
    """
    Merge teams from the old duplicate PUUID into the canonical player record,
    then remove the duplicate from the list.
    """
    old = next((p for p in player_list if p.get('profile', {}).get('puuid') == _MERGE_OLD_PUUID), None)
    new = next((p for p in player_list if p.get('profile', {}).get('puuid') == _MERGE_NEW_PUUID), None)
    if not old or not new:
        return player_list

    # Merge teams — old entries fill in seasons not already present on new
    existing_seasons = {list(t.keys())[0] for t in new.get('teams', []) if t}
    for team_entry in old.get('teams', []):
        season_key = list(team_entry.keys())[0] if team_entry else None
        if season_key and season_key not in existing_seasons:
            new.setdefault('teams', []).append(team_entry)
            existing_seasons.add(season_key)

    return [p for p in player_list if p.get('profile', {}).get('puuid') != _MERGE_OLD_PUUID]

_db = MongoConnection()
players = _db.get_player_collection()
match_performances = _db.get_match_performances_collection()

def get_player_by_discord_id(discord_id):
    """Return a player document matching the given Discord user ID, or None."""
    return players.find_one({'discord.id': str(discord_id)}, {'_id': 0})


def get_player_me_by_discord_id(discord_id):
    """Return a lightweight player document for /me: excludes champion_mastery."""
    return players.find_one(
        {'discord.id': str(discord_id)},
        {'_id': 0, 'champion_mastery': 0}
    )


def check_admin_auth(data=None, cookie_user_id=None):
    """
    Return True if the request is authorized as an admin.
    Accepts either:
      - A JSON body with {"password": ADMIN_PW}
      - A session cookie whose Discord ID maps to a player with is_admin=True
    """
    if data and data.get('password') == os.getenv('ADMIN_PW'):
        return True
    if cookie_user_id:
        doc = players.find_one({'discord.id': str(cookie_user_id)}, {'is_admin': 1})
        return bool(doc and doc.get('is_admin'))
    return False


def set_admin_status(discord_id, is_admin: bool):
    """Grant or revoke admin status for a player by Discord ID."""
    result = players.update_one(
        {'discord.id': str(discord_id)},
        {'$set': {'is_admin': is_admin}}
    )
    return result.matched_count > 0


def create_player_login(user):
    """Create a minimal player document from a Discord user on first login."""
    player_data = {
        'profile': {'name': user.name, 'is_active': True},
        'discord': {
            'id':         str(user.id),
            'username':   user.name,
            'avatar_url': user.avatar_url or '',
        },
    }
    players.insert_one(player_data)
    return player_data


def update_player_login(user):
    """Update Discord metadata for a returning player."""
    players.update_one(
        {'discord.id': str(user.id)},
        {'$set': {
            'discord.username':   user.name,
            'discord.avatar_url': user.avatar_url or '',
        }}
    )


def link_discord_to_player(puuid, user):
    """Link a Discord account to an existing player identified by PUUID."""
    result = players.update_one(
        {'profile.puuid': puuid},
        {'$set': {
            'discord.id':         str(user['id']),
            'discord.username':   user['username'],
            'discord.avatar_url': user.get('avatar_url', ''),
        }}
    )
    return result.matched_count > 0


def get_linked_players_summary():
    """Return all players for the admin dropdown, sorted by name."""
    return list(players.find(
        {},
        {'_id': 0, 'profile.name': 1, 'discord.id': 1, 'is_admin': 1}
    ))


def get_unclaimed_players():
    """Return players that have no Discord account linked yet (missing, null, or empty discord.id)."""
    return list(players.find(
        {'$or': [
            {'discord.id': {'$exists': False}},
            {'discord.id': None},
            {'discord.id': ''},
        ]},
        {'_id': 0, 'champion_mastery': 0}
    ))


@bp.route('/unclaimed', methods=['GET'])
def unclaimed_players():
    """Return players with no Discord account linked. Used for the claim-profile flow."""
    return jsonify(get_unclaimed_players())


@bp.route('/<puuid>/link-discord', methods=['POST'])
def link_discord(puuid):
    """
    Admin endpoint to manually link a Discord account to an existing player by PUUID.
    Body: { discord_id, discord_username, discord_avatar (optional), password (optional) }
    """
    data = request.get_json(force=True, silent=True) or {}
    discord_id = str(data.get('discord_id', '')).strip()
    if not discord_id:
        return jsonify({'message': 'discord_id is required'}), 400
    if players.find_one({'discord.id': discord_id}):
        return jsonify({'message': 'That Discord account is already linked to a player'}), 409
    user = {
        'id':         discord_id,
        'username':   data.get('discord_username', ''),
        'avatar_url': data.get('discord_avatar', ''),
    }
    if not link_discord_to_player(puuid, user):
        return jsonify({'message': 'Player not found'}), 404
    return jsonify({'message': 'Discord account linked successfully'})


@bp.route('/add', methods=['POST'])
def add_player():
    """Add a new player or update an existing one by PUUID. Requires admin password."""
    form_data = request.json
    riot_data = get_riot_data(form_data['name'], form_data['tag'])
    discord_data = {
        'id':         form_data['discord_id'],
        'username':   form_data['discord_username'],
        'avatar_url': form_data['discord_avatar'],
    }
    profile_data = {
        'puuid':          riot_data['puuid'],
        'name':           riot_data['gameName'],
        'tag':            riot_data['tagLine'],
        'level':          riot_data['summonerLevel'],
        'email':          form_data['email'],
        'bio':            form_data['bio'],
        'primary_role':   form_data['primaryRole'],
        'secondary_role': form_data['secondaryRole'],
        'can_sub':        form_data['canSub'],
        'revision_date':  riot_data['revisionDate'],
        'images':         get_images(riot_data['profileIconId']),
        'availability':   form_data['availability'],
        'is_active':      True,
    }
    player_data = {
        'profile':          profile_data,
        'discord':          discord_data,
        'champion_mastery': get_champion_mastery(profile_data['puuid']),
    }
    if players.find_one({'profile.puuid': profile_data['puuid']}) is None:
        result = players.insert_one(player_data)
        return jsonify({'message': 'Player added successfully', '_id': str(result.inserted_id)}), 201
    players.update_one({'profile.puuid': profile_data['puuid']}, {'$set': player_data})
    return jsonify({'message': 'Player already exists. Updated with provided data'})

@bp.route('/<puuid>', methods=['GET'])
def get_player_by_puuid(puuid):
    """Return a single player document by PUUID, excluding match history."""
    player_data = players.find_one({'profile.puuid': puuid}, {'_id': 0})
    if player_data is None:
        return jsonify({'message': 'Player not found'}), 404
    return jsonify(player_data)

@bp.route('/<puuid>/matches', methods=['GET'])
def get_player_matches(puuid):
    """
    Return paginated match history for a player.

    Query params:
        page (int):       Page number, default 1.
        per_page (int):   Results per page, 1-50, default 10.
        champion (str):   Optional champion name filter.
    """
    page     = max(1, int(request.args.get('page', 1)))
    per_page = min(50, max(1, int(request.args.get('per_page', 10))))
    champion = request.args.get('champion', None)

    # If looking up the canonical account, also include the old duplicate account's history.
    puuids = [puuid]
    if puuid == _MERGE_NEW_PUUID:
        puuids.append(_MERGE_OLD_PUUID)
    query: dict = {'puuid': {'$in': puuids}} if len(puuids) > 1 else {'puuid': puuid}
    if champion:
        query['champion.name'] = champion

    total = match_performances.count_documents(query)
    pipeline = [
        {'$match': query},
        {'$sort': {'gameStartTimestamp': -1}},
        {'$skip': (page - 1) * per_page},
        {'$limit': per_page},
        # Enrich with opponent champion/team using the pre-resolved opponentPuuid
        {'$lookup': {
            'from': 'match_performances',
            'let': {'mid': '$matchId', 'opp': '$opponentPuuid'},
            'pipeline': [
                {'$match': {'$expr': {'$and': [
                    {'$eq': ['$matchId', '$$mid']},
                    {'$eq': ['$puuid',   '$$opp']},
                ]}}},
                {'$project': {'_id': 0, 'champion': 1, 'teamName': 1}},
            ],
            'as': 'opponentDoc',
        }},
        # Enrich with VOD URL from the matches collection
        {'$lookup': {
            'from': 'matches',
            'let': {'mid': '$matchId'},
            'pipeline': [
                {'$match': {'$expr': {'$eq': ['$metadata.matchId', '$$mid']}}},
                {'$project': {'_id': 0, 'vod': '$info.vod'}},
            ],
            'as': 'matchDoc',
        }},
        {'$addFields': {
            'opponentTeamName': {'$arrayElemAt': ['$opponentDoc.teamName', 0]},
            'opponentChampion': {'$arrayElemAt': ['$opponentDoc.champion', 0]},
            'vod': {'$arrayElemAt': ['$matchDoc.vod', 0]},
        }},
        {'$project': {'_id': 0, 'opponentDoc': 0, 'matchDoc': 0}},
    ]
    match_results = list(match_performances.aggregate(pipeline))

    return jsonify({
        'matches':  match_results,
        'total':    total,
        'page':     page,
        'per_page': per_page,
        'pages':    max(1, (total + per_page - 1) // per_page),
    })

@bp.route('/<puuid>/champion-stats', methods=['GET'])
def get_player_champion_stats(puuid):
    """Return aggregated per-champion statistics for a player."""
    puuids = [puuid]
    if puuid == _MERGE_NEW_PUUID:
        puuids.append(_MERGE_OLD_PUUID)
    query = {'puuid': {'$in': puuids}} if len(puuids) > 1 else {'puuid': puuid}
    pipeline = [
        {'$match': query},
        {'$group': {
            '_id':               '$champion.name',
            'champion':          {'$first': '$champion'},
            'gamesPlayed':       {'$sum': 1},
            'wins':              {'$sum': {'$cond': ['$win', 1, 0]}},
            'losses':            {'$sum': {'$cond': ['$win', 0, 1]}},
            'kills':             {'$sum': '$kills'},
            'deaths':            {'$sum': '$deaths'},
            'assists':           {'$sum': '$assists'},
            'killParticipation': {'$avg': '$killParticipation'},
            'dpm':               {'$avg': '$dpm'},
            'cs14':              {'$avg': '$cs14'},
            'csm':               {'$avg': '$csm'},
            'gpm':               {'$avg': '$gpm'},
            'vspm':              {'$avg': '$vspm'},
        }},
        {'$addFields': {
            'kda': {
                '$divide': [
                    {'$add': ['$kills', '$assists']},
                    {'$max': [1, '$deaths']},
                ]
            }
        }},
        {'$sort': {'gamesPlayed': -1}},
        {'$project': {'_id': 0}},
    ]
    stats = list(match_performances.aggregate(pipeline))
    return jsonify(stats)

@bp.route('/', methods=['GET'], strict_slashes=False)
def get_players():
    """Return all player documents, with duplicate accounts merged."""
    player_data = list(players.find({}, {'_id': 0}))
    player_data = _merge_duplicate_players(player_data)
    return jsonify(player_data)

@bp.route('/spells', methods=['GET'])
def get_runes():
    """Return a flattened DDragon rune/perk ID-to-key dictionary."""
    runes = ddragon_get_runes_dict()
    return jsonify(runes)

def get_riot_data(summoner_name, summoner_tag):
    """Fetch combined Riot account and summoner data by in-game name and tag."""
    account_url = f'https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{summoner_name}/{summoner_tag}'
    account = fetch_riot_data(account_url)
    summoner_url = f"https://na1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{account['puuid']}"
    summoner = fetch_riot_data(summoner_url)
    return {**summoner, **account}

def get_riot_data_by_puuid(puuid):
    """Fetch combined Riot account and summoner data by PUUID."""
    account_url = f'https://americas.api.riotgames.com/riot/account/v1/accounts/by-puuid/{puuid}'
    account = fetch_riot_data(account_url)
    summoner_url = f'https://na1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}'
    summoner = fetch_riot_data(summoner_url)
    return {**summoner, **account}

def add_team_to_player(data, team_name, season):
    """Associate a player with a team for a given season."""
    result = players.update_one(
        {'profile.puuid': data['player']['puuid']},
        {'$addToSet': {'teams': {season: {'role': data['role'], 'name': team_name}}}}
    )
    return result

def get_images(profile_icon_id):
    """Return a dict of image URLs for a given profile icon ID."""
    return {'icon': f'/img/profileicon/{profile_icon_id}.png'}

def ddragon_get_runes_dict():
    """
    Fetch and return a flattened rune ID-to-key mapping from DDragon.

    Returns a dict combining top-level perk tree IDs (e.g. Domination, Precision)
    and individual rune IDs, all mapped to their lowercase key names.
    Returns an empty dict if the request fails.
    """
    url = f'{DDRAGON_BASE_URL}/data/en_US/runesReforged.json'
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException:
        return {}
    perk_dict = {item['id']: item['icon'].split('/')[-1].split('.')[0].lower() for item in data}
    rune_dict = {rune['id']: rune['key'].lower() for item in data for slot in item['slots'] for rune in slot['runes']}
    return {**perk_dict, **rune_dict}

def fetch_riot_data(url):
    """Make an authenticated GET request to the Riot API and return parsed JSON."""
    headers = {'X-Riot-Token': os.getenv('RIOT_API_KEY')}
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        raise requests.exceptions.HTTPError(f'Failed to fetch Riot data: {response.text}')
    return response.json()


@bp.route('/<puuid>/refresh', methods=['POST'])
def refresh_player_riot_data(puuid):
    """Refresh a player's Riot data using their PUUID (name, tag, level, profile icon, champion mastery)."""
    player = players.find_one({'profile.puuid': puuid})
    if player is None:
        return jsonify({'message': 'Player not found'}), 404

    # Check the 24-hour cooldown BEFORE hitting the Riot API to avoid wasting quota.
    last_refreshed = player['profile'].get('last_refreshed')
    if last_refreshed:
        last_updated = datetime.fromtimestamp(last_refreshed / 1000)
        if datetime.now() - last_updated < timedelta(hours=24):
            return jsonify({'message': 'Profile was updated within the last 24 hours. Please try again later.'}), 429

    try:
        riot_data = get_riot_data_by_puuid(puuid)
        now_ms = int(datetime.now().timestamp() * 1000)
        updated_fields = {
            'profile.name':           riot_data['gameName'],
            'profile.tag':            riot_data['tagLine'],
            'profile.level':          riot_data.get('summonerLevel'),
            'profile.revision_date':  riot_data.get('revisionDate'),
            'profile.last_refreshed': now_ms,
            'profile.images':         get_images(riot_data['profileIconId']),
            'champion_mastery':       get_champion_mastery(puuid),
        }
        players.update_one({'profile.puuid': puuid}, {'$set': updated_fields})
        updated_player = players.find_one({'profile.puuid': puuid}, {'_id': 0})
        return jsonify({'message': 'Player refreshed successfully', 'player': updated_player})
    except Exception as e:
        return jsonify({'message': f'Error refreshing player: {str(e)}'}), 500
