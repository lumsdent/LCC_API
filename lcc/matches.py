"""
matches.py
----------
Flask Blueprint providing all match-related API endpoints for the LCC API.

Includes routes for adding, updating, and retrieving matches (both Riot API-sourced
and manually entered), assigning MVPs, updating VODs, refreshing match data, and
aggregating player/champion statistics by season or all-time.
"""
import os
from flask import request, jsonify, Blueprint
from .mongo_connection import MongoConnection
from .process_match_reports import process_match, get_matchups
from .players import save_match_history, check_admin_auth

def _cookie_admin_check():
    """Return a 401 response tuple if the cookie token is not an admin, else None."""
    if not check_admin_auth(cookie_user_id=request.cookies.get('token')):
        return jsonify({'message': 'Unauthorized'}), 401
    return None

bp = Blueprint('matches', __name__, url_prefix='/matches')

ROLES = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'SUPPORT']

# Duplicate accounts belonging to the same player — remap old → canonical in stats.
_MERGE_OLD_PUUID = 'OMb9S_LJfcHcmNf2EeoK6oKVZPN_ilQ_atdZLBHcS-1cNv38UZObF9COSP54dJn9eD4-mP23xpHUug'
_MERGE_NEW_PUUID = '2_h_CpcRsZypWQHR66PnB_DU1rHiQYz8AmRETV54QFVuZuwX9Ly_ys7R3SOh7fFo9U1CZ9VlPv50Aw'

_db = MongoConnection()
matches = _db.get_matches_collection()
matches_index = _db.get_match_index_collection()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_password(data):
    """Return a 401 response tuple if the password is wrong, else None."""
    if data.get('password') != os.getenv('ADMIN_PW'):
        return jsonify({'message': 'Incorrect password'}), 401
    return None


def save_match(data):
    """Insert a new match document into the matches collection."""
    matches.insert_one(data)


def update_match(query, data):
    """Replace an existing match document that matches query with data."""
    matches.replace_one(query, data)


def save_matchup(matchup):
    """Persist a single matchup record to match history."""
    save_match_history(matchup)


def _process_matchups(processed_match):
    """Extract and save per-role matchup records from a processed match."""
    for role in ROLES:
        for matchup in get_matchups(processed_match, role):
            save_matchup(matchup)


def _build_player(p, mins):
    """
    Build a normalised player sub-document for a match record.

    Args:
        p (dict): Raw player data from the manual entry payload.
        mins (float): Game duration in minutes used to compute per-minute stats.

    Returns:
        dict: Player document with computed KDA, CSM, DPM, GPM, and VSPM fields.
    """
    k, d, a = int(p.get('kills', 0)), int(p.get('deaths', 0)), int(p.get('assists', 0))
    kda  = round((k + a) / d, 2) if d > 0 else float(k + a)
    cs   = int(p.get('cs', 0))
    dmg  = int(p.get('dmg', 0))
    gold = int(p.get('goldEarned', 0))
    vis  = int(p.get('visionScore', 0))
    per_min = lambda v: round(v / mins, 2) if mins else 0
    return {
        'role':    p.get('role', ''),
        'profile': {'puuid': p.get('puuid', ''), 'name': p.get('name', '')},
        'champion': {
            'name':  p.get('champion', ''), 'level': 18,
            'image': {'square': f"/img/champion/{p.get('champion', '')}.png"},
        },
        'kills': k, 'deaths': d, 'assists': a, 'kda': kda,
        'cs': cs, 'cs14': int(p.get('cs14', 0)), 'csd': int(p.get('csd', 0)),
        'csm': per_min(cs),
        'dmg': dmg, 'dpm': per_min(dmg),
        'goldEarned': gold, 'goldSpent': gold, 'gpm': per_min(gold),
        'visionScore': vis, 'vspm': per_min(vis),
        'wardsPlaced':  int(p.get('wardsPlaced',  0)),
        'wardsKilled':  int(p.get('wardsKilled',  0)),
        'killParticipation': int(p.get('killParticipation', 0)),
        'firstBlood':   bool(p.get('firstBlood', False)),
        'soloKills':    int(p.get('soloKills', 0)),
        'effectiveHealAndShielding': 0, 'totalDamageTaken': 0,
        'teamDmgPercent': 0, 'damageTakenPercent': 0,
        'build': [], 'trinket': {}, 'runes': {}, 'summonerSpells': {},
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route('', methods=['GET'], strict_slashes=False)
def get_all_matches():
    """Return all match documents, sorted by game creation timestamp descending."""
    results = list(matches.find({}, {'_id': 0}).sort('info.gameCreation', -1))
    return jsonify(results)


@bp.route('/add', methods=['POST'])
def add_match():
    """Add or update a match from a Riot match ID. Requires admin cookie auth."""
    if err := _cookie_admin_check():
        return err
    data = request.json

    match_id = data['matchId']
    processed = process_match(data)
    match_query = {'metadata.matchId': 'NA1_' + match_id}

    if matches.find_one(match_query):
        update_match(match_query, processed)
        action, status = 'updated', 200
    else:
        save_match(processed)
        action, status = 'added', 201

    _process_matchups(processed)
    return jsonify({'message': f'Match {action} successfully'}), status

@bp.route('/lcc/<lcc_id>', methods=['GET'])
def get_match_by_lcc_id(lcc_id):
    """Return a single match document by its LCC match ID."""
    match_data = matches.find_one({'metadata.matchIdLCC': str(lcc_id)}, {'_id': 0})
    return jsonify({'data': match_data})


@bp.route('/lcc/<lcc_id>/mvp', methods=['PATCH'])
def set_mvp(lcc_id):
    """Assign the MVP for a match identified by its LCC ID. Requires admin cookie auth."""
    if err := _cookie_admin_check():
        return err
    data = request.json
    result = matches.update_one(
        {'metadata.matchIdLCC': str(lcc_id)},
        {'$set': {'metadata.mvp': {'puuid': data.get('puuid'), 'playerName': data.get('playerName')}}}
    )
    if result.matched_count == 0:
        return jsonify({'message': 'Match not found'}), 404
    return jsonify({'message': 'MVP assigned successfully'}), 200


@bp.route('/refresh', methods=['POST'])
def refresh_matches():
    """
    Re-process all matches in the matches_index from the Riot API.

    Iterates every record in matches_index, re-fetches and processes each match,
    then upserts the result and regenerates matchup history. Requires admin password.
    """
    if err := _cookie_admin_check():
        return err
    data = request.json or {}

    index_records = list(matches_index.find({}, {'_id': 0}))
    if not index_records:
        return jsonify({'message': 'No records found in matches_index'}), 404

    added, updated, errors = 0, 0, []
    for record in index_records:
        try:
            match_id = str(record['matchId']).replace('NA1_', '')
            payload = {
                'matchId':  match_id,
                'season':   record['season'],
                'blueTeam': record['blueTeamName'],
                'redTeam':  record['redTeamName'],
            }
            processed = process_match(payload)
            match_query = {'metadata.matchId': 'NA1_' + match_id}
            if matches.find_one(match_query):
                update_match(match_query, processed)
                updated += 1
            else:
                save_match(processed)
                added += 1
            _process_matchups(processed)
        except Exception as e:
            errors.append(f"{record.get('matchId', '?')}: {e}")

    msg = f'Refresh complete: {added} added, {updated} updated'
    if errors:
        msg += f', {len(errors)} errors'
    return jsonify({'message': msg, 'errors': errors}), 200


@bp.route('/manual', methods=['POST'])
def add_manual_match():
    """
    Create or update a manually entered match record. Requires admin cookie auth.

    Accepts a full match payload with blue/red team rosters, game duration in
    seconds, and metadata. Builds normalised player documents and upserts both
    the match document and the matches_index entry.
    """
    if err := _cookie_admin_check():
        return err
    data = request.json

    lcc_id        = str(data['matchIdLCC'])
    season        = str(data['season'])
    duration_secs = int(data.get('gameDuration', 1800))
    mins          = duration_secs / 60
    blue_won      = bool(data.get('blueWon', True))

    blue_players = [_build_player(p, mins) for p in data.get('bluePlayers', [])]
    red_players  = [_build_player(p, mins) for p in data.get('redPlayers',  [])]

    def _team(name_key, side, team_id, won, players):
        return {
            'name': data.get(name_key, ''), 'side': side, 'teamId': team_id,
            'gameOutcome': won,
            'kills': sum(p['kills'] for p in players),
            'gold':  sum(p['goldEarned'] for p in players),
            'players': players, 'bans': [], 'objectives': {},
        }

    match_doc = {
        'metadata': {
            'matchId':    f'MANUAL_{lcc_id}',
            'matchIdLCC': lcc_id,
            'season':     season,
            'matchName':  f"{data.get('blueTeamName', '')} vs {data.get('redTeamName', '')}",
            'participants': [p['profile']['puuid'] for p in blue_players + red_players],
        },
        'info': {
            'gameCreation': 0, 'gameDuration': duration_secs,
            'gameStartTime': 0, 'gameEndTimestamp': 0,
            'gameVersion': data.get('gameVersion', '15.5.1'),
            'gameMode': 'CLASSIC', 'gameId': f'MANUAL_{lcc_id}',
            'teams': [
                _team('blueTeamName', 'Blue', 100,       blue_won, blue_players),
                _team('redTeamName',  'Red',  200, not blue_won,  red_players),
            ],
        },
    }

    match_query = {'metadata.matchId': f'MANUAL_{lcc_id}'}
    if matches.find_one(match_query):
        update_match(match_query, match_doc)
        action, status = 'updated', 200
    else:
        save_match(match_doc)
        action, status = 'added', 201

    matches_index.replace_one(
        {'matchId': f'MANUAL_{lcc_id}'},
        {'matchId': f'MANUAL_{lcc_id}', 'matchIdLCC': lcc_id, 'season': season,
         'blueTeamName': data.get('blueTeamName', ''),
         'redTeamName':  data.get('redTeamName',  '')},
        upsert=True,
    )
    return jsonify({'message': f'Manual match {action} successfully'}), status


@bp.route('/<match_id>', methods=['GET'])
def get_match(match_id):
    """Return a single match document by its Riot match ID (without the NA1_ prefix)."""
    match_data = matches.find_one({'metadata.matchId': 'NA1_' + match_id}, {'_id': 0})
    return jsonify({'data': match_data})


@bp.route('/<match_id>/vod', methods=['PATCH'])
def update_vod(match_id):
    """Set or update the VOD URL for a match. Requires admin cookie auth."""
    if not check_admin_auth(cookie_user_id=request.cookies.get('token')):
        return jsonify({'message': 'Unauthorized'}), 401
    data = request.json
    vod_url = data.get('vod')
    if not vod_url:
        return jsonify({'message': 'No VOD URL provided'}), 400
    result = matches.update_one(
        {'metadata.matchId': 'NA1_' + match_id},
        {'$set': {'info.vod': vod_url}}
    )
    if result.matched_count == 0:
        return jsonify({'message': 'Match not found'}), 404
    return jsonify({'message': 'VOD updated successfully'}), 200

@bp.route('/seasons', methods=['GET'])
def get_seasons():
    """Return a sorted list of all distinct season identifiers present in matches."""
    seasons = matches.distinct("metadata.season")
    seasons.sort(key=lambda s: (int(''.join(filter(str.isdigit, str(s))) or 0), ''.join(c for c in str(s) if not c.isdigit())))
    return jsonify(seasons)

def _player_stats_pipeline(season_match=None):
    """
    Build a MongoDB aggregation pipeline for player statistics.

    Args:
        season_match (dict | None): Optional ``$match`` stage filter, e.g.
            ``{"metadata.season": "S1"}``. Pass ``None`` for all-time stats.

    Returns:
        list: Aggregation pipeline stages ready for ``collection.aggregate()``.
    """
    pipeline = []
    if season_match:
        pipeline.append({'$match': season_match})
    pipeline += [
        {'$sort': {'info.gameCreation': 1}},
        {'$unwind': '$info.teams'},
        {'$unwind': '$info.teams.players'},
        # Remap duplicate PUUID to the canonical account before grouping
        {'$set': {
            'info.teams.players.profile.puuid': {
                '$cond': {
                    'if':   {'$eq': ['$info.teams.players.profile.puuid', _MERGE_OLD_PUUID]},
                    'then': _MERGE_NEW_PUUID,
                    'else': '$info.teams.players.profile.puuid',
                }
            }
        }},
        {'$group': {
            '_id':                        '$info.teams.players.profile.puuid',
            'playerName':                 {'$last': '$info.teams.players.profile.name'},
            'team':                       {'$last': '$info.teams.name'},
            'games':                      {'$sum': 1},
            'minutesPlayed':              {'$sum': {'$divide': ['$info.gameDuration', 60]}},
            'wins':                       {'$sum': {'$cond': [{'$eq': ['$info.teams.gameOutcome', True]}, 1, 0]}},
            'kills':                      {'$sum': '$info.teams.players.kills'},
            'deaths':                     {'$sum': '$info.teams.players.deaths'},
            'assists':                    {'$sum': '$info.teams.players.assists'},
            'totalDamage':                {'$sum': '$info.teams.players.dmg'},
            'totalDamageTaken':           {'$sum': '$info.teams.players.totalDamageTaken'},
            'totalGold':                  {'$sum': '$info.teams.players.goldEarned'},
            'goldSpent':                  {'$sum': '$info.teams.players.goldSpent'},
            'visionScore':                {'$sum': '$info.teams.players.visionScore'},
            'wardsPlaced':                {'$sum': '$info.teams.players.wardsPlaced'},
            'wardsKilled':                {'$sum': '$info.teams.players.wardsKilled'},
            'totalCs':                    {'$sum': '$info.teams.players.cs'},
            'totalCs14':                  {'$sum': '$info.teams.players.cs14'},
            'totalCsd14':                 {'$sum': '$info.teams.players.csd'},
            'championsPlayed':            {'$addToSet': '$info.teams.players.champion.name'},
            'roles':                      {'$addToSet': '$info.teams.players.role'},
            'soloKills':                  {'$sum': '$info.teams.players.soloKills'},
            'effectiveHealAndShielding':  {'$sum': {'$ifNull': ['$info.teams.players.effectiveHealAndShielding', 0]}},
            'firstBloods':                {'$sum': {'$cond': [{'$eq': ['$info.teams.players.firstBlood', True]}, 1, 0]}},
            'killParticipationSum':        {'$sum': '$info.teams.players.killParticipation'},
        }},
        {'$project': {
            '_id':                          0,
            'puuid':                        '$_id',
            'playerName':                   1,
            'team':                         1,
            'rolesPlayed':                  '$roles',
            'games':                        1,
            'minutesPlayed':                1,
            'avgGameTime':                  {'$divide': ['$minutesPlayed', '$games']},
            'wins':                         1,
            'losses':                       {'$subtract': ['$games', '$wins']},
            'winRate':                      {'$multiply': [{'$divide': ['$wins', '$games']}, 100]},
            'kills':                        1,
            'deaths':                       1,
            'assists':                      1,
            'kda':                          {'$cond': [{'$eq': ['$deaths', 0]}, {'$add': ['$kills', '$assists']}, {'$divide': [{'$add': ['$kills', '$assists']}, '$deaths']}]},
            'killParticipationPercentage':  {'$divide': ['$killParticipationSum', '$games']},
            'totalDamage':                  1,
            'dpm':                          {'$divide': ['$totalDamage', '$minutesPlayed']},
            'damagePerGold':                {'$divide': ['$totalDamage', '$totalGold']},
            'totalDamageTaken':             1,
            'avgDamageTaken':               {'$divide': ['$totalDamageTaken', '$games']},
            'totalGold':                    1,
            'gpm':                          {'$divide': ['$totalGold', '$minutesPlayed']},
            'unspentGold':                  {'$subtract': ['$totalGold', '$goldSpent']},
            'totalCs':                      1,
            'avgCs14':                      {'$divide': ['$totalCs14', '$games']},
            'totalCsd14':                   1,
            'avgCsd14':                     {'$divide': ['$totalCsd14', '$games']},
            'avgCS':                        {'$divide': ['$totalCs', '$games']},
            'csm':                          {'$divide': ['$totalCs', '$minutesPlayed']},
            'wardsPlaced':                  1,
            'wardsKilled':                  1,
            'visionScore':                  1,
            'vspm':                         {'$divide': ['$visionScore', '$minutesPlayed']},
            'avgVisionScore':               {'$divide': ['$visionScore', '$games']},
            'championsPlayed':              1,
            'uniqueChampionsCount':         {'$size': '$championsPlayed'},
            'firstBloods':                  1,
            'soloKills':                    1,
            'avgSoloKills':                 {'$divide': ['$soloKills', '$games']},
            'effectiveHealAndShielding':    1,
            'avgHealShield':                {'$divide': ['$effectiveHealAndShielding', '$games']},
        }},
        {'$sort': {'winRate': -1}},
    ]
    return pipeline

@bp.route('/stats/season/<season_id>', methods=['GET'])
def get_player_season_stats(season_id):
    """Return aggregated player statistics for the specified season."""
    pipeline = _player_stats_pipeline({"metadata.season": str(season_id)})
    results = list(matches.aggregate(pipeline))
    return jsonify(results)

@bp.route('/stats/alltime', methods=['GET'])
def get_player_alltime_stats():
    """Return aggregated player statistics across all seasons."""
    pipeline = _player_stats_pipeline()
    results = list(matches.aggregate(pipeline))
    return jsonify(results)

def _champion_stats_pipeline(season_match=None):
    """
    Build a MongoDB aggregation pipeline for champion statistics.

    Args:
        season_match (dict | None): Optional ``$match`` stage filter, e.g.
            ``{"metadata.season": "S1"}``. Pass ``None`` for all-time stats.

    Returns:
        list: Aggregation pipeline stages ready for ``collection.aggregate()``.
    """
    pipeline = []
    if season_match:
        pipeline.append({'$match': season_match})
    pipeline += [
        {'$unwind': '$info.teams'},
        {'$unwind': '$info.teams.players'},
        {'$group': {
            '_id':                  '$info.teams.players.champion.name',
            'championImage':        {'$first': '$info.teams.players.champion.image.square'},
            'games':                {'$sum': 1},
            'minutesPlayed':        {'$sum': {'$divide': ['$info.gameDuration', 60]}},
            'wins':                 {'$sum': {'$cond': [{'$eq': ['$info.teams.gameOutcome', True]}, 1, 0]}},
            'kills':                {'$sum': '$info.teams.players.kills'},
            'deaths':               {'$sum': '$info.teams.players.deaths'},
            'assists':              {'$sum': '$info.teams.players.assists'},
            'totalDamage':          {'$sum': '$info.teams.players.dmg'},
            'totalGold':            {'$sum': '$info.teams.players.goldEarned'},
            'totalCs':              {'$sum': '$info.teams.players.cs'},
            'totalCs14':            {'$sum': '$info.teams.players.cs14'},
            'totalCsd14':           {'$sum': '$info.teams.players.csd'},
            'visionScore':          {'$sum': '$info.teams.players.visionScore'},
            'killParticipationSum': {'$sum': '$info.teams.players.killParticipation'},
            'firstBloods':          {'$sum': {'$cond': [{'$eq': ['$info.teams.players.firstBlood', True]}, 1, 0]}},
            'soloKills':            {'$sum': '$info.teams.players.soloKills'},
            'uniquePlayers':        {'$addToSet': '$info.teams.players.profile.puuid'},
        }},
        {'$project': {
            '_id':                   0,
            'champion':              '$_id',
            'championImage':         1,
            'games':                 1,
            'wins':                  1,
            'losses':                {'$subtract': ['$games', '$wins']},
            'winRate':               {'$multiply': [{'$divide': ['$wins', '$games']}, 100]},
            'avgKills':              {'$divide': ['$kills', '$games']},
            'avgDeaths':             {'$divide': ['$deaths', '$games']},
            'avgAssists':            {'$divide': ['$assists', '$games']},
            'kda':                   {'$cond': [
                {'$eq': ['$deaths', 0]},
                {'$add': ['$kills', '$assists']},
                {'$divide': [{'$add': ['$kills', '$assists']}, '$deaths']},
            ]},
            'avgKillParticipation':  {'$divide': ['$killParticipationSum', '$games']},
            'dpm':                   {'$divide': ['$totalDamage', '$minutesPlayed']},
            'avgDamage':             {'$divide': ['$totalDamage', '$games']},
            'gpm':                   {'$divide': ['$totalGold', '$minutesPlayed']},
            'avgGold':               {'$divide': ['$totalGold', '$games']},
            'csm':                   {'$divide': ['$totalCs', '$minutesPlayed']},
            'avgCs':                 {'$divide': ['$totalCs', '$games']},
            'avgCs14':               {'$divide': ['$totalCs14', '$games']},
            'avgCsd14':              {'$divide': ['$totalCsd14', '$games']},
            'vspm':                  {'$divide': ['$visionScore', '$minutesPlayed']},
            'avgVisionScore':        {'$divide': ['$visionScore', '$games']},
            'firstBloods':           1,
            'soloKills':             1,
            'uniquePlayersCount':    {'$size': '$uniquePlayers'},
        }},
        {'$sort': {'games': -1}},
    ]
    return pipeline

@bp.route('/champion-stats/season/<season_id>', methods=['GET'])
def get_champion_season_stats(season_id):
    """Return aggregated champion statistics for the specified season."""
    pipeline = _champion_stats_pipeline({"metadata.season": str(season_id)})
    results = list(matches.aggregate(pipeline))
    return jsonify(results)

@bp.route('/champion-stats/alltime', methods=['GET'])
def get_champion_alltime_stats():
    """Return aggregated champion statistics across all seasons."""
    pipeline = _champion_stats_pipeline()
    results = list(matches.aggregate(pipeline))
    return jsonify(results)

@bp.route('/champion/<champion_name>/matches', methods=['GET'])
def get_matches_by_champion(champion_name):
    """
    Return all individual match appearances for a given champion.

    Accepts an optional ``season`` query parameter to filter results.
    Results are sorted by game creation timestamp descending.
    """
    season = request.args.get('season', None)
    pipeline = []
    if season:
        pipeline.append({'$match': {'metadata.season': str(season)}})
    pipeline += [
        {'$unwind': '$info.teams'},
        {'$unwind': '$info.teams.players'},
        {'$match': {'info.teams.players.champion.name': champion_name}},
        {'$project': {
            '_id':              0,
            'matchId':          '$metadata.matchId',
            'season':           '$metadata.season',
            'gameCreation':     '$info.gameCreation',
            'gameDuration':     '$info.gameDuration',
            'gameVersion':      '$info.gameVersion',
            'teamName':         '$info.teams.name',
            'win':              '$info.teams.gameOutcome',
            'playerName':       '$info.teams.players.profile.name',
            'puuid':            '$info.teams.players.profile.puuid',
            'kills':            '$info.teams.players.kills',
            'deaths':           '$info.teams.players.deaths',
            'assists':          '$info.teams.players.assists',
            'kda':              '$info.teams.players.kda',
            'cs':               '$info.teams.players.cs',
            'cs14':             '$info.teams.players.cs14',
            'csd':              '$info.teams.players.csd',
            'dmg':              '$info.teams.players.dmg',
            'dpm':              '$info.teams.players.dpm',
            'goldEarned':       '$info.teams.players.goldEarned',
            'killParticipation':'$info.teams.players.killParticipation',
            'visionScore':      '$info.teams.players.visionScore',
        }},
        {'$sort': {'gameCreation': -1}},
    ]
    results = list(matches.aggregate(pipeline))
    return jsonify(results)

