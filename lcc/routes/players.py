from flask import request, jsonify

from riot_util import fetch_riot_data
from mongo_connection import MongoConnection
from process_match_reports import get_champion_mastery, find_player
from . import routes
import requests

DDRAGON_URL = "https://ddragon.leagueoflegends.com/cdn/"
CDN_VERSION = "14.20.1"
players = MongoConnection().get_player_collection()

@routes.route('/players/add', methods=['POST'])
def add_player():
    form_data = request.json
    print(form_data)
    riot_data = get_riot_data(form_data["name"], form_data["tag"])
    discord_data = {"id": form_data["discord_id"], "username": form_data["discord_username"], "avatar_url": form_data["discord_avatar"]}
    
    profile_data = {"puuid": riot_data["puuid"],
                                "name": riot_data["gameName"],
                                "tag": riot_data["tagLine"],
                                "level": riot_data["summonerLevel"],
                                "email": form_data["email"],
                                "bio": form_data["bio"],
                                "primary_role": form_data["primaryRole"],
                                "secondary_role": form_data["secondaryRole"],
                                "can_sub": form_data["canSub"],
                                "revision_date": riot_data["revisionDate"],
                                "images": get_images(riot_data["profileIconId"])}
    
    player_data = {"profile": profile_data, "discord": discord_data, "champion_mastery": get_champion_mastery(profile_data["puuid"])}
    
    if players.find_one({"profile.puuid": profile_data["puuid"]}) is None:
        result = players.insert_one(player_data)
        return jsonify({'message': 'Player added successfully'}, {'_id': str(result.inserted_id)})
    else:
        players.update_one(
            {"profile.puuid": profile_data["puuid"]},
            {"$set": player_data}
        )
        return jsonify({'message': 'Player already exists. Updated with provided data'})

@routes.route('/players/admins', methods=['GET'])
def get_players_admin():
    print("Getting admin players")
    admin_players = list(players.find({"isAdmin": True}, {"_id": 0, "discord.id": 1}))
    print(admin_players)
    return jsonify(admin_players)

@routes.route('/players/<puuid>', methods=['GET'])
def get_player_by_puuid(puuid):
    player_data = find_player(puuid)
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
    print("here  ", data)
    result = players.update_one(
        {"profile.puuid": data["player"]["puuid"]},
        {"$addToSet": {"teams": {season: {"role":data["role"],"name": team_name}}}}
    )
    return result

def save_match_history(data):
    players.find_one_and_update(
        {"profile.puuid": data["profile"]["puuid"]},
        {"$addToSet": {"match_history": data}}
    )

def get_images(profile_icon_id):
    return {
        "icon": f"{DDRAGON_URL}{CDN_VERSION}/img/profileicon/{profile_icon_id}.png"
    }

def ddragon_get_runes_dict(version="14.2.1"):
    url = f"http://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/runesReforged.json"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise an error for bad status codes
        html = response.json()
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return {}
    perk_dict = {}
    for item in html:
        # Split the URL by '/' and get the last part
        filename = item["icon"].split('/')[-1]
        # Remove the file extension and convert to lowercase
        rune_key = filename.split('.')[0].lower()
        perk_dict[item["id"]] = rune_key # Domination (8100), Inspiration (8300), Precision (8000), Resolve (8400), Sorcery (8200)
    rune_dict = {rune["id"]: rune["key"].lower() for item in html for slot in item["slots"] for rune in slot["runes"]}
    return {**perk_dict, **rune_dict}
