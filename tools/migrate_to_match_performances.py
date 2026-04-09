#!/usr/bin/env python3
"""
migrate_to_match_performances.py
---------------------------------
One-time migration: reads every document from the ``matches`` collection,
extracts per-player stats, and upserts them as individual documents in the
new ``match_performances`` collection.

Also creates the indexes needed for efficient aggregation queries.

Run from the project root:
    python tools/migrate_to_match_performances.py

Safe to re-run — all writes are upserts keyed on (matchId, puuid).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.operations import ReplaceOne
from pymongo.server_api import ServerApi

# ---------------------------------------------------------------------------
# PUUID merge constants (same as in process_match_reports.py)
# ---------------------------------------------------------------------------
_MERGE_OLD_PUUID = 'OMb9S_LJfcHcmNf2EeoK6oKVZPN_ilQ_atdZLBHcS-1cNv38UZObF9COSP54dJn9eD4-mP23xpHUug'
_MERGE_NEW_PUUID = '2_h_CpcRsZypWQHR66PnB_DU1rHiQYz8AmRETV54QFVuZuwX9Ly_ys7R3SOh7fFo9U1CZ9VlPv50Aw'


def _normalize_puuid(puuid: str) -> str:
    return _MERGE_NEW_PUUID if puuid == _MERGE_OLD_PUUID else puuid


def build_performances(match_data: dict) -> list[dict]:
    """
    Convert a single match document into a list of ``match_performances`` documents
    (one per player, ten per match).
    """
    metadata      = match_data.get('metadata', {})
    info          = match_data.get('info', {})
    match_id      = metadata.get('matchId', '')
    season        = metadata.get('season', '')
    game_start    = info.get('gameStartTime', 0)
    game_creation = info.get('gameCreation', 0)
    game_duration = info.get('gameDuration', 0)
    game_version  = info.get('gameVersion', '')

    # Build role → {teamId: normalized_puuid} to resolve lane opponents.
    role_teams: dict = {}
    for team in info.get('teams', []):
        for player in team.get('players', []):
            puuid = _normalize_puuid(player['profile']['puuid'])
            role_teams.setdefault(player['role'], {})[team['teamId']] = puuid

    # Flatten to puuid → opponent_puuid.
    opponent_map: dict = {}
    for team_map in role_teams.values():
        puuids = list(team_map.values())
        if len(puuids) == 2:
            opponent_map[puuids[0]] = puuids[1]
            opponent_map[puuids[1]] = puuids[0]

    docs = []
    for team in info.get('teams', []):
        for player in team.get('players', []):
            puuid = _normalize_puuid(player['profile']['puuid'])
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
                'kills':                     player.get('kills', 0),
                'deaths':                    player.get('deaths', 0),
                'assists':                   player.get('assists', 0),
                'kda':                       player.get('kda', 0),
                'cs':                        player.get('cs', 0),
                'csm':                       player.get('csm', 0),
                'cs14':                      player.get('cs14', 0),
                'csd':                       player.get('csd', 0),
                'dmg':                       player.get('dmg', 0),
                'dpm':                       player.get('dpm', 0),
                'goldEarned':                player.get('goldEarned', 0),
                'goldSpent':                 player.get('goldSpent', 0),
                'gpm':                       player.get('gpm', 0),
                'visionScore':               player.get('visionScore', 0),
                'vspm':                      player.get('vspm', 0),
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
            docs.append(doc)
    return docs


def create_indexes(collection) -> None:
    """Create the compound indexes required for common aggregation and lookup patterns."""
    index_specs = [
        # Player season stats aggregation
        [('puuid', ASCENDING), ('season', ASCENDING)],
        # Paginated player match history
        [('puuid', ASCENDING), ('gameStartTimestamp', DESCENDING)],
        # Full scoreboard reconstruction for one match
        [('matchId', ASCENDING)],
        # Opponent resolution (same role, same match)
        [('matchId', ASCENDING), ('role', ASCENDING)],
        # League-wide champion stats per season
        [('champion.name', ASCENDING), ('season', ASCENDING)],
        # Player champion breakdown
        [('puuid', ASCENDING), ('champion.name', ASCENDING)],
        # Head-to-head records
        [('puuid', ASCENDING), ('opponentPuuid', ASCENDING)],
        # Season filter for champion stats all-time
        [('season', ASCENDING)],
    ]
    for spec in index_specs:
        collection.create_index(spec)
    print(f'  Created {len(index_specs)} indexes.')


def main() -> None:
    mongo_uri        = os.getenv('MONGO_URI')
    mongo_collection = sys.argv[1] if len(sys.argv) > 1 else os.getenv('MONGO_COLLECTION')
    if not mongo_uri or not mongo_collection:
        print('ERROR: MONGO_URI must be set in .env and a database name must be provided')
        print('Usage: python tools/migrate_to_match_performances.py [database_name]')
        sys.exit(1)
    print(f'Target database: {mongo_collection}')

    client = MongoClient(mongo_uri, server_api=ServerApi('1'))
    db     = client[mongo_collection]

    matches_col      = db['matches']
    performances_col = db['match_performances']

    print('Creating indexes on match_performances...')
    create_indexes(performances_col)

    all_matches = list(matches_col.find({}, {'_id': 0}))
    total_matches = len(all_matches)
    print(f'Found {total_matches} matches to migrate.')

    upserted, error_count, errors = 0, 0, []
    bulk_ops = []
    for i, match in enumerate(all_matches, 1):
        match_id = match.get('metadata', {}).get('matchId', '?')
        try:
            docs = build_performances(match)
            for doc in docs:
                bulk_ops.append(
                    ReplaceOne({'matchId': doc['matchId'], 'puuid': doc['puuid']}, doc, upsert=True)
                )
                upserted += 1
        except Exception as exc:
            errors.append(f'{match_id}: {exc}')
            error_count += 1

    if bulk_ops:
        print(f'Writing {len(bulk_ops)} documents in a single bulk operation...')
        performances_col.bulk_write(bulk_ops, ordered=False)
        print('  Done.')

    print('\nMigration complete.')
    print(f'  Matches processed : {total_matches - error_count}/{total_matches}')
    print(f'  Performance docs  : {upserted} upserted')
    if errors:
        print(f'  Errors ({error_count}):')
        for err in errors:
            print(f'    {err}')

    # ── Cleanup ───────────────────────────────────────────────────────────────
    # Strip match_history from all player documents now that match_performances
    # is the authoritative source. This is irreversible — only runs if the
    # performance docs were written without errors.
    if error_count == 0:
        players_col = db['players']
        result = players_col.update_many(
            {'match_history': {'$exists': True}},
            {'$unset': {'match_history': ''}}
        )
        print(f'\nCleanup: removed match_history from {result.modified_count} player documents.')
    else:
        print(f'\nCleanup skipped — {error_count} migration errors must be resolved first.')


if __name__ == '__main__':
    main()
