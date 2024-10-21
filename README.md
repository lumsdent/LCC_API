# LCC
Repository for the LCC, League Community Cup API for handling match data, tournament entries, and league player stats. 

## Prerequisites
### Riot API
To use the fetch, you will need to create a Riot account and generate a riot API key.  Learn more by visiting https://developer.riotgames.com/docs/portal.  

Create a ```.env``` file and add
```
RIOT_API_KEY='your-key-here'
MONGO_URI='mongo-connection-string-here'
```

### Dependency Installation

1. Activate your virtual environment
2. Run ```pip install -r requirements.txt```