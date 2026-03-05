from dotenv import load_dotenv
from lcc.main import app

if __name__ == '__main__':
    load_dotenv(dotenv_path=".env", verbose=True, override=True)
    app.run(debug=True, host='0.0.0.0')