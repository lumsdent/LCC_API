"""
teams.py
--------
Flask Blueprint providing all team-related API endpoints for the LCC API.

Includes routes for creating and querying teams, managing rosters by season,
assigning players, and aggregating win/loss records.
"""
from bson import ObjectId
from datetime import datetime
from flask import request, jsonify, Blueprint
from .mongo_connection import MongoConnection
from .players import add_team_to_player

bp = Blueprint('teams', __name__)

_db = MongoConnection()
teams = _db.get_teams_collection()
matches = _db.get_matches_collection()


# ── Helpers ───────────────────────────────────────────────────────────────────

def convert_object_ids(document):
    """Recursively convert all ObjectId values in a document to strings."""
    if isinstance(document, list):
        return [convert_object_ids(item) for item in document]
    if isinstance(document, dict):
        return {key: convert_object_ids(value) for key, value in document.items()}
    if isinstance(document, ObjectId):
        return str(document)
    return document


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route('/teams/<season>/add', methods=['POST'])
def add_team(season):
    """Add a new team or update an existing team's roster for a season."""
    data = request.json
    roster = data.get('roster', [])
    if teams.find_one({'team_name': data['teamName']}) is None:
        teams.insert_one({'team_name': data['teamName'], 'rosters': {season: roster}, 'image': data['image']})
        return jsonify({'message': 'Team added successfully'})
    if teams.find_one({'team_name': data['teamName'], f'rosters.{season}': {'$exists': False}}):
        teams.update_one(
            {'team_name': data['teamName']},
            {'$set': {f'rosters.{season}': roster, 'image': data['image']}}
        )
        return jsonify({'message': 'Team roster updated'})
    return jsonify({'message': 'Team already exists'})
 
@bp.route('/teams/all', methods=['GET'])
def get_all_teams():
    """Return all team documents."""
    team_data = list(teams.find({}, {'_id': 0}))
    return jsonify(team_data)

@bp.route('/teams/records', methods=['GET'])
def get_team_records():
    """Aggregate wins/losses/rosters across all provided team_ids into a single combined record."""
    team_ids_param = request.args.get('team_ids', '')
    if not team_ids_param:
        return jsonify({'message': 'team_ids parameter is required'}), 400
    team_ids = [tid.strip() for tid in team_ids_param.split(',') if tid.strip()]

    # Fetch a doc for each team_id — each is a separate team name in MongoDB
    team_docs = list(teams.find({'team_name': {'$in': team_ids}}, {'_id': 0, 'team_name': 1, 'rosters': 1}))
    if not team_docs:
        return jsonify({'message': 'No teams found'}), 404

    all_team_names = [doc['team_name'] for doc in team_docs]

    pipeline = [
        {'$unwind': '$info.teams'},
        {'$match': {'info.teams.name': {'$in': all_team_names}}},
        {'$unwind': '$info.teams.players'},
        {'$group': {
            '_id': {
                'matchId': '$metadata.matchId',
                'team':    '$info.teams.name',
                'season':  '$metadata.season',
            },
            'gameOutcome': {'$first': '$info.teams.gameOutcome'},
            'teamKills':   {'$first': '$info.teams.kills'},
            'assists':     {'$sum': {'$ifNull': ['$info.teams.players.assists', 0]}},
            'deaths':      {'$sum': {'$ifNull': ['$info.teams.players.deaths', 0]}},
        }},
        {'$group': {
            '_id':     {'season': '$_id.season'},
            'wins':    {'$sum': {'$cond': [{'$eq': ['$gameOutcome', True]},  1, 0]}},
            'losses':  {'$sum': {'$cond': [{'$eq': ['$gameOutcome', False]}, 1, 0]}},
            'kills':   {'$sum': {'$ifNull': ['$teamKills', 0]}},
            'assists': {'$sum': {'$ifNull': ['$assists',   0]}},
            'deaths':  {'$sum': {'$ifNull': ['$deaths',    0]}},
        }},
    ]

    results = list(matches.aggregate(pipeline))

    # Build a single combined record for all team_ids
    combined = {
        "teamName": team_ids[0],
        "formerNames": team_ids[1:],
        "seasons": [],
        "totalWins": 0,
        "totalLosses": 0,
        "totalKills": 0,
        "totalAssists": 0,
        "totalDeaths": 0
    }

    seasons_map = {}
    for item in results:
        season = item["_id"]["season"]
        wins = item.get("wins", 0)
        losses = item.get("losses", 0)
        kills = item.get("kills", 0)
        assists = item.get("assists", 0)
        deaths = item.get("deaths", 0)

        seasons_map[str(season)] = {
            "season": season,
            "wins": wins,
            "losses": losses,
            "kills": kills,
            "assists": assists,
            "deaths": deaths,
            "roster": []
        }
        combined["totalWins"] += wins
        combined["totalLosses"] += losses
        combined["totalKills"] += kills
        combined["totalAssists"] += assists
        combined["totalDeaths"] += deaths

    # Merge rosters from all team docs
    for team_doc in team_docs:
        for season_key, roster in (team_doc.get("rosters") or {}).items():
            if season_key not in seasons_map:
                seasons_map[season_key] = {
                    "season": season_key,
                    "wins": 0,
                    "losses": 0,
                    "kills": 0,
                    "assists": 0,
                    "deaths": 0,
                    "roster": roster
                }
            else:
                seasons_map[season_key]["roster"] = roster

    def season_sort_key(s):
        season_str = str(s["season"])
        digits = ''.join(filter(str.isdigit, season_str))
        suffix = ''.join(c for c in season_str if not c.isdigit())
        return (int(digits) if digits else 0, suffix)

    combined["seasons"] = sorted(seasons_map.values(), key=season_sort_key)

    return jsonify([combined])

@bp.route('/teams/<season>', methods=['GET'])
def get_all_teams_by_season(season):
    """Return all teams that have a roster registered for the given season."""
    team_data = list(teams.find({f'rosters.{season}': {'$exists': True}}, {'_id': 0}))
    return jsonify(team_data)


@bp.route('/roster/<team_name>/<season>', methods=['GET'])
def get_team_roster_by_season(team_name, season):
    """Return the roster for a specific team and season."""
    team_data = teams.find_one({'team_name': team_name}, {'_id': 0})
    roster = (team_data or {}).get('rosters', {}).get(str(season))
    if roster is not None:
        return jsonify(roster)
    return jsonify({'message': 'No roster found'})


@bp.route('/roster/<team_name>', methods=['GET'])
def get_team_roster(team_name):
    """Return the full team document including all season rosters."""
    team_data = teams.find_one({'team_name': team_name}, {'_id': 0})
    return jsonify(team_data)

@bp.route('/roster/<team_name>/<season>/add', methods=['POST'])
def add_player_to_team(team_name, season):
    """Add a player to a team's season roster. Requires admin password."""
    data = request.json
    if err := _check_password(data):
        return err
    if teams.find_one({'team_name': data['team_name']}) is None:
        return jsonify({'message': 'Team not found'})
    updated_team = teams.find_one_and_update(
        {'team_name': data['team_name']},
        {'$addToSet': {f'rosters.{season}': data}},
        return_document=True
    )
    add_team_to_player(data, team_name, season)
    return jsonify({'message': 'Player added to team roster', 'updatedTeam': convert_object_ids(updated_team)})

@bp.route('/roster/assign', methods=['POST'])
def assign_player_to_team():
    """Assign a player to a team roster for a given season."""
    data = request.json
    if teams.find_one({'team_name': data['teamName']}) is None:
        return jsonify({'message': 'Team not found'})
    updated_team = teams.find_one_and_update(
        {'team_name': data['teamName']},
        {'$push': {f"rosters.{data['season']}": {
            'name':        data['player']['name'],
            'role':        data['role'],
            'puuid':       data['player']['puuid'],
            'date_joined': datetime.now(),
        }}},
        return_document=True
    )
    add_team_to_player(data, data['teamName'], data['season'])
    return jsonify({'message': 'Player added to team roster', 'updatedTeam': convert_object_ids(updated_team)})