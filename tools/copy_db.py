#!/usr/bin/env python3
"""
copy_db.py
----------
Copies all collections from a source MongoDB database to a destination database.

Usage:
    python tools/copy_db.py [source_db] [dest_db]

Defaults:
    source_db = lcc_lol
    dest_db   = lcc_lol_bkp

Safe to re-run — destination collections are dropped and rebuilt each time.
"""
import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.server_api import ServerApi

load_dotenv()

SOURCE_DB = sys.argv[1] if len(sys.argv) > 1 else 'lcc_lol'
DEST_DB   = sys.argv[2] if len(sys.argv) > 2 else 'lcc_lol_bkp1'

client = MongoClient(os.getenv('MONGO_URI'), server_api=ServerApi('1'))

source = client[SOURCE_DB]
dest   = client[DEST_DB]

collections = source.list_collection_names()
if not collections:
    print(f'No collections found in {SOURCE_DB}. Check the database name.')
    sys.exit(1)

print(f'Copying {SOURCE_DB} → {DEST_DB}')
print(f'Collections: {", ".join(collections)}\n')

for col_name in collections:
    src_col  = source[col_name]
    dest_col = dest[col_name]

    count = src_col.count_documents({})
    print(f'  [{col_name}] {count} documents ...', end=' ', flush=True)

    if count == 0:
        print('skipped (empty)')
        continue

    # Drop destination collection to start clean
    dest_col.drop()

    # Batch insert in chunks of 500 to avoid memory spikes on large collections
    batch = []
    inserted = 0
    for doc in src_col.find({}):
        batch.append(doc)
        if len(batch) == 500:
            dest_col.insert_many(batch)
            inserted += len(batch)
            batch = []
    if batch:
        dest_col.insert_many(batch)
        inserted += len(batch)

    # Recreate indexes (skip the default _id index)
    for idx in src_col.list_indexes():
        if idx['name'] == '_id_':
            continue
        keys   = list(idx['key'].items())
        opts   = {k: v for k, v in idx.items() if k not in ('key', 'ns', 'v')}
        opts.pop('name', None)  # let MongoDB generate the name
        try:
            dest_col.create_index(keys, **opts)
        except Exception as e:
            print(f'\n    Warning: could not recreate index {idx["name"]}: {e}')

    print(f'done ({inserted} docs)')

print(f'\nCopy complete: {SOURCE_DB} → {DEST_DB}')
client.close()
