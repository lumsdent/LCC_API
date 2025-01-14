import os
import random
import requests
from marshmallow import Schema, fields, EXCLUDE
from .mongo_connection import MongoConnection

DDRAGON_URL = "https://ddragon.leagueoflegends.com/cdn/"
CDN_VERSION = "15.1.1"

def process_match(user_data):
    
    match_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/NA1_{user_data["matchId"]}"
    riot_match_data = fetch_riot_data(match_url)

    processed_match = process_match_data(riot_match_data, user_data)
    # Fetch and process timeline data
    # timeline_url = match_url + "/timeline"
    # riot_timeline_data = fetch_riot_data(timeline_url)
    # processed_timeline_data = process_timeline_data(riot_timeline_data)
    # position_data = get_position_data(riot_match_data["info"]["participants"])
    # for position, teams in position_data.items():
    #     processed_timeline_data[teams[100]]["csd14"] = processed_timeline_data[teams[100]]["cs14"] - processed_timeline_data[teams[200]]["cs14"]
    #     processed_timeline_data[teams[200]]["csd14"] = processed_timeline_data[teams[200]]["cs14"] - processed_timeline_data[teams[100]]["cs14"]
    # # Merge the timeline data with the match data
    # processed_match["participants"] = [dict(participant, **processed_timeline_data[participant["puuid"]]) for participant in processed_match["participants"]]
    
    # ordered_keys = ["puuid", "player", "champion", "role", "win", "gameLength", "champLevel", "kills", "deaths", "assists", "kda", "kp", "cs", "csm", "cs14", "csd14", "gold", "gpm", "dmg", "dpm", "teamDmg%", "dmgTakenTeam%", "firstBlood", "soloBolos", "tripleKills", "quadraKills", "pentaKills", "multikills", "visionScore", "vspm", "ccTime", "effectiveHealShield", "objectivesStolen"]
    # processed_match["participants"] = [{key: participant[key] for key in ordered_keys} for participant in processed_match["participants"]]
    
    return processed_match
    

def build_matchup( player):
    return {
        "puuid": player["profile"]["puuid"],
        "teamImage": player["team"]["image"],
        "teamName": player["team"]["name"],
        "player": player["profile"]["name"],
        "championName": player["champion"]["name"],
        "championImage": player["champion"]["image"]
    }

def get_matchups(match_data, role):
    matchups = []
    for team in match_data["info"]["teams"]:
        for player in team["players"]:
            if player["role"] == role:
                player["matchId"] = match_data["metadata"]["matchId"]
                player["gameStartTimestamp"] = match_data["info"]["gameStartTime"]
                player["win"] = team["gameOutcome"]
                player["team"] = {"name": team["name"], "image": f"{team["name"].lower()}.png"}
                matchups.append(player)
                break
    if len(matchups) == 2:
        matchups[0]["vs"] = build_matchup(matchups[1])
        matchups[1]["vs"] = build_matchup(matchups[0])
    return matchups
    
def get_position_data(participants):
    position_data = {
        'TOP': {100: None, 200: None},
        'JUNGLE': {100: None, 200: None},
        'MIDDLE': {100: None, 200: None},
        'BOTTOM': {100: None, 200: None},
        'UTILITY': {100: None, 200: None},
    }

    for participant in participants:
        position = participant['teamPosition']
        team = participant['teamId']
        puuid = participant['puuid']
        if position in position_data and team in position_data[position]:
            position_data[position][team] = puuid
    return position_data

# def aggregate_player_season_data(match):
#     for participant in match["participants"]:
#         puuid = participant['puuid']
#         #get player season data from db
#         db = MongoConnection().get_player_stats_collection()
#         player = db.find_one({"puuid": puuid})
        
#         if not player:
#             player = {
#                 'puuid': puuid,
#                 'riotIdGameName': participant['player'],
#                 'matches': 0,
#                 'game_minutes': 0,
#                 'kills': 0,
#                 'deaths': 0,
#                 'assists': 0,
#                 'kda': 0,
#                 'dmg': 0,
#                 'dpm': 0,
#                 'cs': 0,
#                 'csm': 0,
#                 'totalCsd14': 0,
#                 'avgCsd14': 0,
#                 'first_blood': 0,
#                 'solo_kills': 0
#             }
#         player['matches'] += 1
#         player['game_minutes'] += round(participant['gameLength'], 2)
#         player['kills'] += participant['kills']
#         player['deaths'] += participant['deaths']
#         player['assists'] += participant['assists']
#         if player['deaths'] == 0:
#             player['kda'] = player['kills'] + player['assists']
#         else:
#             player['kda'] = round((player['kills'] + player['assists']) / player['deaths'], 2)
#         player['dmg'] += participant['dmg']
#         player['dpm'] = round(player['dmg'] / player['game_minutes'], 2)
#         player['cs'] += participant['cs']
#         player['csm'] = round(player['cs'] / player['game_minutes'], 2)
#         player['totalCsd14'] += participant['csd14']
#         player['first_blood'] += participant['firstBlood']
#         player['solo_kills'] += participant['soloBolos']
        
#     # for player in players:
#     #     for puuid, pdata in player.items():
#     #         pdata['avgCsd14'] = round(pdata['totalCsd14']/pdata["matches"], 1)
#         db.update_one({"puuid": puuid}, {"$set": player}, upsert=True)
    

def fetch_riot_data(url):
    api_key = os.getenv("RIOT_API_KEY")
    headers = {"X-Riot-Token": api_key}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise requests.exceptions.HTTPError(f"Failed to fetch match data: {response.text}")
    return response.json()
        
def process_match_data(match_data, user_data):
    match_information = {}
    blue_team_players = []
    red_team_players = []
    match_overview = {
        "gameCreation": match_data["info"]["gameCreation"], 
        "gameDuration": match_data["info"]["gameDuration"],
        "gameStartTime": match_data["info"]["gameStartTimestamp"],
        "gameEndTimestamp": match_data["info"]["gameEndTimestamp"],
        "gameId": match_data["metadata"]["matchId"],
        "gameMode": match_data["info"]["gameMode"],
        "gameVersion": match_data["info"]["gameVersion"],
        }
    
    
    for participant in match_data["info"]["participants"]:
        player = get_player(participant, match_overview)
        if participant["teamId"] == 100:
            blue_game_result = participant["win"]
            blue_team_players.append(player)
        else:
            red_game_result = participant["win"]
            red_team_players.append(player)
    for team in match_data["info"]["teams"]:
        if team["teamId"] == 100:
            blue_team = {"name": user_data["blueTeam"],
                "side": "Blue",
                "teamId": 100,
                "gameOutcome": blue_game_result,
                "kills": sum([player["kills"] for player in blue_team_players]),
                "gold": sum([player["goldEarned"] for player in blue_team_players]),
                "bans": get_bans(team),
                "objectives": get_objectives(team),
                "players": blue_team_players
                }
        else:
            red_team = {"name": user_data["redTeam"],
                "side": "Red",
                "teamId": 200,
                "gameOutcome": red_game_result,
                "kills": sum([player["kills"] for player in red_team_players]),
                "gold": sum([player["goldEarned"] for player in red_team_players]),
                "bans": get_bans(team),
                "objectives": get_objectives(team),
                "players": red_team_players
                }
    match_overview["teams"] = [blue_team, red_team]
    
    metadata =  match_data["metadata"]
    metadata["matchName"] = user_data["blueTeam"] + " vs " + user_data["redTeam"]
    match_information = {"metadata": metadata, "info": match_overview}
    return match_information

def get_bans(team):
    bans = []
    for ban in team["bans"]:
        banned_champ = get_champion_by_id(ban["championId"])
        banned_champ["pickTurn"] = ban["pickTurn"]
        bans.append(banned_champ)
    return bans

def get_champion_mastery(puuid):
    url = f"https://na1.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
    try:
        response = fetch_riot_data(url)
        top_champions = []
        for mastery in response[:3]: 
            champion = get_champion_by_id(mastery["championId"])

            champion["championMastery"]= mastery["championLevel"]
            champion["championPoints"]= mastery["championPoints"]
            champion["lastPlayTime"]= mastery["lastPlayTime"]
            top_champions.append(champion)
        return top_champions
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return []

def get_champion_by_id(champion_id):
    champion_data = fetch_champion_data()
    for champion in champion_data:
        if int(champion["key"]) == champion_id:
            return {
            "id": champion["id"],
            "name": champion["name"],
            "title": champion["title"],
            "image": {
                "full": f"/img/champion/{champion['image']['full']}",
                "square": f"/img/champion/{champion['image']['full']}"
            }
        }

def fetch_champion_data():
    url = f"{DDRAGON_URL}{CDN_VERSION}/data/en_US/champion.json"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise an error for bad status codes
        return response.json()["data"].values()
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return {}
    
# TODO handle better
players = MongoConnection().get_player_collection()

def find_player(puuid):
    return players.find_one({"profile.puuid": puuid}, {'_id': 0})
    
def get_objectives(team):
    team_objectives = team["objectives"]
    team_objectives["baron"]["image"] = f"https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-match-history/global/default/baron-{team["teamId"]}.png"
    team_objectives["dragon"]["image"] = f"https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-match-history/global/default/dragon-{team["teamId"]}.png"
    team_objectives["riftHerald"]["image"] = f"https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-match-history/global/default/herald-{team["teamId"]}.png"
    team_objectives["tower"]["image"] = f"https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-match-history/global/default/tower-{team["teamId"]}.png"
    team_objectives["inhibitor"]["image"] = f"https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-match-history/global/default/inhibitor-{team["teamId"]}.png"
    team_objectives["horde"]["image"] = "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-match-history/global/default/horde.png"
    return team_objectives
    
    
def process_timeline_data(timeline_data):
     #Find 14 minute
    for frame in timeline_data["info"]["frames"]:
        #840000 is the millisecond timestamp for 14 minutes. Timestamps are not exact, so we need to check a range of timestamps
        if frame["timestamp"] > 840000 and frame["timestamp"] < 850000:
            minute_14 = frame["participantFrames"]
            break
    #Find Game participants
    participant_data_dict = {}
    for participant in timeline_data["info"]["participants"]:
        puuid = participant["puuid"]
        participant_id = participant["participantId"]
        #Match participant data with 14 minute data
        for pid, pdata in minute_14.items():
            if str(pid) == str(participant_id):
                participant_data_dict[puuid] = pdata
    
    #Pull and aggregate data from timeline per participant
    participants = {}
    for puuid, pdata in participant_data_dict.items():
        participant_data_14 = {}
        participant_data_14["cs14"] = pdata["minionsKilled"] + pdata["jungleMinionsKilled"]
        participants[puuid] = participant_data_14
    return participants


def fetch_item_data():
    url = f"{DDRAGON_URL}{CDN_VERSION}/data/en_US/item.json"
    response = requests.get(url, timeout=10)
    if response.status_code == 200:
        return response.json()["data"]
    else:
        raise Exception("Failed to fetch item data")

# Get the item name using the participant's item ID
def get_item_name(item_data, item_id):
    return item_data.get(str(item_id), {}).get("name", "Unknown Item")

# Get the build for a participant
def get_build(participant, item_data):  
    build = []
    for i in range(6):  # There are 6 item slots
       build.append(get_item(participant, i, item_data))
    return build

def get_item(participant, item_number, item_data):
    item_id = participant.get(f"item{item_number}")
    if item_id:
        item_name = get_item_name(item_data, item_id)
        return {"id": item_id, "name": item_name, "image": f"/img/item/{item_id}.png"}
    return {"id": 0, "name": "Empty Slot", "image": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/assets/items/icons2d/gp_ui_placeholder.png"}

def get_champion(participant):
    champion = {}
    champion["id"] = participant["championId"]
    champion["name"] = participant["championName"]
    # champion["pick_turn"] = participant["pickTurn"]
    # champion["title"] = participant["championTitle"]
    champion["level"] = participant["champLevel"]
    champion["experience"] = participant["champExperience"]
    champion["image"] = {"square": f"/img/champion/{champion['name']}.png"}
    return champion

def get_profile(participant):
    puuid = participant["puuid"]
    player_data = find_player(puuid)
    if player_data and 'profile' in player_data:
        return player_data['profile']
    else:
        return get_riot_account(puuid)

def get_riot_account(puuid):
    account_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-puuid/{puuid}"
    account = fetch_riot_data(account_url)
    summoner_url = f"https://na1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{account['puuid']}"
    summoner = fetch_riot_data(summoner_url)
    return  {"puuid": account["puuid"],
            "name": account["gameName"],
            "tag": account["tagLine"],
            "level": summoner["summonerLevel"],
            "revision_date": summoner["revisionDate"],
            "images": {"icon": f"/img/profileicon/{summoner["profileIconId"]}.png"}}


def get_runes(participant):
    runes = {}
    participant_runes = participant["perks"]
    participant_rune_style = participant_runes["styles"]
    primary_runes = participant_rune_style[0]
    secondary_runes = participant_rune_style[1]
    primary_tree_id = primary_runes["style"]
    primary_tree = primary_runes["selections"]
    primary_perk_ids = [selection["perk"] for selection in primary_tree]
    secondary_tree_id = secondary_runes["style"]
    secondary_tree = secondary_runes["selections"]
    secondary_perk_ids = [selection["perk"] for selection in secondary_tree]
    # TODO update API contract to include all runes
    rune_data = ddragon_get_runes_dict()
    primary = {}
    primary["name"] = rune_data[primary_tree_id]

    primary['image'] = get_rune_image(rune_data[primary_tree_id]["key"])
    primary["keystone"] = {
        "id": primary_perk_ids[0],
        "name": rune_data[primary_perk_ids[0]],
        "image": get_rune_image(rune_data[primary_perk_ids[0]])
    }
    secondary = {}
    secondary["name"] = rune_data[secondary_tree_id]
    secondary['image'] = get_rune_image(rune_data[secondary_tree_id]["key"])
    runes["primary"] = primary
    runes["secondary"] = secondary
    return runes

def get_rune_image(rune_key):
    rune_image_dict =  {
        #precision
        "7201_precision": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/7201_precision.png",
        "lethaltempo": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/lethaltempo/lethaltempotemp.png",
        "absorblife": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/absorblife/absorblife.png",
        "conqueror": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/conqueror/conqueror.png",
        "coupdegrace": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/coupdegrace/coupdegrace.png",
        "cutdown": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/cutdown/cutdown.png",
        "fleetfootwork": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/fleetfootwork/fleetfootwork.png",
        "legendalacrity": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/legendalacrity/legendalacrity.png",
        "legendbloodline": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/legendbloodline/legendbloodline.png",
        "legendhaste": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/legendhaste/legendhaste.png",
        "presenceofmind": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/presenceofmind/presenceofmind.png",
        "presstheattack": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/precision/presstheattack/presstheattack.png",
        #domination
        "7200_domination": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/7200_domination.png",
        "cheapshot": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/cheapshot/cheapshot.png",
        "darkharvest": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/darkharvest/darkharvest.png",
        "electrocute": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/electrocute/electrocute.png",
        "eyeballcollection": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/eyeballcollection/eyeballcollection.png",
        "ghostporo": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/ghostporo/ghostporo.png",
        "hailofblades": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/hailofblades/hailofblades.png",
        "ingenioushunter": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/ingenioushunter/ingenioushunter.png",
        "predator": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/predator/predator.png",
        "relentlesshunter": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/relentlesshunter/relentlesshunter.png",
        "suddenimpact": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/suddenimpact/suddenimpact.png",
        "tasteofblood": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/tasteofblood/greenterror_tasteofblood.png",
        "ultimatehunter": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/ultimatehunter/ultimatehunter.png",
        "zombieward": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/domination/zombieward/zombieward.png",
        #inspiration
        "7203_whimsy": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/7203_whimsy.png",
        "biscuitdelivery": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/biscuitdelivery/biscuitdelivery.png",
        "cashback": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/cashback/cashback2.png",
        "celestialbody": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/celestialbody/celestialbody.png",
        "cosmicinsight": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/cosmicinsight/cosmicinsight.png",
        "firststrike": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/firststrike/firststrike.png",
        "glacialaugment": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/glacialaugment/glacialaugment.png",
        "hextechflashtraption": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/hextechflashtraption/hextechflashtraption.png",
        "jackofalltrades": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/jackofalltrades/jackofalltrades2.png",
        "kleptomancy": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/kleptomancy/kleptomancy.png",
        "magicalfootwear": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/magicalfootwear/magicalfootwear.png",
        "perfecttiming": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/perfecttiming/alchemistcabinet.png",
        "timewarptonic": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/timewarptonic/timewarptonic.png",
        "unsealedspellbook": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/inspiration/unsealedspellbook/unsealedspellbook.png",
        #resolve
        "7204_resolve": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/7204_resolve.png",
        "approachvelocity": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/approachvelocity/approachvelocity.png",
        "boneplating": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/boneplating/boneplating.png",
        "chrysalis": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/chrysalis/chrysalis.png",
        "conditioning": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/conditioning/conditioning.png",
        "demolish": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/demolish/demolish.png",
        "fontoflife": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/fontoflife/fontoflife.png",
        "graspoftheundying": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/graspoftheundying/graspoftheundying.png",
        "guardian": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/guardian/guardian.png",
        "ironskin": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/ironskin/ironskin.png",
        "mirrorshell": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/mirrorshell/mirrorshell.png",
        "overgrowth": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/overgrowth/overgrowth.png",
        "revitalize": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/revitalize/revitalize.png",
        "secondwind": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/secondwind/secondwind.png",
        "aftershock": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/resolve/veteranaftershock/veteranaftershock.png",
        #sorcery
        "7202_sorcery": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/7202_sorcery.png",
        "absolutefocus": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/absolutefocus/absolutefocus.png",
        "arcanecomet": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/arcanecomet/arcanecomet.png",
        "celerity": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/celerity/celeritytemp.png",
        "gatheringstorm": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/gatheringstorm/gatheringstorm.png",
        "laststand": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/laststand/laststand.png",
        "manaflowband": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/manaflowband/manaflowband.png",
        "nimbuscloak": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/nimbuscloak/6361.png",
        "nullifyingorb": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/nullifyingorb/pokeshield.png",
        "phaserush": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/phaserush/phaserush.png",
        "scorch": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/scorch/scorch.png",
        "summonaery": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/summonaery/summonaery.png",
        "transcendence": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/transcendence/transcendence.png",
        "unflinching": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/unflinching/unflinching.png",
        "waterwalking": "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/styles/sorcery/waterwalking/waterwalking.png",
        }
    return rune_image_dict[rune_key]

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
        perk_dict[item["id"]] = {"name": item["key"], "key":rune_key} # Domination (8100), Inspiration (8300), Precision (8000), Resolve (8400), Sorcery (8200)
    rune_dict = {rune["id"]: rune["key"].lower() for item in html for slot in item["slots"] for rune in slot["runes"]}
    return {**perk_dict, **rune_dict}

def fetch_summoner_spell_data():
    url = f"{DDRAGON_URL}{CDN_VERSION}/data/en_US/summoner.json"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raise an error for bad status codes
        data =  response.json()["data"]
        return {spell["key"]: spell for spell in data.values()}
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return {}

def get_spell_image(spell_key):
    return f"/img/spell/{spell_key}.png"

def get_spells(participant):
    spell_data = fetch_summoner_spell_data()
    spells = []

    for i in range(2):  # There are 2 summoner spells
        spell_id = participant.get(f"summoner{i+1}Id")
        spell_casts = participant.get(f"summoner{i+1}Casts")
        if spell_id:
            spell_key = spell_data.get(str(spell_id), {}).get("id", "Unknown Spell")
            spell_name = spell_data.get(str(spell_id), {}).get("name", "Unknown Spell")
            spell_image = get_spell_image(spell_key)
            spells.append({
                "casts": spell_casts,
                "id": spell_id,
                "name": spell_name,
                "image": spell_image
            })
    return spells

def get_player(participant, match_overview):
    item_data = fetch_item_data()
    player = {}
    player["role"] = "SUPPORT" if participant["teamPosition"] == "UTILITY" else participant["teamPosition"]
    player["build"] = get_build(participant, item_data)
    player["trinket"] = get_item(participant, 6, item_data)
    player["champion"] = get_champion(participant)
    player["assists"] = participant["assists"]
    player["deaths"] = participant["deaths"]
    player["kills"] = participant["kills"]
    player["kda"] = round(participant["challenges"]["kda"], 2)
    player["profile"] = get_profile(participant)
    player["runes"] = get_runes(participant)
    player["summonerSpells"] = get_spells(participant)
    player["firstBlood"] = participant["firstBloodKill"]
    # player["mvp"] = isMVP(participant)
    player["cs"] = participant["totalMinionsKilled"] + participant["neutralMinionsKilled"]
    player["csm"] = round(player["cs"]/(match_overview["gameDuration"]/60), 2)
    player["cs14"] = random.randint(90, 140)
    player["dmg"] = participant["totalDamageDealtToChampions"]
    player["dpm"] = round(player["dmg"]/(match_overview["gameDuration"]/60), 2)
    player["teamDmgPercent"] = round(participant["challenges"]["teamDamagePercentage"]*100, 0)
    player["goldEarned"] = participant["goldEarned"]
    player["goldSpent"] = participant["goldSpent"]
    player["gpm"] = round(player["goldEarned"]/(match_overview["gameDuration"]/60), 2)
    player["killParticipation"] = round(participant["challenges"]["killParticipation"]*100, 0)
    player["effectiveHealAndShielding"] = round(participant["challenges"]["effectiveHealAndShielding"], 0)
    player["totalDamageTaken"] = participant["totalDamageTaken"]
    player["damageTakenPercent"] = round(participant["challenges"]["damageTakenOnTeamPercentage"]*100, 0)
    player["visionScore"] = participant["visionScore"]
    player["vspm"] = round(player["visionScore"]/(match_overview["gameDuration"]/60), 2)
    player["visionWardsBought"] = participant["visionWardsBoughtInGame"]
    player["wardsKilled"] = participant["wardsKilled"]
    player["wardsPlaced"] = participant["wardsPlaced"]
    player["soloKills"] = participant["challenges"]["soloKills"]
    return player
