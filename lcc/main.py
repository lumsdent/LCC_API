import os
import secrets
from flask import Flask, redirect, url_for, make_response, session, g, request
from dotenv import load_dotenv

from flask_cors import CORS
from flask_discord import DiscordOAuth2Session, Unauthorized

from . import players
from . import teams
from . import matches

app = Flask(__name__)
CORS(app, supports_credentials=True)

app.register_blueprint(players.bp)
app.register_blueprint(teams.bp)
app.register_blueprint(matches.bp)

app.secret_key = secrets.token_urlsafe(16)
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "true"
app.config["DISCORD_CLIENT_ID"] = os.getenv("DISCORD_CLIENT_ID")
app.config["DISCORD_CLIENT_SECRET"] = os.getenv("DISCORD_CLIENT_SECRET")
app.config["DISCORD_REDIRECT_URI"] = os.getenv("DISCORD_REDIRECT_URI")

discord = DiscordOAuth2Session(app)

@app.route('/')
def sanity_check():
    """Check if the API is running"""
    return "Welcome to the LCC API!"

@app.route("/auth/discord/login/")
def login():
    return discord.create_session(scope=["identify"])

@app.route("/auth/discord/callback/")
def callback():
    discord.callback()
    user = discord.fetch_user()
    player = players.get_player_by_discord_id(user.id)
    if player is None:
        player = players.create_player_login(user)
    else:
        players.update_player_login(user)
    response = make_response(redirect(os.getenv("FRONTEND_URL")))
    response.set_cookie("token", str(user.id), httponly=True, secure=False, samesite='Lax')
    return response


@app.errorhandler(Unauthorized)
def redirect_unauthorized(e):
    return redirect(url_for("login"))

	
@app.route("/me/")
def me():
    user_id = request.cookies.get('token')
    player = players.get_player_by_discord_id(user_id)
    user_info = {"id": player.discord.id, "username": player.discord.username}
    return user_info


@app.route("/logout/")
def logout():
    discord.revoke()
    session.clear()
    response = make_response(redirect(os.getenv('FRONTEND_URL')))
    return response

if __name__ == '__main__':
    load_dotenv(dotenv_path=".env", verbose=True, override=True)
    app.run(debug='true', host='0.0.0.0')
