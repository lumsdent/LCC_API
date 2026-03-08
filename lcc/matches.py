import os
from flask import request, jsonify, Blueprint
from .mongo_connection import MongoConnection
from .process_match_reports import process_match, get_matchups
from .players import save_match_history

bp = Blueprint('matches', __name__, url_prefix='/matches')

matches = MongoConnection().get_matches_collection()
matches_index = MongoConnection().get_match_index_collection()

@bp.route('/add', methods=['POST'])
def add_match():
    password = os.getenv("ADMIN_PW")
    data = request.json
    if data["password"] != password:
        return jsonify({'message': 'Incorrect password'}), 401
   
    print('Processing match')
    match_id = data["matchId"]
    processed_match = process_match(data)
    match_query = {"metadata.matchId": "NA1_" + match_id}
    
    # Check if match exists
    existing_match = matches.find_one(match_query)
    is_new_match = existing_match is None
    
    if is_new_match:
        # Insert new match
        save_match(processed_match)
        action = "added"
    else:
        # Update existing match
        update_match(match_query, processed_match)
        action = "updated"
    
    # Process matchups regardless if new or updated
    roles = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "SUPPORT"]
    matchups_data = []
    for role in roles:
        matchups = get_matchups(processed_match, role)
        matchups_data.extend(matchups)
    
    for matchup in matchups_data:
        save_matchup(matchup)
    
    status_code = 201 if is_new_match else 200
    return jsonify({'message': f'Match {action} successfully'}), status_code

@bp.route('/lcc/<lcc_id>', methods=['GET'])
def get_match_by_lcc_id(lcc_id):
    match_data = matches.find_one({'metadata.matchIdLCC': str(lcc_id)}, {'_id': 0})
    return jsonify({'data': match_data})


@bp.route('/lcc/<lcc_id>/mvp', methods=['PATCH'])
def set_mvp(lcc_id):
    password = os.getenv('ADMIN_PW')
    data = request.json
    if data.get('password') != password:
        return jsonify({'message': 'Incorrect password'}), 401
    mvp = {'puuid': data.get('puuid'), 'playerName': data.get('playerName')}
    result = matches.update_one(
        {'metadata.matchIdLCC': str(lcc_id)},
        {'$set': {'metadata.mvp': mvp}}
    )
    if result.matched_count == 0:
        return jsonify({'message': 'Match not found'}), 404
    return jsonify({'message': 'MVP assigned successfully'}), 200


@bp.route('/refresh', methods=['POST'])
def refresh_matches():
    password = os.getenv('ADMIN_PW')
    data = request.json
    if data.get('password') != password:
        return jsonify({'message': 'Incorrect password'}), 401
    index_records = list(matches_index.find({}, {'_id': 0}))
    if not index_records:
        return jsonify({'message': 'No records found in matches_index'}), 404
    added, updated, errors = 0, 0, []
    for record in index_records:
        try:
            match_id_clean = str(record['matchId']).replace('NA1_', '')
            payload = {
                'matchId':  match_id_clean,
                'season':   record['season'],
                'blueTeam': record['blueTeamName'],
                'redTeam':  record['redTeamName'],
                'password': data['password'],
            }
            processed = process_match(payload)
            match_query = {'metadata.matchId': 'NA1_' + match_id_clean}
            existing = matches.find_one(match_query)
            if existing:
                update_match(match_query, processed)
                updated += 1
            else:
                save_match(processed)
                added += 1
            roles = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'SUPPORT']
            for role in roles:
                for matchup in get_matchups(processed, role):
                    save_matchup(matchup)
        except Exception as e:
            errors.append(f"{record.get('matchId', '?')}: {str(e)}")
    msg = f'Refresh complete: {added} added, {updated} updated'
    if errors:
        msg += f', {len(errors)} errors'
    return jsonify({'message': msg, 'errors': errors}), 200


@bp.route('/manual', methods=['POST'])
def add_manual_match():
    password = os.getenv('ADMIN_PW')
    data = request.json
    if data.get('password') != password:
        return jsonify({'message': 'Incorrect password'}), 401

    lcc_id = str(data['matchIdLCC'])
    season = str(data['season'])
    duration_secs = int(data.get('gameDuration', 1800))
    mins = duration_secs / 60
    blue_won = bool(data.get('blueWon', True))

    def build_player(p):
        k, d, a = int(p.get('kills', 0)), int(p.get('deaths', 0)), int(p.get('assists', 0))
        kda = round((k + a) / d, 2) if d > 0 else float(k + a)
        cs, dmg, gold, vis = int(p.get('cs', 0)), int(p.get('dmg', 0)), int(p.get('goldEarned', 0)), int(p.get('visionScore', 0))
        return {
            'role':    p.get('role', ''),
            'profile': {'puuid': p.get('puuid', ''), 'name': p.get('name', '')},
            'champion': {'name': p.get('champion', ''), 'level': 18,
                         'image': {'square': f"/img/champion/{p.get('champion', '')}.png"}},
            'kills': k, 'deaths': d, 'assists': a, 'kda': kda,
            'cs':  cs,  'cs14': int(p.get('cs14', 0)), 'csd': int(p.get('csd', 0)),
            'csm': round(cs / mins, 2) if mins else 0,
            'dmg': dmg, 'dpm': round(dmg / mins, 2) if mins else 0,
            'goldEarned': gold, 'goldSpent': gold,
            'gpm': round(gold / mins, 2) if mins else 0,
            'visionScore': vis, 'vspm': round(vis / mins, 2) if mins else 0,
            'wardsPlaced':  int(p.get('wardsPlaced',  0)),
            'wardsKilled':  int(p.get('wardsKilled',  0)),
            'killParticipation': int(p.get('killParticipation', 0)),
            'firstBlood':   bool(p.get('firstBlood', False)),
            'soloKills':    int(p.get('soloKills', 0)),
            'effectiveHealAndShielding': 0, 'totalDamageTaken': 0,
            'teamDmgPercent': 0, 'damageTakenPercent': 0,
            'build': [], 'trinket': {}, 'runes': {}, 'summonerSpells': {},
        }

    blue_players = [build_player(p) for p in data.get('bluePlayers', [])]
    red_players  = [build_player(p) for p in data.get('redPlayers',  [])]

    blue_team = {
        'name': data.get('blueTeamName', ''), 'side': 'Blue', 'teamId': 100,
        'gameOutcome': blue_won,
        'kills': sum(p['kills'] for p in blue_players),
        'gold':  sum(p['goldEarned'] for p in blue_players),
        'players': blue_players, 'bans': [], 'objectives': {},
    }
    red_team = {
        'name': data.get('redTeamName', ''), 'side': 'Red', 'teamId': 200,
        'gameOutcome': not blue_won,
        'kills': sum(p['kills'] for p in red_players),
        'gold':  sum(p['goldEarned'] for p in red_players),
        'players': red_players, 'bans': [], 'objectives': {},
    }

    match_doc = {
        'metadata': {
            'matchId':   f'MANUAL_{lcc_id}',
            'matchIdLCC': lcc_id,
            'season':    season,
            'matchName': f"{data.get('blueTeamName', '')} vs {data.get('redTeamName', '')}",
            'participants': [p['profile']['puuid'] for p in blue_players + red_players],
        },
        'info': {
            'gameCreation': 0, 'gameDuration': duration_secs,
            'gameStartTime': 0, 'gameEndTimestamp': 0,
            'gameVersion': data.get('gameVersion', '15.5.1'),
            'gameMode': 'CLASSIC', 'gameId': f'MANUAL_{lcc_id}',
            'teams': [blue_team, red_team],
        },
    }

    match_query = {'metadata.matchId': f'MANUAL_{lcc_id}'}
    existing = matches.find_one(match_query)
    if existing:
        update_match(match_query, match_doc)
        action = 'updated'
    else:
        save_match(match_doc)
        action = 'added'

    matches_index.replace_one(
        {'matchId': f'MANUAL_{lcc_id}'},
        {'matchId': f'MANUAL_{lcc_id}', 'matchIdLCC': lcc_id, 'season': season,
         'blueTeamName': data.get('blueTeamName', ''),
         'redTeamName':  data.get('redTeamName',  '')},
        upsert=True,
    )

    return jsonify({'message': f'Manual match {action} successfully'}), 201 if action == 'added' else 200



    match_data = list(matches.find({}, {'_id': 0}))
    return jsonify(match_data)

@bp.route('/<match_id>', methods=['GET'])
def get_match(match_id):
    match_data = matches.find_one({"metadata.matchId": "NA1_" + match_id}, {'_id': 0})
    return jsonify({"data" :match_data})

def save_match(data):
    matches.insert_one(data)

def update_match(query, data):
    matches.replace_one(query, data)

@bp.route('/<match_id>/vod', methods=['PATCH'])
def update_vod(match_id):
    password = os.getenv("ADMIN_PW")
    data = request.json
    if data.get("password") != password:
        return jsonify({'message': 'Incorrect password'}), 401
    vod_url = data.get("vod")
    if not vod_url:
        return jsonify({'message': 'No VOD URL provided'}), 400
    result = matches.update_one(
        {"metadata.matchId": "NA1_" + match_id},
        {"$set": {"info.vod": vod_url}}
    )
    if result.matched_count == 0:
        return jsonify({'message': 'Match not found'}), 404
    return jsonify({'message': 'VOD updated successfully'}), 200
    
def save_matchup(matchup):
    save_match_history(matchup)

@bp.route('/seasons', methods=['GET'])
def get_seasons():
    seasons = matches.distinct("metadata.season")
    seasons.sort(key=lambda s: (int(''.join(filter(str.isdigit, str(s))) or 0), ''.join(c for c in str(s) if not c.isdigit())))
    return jsonify(seasons)

def _player_stats_pipeline(season_match=None):
    pipeline = []
    if season_match:
        pipeline.append({"$match": season_match})
    pipeline += [
        {"$unwind": "$info.teams"},
        {"$unwind": "$info.teams.players"},
        {"$group": {
            "_id": "$info.teams.players.profile.puuid",
            "playerName": {"$first": "$info.teams.players.profile.name"},
            "team": {"$first": "$info.teams.name"},
            "games": {"$sum": 1},
            "minutesPlayed": {"$sum": {"$divide": ["$info.gameDuration", 60]}},
            "wins": {"$sum": {"$cond": [{"$eq": ["$info.teams.gameOutcome", True]}, 1, 0]}},
            "kills": {"$sum": "$info.teams.players.kills"},
            "deaths": {"$sum": "$info.teams.players.deaths"},
            "assists": {"$sum": "$info.teams.players.assists"},
            "totalDamage": {"$sum": "$info.teams.players.dmg"},
            "totalDamageTaken": {"$sum": "$info.teams.players.totalDamageTaken"},
            "totalGold": {"$sum": "$info.teams.players.goldEarned"},
            "goldSpent": {"$sum": "$info.teams.players.goldSpent"},
            "visionScore": {"$sum": "$info.teams.players.visionScore"},
            "wardsPlaced": {"$sum": "$info.teams.players.wardsPlaced"},
            "wardsKilled": {"$sum": "$info.teams.players.wardsKilled"},
            "totalCs": {"$sum": "$info.teams.players.cs"},
            "totalCs14": {"$sum": "$info.teams.players.cs14"},
            "totalCsd14": {"$sum": "$info.teams.players.csd"},
            "championsPlayed": {"$addToSet": "$info.teams.players.champion.name"},
            "roles": {"$addToSet": "$info.teams.players.role"},
            "soloKills": {"$sum": "$info.teams.players.soloKills"},
            "effectiveHealAndShielding": {"$sum": {"$ifNull": ["$info.teams.players.effectiveHealAndShielding", 0]}},
            "firstBloods": {"$sum": {"$cond": [{"$eq": ["$info.teams.players.firstBlood", True]}, 1, 0]}},
            "killParticipationSum": {"$sum": "$info.teams.players.killParticipation"},
        }},
        {"$project": {
            "_id": 0,
            "puuid": "$_id",
            "playerName": 1,
            "team": 1,
            "rolesPlayed": "$roles",
            "games": 1,
            "minutesPlayed": 1,
            "avgGameTime": {"$divide": ["$minutesPlayed", "$games"]},
            "wins": 1,
            "losses": {"$subtract": ["$games", "$wins"]},
            "winRate": {"$multiply": [{"$divide": ["$wins", "$games"]}, 100]},
            "kills": 1,
            "deaths": 1,
            "assists": 1,
            "kda": {"$cond": [{"$eq": ["$deaths", 0]}, {"$add": ["$kills", "$assists"]}, {"$divide": [{"$add": ["$kills", "$assists"]}, "$deaths"]}]},
            "killParticipationPercentage": {"$divide": ["$killParticipationSum", "$games"]},
            "totalDamage": 1,
            "dpm": {"$divide": ["$totalDamage", "$minutesPlayed"]},
            "damagePerGold": {"$divide": ["$totalDamage", "$totalGold"]},
            "totalDamageTaken": 1,
            "avgDamageTaken": {"$divide": ["$totalDamageTaken", "$games"]},
            "totalGold": 1,
            "gpm": {"$divide": ["$totalGold", "$minutesPlayed"]},
            "unspentGold": {"$subtract": ["$totalGold", "$goldSpent"]},
            "totalCs": 1,
            "avgCs14": {"$divide": ["$totalCs14", "$games"]},
            "totalCsd14": 1,
            "avgCsd14": {"$divide": ["$totalCsd14", "$games"]},
            "avgCS": {"$divide": ["$totalCs", "$games"]},
            "csm": {"$divide": ["$totalCs", "$minutesPlayed"]},
            "wardsPlaced": 1,
            "wardsKilled": 1,
            "visionScore": 1,
            "vspm": {"$divide": ["$visionScore", "$minutesPlayed"]},
            "avgVisionScore": {"$divide": ["$visionScore", "$games"]},
            "championsPlayed": 1,
            "uniqueChampionsCount": {"$size": "$championsPlayed"},
            "firstBloods": 1,
            "soloKills": 1,
            "avgSoloKills": {"$divide": ["$soloKills", "$games"]},
            "effectiveHealAndShielding": 1,
            "avgHealShield": {"$divide": ["$effectiveHealAndShielding", "$games"]},
        }},
        {"$sort": {"winRate": -1}}
    ]
    return pipeline

@bp.route('/stats/season/<season_id>', methods=['GET'])
def get_player_season_stats(season_id):
    pipeline = _player_stats_pipeline({"metadata.season": str(season_id)})
    results = list(matches.aggregate(pipeline))
    return jsonify(results)

@bp.route('/stats/alltime', methods=['GET'])
def get_player_alltime_stats():
    pipeline = _player_stats_pipeline()
    results = list(matches.aggregate(pipeline))
    return jsonify(results)

def _champion_stats_pipeline(season_match=None):
    pipeline = []
    if season_match:
        pipeline.append({"$match": season_match})
    pipeline += [
        {"$unwind": "$info.teams"},
        {"$unwind": "$info.teams.players"},
        {"$group": {
            "_id": "$info.teams.players.champion.name",
            "championImage": {"$first": "$info.teams.players.champion.image.square"},
            "games": {"$sum": 1},
            "minutesPlayed": {"$sum": {"$divide": ["$info.gameDuration", 60]}},
            "wins": {"$sum": {"$cond": [{"$eq": ["$info.teams.gameOutcome", True]}, 1, 0]}},
            "kills": {"$sum": "$info.teams.players.kills"},
            "deaths": {"$sum": "$info.teams.players.deaths"},
            "assists": {"$sum": "$info.teams.players.assists"},
            "totalDamage": {"$sum": "$info.teams.players.dmg"},
            "totalGold": {"$sum": "$info.teams.players.goldEarned"},
            "totalCs": {"$sum": "$info.teams.players.cs"},
            "totalCs14": {"$sum": "$info.teams.players.cs14"},
            "totalCsd14": {"$sum": "$info.teams.players.csd"},
            "visionScore": {"$sum": "$info.teams.players.visionScore"},
            "killParticipationSum": {"$sum": "$info.teams.players.killParticipation"},
            "firstBloods": {"$sum": {"$cond": [{"$eq": ["$info.teams.players.firstBlood", True]}, 1, 0]}},
            "soloKills": {"$sum": "$info.teams.players.soloKills"},
            "uniquePlayers": {"$addToSet": "$info.teams.players.profile.puuid"},
        }},
        {"$project": {
            "_id": 0,
            "champion": "$_id",
            "championImage": 1,
            "games": 1,
            "wins": 1,
            "losses": {"$subtract": ["$games", "$wins"]},
            "winRate": {"$multiply": [{"$divide": ["$wins", "$games"]}, 100]},
            "avgKills": {"$divide": ["$kills", "$games"]},
            "avgDeaths": {"$divide": ["$deaths", "$games"]},
            "avgAssists": {"$divide": ["$assists", "$games"]},
            "kda": {"$cond": [
                {"$eq": ["$deaths", 0]},
                {"$add": ["$kills", "$assists"]},
                {"$divide": [{"$add": ["$kills", "$assists"]}, "$deaths"]}
            ]},
            "avgKillParticipation": {"$divide": ["$killParticipationSum", "$games"]},
            "dpm": {"$divide": ["$totalDamage", "$minutesPlayed"]},
            "avgDamage": {"$divide": ["$totalDamage", "$games"]},
            "gpm": {"$divide": ["$totalGold", "$minutesPlayed"]},
            "avgGold": {"$divide": ["$totalGold", "$games"]},
            "csm": {"$divide": ["$totalCs", "$minutesPlayed"]},
            "avgCs": {"$divide": ["$totalCs", "$games"]},
            "avgCs14": {"$divide": ["$totalCs14", "$games"]},
            "avgCsd14": {"$divide": ["$totalCsd14", "$games"]},
            "vspm": {"$divide": ["$visionScore", "$minutesPlayed"]},
            "avgVisionScore": {"$divide": ["$visionScore", "$games"]},
            "firstBloods": 1,
            "soloKills": 1,
            "uniquePlayersCount": {"$size": "$uniquePlayers"},
        }},
        {"$sort": {"games": -1}},
    ]
    return pipeline

@bp.route('/champion-stats/season/<season_id>', methods=['GET'])
def get_champion_season_stats(season_id):
    pipeline = _champion_stats_pipeline({"metadata.season": str(season_id)})
    results = list(matches.aggregate(pipeline))
    return jsonify(results)

@bp.route('/champion-stats/alltime', methods=['GET'])
def get_champion_alltime_stats():
    pipeline = _champion_stats_pipeline()
    results = list(matches.aggregate(pipeline))
    return jsonify(results)

@bp.route('/champion/<champion_name>/matches', methods=['GET'])
def get_matches_by_champion(champion_name):
    season = request.args.get('season', None)
    pipeline = []
    if season:
        pipeline.append({"$match": {"metadata.season": str(season)}})
    pipeline += [
        {"$unwind": "$info.teams"},
        {"$unwind": "$info.teams.players"},
        {"$match": {"info.teams.players.champion.name": champion_name}},
        {"$project": {
            "_id": 0,
            "matchId": "$metadata.matchId",
            "season": "$metadata.season",
            "gameCreation": "$info.gameCreation",
            "gameDuration": "$info.gameDuration",
            "gameVersion": "$info.gameVersion",
            "teamName": "$info.teams.name",
            "win": "$info.teams.gameOutcome",
            "playerName": "$info.teams.players.profile.name",
            "puuid": "$info.teams.players.profile.puuid",
            "kills": "$info.teams.players.kills",
            "deaths": "$info.teams.players.deaths",
            "assists": "$info.teams.players.assists",
            "kda": "$info.teams.players.kda",
            "cs": "$info.teams.players.cs",
            "cs14": "$info.teams.players.cs14",
            "csd": "$info.teams.players.csd",
            "dmg": "$info.teams.players.dmg",
            "dpm": "$info.teams.players.dpm",
            "goldEarned": "$info.teams.players.goldEarned",
            "killParticipation": "$info.teams.players.killParticipation",
            "visionScore": "$info.teams.players.visionScore",
        }},
        {"$sort": {"gameCreation": -1}},
    ]
    results = list(matches.aggregate(pipeline))
    return jsonify(results)

