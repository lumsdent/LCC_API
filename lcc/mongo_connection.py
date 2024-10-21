from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import os
from dotenv import load_dotenv

class MongoConnection:
    def __init__(self):
        load_dotenv()
        self.client = MongoClient(os.getenv("MONGO_URI"), server_api=ServerApi('1'))
        self.db = self.client['lcc_lol']

    def get_matches_collection(self):
        return self.db['matches']
    
    def get_teams_collection(self):
        return self.db['teams']    

    def get_player_collection(self):
        return self.db['players']
    
    def get_practice_collection(self):
        return self.db['practice']