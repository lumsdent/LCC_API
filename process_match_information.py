import requests
import os
from dotenv import load_dotenv
import outputs


def main():
    # Accept user input for the file name
    tournament_name = input("Enter the tournament file name (Enter to use LCC_Season_2): ")
    file_path = f"tournaments/{(tournament_name,'LCC_Season_2')[tournament_name == '']}.txt"    
    file_name = file_path.split("/")[-1].split(".")[0]
  
    # Open the file and read the match IDs
    with open(file_path, "r") as file:
        match_ids = file.readlines()

    if not match_ids:
        print("No match IDs found in the file.")
        return
    
    processed_matches = []
    # For each listed match, fetch and transform the data
    for match_id in match_ids:
        match_id = match_id.strip()
        match_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/NA1_{match_id}"
        riot_match_data = fetch_riot_data(match_url)
        processed_match = process_match_data(riot_match_data)

        # Fetch and process timeline data
        timeline_url = match_url + "/timeline"
        riot_timeline_data = fetch_riot_data(timeline_url)
        processed_timeline_data = process_timeline_data(riot_timeline_data)

        # Merge the timeline data with the match data
        processed_match["participants"] = [dict(participant, **processed_timeline_data[participant["puuid"]]) for participant in processed_match["participants"]]

        # Dump each processed match data to json file for future additional programmatic use
        outputs.build_match_json(file_name, match_id, processed_match)
        
        # Add to list for excel workbook
        processed_matches.append(processed_match)
    outputs.build_excel_workbook(processed_matches)
    print("Excel workbook created successfully.")

def fetch_riot_data(url):
    api_key = os.getenv("RIOT_API_KEY")
    headers = {"X-Riot-Token": api_key}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch match data: {response.text}")
    return response.json()
        
def process_match_data(match_data):
    match_information = {}
    participant_information = []
    
    match_information["game_id"] = match_data["metadata"]["matchId"]
    
    for participant in match_data["info"]["participants"]:
        participant_information.append(process_participant_data(participant))
    match_information["participants"] = participant_information
    return match_information

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

def process_participant_data(participant_data):
    participant_information = {}
    participant_information["puuid"] = participant_data["puuid"]
    participant_information["riotIdGameName"] = participant_data["riotIdGameName"]
    participant_information["championName"] = participant_data["championName"]
    participant_information["role"] = participant_data["teamPosition"]
    participant_information["win"] = participant_data["win"]
    participant_information["gameLength"] = participant_data["challenges"]["gameLength"]/60
    participant_information["champLevel"] = participant_data["champLevel"]
    participant_information["kills"] = participant_data["kills"]
    participant_information["deaths"] = participant_data["deaths"]
    participant_information["assists"] = participant_data["assists"]
    participant_information["kda"] = participant_data["challenges"]["kda"]
    participant_information["killParticipation"] = participant_data["challenges"]["killParticipation"]
    
    participant_information["cs"] = participant_data["totalMinionsKilled"] + participant_data["neutralMinionsKilled"]
    participant_information["csm"] = participant_information["cs"]/participant_information["gameLength"]
   
    participant_information["goldEarned"] = participant_data["goldEarned"]
    participant_information["goldPerMinute"] = participant_data["challenges"]["goldPerMinute"]
    participant_information["objectivesStolen"] = participant_data["objectivesStolen"]
    
    participant_information["totalDamageDealtToChampions"] = participant_data["totalDamageDealtToChampions"]
    participant_information["damagePerMinute"] = participant_data["challenges"]["damagePerMinute"]
    participant_information["teamDamagePercentage"] = participant_data["challenges"]["teamDamagePercentage"]
    participant_information["damageTakenOnTeamPercentage"] = participant_data["challenges"]["damageTakenOnTeamPercentage"]

    participant_information["firstBloodKill"] = participant_data["firstBloodKill"]
    participant_information["soloKills"] = participant_data["challenges"]["soloKills"]

    participant_information["tripleKills"] = participant_data["tripleKills"]
    participant_information["quadraKills"] = participant_data["quadraKills"]
    participant_information["pentaKills"] = participant_data["pentaKills"]
    participant_information["multikills"] = participant_data["challenges"]["multikills"]
    
    participant_information["visionScore"] = participant_data["visionScore"]
    participant_information["visionScorePerMinute"] = participant_data["challenges"]["visionScorePerMinute"]
    participant_information["totalTimeCCDealt"] = participant_data["totalTimeCCDealt"]
    participant_information["effectiveHealAndShielding"] = participant_data["challenges"]["effectiveHealAndShielding"]
    return participant_information




load_dotenv(dotenv_path=".env", verbose=True, override=True)           
main()