from flask import request, jsonify, Blueprint
from .mongo_connection import MongoConnection
from .process_match_reports import process_match, get_matchups
from .players import save_match_history

bp = Blueprint('matches', __name__, url_prefix='/matches')

matches = MongoConnection().get_matches_collection()

@bp.route('/add', methods=['POST'])
def add_match():
    print('Adding match')
    data = request.json
    match_id = data["matchId"]
    if matches.find_one({"metadata.matchId": "NA1_" + match_id}) is None:
        processed_match = process_match(data)
        save_match(processed_match)
        roles = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "SUPPORT"]
        matchups_data = []
        for role in roles:
            matchups = get_matchups(processed_match, role)
            matchups_data.extend(matchups)
        for matchup in matchups_data:
            save_matchup(matchup)
        return jsonify({'message': 'Match added successfully'})
    else:
        return jsonify({'message': 'Match already exists'})

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
    
def save_matchup(matchup):
    save_match_history(matchup)