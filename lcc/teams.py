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
 
@bp.route('/teams/<season>', methods=['GET'])
def get_all_teams_by_season(season):
    season = season
    team_data = list(teams.find({f"rosters.{season}": {"$exists": True, "$ne": [], "$ne": None}}, {'_id': 0}))
    return jsonify(team_data)

@bp.route('/teams/all', methods=['GET'])
def get_all_teams():
    team_data = list(teams.find({}, {'_id': 0}))
    return jsonify(team_data)

@bp.route('/teams/records', methods=['GET'])
def get_team_records():
    """Return wins/losses per season and totals for teams by team_ids, including rosters."""
    # Get team_ids from query parameter (comma-separated)
    team_ids_param = request.args.get('team_ids', '')
    if not team_ids_param:
        return jsonify({'message': 'team_ids parameter is required'}), 400
    team_ids = [tid.strip() for tid in team_ids_param.split(',')]
    
    # Get all team documents for the requested team_ids
    team_docs = list(teams.find({"team_name": {"$in": team_ids}}, {'_id': 0, 'team_id': 1, 'team_name': 1, 'former_name': 1, 'rosters': 1}))
    if not team_docs:
        return jsonify({'message': 'No teams found'}), 404
    
    # Build mapping of team_name -> team_doc and collect all names (current and former)
    team_name_to_doc = {}
    all_team_names = []
    
    for team_doc in team_docs:
        team_name = team_doc.get("team_name")
        former_name = team_doc.get("former_name")
        
        team_name_to_doc[team_name] = team_doc
        all_team_names.append(team_name)
        
        if former_name:
            team_name_to_doc[former_name] = team_doc
            all_team_names.append(former_name)
    
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
            "_id": {
                "team": "$_id.team",
                "season": "$_id.season"
            },
            "wins": {"$sum": {"$cond": [{"$eq": ["$gameOutcome", True]}, 1, 0]}},
            "losses": {"$sum": {"$cond": [{"$eq": ["$gameOutcome", False]}, 1, 0]}},
            "kills": {"$sum": {"$ifNull": ["$teamKills", 0]}},
            "assists": {"$sum": {"$ifNull": ["$assists", 0]}},
            "deaths": {"$sum": {"$ifNull": ["$deaths", 0]}}
        }}
    ]

    results = list(matches.aggregate(pipeline))

    # Group results by team (using current team name)
    records_by_team = {}
    for team_doc in team_docs:
        current_team_name = team_doc.get("team_name")
        if current_team_name and current_team_name not in records_by_team:
            records_by_team[current_team_name] = {
                "teamName": current_team_name,
                "seasons": [],
                "totalWins": 0,
                "totalLosses": 0,
                "totalKills": 0,
                "totalAssists": 0,
                "totalDeaths": 0
            }
    
    for item in results:
        matched_team_name = item["_id"]["team"]
        team_doc = team_name_to_doc.get(matched_team_name)
        
        if not team_doc:
            continue
            
        # Use the current team name as the key
        current_team_name = team_doc.get("team_name")
        
        season = item["_id"]["season"]
        wins = item.get("wins", 0)
        losses = item.get("losses", 0)
        kills = item.get("kills", 0)
        assists = item.get("assists", 0)
        deaths = item.get("deaths", 0)

        records_by_team[current_team_name]["seasons"].append({
            "season": season,
            "wins": wins,
            "losses": losses,
            "kills": kills,
            "assists": assists,
            "deaths": deaths,
            "roster": []  # Will be populated below
        })
        records_by_team[current_team_name]["totalWins"] += wins
        records_by_team[current_team_name]["totalLosses"] += losses
        records_by_team[current_team_name]["totalKills"] += kills
        records_by_team[current_team_name]["totalAssists"] += assists
        records_by_team[current_team_name]["totalDeaths"] += deaths

    # Fetch roster data for each team, ensuring seasons exist even without matches
    for team_doc in team_docs:
        team_name = team_doc.get("team_name")
        if team_name not in records_by_team:
            continue

        rosters = team_doc.get("rosters", {})
        if rosters:
            existing_seasons = {str(s["season"]) for s in records_by_team[team_name]["seasons"]}
            for season_key, roster in rosters.items():
                if season_key not in existing_seasons:
                    records_by_team[team_name]["seasons"].append({
                        "season": season_key,
                        "wins": 0,
                        "losses": 0,
                        "kills": 0,
                        "assists": 0,
                        "deaths": 0,
                        "roster": roster
                    })
                else:
                    for season_record in records_by_team[team_name]["seasons"]:
                        if str(season_record["season"]) == season_key:
                            season_record["roster"] = roster
                            break

    # Sort seasons for each team
    for record in records_by_team.values():
        record["seasons"].sort(
            key=lambda s: int(s["season"]) if str(s["season"]).isdigit() else str(s["season"])
        )

    return jsonify(list(records_by_team.values()))

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