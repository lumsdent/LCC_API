"""
main.py
-------
Flask application factory for the LCC API.

Registers all blueprints, configures Discord OAuth2, and defines top-level
routes (health check, auth flow, /me, logout).
"""
import os
import secrets
from flask import Flask, redirect, url_for, make_response, session, request, jsonify
from dotenv import load_dotenv
from flask_cors import CORS
from flask_discord import DiscordOAuth2Session, Unauthorized

from . import players
from . import teams
from . import matches
from . import practice
from . import tournament

app = Flask(__name__)

# In production (HTTPS) cookies must be SameSite=None; Secure so the browser
# will send them on cross-origin fetch requests from the frontend domain.
_frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:5173')
_is_prod = _frontend_url.startswith('https')

CORS(app, supports_credentials=True, origins=[_frontend_url])

app.register_blueprint(players.bp)
app.register_blueprint(teams.bp)
app.register_blueprint(matches.bp)
app.register_blueprint(practice.bp)
app.register_blueprint(tournament.bp)

app.secret_key = secrets.token_urlsafe(16)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = 'true'
app.config['DISCORD_CLIENT_ID']     = os.getenv('DISCORD_CLIENT_ID')
app.config['DISCORD_CLIENT_SECRET'] = os.getenv('DISCORD_CLIENT_SECRET')
app.config['DISCORD_REDIRECT_URI']  = os.getenv('DISCORD_REDIRECT_URI')

discord = DiscordOAuth2Session(app)


@app.route('/')
def sanity_check():
    """Health check — confirms the API is running."""
    return 'Welcome to the LCC API!'


@app.route('/auth/discord/login/')
def login():
    """Initiate the Discord OAuth2 login flow."""
    return discord.create_session(scope=['identify'])


@app.route('/auth/discord/callback/')
def callback():
    """Handle the Discord OAuth2 callback, upsert the player, and set the session cookie."""
    discord.callback()
    user   = discord.fetch_user()
    player = players.get_player_by_discord_id(user.id)
    if player is None:
        # No player linked to this Discord account yet.
        # Check if there are any existing players that can be claimed.
        unclaimed = players.get_unclaimed_players()
        if unclaimed:
            # Stash discord info in session and send user to the claim-profile page.
            session['pending_discord'] = {
                'id':         str(user.id),
                'username':   user.name,
                'avatar_url': user.avatar_url or '',
            }
            return redirect(os.getenv('FRONTEND_URL') + '/claim-profile')
        # No existing unclaimed players — create a fresh profile.
        players.create_player_login(user)
    else:
        players.update_player_login(user)
    response = make_response(redirect(os.getenv('FRONTEND_URL')))
    response.set_cookie('token', str(user.id), httponly=True, secure=_is_prod, samesite='None' if _is_prod else 'Lax')
    return response


@app.route('/claim-pending/')
def claim_pending():
    """Return the Discord user info stored in session during the claim flow."""
    pending = session.get('pending_discord')
    if not pending:
        return jsonify({'message': 'No pending claim'}), 404
    return jsonify(pending)


@app.route('/claim-profile/<puuid>/', methods=['POST'])
def claim_profile(puuid):
    """
    Complete the claim flow: link the pending Discord session to an existing player,
    then set the auth cookie and redirect home.
    """
    pending = session.pop('pending_discord', None)
    if not pending:
        return jsonify({'message': 'No pending claim — please log in again'}), 400
    if players.get_player_by_discord_id(pending['id']):
        return jsonify({'message': 'Discord account is already linked to a player'}), 409
    if not players.link_discord_to_player(puuid, pending):
        return jsonify({'message': 'Player not found'}), 404
    response = make_response(jsonify({'message': 'ok'}))
    response.set_cookie('token', pending['id'], httponly=True, secure=_is_prod, samesite='None' if _is_prod else 'Lax')
    return response


@app.errorhandler(Unauthorized)
def redirect_unauthorized(_e):
    """Redirect unauthenticated Discord sessions back to the login route."""
    return redirect(url_for('login'))


@app.route('/me/')
def me():
    """Return the current player's lightweight profile based on the session cookie."""
    user_id = request.cookies.get('token')
    if not user_id:
        return jsonify({'message': 'Not authenticated'}), 401
    player = players.get_player_me_by_discord_id(user_id)
    if not player:
        return jsonify({'message': 'Player not found'}), 404
    return jsonify(player)


@app.route('/admin/players', methods=['GET'])
def admin_players():
    """Return a lightweight list of players with linked Discord accounts for admin dropdowns."""
    cookie_user_id = request.cookies.get('token')
    if not players.check_admin_auth(cookie_user_id=cookie_user_id):
        return jsonify({'message': 'Unauthorized'}), 401
    player_list = players.get_linked_players_summary()
    return jsonify(player_list)


@app.route('/admin/set-admin', methods=['POST'])
def admin_set_admin():
    """Grant admin status to a player by Discord ID. Requires the requester to be an admin."""
    cookie_user_id = request.cookies.get('token')
    if not players.check_admin_auth(cookie_user_id=cookie_user_id):
        return jsonify({'message': 'Unauthorized'}), 401
    data = request.get_json(force=True, silent=True) or {}
    discord_id = str(data.get('discordId', '')).strip()
    if not discord_id:
        return jsonify({'message': 'discordId is required'}), 400
    found = players.set_admin_status(discord_id, True)
    if not found:
        return jsonify({'message': f'No player found with Discord ID {discord_id}'}), 404
    return jsonify({'message': f'Admin granted to Discord ID {discord_id}'})


@app.route('/admin/revoke-admin', methods=['POST'])
def admin_revoke_admin():
    """Revoke admin status from a player by Discord ID. Requires the requester to be an admin."""
    cookie_user_id = request.cookies.get('token')
    if not players.check_admin_auth(cookie_user_id=cookie_user_id):
        return jsonify({'message': 'Unauthorized'}), 401
    data = request.get_json(force=True, silent=True) or {}
    discord_id = str(data.get('discordId', '')).strip()
    if not discord_id:
        return jsonify({'message': 'discordId is required'}), 400
    found = players.set_admin_status(discord_id, False)
    if not found:
        return jsonify({'message': f'No player found with Discord ID {discord_id}'}), 404
    return jsonify({'message': f'Admin revoked from Discord ID {discord_id}'})


@app.route('/logout/')
def logout():
    """Revoke the Discord session and clear the server-side session."""
    discord.revoke()
    session.clear()
    response = make_response(redirect(os.getenv('FRONTEND_URL')))
    response.delete_cookie('token', samesite='None' if _is_prod else 'Lax', secure=_is_prod)
    return response


if __name__ == '__main__':
    load_dotenv(dotenv_path='.env', verbose=True, override=True)
    app.run(debug=True, host='0.0.0.0')
