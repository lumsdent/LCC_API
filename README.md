# LCC API

REST API for the League Community Cup (LCC) — handles match ingestion, player profiles, team management, tournament entries, and league-wide stat aggregations.

Built with **Flask**, **MongoDB Atlas (PyMongo)**, and the **Riot Games API**.

---

## Data Model

Matches are stored in two MongoDB collections:

| Collection | Purpose |
|---|---|
| `matches` | Full match archive (team rosters, bans, objectives, scoreboard) |
| `match_performances` | Fact table — one document per player per match. Used for all stat aggregations. |
| `players` | Player profiles (no embedded match history) |
| `teams` | Team metadata and season rosters |
| `practice` | Practice session records |
| `tournaments` / `tournament_codes` | Tournament bracket data |

`match_performances` is the single source of truth for stats. It is populated automatically when matches are added or refreshed, and can be rebuilt from `matches` using the migration script.

---

## Prerequisites

### Environment Variables

Create a `.env` file in the project root:

```
RIOT_API_KEY=your-riot-api-key
MONGO_URI=your-mongodb-atlas-connection-string
MONGO_COLLECTION=your-database-name
ADMIN_PW=your-admin-password
DISCORD_CLIENT_ID=your-discord-client-id
DISCORD_CLIENT_SECRET=your-discord-client-secret
DISCORD_REDIRECT_URI=your-discord-redirect-uri
SECRET_KEY=your-flask-secret-key
```

A Riot API key can be obtained at https://developer.riotgames.com/docs/portal.

### Dependency Installation

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## Running the API

```bash
flask --app lcc.main run
```

Or via the Docker tasks defined in `.vscode/tasks.json`.

---

## API Routes

### Matches — `/matches`

| Method | Route | Description |
|---|---|---|
| `GET` | `/matches` | All matches, sorted by date descending |
| `POST` | `/matches/add` | Add or update a match from a Riot match ID (admin) |
| `POST` | `/matches/manual` | Add or update a manually entered match (admin) |
| `POST` | `/matches/refresh` | Re-fetch all matches from Riot API via matches_index (admin) |
| `GET` | `/matches/<match_id>` | Single match by Riot ID |
| `GET` | `/matches/lcc/<lcc_id>` | Single match by LCC ID |
| `PATCH` | `/matches/lcc/<lcc_id>/mvp` | Assign MVP for a match (admin) |
| `PATCH` | `/matches/<match_id>/vod` | Set VOD URL for a match (admin) |
| `GET` | `/matches/seasons` | List of all distinct season identifiers |
| `GET` | `/matches/stats/season/<season_id>` | Aggregated player stats for a season |
| `GET` | `/matches/stats/alltime` | Aggregated player stats all-time |
| `GET` | `/matches/champion-stats/season/<season_id>` | Champion stats for a season |
| `GET` | `/matches/champion-stats/alltime` | Champion stats all-time |
| `GET` | `/matches/champion/<champion_name>/matches` | All appearances for a champion |

### Players — `/players`

| Method | Route | Description |
|---|---|---|
| `GET` | `/players` | All player profiles |
| `POST` | `/players/add` | Add or update a player (admin) |
| `GET` | `/players/<puuid>` | Single player profile |
| `POST` | `/players/<puuid>/refresh` | Refresh Riot data for a player |
| `GET` | `/players/<puuid>/matches` | Paginated match history (`page`, `per_page`, `champion`) |
| `GET` | `/players/<puuid>/champion-stats` | Per-champion stats for a player |
| `GET` | `/players/unclaimed` | Players without a linked Discord account |
| `POST` | `/players/<puuid>/link-discord` | Link a Discord account to a player (admin) |
| `DELETE` | `/players/<puuid>/delete` | Remove a match history entry by index (admin) |

### Teams — `/teams`

| Method | Route | Description |
|---|---|---|
| `GET` | `/teams` | All teams |
| `GET` | `/teams/<team_name>` | Single team with roster |
| `GET` | `/teams/<team_name>/records` | Win/loss records and stats for a team |

### Auth — `/`

| Method | Route | Description |
|---|---|---|
| `GET` | `/login` | Discord OAuth2 redirect |
| `GET` | `/callback` | Discord OAuth2 callback |
| `GET` | `/me` | Current logged-in player profile |
| `POST` | `/logout` | Clear session cookie |

---

## Tools

### `tools/migrate_to_match_performances.py`

One-time migration script that reads all documents from `matches` and populates the `match_performances` collection. Also creates the required compound indexes.

Safe to re-run — all writes are upserts.

```bash
python tools/migrate_to_match_performances.py
```

### `tools/csv_to_match_json.py`

Converts an LCC stats CSV export into match JSON documents that can be inserted directly into MongoDB. Useful for matches where no Riot match ID is available.
