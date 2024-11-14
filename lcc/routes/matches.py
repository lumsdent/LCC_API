from flask import request, jsonify
from riot_util import fetch_riot_data
from mongo_connection import MongoConnection
from . import routes
from process_match_reports import process_match
from .players import update_player_matches

matches = MongoConnection().get_matches_collection()

@routes.route('/matches/add', methods=['POST'])
def add_match():
    print('Adding match')
    data = request.json
    match_id = data["match_id"]
    if matches.find_one({"match_id": "NA1_" + match_id}) is None:
        processed_match = process_match(match_id)
        # matches.insert_one(processed_match)   
        participants = processed_match.get("participants", [])
        for participant in participants:
            puuid = participant.get("puuid")
            if puuid:
                update_player_matches(puuid, match_id)
        return jsonify({'message': 'Match added successfully'})
    else:
        return jsonify({'message': 'Match already exists'})

@routes.route('/matches', methods=['GET'])
def get_all_matches():
    match_data = list(matches.find({}, {'_id': 0}))
    return jsonify(match_data)

@routes.route('/matches/<match_id>', methods=['GET'])
def get_match(match_id):
    match_data = matches.find_one({"match_id": match_id}, {'_id': 0})
    return jsonify(match_data)
