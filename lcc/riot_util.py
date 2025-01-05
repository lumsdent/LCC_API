import requests
import os

def fetch_riot_data(url):
    api_key = os.getenv("RIOT_API_KEY")
    headers = {"X-Riot-Token": api_key}
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        raise requests.exceptions.HTTPError(f"Failed to fetch match data: {response.text}")
    return response.json()