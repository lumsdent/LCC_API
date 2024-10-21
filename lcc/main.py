from flask import Flask
from dotenv import load_dotenv

from flask_cors import CORS
from routes import routes

app = Flask(__name__)
CORS(app)

app.register_blueprint(routes)

@app.route('/')
def sanity_check():
    return "Welcome to the LCC API!"

if __name__ == '__main__':
    load_dotenv(dotenv_path=".env", verbose=True, override=True)  
    app.run(debug='true', host='0.0.0.0')