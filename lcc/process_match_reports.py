"""
process_match_reports.py
------------------------
Contains helpers for fetching and transforming Riot API match data into the
normalised document format stored in MongoDB.

Provides ``process_match``, ``get_matchups``, player/champion helpers, and
all DDragon data-fetching utilities.
"""
import os
import requests
from .mongo_connection import MongoConnection

DDRAGON_CDN = 'https://ddragon.leagueoflegends.com/cdn/latest'

# Duplicate accounts belonging to the same player — remap old → canonical.
_MERGE_OLD_PUUID = 'OMb9S_LJfcHcmNf2EeoK6oKVZPN_ilQ_atdZLBHcS-1cNv38UZObF9COSP54dJn9eD4-mP23xpHUug'
_MERGE_NEW_PUUID = '2_h_CpcRsZypWQHR66PnB_DU1rHiQYz8AmRETV54QFVuZuwX9Ly_ys7R3SOh7fFo9U1CZ9VlPv50Aw'

def process_match(user_data):
    """Fetch a match and its timeline from the Riot API and return a processed match document."""
    match_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/NA1_{user_data['matchId']}"
    riot_match_data = fetch_riot_data(match_url)
    riot_timeline_data = fetch_riot_data(match_url + '/timeline')
    timeline_data = process_timeline_data(riot_timeline_data)
    return process_match_data(riot_match_data, timeline_data, user_data)

def build_matchup(player):
    """Build a compact matchup reference dict from a player sub-document."""
    return {
        'puuid':         player['profile']['puuid'],
        'teamImage':     player['team']['image'],
        'teamName':      player['team']['name'],
        'player':        player['profile']['name'],
        'championName':  player['champion']['name'],
        'championImage': player['champion']['image'],
    }

def get_matchups(match_data, role):
    """
    Return a list of 0–2 player sub-documents for the given role, each augmented
    with match context and a ``vs`` reference to the lane opponent.
    """
    matchups = []
    for team in match_data['info']['teams']:
        for player in team['players']:
            if player['role'] == role:
                player['matchId']            = match_data['metadata']['matchId']
                player['season']             = match_data['metadata']['season']
                player['gameStartTimestamp'] = match_data['info']['gameStartTime']
                player['win']                = team['gameOutcome']
                player['team']               = {'name': team['name'], 'image': f"{team['name'].lower()}.png"}
                matchups.append(player)
                break
    if len(matchups) == 2:
        matchups[0]['vs'] = build_matchup(matchups[1])
        matchups[1]['vs'] = build_matchup(matchups[0])
    return matchups


def save_match_performances(match_data):
    """
    Extract per-player performance records from a processed match document and
    upsert them into the ``match_performances`` collection.

    Resolves ``opponentPuuid`` for each player via role-matching across teams, and
    normalises the legacy duplicate account PUUID to the canonical value before writing.
    """
    _performances = _db.get_match_performances_collection()

    match_id      = match_data['metadata']['matchId']
    season        = match_data['metadata']['season']
    game_start    = match_data['info'].get('gameStartTime', 0)
    game_creation = match_data['info'].get('gameCreation', 0)
    game_duration = match_data['info'].get('gameDuration', 0)
    game_version  = match_data['info'].get('gameVersion', '')

    # Build role → {teamId: normalized_puuid} so we can resolve lane opponents.
    role_teams: dict = {}
    for team in match_data['info']['teams']:
        for player in team['players']:
            puuid = player['profile']['puuid']
            if puuid == _MERGE_OLD_PUUID:
                puuid = _MERGE_NEW_PUUID
            role_teams.setdefault(player['role'], {})[team['teamId']] = puuid

    # Flatten to puuid → opponent_puuid.
    opponent_map: dict = {}
    for team_map in role_teams.values():
        puuids = list(team_map.values())
        if len(puuids) == 2:
            opponent_map[puuids[0]] = puuids[1]
            opponent_map[puuids[1]] = puuids[0]

    for team in match_data['info']['teams']:
        for player in team['players']:
            puuid = player['profile']['puuid']
            if puuid == _MERGE_OLD_PUUID:
                puuid = _MERGE_NEW_PUUID

            doc = {
                'matchId':                   match_id,
                'season':                    season,
                'gameStartTimestamp':        game_start,
                'gameCreation':              game_creation,
                'gameDuration':              game_duration,
                'gameVersion':               game_version,
                'win':                       team['gameOutcome'],
                'teamSide':                  team.get('side', ''),
                'teamName':                  team['name'],
                'teamImage':                 f"{team['name'].replace(' ', '_').lower()}.png",
                'puuid':                     puuid,
                'playerName':                player['profile']['name'],
                'playerIcon':                player['profile'].get('images', {}).get('icon', ''),
                'role':                      player['role'],
                'champion':                  player['champion'],
                'build':                     player.get('build', []),
                'trinket':                   player.get('trinket', {}),
                'runes':                     player.get('runes', {}),
                'summonerSpells':            player.get('summonerSpells', []),
                'kills':                     player['kills'],
                'deaths':                    player['deaths'],
                'assists':                   player['assists'],
                'kda':                       player['kda'],
                'cs':                        player['cs'],
                'csm':                       player['csm'],
                'cs14':                      player['cs14'],
                'csd':                       player['csd'],
                'dmg':                       player['dmg'],
                'dpm':                       player['dpm'],
                'goldEarned':                player['goldEarned'],
                'goldSpent':                 player.get('goldSpent', 0),
                'gpm':                       player['gpm'],
                'visionScore':               player['visionScore'],
                'vspm':                      player['vspm'],
                'visionWardsBought':         player.get('visionWardsBought', 0),
                'wardsPlaced':               player.get('wardsPlaced', 0),
                'wardsKilled':               player.get('wardsKilled', 0),
                'killParticipation':         player.get('killParticipation', 0),
                'soloKills':                 player.get('soloKills', 0),
                'firstBlood':                player.get('firstBlood', False),
                'effectiveHealAndShielding': player.get('effectiveHealAndShielding', 0),
                'totalDamageTaken':          player.get('totalDamageTaken', 0),
                'damageTakenPercent':        player.get('damageTakenPercent', 0),
                'teamDmgPercent':            player.get('teamDmgPercent', 0),
                'opponentPuuid':             opponent_map.get(puuid, ''),
            }
            _performances.replace_one(
                {'matchId': match_id, 'puuid': puuid},
                doc,
                upsert=True,
            )


    """
    Build a role → team ID → PUUID mapping from a list of Riot participant dicts.

    Returns a dict keyed by position name (TOP, JUNGLE, etc.) where each value
    maps team ID 100/200 to the occupying player's PUUID.
    """
    position_data = {
        'TOP':     {100: None, 200: None},
        'JUNGLE':  {100: None, 200: None},
        'MIDDLE':  {100: None, 200: None},
        'BOTTOM':  {100: None, 200: None},
        'UTILITY': {100: None, 200: None},
    }
    for participant in participants:
        position = participant['teamPosition']
        team     = participant['teamId']
        if position in position_data and team in position_data[position]:
            position_data[position][team] = participant['puuid']
    return position_data

def fetch_riot_data(url):
    """Make an authenticated GET request to the Riot API and return parsed JSON."""
    headers = {'X-Riot-Token': os.getenv('RIOT_API_KEY')}
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        raise requests.exceptions.HTTPError(f'Failed to fetch Riot data: {response.text}')
    return response.json()
        
def process_match_data(match_data, timeline_data, user_data):
    """
    Transform raw Riot match/timeline data and user-supplied metadata into the
    normalised match document stored in MongoDB.
    """
    blue_team_players = []
    red_team_players = []
    match_overview = {
        'gameCreation':    match_data['info']['gameCreation'],
        'gameDuration':    match_data['info']['gameDuration'],
        'gameStartTime':   match_data['info']['gameStartTimestamp'],
        'gameEndTimestamp': match_data['info']['gameEndTimestamp'],
        'gameId':          match_data['metadata']['matchId'],
        'gameMode':        match_data['info']['gameMode'],
        'gameVersion':     match_data['info']['gameVersion'],
    }
    csd14_data = calculate_csd14(match_data, timeline_data)
    for participant in match_data['info']['participants']:
        player = get_player(participant, match_overview)
        puuid  = participant['puuid']
        player['cs14'] = timeline_data[puuid]['cs14'] if puuid in timeline_data else round(player['csm'] * 14)
        player['csd']  = csd14_data.get(puuid, 0)
        if participant['teamId'] == 100:
            blue_game_result = participant['win']
            blue_team_players.append(player)
        else:
            red_game_result = participant['win']
            red_team_players.append(player)
    for team in match_data['info']['teams']:
        if team['teamId'] == 100:
            blue_team = {
                'name':        user_data['blueTeam'],
                'side':        'Blue',
                'teamId':      100,
                'gameOutcome': blue_game_result,
                'kills':       sum(p['kills'] for p in blue_team_players),
                'gold':        sum(p['goldEarned'] for p in blue_team_players),
                'bans':        get_bans(team),
                'objectives':  get_objectives(team),
                'players':     blue_team_players,
            }
        else:
            red_team = {
                'name':        user_data['redTeam'],
                'side':        'Red',
                'teamId':      200,
                'gameOutcome': red_game_result,
                'kills':       sum(p['kills'] for p in red_team_players),
                'gold':        sum(p['goldEarned'] for p in red_team_players),
                'bans':        get_bans(team),
                'objectives':  get_objectives(team),
                'players':     red_team_players,
            }
    match_overview['teams'] = [blue_team, red_team]
    metadata = match_data['metadata']
    metadata['matchName'] = f"{user_data['blueTeam']} vs {user_data['redTeam']}"
    metadata['season']    = user_data['season']
    return {'metadata': metadata, 'info': match_overview}

def get_bans(team):
    """Return a list of banned champion dicts (with pick turn) for a team."""
    bans = []
    for ban in team['bans']:
        banned_champ = get_champion_by_id(ban['championId'])
        banned_champ['pickTurn'] = ban['pickTurn']
        bans.append(banned_champ)
    return bans

def get_champion_mastery(puuid):
    """Return the top 3 champion mastery entries for a player, or [] on failure."""
    url = f'https://na1.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}'
    try:
        response = fetch_riot_data(url)
        top_champions = []
        for mastery in response[:3]:
            champion = get_champion_by_id(mastery['championId'])
            if champion is None:
                continue
            champion['championMastery'] = mastery['championLevel']
            champion['championPoints']  = mastery['championPoints']
            champion['lastPlayTime']    = mastery['lastPlayTime']
            top_champions.append(champion)
        return top_champions
    except requests.exceptions.RequestException:
        return []

def get_champion_by_id(champion_id):
    """Look up a champion by its numeric Riot ID and return a normalised champion dict, or None if not found."""
    for champion in fetch_champion_data():
        if int(champion['key']) == champion_id:
            return {
                'id':    champion['id'],
                'name':  champion['name'],
                'title': champion['title'],
                'image': {
                    'full':   f"/img/champion/{champion['image']['full']}",
                    'square': f"/img/champion/{champion['image']['full']}",
                },
            }
    return None

def fetch_champion_data():
    """Fetch and return an iterable of champion data dicts from DDragon."""
    url = f'{DDRAGON_CDN}/data/en_US/champion.json'
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()['data'].values()
    except requests.exceptions.RequestException:
        return {}
    
_db = MongoConnection()
_players = _db.get_player_collection()


def find_player(puuid):
    """Return a player document by PUUID, or None if not found."""
    return _players.find_one({'profile.puuid': puuid}, {'_id': 0})
    
def get_objectives(team):
    """Augment a team's objectives dict with CDragon image URLs and return it."""
    cdn = 'https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-match-history/global/default'
    tid = team['teamId']
    obj = team['objectives']
    obj['baron']['image']      = f'{cdn}/baron-{tid}.png'
    obj['dragon']['image']     = f'{cdn}/dragon-{tid}.png'
    obj['riftHerald']['image'] = f'{cdn}/herald-{tid}.png'
    obj['tower']['image']      = f'{cdn}/tower-{tid}.png'
    obj['inhibitor']['image']  = f'{cdn}/inhibitor-{tid}.png'
    obj['horde']['image']      = f'{cdn}/horde.png'
    return obj
    
    
def process_timeline_data(timeline_data):
    """
    Extract CS@14 for every participant from raw Riot timeline data.

    Scans frames for the 14-minute timestamp window (840–850 s) and returns
    a ``{puuid: {'cs14': int}}`` dict.
    """
    minute_14 = None
    for frame in timeline_data['info']['frames']:
        if 840000 < frame['timestamp'] < 850000:
            minute_14 = frame['participantFrames']
            break
    if minute_14 is None:
        return {}
    participant_map = {
        participant['puuid']: participant['participantId']
        for participant in timeline_data['info']['participants']
    }
    participants = {}
    for puuid, pid in participant_map.items():
        pdata = minute_14.get(str(pid))
        if pdata:
            participants[puuid] = {
                'cs14': pdata['minionsKilled'] + pdata['jungleMinionsKilled']
            }
    return participants

def calculate_csd14(match_data, timeline_data):
    """Calculate CS difference at 14 minutes for each player versus their lane opponent."""
    position_data = get_position_data(match_data['info']['participants'])
    csd14_data = {}
    for role in ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']:
        blue = position_data[role][100]
        red  = position_data[role][200]
        if blue is None or red is None:
            continue
        if blue in timeline_data and red in timeline_data:
            blue_cs = timeline_data[blue]['cs14']
            red_cs  = timeline_data[red]['cs14']
            csd14_data[blue] = blue_cs - red_cs
            csd14_data[red]  = red_cs  - blue_cs
    return csd14_data


def fetch_item_data():
    """Fetch and return the DDragon item data dict keyed by item ID string."""
    url = f'{DDRAGON_CDN}/data/en_US/item.json'
    response = requests.get(url, timeout=10)
    if response.status_code == 200:
        return response.json()['data']
    raise RuntimeError('Failed to fetch item data')


def get_item_name(item_data, item_id):
    """Return the name of an item by ID, or 'Unknown Item' if not found."""
    return item_data.get(str(item_id), {}).get('name', 'Unknown Item')


def get_build(participant, item_data):
    """Return a list of 6 item dicts representing a participant's build."""
    return [get_item(participant, i, item_data) for i in range(6)]


def get_item(participant, item_number, item_data):
    """Return a single item dict for the given slot, or an empty-slot placeholder."""
    item_id = participant.get(f'item{item_number}')
    if item_id:
        return {
            'id':    item_id,
            'name':  get_item_name(item_data, item_id),
            'image': f'/img/item/{item_id}.png',
        }
    return {
        'id':    0,
        'name':  'Empty Slot',
        'image': 'https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/assets/items/icons2d/gp_ui_placeholder.png',
    }

def get_champion(participant):
    """Build a champion sub-document from a Riot participant dict."""
    return {
        'id':         participant['championId'],
        'name':       participant['championName'],
        'level':      participant['champLevel'],
        'experience': participant['champExperience'],
        'image':      {'square': f"/img/champion/{participant['championName']}.png"},
    }

def get_profile(participant):
    """Return the player's profile from MongoDB, falling back to a live Riot API lookup."""
    puuid       = participant['puuid']
    player_data = find_player(puuid)
    if player_data and 'profile' in player_data:
        return player_data['profile']
    return get_riot_account(puuid)

def get_riot_account(puuid):
    """Fetch basic account and summoner info for a PUUID from the Riot API."""
    account  = fetch_riot_data(f'https://americas.api.riotgames.com/riot/account/v1/accounts/by-puuid/{puuid}')
    summoner = fetch_riot_data(f"https://na1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{account['puuid']}")
    return {
        'puuid':         account['puuid'],
        'name':          account['gameName'],
        'tag':           account['tagLine'],
        'level':         summoner['summonerLevel'],
        'revision_date': summoner['revisionDate'],
        'images':        {'icon': f"/img/profileicon/{summoner['profileIconId']}.png"},
    }


def get_runes(participant):
    """
    Build a runes sub-document with primary and secondary tree info.

    Returns a dict with ``primary`` (name, image, keystone) and
    ``secondary`` (name, image) keys.
    """
    styles           = participant['perks']['styles']
    primary_raw      = styles[0]
    secondary_raw    = styles[1]
    rune_data        = ddragon_get_runes_dict()

    primary_tree_id  = primary_raw['style']
    primary_perk_ids = [s['perk'] for s in primary_raw['selections']]
    secondary_tree_id = secondary_raw['style']

    primary = {
        'name':     rune_data[primary_tree_id],
        'image':    get_rune_image(rune_data[primary_tree_id]['key']),
        'keystone': {
            'id':    primary_perk_ids[0],
            'name':  rune_data[primary_perk_ids[0]],
            'image': get_rune_image(rune_data[primary_perk_ids[0]]),
        },
    }
    secondary = {
        'name':  rune_data[secondary_tree_id],
        'image': get_rune_image(rune_data[secondary_tree_id]['key']),
    }
    return {'primary': primary, 'secondary': secondary}

def get_rune_image(rune_key):
    """Return the CDragon image URL for a rune identified by its lowercase key."""
    rune_image_dict = {
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
    """
    Fetch and return a rune ID mapping from DDragon.

    Tree IDs map to ``{'name': str, 'key': str}`` dicts; individual rune IDs
    map to their lowercase key string. Returns ``{}`` on failure.
    """
    url = f'{DDRAGON_CDN}/data/en_US/runesReforged.json'
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException:
        return {}
    perk_dict = {
        item['id']: {'name': item['key'], 'key': item['icon'].split('/')[-1].split('.')[0].lower()}
        for item in data
    }
    rune_dict = {rune['id']: rune['key'].lower() for item in data for slot in item['slots'] for rune in slot['runes']}
    return {**perk_dict, **rune_dict}

def fetch_summoner_spell_data():
    """Fetch summoner spell data from DDragon, keyed by numeric spell ID string."""
    url = f'{DDRAGON_CDN}/data/en_US/summoner.json'
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()['data']
        return {spell['key']: spell for spell in data.values()}
    except requests.exceptions.RequestException:
        return {}

def get_spell_image(spell_key):
    """Return the local image path for a summoner spell."""
    return f'/img/spell/{spell_key}.png'


def get_spells(participant):
    """Return a list of 2 summoner spell dicts for a participant."""
    spell_data = fetch_summoner_spell_data()
    spells = []
    for i in range(2):
        spell_id    = participant.get(f'summoner{i + 1}Id')
        spell_casts = participant.get(f'summoner{i + 1}Casts')
        if spell_id:
            spell_key  = spell_data.get(str(spell_id), {}).get('id', 'Unknown Spell')
            spell_name = spell_data.get(str(spell_id), {}).get('name', 'Unknown Spell')
            spells.append({
                'casts': spell_casts,
                'id':    spell_id,
                'name':  spell_name,
                'image': get_spell_image(spell_key),
            })
    return spells

def get_player(participant, match_overview):
    """
    Build a full player sub-document from a Riot participant dict.

    Computes per-minute stats (CSM, DPM, GPM, VSPM) using ``gameDuration``
    from ``match_overview``. CS@14 and CSD@14 are injected by the caller.
    """
    item_data = fetch_item_data()
    mins      = match_overview['gameDuration'] / 60
    cs        = participant['totalMinionsKilled'] + participant['neutralMinionsKilled']
    dmg       = participant['totalDamageDealtToChampions']
    gold      = participant['goldEarned']
    vs        = participant['visionScore']
    return {
        'role':                       'SUPPORT' if participant['teamPosition'] == 'UTILITY' else participant['teamPosition'],
        'build':                      get_build(participant, item_data),
        'trinket':                    get_item(participant, 6, item_data),
        'champion':                   get_champion(participant),
        'assists':                    participant['assists'],
        'deaths':                     participant['deaths'],
        'kills':                      participant['kills'],
        'kda':                        round(participant['challenges']['kda'], 2),
        'profile':                    get_profile(participant),
        'runes':                      get_runes(participant),
        'summonerSpells':             get_spells(participant),
        'firstBlood':                 participant['firstBloodKill'],
        'cs':                         cs,
        'csm':                        round(cs / mins, 2),
        'dmg':                        dmg,
        'dpm':                        round(dmg / mins, 2),
        'teamDmgPercent':             round(participant['challenges']['teamDamagePercentage'] * 100, 0),
        'goldEarned':                 gold,
        'goldSpent':                  participant['goldSpent'],
        'gpm':                        round(gold / mins, 2),
        'killParticipation':          round(participant['challenges']['killParticipation'] * 100, 0),
        'effectiveHealAndShielding':  round(participant['challenges']['effectiveHealAndShielding'], 0),
        'totalDamageTaken':           participant['totalDamageTaken'],
        'damageTakenPercent':         round(participant['challenges']['damageTakenOnTeamPercentage'] * 100, 0),
        'visionScore':                vs,
        'vspm':                       round(vs / mins, 2),
        'visionWardsBought':          participant['visionWardsBoughtInGame'],
        'wardsKilled':                participant['wardsKilled'],
        'wardsPlaced':                participant['wardsPlaced'],
        'soloKills':                  participant['challenges']['soloKills'],
    }
