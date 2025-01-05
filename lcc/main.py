import os
import secrets
from flask import Flask, redirect, url_for, make_response, session, g
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
    app.logger.info(user)
    session.clear()
    session['id'] = user.id
    session['username'] = user.username
    response = make_response(redirect(os.getenv("FRONTEND_URL")))
    return response


@app.errorhandler(Unauthorized)
def redirect_unauthorized(e):
    return redirect(url_for("login"))

	
@app.route("/me/")
def me():
    user_info = {"id": session.get('id'), "username": session.get('username')}
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
