import os
from flask import request, jsonify, Blueprint
from .mongo_connection import MongoConnection
from .process_match_reports import process_match, get_matchups
from .players import save_match_history

bp = Blueprint('matches', __name__, url_prefix='/matches')

matches = MongoConnection().get_matches_collection()

@bp.route('/add', methods=['POST'])
def add_match():
    password = os.getenv("ADMIN_PW")
    data = request.json
    if(data["password"] != password):
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

@bp.route('/', methods=['GET'])
def get_all_matches():
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

@bp.route('/stats/season/<season_id>', methods=['GET'])
def get_player_season_stats(season_id):
    """Get aggregate stats for all players in a specific season"""
    pipeline = [
        # Match only documents from the current season
        {"$match": {"metadata.season": str(season_id)}},
        
        # Unwind teams to process each team separately
        {"$unwind": "$info.teams"},
        
        # Unwind players to process each player separately
        {"$unwind": "$info.teams.players"},
        
        # Group by player
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
        
        # Calculate additional stats
        {"$project": {
            "_id": 0,
            "puuid": "$_id",
            "playerName": 1,
            "team": 1,
            "rolesPlayed": "$roles",
            # Game Info
            "games": 1,
            "minutesPlayed": 1,
            "avgGameTime": {"$divide": ["$minutesPlayed", "$games"]},
            "wins": 1,
            "losses": {"$subtract": ["$games", "$wins"]},
            "winRate": {"$multiply": [{"$divide": ["$wins", "$games"]}, 100]},
            # KDA
            "kills": 1,
            "deaths": 1,
            "assists": 1,
            "kda": {"$cond": [
                {"$eq": ["$deaths", 0]},
                {"$add": ["$kills", "$assists"]},
                {"$divide": [{"$add": ["$kills", "$assists"]}, "$deaths"]}
            ]},
            "avgKills": {"$divide": ["$kills", "$games"]},
            "avgDeaths": {"$divide": ["$deaths", "$games"]},
            "avgAssists": {"$divide": ["$assists", "$games"]},
            "killParticipationPercentage": {"$divide": ["$killParticipationSum", "$games"]},
            # Damage
            "totalDamage": 1,
            "avgDamagePerGame": {"$divide": ["$totalDamage", "$games"]},
            "dpm": {"$divide": ["$totalDamage", "$minutesPlayed"]},
            "damagePerGold": {"$divide": ["$totalDamage", "$totalGold"]},
            
            "totalDamageTaken": 1,
            "avgDamageTaken": {"$divide": ["$totalDamageTaken", "$games"]},

            # Gold
            "totalGold": 1,
            "gpm": {"$divide": ["$totalGold", "$minutesPlayed"]},
            "unspentGold": {"$subtract": ["$totalGold", "$goldSpent"]},

            #CS
            "totalCs": 1,
            "avgCs14": {"$divide": ["$totalCs14", "$games"]},
            "totalCsd14": 1,
            "avgCsd14": {"$divide": ["$totalCsd14", "$games"]},
            "avgCS": {"$divide": ["$totalCs", "$games"]},
            "csm": {"$divide": ["$totalCs", "$minutesPlayed"]},
            
            #Vision
            "wardsPlaced": 1,
            "wardsKilled": 1,
            "visionScore": 1,
            "vspm": {"$divide": ["$visionScore", "$minutesPlayed"]},
            "wardsPerMinute": {"$divide": ["$wardsPlaced", "$minutesPlayed"]},
            "avgVisionScore": {"$divide": ["$visionScore", "$games"]},
            
            # Champions
            "championsPlayed": 1,
            "uniqueChampionsCount": {"$size": "$championsPlayed"},
            
            # Etc
            "firstBloods": 1,
            "soloKills": 1,
            "avgSoloKills": {"$divide": ["$soloKills", "$games"]},
            
            "effectiveHealAndShielding": 1,
            "avgHealShield": {"$divide": ["$effectiveHealAndShielding", "$games"]},
            
        }},
        
        # Sort by win rate descending
        {"$sort": {"winRate": -1}}
    ]
    
    results = list(matches.aggregate(pipeline))
    return jsonify(results)