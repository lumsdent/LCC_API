"""
mongo_connection.py
-------------------
Provides the MongoConnection class for connecting to MongoDB Atlas and
returning collection references used throughout the LCC API.
"""
import os
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from dotenv import load_dotenv


class MongoConnection:
    """Wrapper around a PyMongo client that exposes named collection accessors."""

    def __init__(self):
        load_dotenv()
        self.client = MongoClient(os.getenv('MONGO_URI'), server_api=ServerApi('1'))
        self.db = self.client[os.getenv('MONGO_COLLECTION')]

    def get_match_index_collection(self):
        """Return the ``matches_index`` collection."""
        return self.db['matches_index']

    def get_matches_collection(self):
        """Return the ``matches`` collection."""
        return self.db['matches']

    def get_teams_collection(self):
        """Return the ``teams`` collection."""
        return self.db['teams']

    def get_player_collection(self):
        """Return the ``players`` collection."""
        return self.db['players']

    def get_practice_collection(self):
        """Return the ``practice`` collection."""
        return self.db['practice']

    def get_tournaments_collection(self):
        """Return the ``tournaments`` collection."""
        return self.db['tournaments']

    def get_tournament_codes_collection(self):
        """Return the ``tournament_codes`` collection."""
        return self.db['tournament_codes']

    def get_match_performances_collection(self):
        """Return the ``match_performances`` collection (one doc per player per match)."""
        return self.db['match_performances']