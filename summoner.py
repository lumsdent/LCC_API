from riot_util import fetch_riot_data


def get_summoner_data(summoner_name, summoner_tag):
    summoner_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{summoner_name}/{summoner_tag}"
    summoner = fetch_riot_data(summoner_url)
    url = f"https://na1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{summoner['puuid']}"
    return fetch_riot_data(url)