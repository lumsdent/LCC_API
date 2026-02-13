from datetime import timedelta, datetime
import os
import requests
from flask import request, jsonify, Blueprint
from .mongo_connection import MongoConnection
from .process_match_reports import get_champion_mastery, find_player

bp = Blueprint('players', __name__, url_prefix='/players')

DDRAGON_URL = "https://ddragon.leagueoflegends.com/cdn/"
CDN_VERSION = "16.3.1"
players = MongoConnection().get_player_collection()

@bp.route('/add', methods=['POST'])
def add_player():
    form_data = request.json
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
                                "images": get_images(riot_data["profileIconId"]),
                                "availability": form_data["availability"],
                                "is_active": True}
    
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

@bp.route('/<puuid>', methods=['GET'])
def get_player_by_puuid(puuid):
    player_data = find_player(puuid)
    return jsonify(player_data)

@bp.route('/', methods=['GET'])
def get_players():
    player_data = list(players.find({}, {'_id': 0}))
    return jsonify(player_data)

@bp.route('/spells', methods=['GET'])
def get_runes():
    runes = ddragon_get_runes_dict()
    return jsonify(runes)

def get_riot_data(summoner_name, summoner_tag):
    account_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{summoner_name}/{summoner_tag}"
    account = fetch_riot_data(account_url)
    summoner_url = f"https://na1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{account['puuid']}"
    summoner = fetch_riot_data(summoner_url)
    return {**summoner, **account}

def add_team_to_player(data, team_name, season):
    result = players.update_one(
        {"profile.puuid": data["player"]["puuid"]},
        {"$addToSet": {"teams": {season: {"role":data["role"],"name": team_name}}}}
    )
    return result

def save_match_history(data):
    """Save or update match history entry for a player
    
    If the player doesn't exist, creates a new player document.
    If the match already exists in the player's history, updates it.
    Otherwise, adds a new match to the player's history.
    
    Args:
        data (dict): Match data containing profile and match information
    """
    match_id = data["matchId"]  # Assuming match_id is in the data object
    player_puuid = data["profile"]["puuid"]
    
    # Check if player exists
    player = players.find_one({"profile.puuid": player_puuid})
    
    if player is None:
        # Player doesn't exist, create new player with this match
        players.insert_one({
            "profile": data["profile"], 
            "match_history": [data], 
            "champion_mastery": get_champion_mastery(player_puuid)
        })
    else:
        # Player exists, check if this match already exists
        existing_match = players.find_one({
            "profile.puuid": player_puuid,
            "match_history.matchId": match_id
        })
        
        if existing_match:
            # Match exists, update it
            players.update_one(
                {
                    "profile.puuid": player_puuid,
                    "match_history.matchId": match_id
                },
                {"$set": {"match_history.$": data}}
            )
        else:
            # Match doesn't exist, add it
            players.update_one(
                {"profile.puuid": player_puuid},
                {"$push": {"match_history": data}}
            )

def get_images(profile_icon_id):
    return {
        "icon": f"/img/profileicon/{profile_icon_id}.png"
    }

def ddragon_get_runes_dict():
    url = f"{DDRAGON_URL}{CDN_VERSION}/data/en_US/runesReforged.json"
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

def fetch_riot_data(url):
    api_key = os.getenv("RIOT_API_KEY")
    headers = {"X-Riot-Token": api_key}
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        raise requests.exceptions.HTTPError(f"Failed to fetch match data: {response.text}")
    return response.json()


@bp.route('/<puuid>/delete', methods=['DELETE'])
def delete_player_match_history_endpoint(puuid):
    """API endpoint to delete a match from a player's history by index
    
    Required parameters in JSON body:
    - password: Admin password for authentication
    - index: The array index to delete
    
    Returns:
    - 200 Success message if deleted
    - 404 Not found if player or match doesn't exist
    """

    data = request.json

        
    # Validate index parameter
    if "index" not in data:
        return jsonify({'message': 'Missing required parameter: index'}), 400
    
    try:
        index = int(data["index"])
        if index < 0:
            raise ValueError("Index must be non-negative")
    except ValueError:
        return jsonify({'message': 'Invalid index value, must be a non-negative integer'}), 400
    
    # Delete the match history entry
    result = delete_match_history_by_index(puuid, index)
    
    if result["success"]:
        return jsonify({'message': result["message"]}), 200
    else:
        return jsonify({'message': result["message"]}), 404
    
def delete_match_history_by_index(player_puuid, index):
    """Delete a match history entry by its index in the array
    
    Args:
        player_puuid (str): The PUUID of the player
        index (int): The zero-based index of the match to delete
        
    Returns:
        dict: Status of the operation with success flag and message

    TEMPORARY!!
    """
    # Find the player to confirm they exist and get match_history length
    player = players.find_one({"profile.puuid": player_puuid})
    
    if not player:
        return {"success": False, "message": "Player not found"}
    
    # Check if match_history exists and has sufficient elements
    if not player.get("match_history") or len(player["match_history"]) <= index:
        return {"success": False, "message": f"Match at index {index} does not exist"}
    
    # Get the match_id for logging purposes
    match_id = player["match_history"][index].get("match_id", "unknown")
    
    # Remove the element at the specified index
    # In MongoDB, we first mark the element as null, then pull all null values
    result = players.update_one(
        {"profile.puuid": player_puuid},
        {"$unset": {f"match_history.{index}": 1}}
    )
    
    if result.modified_count > 0:
        # Now pull all null values to clean up the array
        players.update_one(
            {"profile.puuid": player_puuid},
            {"$pull": {"match_history": None}}
        )
        return {
            "success": True, 
            "message": f"Match history entry at index {index} (match_id: {match_id}) deleted"
        }
    else:
        return {"success": False, "message": "Failed to delete match history entry"}