import os
from bson import ObjectId
from flask import request, jsonify, Blueprint
from .mongo_connection import MongoConnection
from .players import add_team_to_player
from datetime import datetime

bp = Blueprint('teams', __name__)
teams = MongoConnection().get_teams_collection()
matches = MongoConnection().get_matches_collection()

@bp.route('/teams/<season>/add', methods=['POST'])
def add_team(season):
    data = request.json
    password = os.getenv("ADMIN_PW")
    if(data["password"] != password):
        return jsonify({'message': 'Incorrect password'}), 401
    roster = data.get("roster", [])
    if teams.find_one({"team_name": data["teamName"]}) is None:
        teams.insert_one({"team_name": data["teamName"], "rosters": {season: roster}, "image": data["image"]})
        return jsonify({'message': 'Team added successfully'})
    elif teams.find_one({"team_name": data["teamName"], f"rosters.{season}": {"$exists": False}}):
        teams.update_one(
            {"team_name": data["teamName"]},
            {"$set": {f"rosters.{season}": roster, "image": data["image"]}}
        )
        return jsonify({'message': 'Team roster updated'})
    else:
        return jsonify({'message': 'Team already exists'})
 
@bp.route('/teams/all', methods=['GET'])
def get_all_teams():
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
    team_docs = list(teams.find({"team_name": {"$in": team_ids}}, {'_id': 0, 'team_name': 1, 'rosters': 1}))
    if not team_docs:
        return jsonify({'message': 'No teams found'}), 404

    all_team_names = [doc["team_name"] for doc in team_docs]

    pipeline = [
        {"$unwind": "$info.teams"},
        {"$match": {"info.teams.name": {"$in": all_team_names}}},
        {"$unwind": "$info.teams.players"},
        {"$group": {
            "_id": {
                "matchId": "$metadata.matchId",
                "team": "$info.teams.name",
                "season": "$metadata.season"
            },
            "gameOutcome": {"$first": "$info.teams.gameOutcome"},
            "teamKills": {"$first": "$info.teams.kills"},
            "assists": {"$sum": {"$ifNull": ["$info.teams.players.assists", 0]}},
            "deaths": {"$sum": {"$ifNull": ["$info.teams.players.deaths", 0]}}
        }},
        {"$group": {
            "_id": {"season": "$_id.season"},
            "wins": {"$sum": {"$cond": [{"$eq": ["$gameOutcome", True]}, 1, 0]}},
            "losses": {"$sum": {"$cond": [{"$eq": ["$gameOutcome", False]}, 1, 0]}},
            "kills": {"$sum": {"$ifNull": ["$teamKills", 0]}},
            "assists": {"$sum": {"$ifNull": ["$assists", 0]}},
            "deaths": {"$sum": {"$ifNull": ["$deaths", 0]}}
        }}
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
    # Include teams registered for the season even if their roster is empty
    team_data = list(teams.find({f"rosters.{season}": {"$exists": True}}, {'_id': 0}))
    return jsonify(team_data)

@bp.route('/roster/<team_name>/<season>', methods=['GET'])
def get_team_roster_by_season(team_name, season):
    team_data = teams.find_one({"team_name": team_name}, {'_id': 0})
    if team_data and "rosters" in team_data and team_data["rosters"][int(season)]:
        return jsonify(team_data["rosters"][int(season)])
    else:
        return jsonify({'message': 'No roster found'})

@bp.route('/roster/<team_name>', methods=['GET'])
def get_team_roster(team_name):
    team_data = teams.find_one({"team_name": team_name}, {'_id': 0})
    return jsonify(team_data)

@bp.route('/roster/<team_name>/<season>/add', methods=['POST'])
def add_player_to_team(team_name, season):
    data = request.json
    password = os.getenv("ADMIN_PW")
    if(data["password"] != password):
        return jsonify({'message': 'Incorrect password'}), 401
    if teams.find_one({"team_name": data["team_name"]}) is not None:
        updated_team = teams.find_one_and_update(
            {"team_name": data["team_name"] },
            {"$addToSet": {f"rosters.{season}": data}},
            return_document=True
        )
        add_team_to_player(data, team_name, season)

        updated_team = convert_object_ids(updated_team)
        print(updated_team)
        return jsonify({'message': 'Player added to team roster', 'updatedTeam': updated_team})
    else:
        return jsonify({'message': 'Team not found'})

@bp.route('/roster/assign', methods=['POST'])
def assign_player_to_team():
    data = request.json
    password = os.getenv("ADMIN_PW")
    if(data["password"] != password):
        return jsonify({'message': 'Incorrect password'}), 401
    if teams.find_one({"team_name": data["teamName"]}) is not None:
        updated_team = teams.find_one_and_update(
            {"team_name": data["teamName"] },
            {"$push": {f"rosters.{data["season"]}": {"name": data["player"]["name"], "role": data["role"], "puuid": data["player"]["puuid"], "date_joined": datetime.now()}}},
            return_document=True
        )
        add_team_to_player(data, data["teamName"], data["season"])

        updated_team = convert_object_ids(updated_team)
        print(updated_team)
        return jsonify({'message': 'Player added to team roster', 'updatedTeam': updated_team})
    else:
        return jsonify({'message': 'Team not found'})

def convert_object_ids(document):
    if isinstance(document, list):
        return [convert_object_ids(item) for item in document]
    elif isinstance(document, dict):
        return {key: convert_object_ids(value) for key, value in document.items()}
    elif isinstance(document, ObjectId):
        return str(document)
    else:
        return document