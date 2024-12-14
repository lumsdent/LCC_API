from flask import Flask, redirect, url_for, request, make_response
from dotenv import load_dotenv

from flask_cors import CORS
from routes import routes
import os 
from flask_discord import DiscordOAuth2Session, Unauthorized
import secrets
from datetime import datetime, timedelta, timezone
import jwt

app = Flask(__name__)
CORS(app)

app.register_blueprint(routes)

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
    original_url = request.args.get('next', '/')
    return discord.create_session(scope=["identify"], data={"next": original_url})

@app.route("/auth/discord/callback/")
def callback():
    discord.callback()
    original_url = request.args.get('next', '/')
    return redirect(url_for(".me", next=original_url))


@app.errorhandler(Unauthorized)
def redirect_unauthorized(e):
    return redirect(url_for("login"))

	
@app.route("/me/")
def me():
    user = discord.fetch_user()
    original_url = request.args.get('next', '/')
    user_info = {
        "id": user.id,
        "username": user.username,
        "discriminator": user.discriminator,
        "avatar_url": str(user.avatar_url)
    }
    token = generate_jwt(user_info)
    response = make_response(redirect(original_url))
    response.set_cookie("token", token, httponly=True, secure=True, samesite='Lax')
    return response

def generate_jwt(user_info):
    payload = {
        "user": user_info,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1)  # Token expiration time
        }
    token = jwt.encode(payload, app.secret_key, algorithm="HS256")
    return token

if __name__ == '__main__':
    load_dotenv(dotenv_path=".env", verbose=True, override=True)
    app.run(debug='true', host='0.0.0.0')
