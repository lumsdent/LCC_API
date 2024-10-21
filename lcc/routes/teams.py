from bson import ObjectId
from flask import request, jsonify
from mongo_connection import MongoConnection
from . import routes
from .players import add_team_to_player

teams = MongoConnection().get_teams_collection()

@routes.route('/teams/<season>/add', methods=['POST'])
def add_team(season):
    data = request.json
    if teams.find_one({"team_name": data["teamName"]}) is None:
        teams.insert_one({"team_name": data["teamName"], "rosters": {season: data["roster"]}})
        return jsonify({'message': 'Team added successfully'})
    elif teams.find_one({"team_name": data["teamName"], f"rosters.{season}": {"$exists": False}}):
        teams.update_one(
            {"team_name": data["teamName"]},
            {"$set": {f"rosters.{season}": data["roster"]}}
        )
        return jsonify({'message': 'Team roster updated'})
    else:
        return jsonify({'message': 'Team already exists'})
 
@routes.route('/teams/<season>', methods=['GET'])
def get_all_teams_by_season(season):
    season = int(season)
    team_data = list(teams.find({f"rosters.{season}": {"$exists": True, "$ne": [], "$ne": None}}, {'_id': 0}))
    return jsonify(team_data)

@routes.route('/teams/all', methods=['GET'])
def get_all_teams():
    team_data = list(teams.find({}, {'_id': 0}))
    return jsonify(team_data)

@routes.route('/roster/<team_name>/<season>', methods=['GET'])
def get_team_roster_by_season(team_name, season):
    team_data = teams.find_one({"team_name": team_name}, {'_id': 0})
    if team_data and "rosters" in team_data and team_data["rosters"][int(season)]:
        return jsonify(team_data["rosters"][int(season)])
    else:
        return jsonify({'message': 'No roster found'})

@routes.route('/roster/<team_name>', methods=['GET'])
def get_team_roster(team_name):
    team_data = teams.find_one({"team_name": team_name}, {'_id': 0})
    return jsonify(team_data)

@routes.route('/roster/<team_name>/<season>/add', methods=['POST'])
def add_player_to_team(team_name, season):
    data = request.json
    if teams.find_one({"team_name": team_name}) is not None:
        updated_team = teams.find_one_and_update(
            {"team_name": team_name },
            {"$addToSet": {f"rosters.{season}": data}},
            return_document=True 
        )
        add_team_to_player(data, team_name, season)
        updated_team = convert_object_ids(updated_team)
        print(updated_team)
        return jsonify({'message': 'Player added to team roster', 'updatedTeam': updated_team})
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