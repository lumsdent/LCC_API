from mongo_connection import MongoConnection
from flask import request, jsonify
from . import routes
from . import get_riot_data

practice = MongoConnection().get_practice_collection()

@routes.route('/practice/add', methods=['POST'])
def add_practice():
    data = request.json
    player = get_riot_data(data["summonerName"], data["tagLine"])
    practice.insert_one({"puuid": player["puuid"], **data})
    return jsonify({'message': 'Practice added successfully'})

@routes.route('/practice/<puuid>', methods=['GET'])
def get_practice(puuid):
    practice_data = list(practice.find({"puuid": puuid}, {'_id': 0}))
    return jsonify(practice_data)