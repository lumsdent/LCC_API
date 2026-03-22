from dotenv import load_dotenv
load_dotenv()
from lcc.mongo_connection import MongoConnection
import json

db = MongoConnection()
mp = db.get_match_performances_collection()

puuid = 'ViL-fqc_05wIgsqrNTZm4GTXv24-oNM0A4p41gcFdq9ltxyATnijVFkdBdE9EEQnErx4q81yTGZT1A'
query = {'puuid': puuid}

pipeline = [
    {'$match': query},
    {'$sort': {'gameStartTimestamp': -1}},
    {'$skip': 0},
    {'$limit': 1},
    {'$lookup': {
        'from': 'match_performances',
        'let': {'mid': '$matchId', 'opp': '$opponentPuuid'},
        'pipeline': [
            {'$match': {'$expr': {'$and': [
                {'$eq': ['$matchId', '$$mid']},
                {'$eq': ['$puuid',   '$$opp']},
            ]}}},
            {'$project': {'_id': 0, 'champion': 1, 'teamName': 1}},
        ],
        'as': 'opponentDoc',
    }},
    {'$lookup': {
        'from': 'matches',
        'let': {'mid': '$matchId'},
        'pipeline': [
            {'$match': {'$expr': {'$eq': ['$metadata.matchId', '$$mid']}}},
            {'$project': {'_id': 0, 'vod': '$info.vod'}},
        ],
        'as': 'matchDoc',
    }},
    {'$addFields': {
        'opponentTeamName': {'$arrayElemAt': ['$opponentDoc.teamName', 0]},
        'opponentChampion': {'$arrayElemAt': ['$opponentDoc.champion', 0]},
        'vod': {'$arrayElemAt': ['$matchDoc.vod', 0]},
    }},
    {'$project': {'_id': 0, 'opponentDoc': 0, 'matchDoc': 0}},
]

result = list(mp.aggregate(pipeline))
if result:
    r = result[0]
    print('opponentChampion:', json.dumps(r.get('opponentChampion'), default=str))
    print('opponentTeamName:', r.get('opponentTeamName'))
    print('teamName:', r.get('teamName'))
    print('vod:', r.get('vod'))
else:
    print('No results')
