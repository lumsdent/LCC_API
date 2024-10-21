from flask import request, jsonify
from riot_util import fetch_riot_data
from mongo_connection import MongoConnection
from . import routes
import requests


players = MongoConnection().get_player_collection()


@routes.route('/players/<puuid>', methods=['GET'])
def get_player_by_puuid(puuid):
    player_data = players.find_one({"puuid": puuid}, {'_id': 0})
    return jsonify(player_data)

@routes.route('/players', methods=['GET'])
def get_players():
    player_data = list(players.find({}, {'_id': 0}))
    print(player_data)
    return jsonify(player_data)

@routes.route('/players/spells', methods=['GET'])
def get_runes():
    runes = ddragon_get_runes_dict()
    return jsonify(runes)

@routes.route('/players/add', methods=['POST'])
def add_player():
    form_data = request.json
    riot_data = get_riot_data(form_data["summonerName"], form_data["tagLine"])
    player_data = make_player(riot_data, form_data)
    print(player_data)
    if players.find_one({"puuid": player_data["puuid"]}) is None:
        result = players.insert_one(player_data)
        return jsonify({'message': 'Player added successfully'}, {'_id': str(result.inserted_id)})
    else:
        return jsonify({'message': 'Player already exists'})
    
def get_riot_data(summoner_name, summoner_tag):
    account_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{summoner_name}/{summoner_tag}"
    account = fetch_riot_data(account_url)
    summoner_url = f"https://na1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{account['puuid']}"
    summoner = fetch_riot_data(summoner_url)
    return {**summoner, **account}

def update_player_matches(puuid, match_id):
    players.update_one(
        {"puuid": puuid},
        {"$addToSet": {"matches": match_id}}
    )

def add_team_to_player(data, team_name, season):
    print(data)
    result = players.update_one(
        {"puuid": data["player"]["puuid"]},
        {"$addToSet": {"teams": {season: {data["role"]: team_name}}}}
    )
    return result

class Player(object):
    def __init__(self):
        self.puuid = ""
        self.userName = ""
        self.userTag = ""
        self.email = ""
        self.bio = ""
        self.availability = ''
        self.canSub = False
        self.profileIconId = 0
        self.summonerLevel = 0
        self.primaryRole = ""
        self.secondaryRole = ""
        self.teams = []
        self.matches = []
        self.stats = []
        self.revisionDate = 0
    
    def to_dict(self):
        return self.__dict__

def make_player(riot_data, registration_data):
    player = Player()
    player.puuid = riot_data["puuid"]
    player.userName = riot_data["gameName"]
    player.userTag = riot_data["tagLine"]
    player.email = registration_data["email"]
    player.bio = registration_data["bio"]
    player.availability = registration_data["availability"]
    player.canSub = registration_data["canSub"]
    player.profileIconId = riot_data["profileIconId"]
    player.summonerLevel = riot_data["summonerLevel"]
    player.primaryRole = registration_data["primaryRole"]
    player.secondaryRole = registration_data["secondaryRole"]
    player.teams = []
    player.matches = []
    player.stats = []
    player.revisionDate = riot_data["revisionDate"]
    return player.to_dict()
    

def ddragon_get_runes_dict(version="14.2.1"):
    url = f"http://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/runesReforged.json"
    html = requests.get(url).json()
    perk_dict = {item["id"]: item["key"] for item in html} #Domination (8100), Inspiration (8300), Precision (8000), Resolve (8400), Sorcery (8200)
    rune_dict = {rune["id"]: rune["key"] for item in html for
                 slot in item["slots"] for rune in slot["runes"]}
    return perk_dict | rune_dict