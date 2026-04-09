"""
csv_to_match_json.py
--------------------
Converts an LCC playoff/stats CSV (with columns: Order, Summoner, Champion,
Team Name, Game ID, Victory, Position, Kills, Deaths, Assists, KDA,
Game Duration, DPM, DMG, CS, CS/M, CS@14, CSD@14, First Blood)
into per-game JSON files matching the LCC match document schema.

Player PUUIDs are resolved by looking up each summoner name in MongoDB.
Team tricodes (e.g. TAR, ZAP) are resolved to full names via teamsData.json.

Usage:
    python tools/csv_to_match_json.py <csv_file> [--season SEASON] [--out-dir OUTPUT_DIR]

Examples:
    python tools/csv_to_match_json.py "downloads/LCC Stats - S3 Playoff Game Stats.csv" --season 3P
    python tools/csv_to_match_json.py stats.csv --season 3P --out-dir example_json/playoffs
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import OrderedDict

# Allow importing from the lcc package (MongoConnection, dotenv) when run from repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# teamsData.json lives in the website repo next to the API repo.
_TEAMS_DATA_PATH = os.path.join(
    os.path.dirname(_REPO_ROOT), 'lcc-website', 'src', 'data', 'teamsData.json'
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

POSITION_MAP = {
    'top':     'TOP',
    'jungle':  'JUNGLE',
    'mid':     'MIDDLE',
    'middle':  'MIDDLE',
    'carry':   'BOTTOM',
    'adc':     'BOTTOM',
    'bot':     'BOTTOM',
    'bottom':  'BOTTOM',
    'support': 'SUPPORT',
    'supp':    'SUPPORT',
}


def parse_int(value: str) -> int | None:
    """Strip commas and parse as int. Returns None if blank or unparseable."""
    if not value or value.strip() == '':
        return None
    cleaned = value.replace(',', '').strip()
    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def parse_float(value: str) -> float | None:
    """Strip commas and parse as float. Returns None if blank or unparseable."""
    if not value or value.strip() == '':
        return None
    cleaned = value.replace(',', '').strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def parse_kda(value: str) -> float | None:
    """Parse KDA. '#DIV/0!' (perfect KDA / 0 deaths) returns None."""
    if not value or value.strip().upper() in ('#DIV/0!', '#DIV/0', ''):
        return None
    return parse_float(value)


def parse_bool(value: str) -> bool:
    return value.strip().upper() == 'TRUE'


def minutes_to_seconds(minutes_str: str) -> int | None:
    """Convert decimal minutes string to whole seconds."""
    m = parse_float(minutes_str)
    if m is None:
        return None
    return round(m * 60)


def champion_image(name: str) -> dict:
    """Build a minimal champion image dict from a display name."""
    # Normalise the image key (remove spaces/apostrophes, handle special cases)
    key = name.replace(' ', '').replace("'", '').replace('.', '')
    return {
        'full':   f'/img/champion/{key}.png',
        'square': f'/img/champion/{key}.png',
    }


# ---------------------------------------------------------------------------
# Team tricode → full name resolver
# ---------------------------------------------------------------------------

def load_tricode_map(teams_data_path: str) -> dict[str, str]:
    """
    Read teamsData.json and return a dict mapping every tricode (e.g. 'TAR')
    to its current full team name (e.g. 'Targon Titans').
    Returns an empty dict if the file cannot be read.
    """
    if not os.path.isfile(teams_data_path):
        print(f'WARNING: teamsData.json not found at {teams_data_path} — tricodes will pass through unchanged.')
        return {}
    with open(teams_data_path, encoding='utf-8-sig') as f:
        data = json.load(f)
    return {team['tricode']: team['name'] for team in data.get('teams', []) if 'tricode' in team}


# ---------------------------------------------------------------------------
# MongoDB player PUUID lookup
# ---------------------------------------------------------------------------

def build_name_puuid_map(players_collection) -> dict[str, str]:
    """
    Query all player documents and return a dict mapping lowercase summoner
    name → PUUID.  When multiple documents share the same name (rare), the
    last one wins — acceptable for a CSV import tool.
    """
    name_map: dict[str, str] = {}
    for doc in players_collection.find({}, {'profile.name': 1, 'profile.puuid': 1, '_id': 0}):
        profile = doc.get('profile', {})
        name    = profile.get('name', '')
        puuid   = profile.get('puuid', '')
        if name and puuid:
            name_map[name.lower()] = puuid
    return name_map


def resolve_puuid(summoner_name: str, name_puuid_map: dict[str, str]) -> str | None:
    """Case-insensitive PUUID lookup. Returns None if not found."""
    if not name_puuid_map:
        return None
    return name_puuid_map.get(summoner_name.strip().lower())


# ---------------------------------------------------------------------------
# Profile builder
# ---------------------------------------------------------------------------

def make_placeholder_profile(summoner_name: str, puuid: str | None = None) -> dict:
    """
    Build a minimal profile dict from a summoner display name.
    If puuid is provided (resolved from MongoDB) it is included.
    """
    return {
        'puuid':    puuid,
        'name':     summoner_name,
        'tag':      None,
        'level':    None,
        'images':   {'icon': None},
        'is_active': True,
    }


def make_player(row: dict, name_puuid_map: dict | None = None) -> dict:
    """Convert one CSV row into a player sub-document."""
    role_raw = row.get('Position', '').strip().lower()
    role = POSITION_MAP.get(role_raw, role_raw.upper())

    champ_name  = row.get('Champion', '').strip()
    kills       = parse_int(row.get('Kills', ''))
    deaths      = parse_int(row.get('Deaths', ''))
    assists     = parse_int(row.get('Assists', ''))
    kda         = parse_kda(row.get('KDA', ''))
    dpm         = parse_float(row.get('DPM', ''))
    dmg         = parse_int(row.get('DMG', ''))
    cs          = parse_int(row.get('CS', ''))
    csm         = parse_float(row.get('CS/M', ''))
    cs14        = parse_int(row.get('CS@14', ''))
    csd         = parse_int(row.get('CSD@14', ''))
    first_blood = parse_bool(row.get('First Blood', 'FALSE'))

    return {
        'role': role,
        # Items/runes/spells are not in the CSV — leave as empty placeholders
        'build':          [],
        'trinket':         None,
        'champion': {
            'id':    None,
            'name':  champ_name,
            'level': None,
            'image': champion_image(champ_name),
        },
        'kills':   kills,
        'deaths':  deaths,
        'assists': assists,
        'kda':     kda,
        'profile': make_placeholder_profile(
            row.get('Summoner', '').strip(),
            puuid=resolve_puuid(row.get('Summoner', ''), name_puuid_map or {}),
        ),
        'runes':           None,
        'summonerSpells':  [],
        'firstBlood':   first_blood,
        'cs':    cs,
        'csm':   csm,
        'dmg':   dmg,
        'dpm':   dpm,
        # Fields not present in CSV — set to None so callers know they're missing
        'teamDmgPercent':          None,
        'goldEarned':              None,
        'goldSpent':               None,
        'gpm':                     None,
        'killParticipation':       None,
        'effectiveHealAndShielding': None,
        'totalDamageTaken':        None,
        'damageTakenPercent':      None,
        'visionScore':             None,
        'vspm':                    None,
        'visionWardsBought':       None,
        'wardsKilled':             None,
        'wardsPlaced':             None,
        'soloKills':               None,
        'cs14': cs14,
        'csd':  csd,
    }


def make_team(
    tricode: str,
    side_index: int,
    rows: list[dict],
    tricode_map: dict[str, str],
    name_puuid_map: dict[str, str],
) -> dict:
    """Build a team sub-document from all rows belonging to this team in one game."""
    sides    = ['Blue', 'Red']
    team_ids = [100, 200]

    full_name    = tricode_map.get(tricode, tricode)  # fall back to tricode if not found
    game_outcome = parse_bool(rows[0].get('Victory', 'FALSE'))
    total_kills  = sum(parse_int(r.get('Kills', '0')) or 0 for r in rows)

    return {
        'name':        full_name,
        'side':        sides[side_index % 2],
        'teamId':      team_ids[side_index % 2],
        'gameOutcome': game_outcome,
        'kills':       total_kills,
        'gold':        None,   # not in CSV
        'bans':        [],     # not in CSV
        'objectives':  {},     # not in CSV
        'players':     [make_player(r, name_puuid_map) for r in rows],
    }


def rows_to_match(
    game_id: str,
    game_rows: list[dict],
    season: str,
    tricode_map: dict[str, str],
    name_puuid_map: dict[str, str],
) -> dict:
    """Convert all rows for a single game ID into a full match document."""
    # Preserve team order of appearance (tricodes from CSV)
    tricodes_ordered: list[str] = list(OrderedDict.fromkeys(r['Team Name'] for r in game_rows))

    game_duration_min = game_rows[0].get('Game Duration', '0')
    duration_seconds  = minutes_to_seconds(game_duration_min)

    teams = []
    for idx, tricode in enumerate(tricodes_ordered):
        team_rows = [r for r in game_rows if r['Team Name'] == tricode]
        teams.append(make_team(tricode, idx, team_rows, tricode_map, name_puuid_map))

    full_names = [tricode_map.get(tc, tc) for tc in tricodes_ordered]
    match_name = ' vs '.join(full_names)

    # Collect resolved PUUIDs for metadata.participants (preserves order: team0 then team1)
    participants = [
        p['profile']['puuid']
        for team in teams
        for p in team['players']
        if p['profile'].get('puuid')
    ]

    return {
        'metadata': {
            'dataVersion': '2',
            'matchId':     game_id,
            'participants': participants,
            'matchName':   match_name,
            'season':      str(season),
        },
        'info': {
            'gameCreation':    None,
            'gameDuration':    duration_seconds,
            'gameStartTime':   None,
            'gameEndTimestamp': None,
            'gameId':          game_id,
            'gameMode':        'CLASSIC',
            'gameVersion':     None,
            'teams':           teams,
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Convert LCC stats CSV to match JSON documents.')
    parser.add_argument('csv_file',          help='Path to the input CSV file')
    parser.add_argument('--season',          default='',    help='Season identifier, e.g. 3P')
    parser.add_argument('--out-dir',         default='',    help='Output directory (default: same dir as CSV)')
    parser.add_argument('--single-file',     action='store_true',
                        help='Write all matches into one JSON array file instead of separate files')
    args = parser.parse_args()

    csv_path = args.csv_file
    if not os.path.isfile(csv_path):
        print(f'ERROR: File not found: {csv_path}')
        return

    out_dir = args.out_dir or os.path.dirname(os.path.abspath(csv_path))
    os.makedirs(out_dir, exist_ok=True)

    # --- Team tricode map ------------------------------------------------
    tricode_map = load_tricode_map(_TEAMS_DATA_PATH)
    if tricode_map:
        print(f'Loaded {len(tricode_map)} team tricodes from teamsData.json')
    else:
        print('No tricode map loaded — team names will use raw CSV values')

    # --- MongoDB PUUID map -----------------------------------------------
    name_puuid_map: dict[str, str] = {}
    try:
        from lcc.mongo_connection import MongoConnection
        _db         = MongoConnection()
        _players    = _db.get_player_collection()
        name_puuid_map = build_name_puuid_map(_players)
        print(f'Loaded {len(name_puuid_map)} player PUUIDs from MongoDB')
    except Exception as exc:
        print(f'WARNING: Could not connect to MongoDB ({exc}) — PUUIDs will be null')

    # --- Read CSV --------------------------------------------------------
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    # Group by Game ID, preserving order of appearance
    games: dict[str, list[dict]] = OrderedDict()
    for row in all_rows:
        gid = row.get('Game ID', '').strip()
        if not gid:
            continue
        games.setdefault(gid, []).append(row)

    matches = [
        rows_to_match(gid, rows, args.season, tricode_map, name_puuid_map)
        for gid, rows in games.items()
    ]

    if args.single_file:
        base_name = re.sub(r'[^\w\-]', '_', os.path.splitext(os.path.basename(csv_path))[0])
        out_path  = os.path.join(out_dir, f'{base_name}.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(matches, f, indent=2)
        print(f'Wrote {len(matches)} matches → {out_path}')
    else:
        for match in matches:
            safe_id  = re.sub(r'[^\w\-]', '_', match['metadata']['matchId'])
            out_path = os.path.join(out_dir, f'{safe_id}.json')
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(match, f, indent=2)
            print(f'  Wrote → {out_path}')
        print(f'\nDone. {len(matches)} match file(s) written to {out_dir}')


if __name__ == '__main__':
    main()
