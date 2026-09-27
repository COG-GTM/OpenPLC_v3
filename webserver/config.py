from dotenv import load_dotenv
import os
import re
import secrets
import logging

from pathlib import Path
from dotenv import load_dotenv, dotenv_values

# Always resolve .env relative to the repo root to guarantee it is found
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
DB_PATH = Path(__file__).resolve().parent.parent / "restapi.db"
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,  # Minimum level to capture
    format='[%(levelname)s] %(asctime)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Function to validate environment variable values
def is_valid_env(var_name, value):
    if var_name == "SQLALCHEMY_DATABASE_URI":
        return value.startswith("sqlite:///")
    elif var_name in ("JWT_SECRET_KEY", "PEPPER", "SECRET_KEY"):
        return bool(re.fullmatch(r"[a-fA-F0-9]{64}", value))
    return False

_TRUE_VALUES = ("1", "true", "yes", "on")

def _env_flag(name, file_values, default=False):
    raw = file_values.get(name)
    if raw is None:
        raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES

# Function to generate a new .env file with valid defaults
def generate_env_file():
    jwt = secrets.token_hex(32)
    pepper = secrets.token_hex(32)
    secret_key = secrets.token_hex(32)
    uri = "sqlite:///{DB_PATH}"

    with open(ENV_PATH, "w") as f:
        f.write("FLASK_ENV=development\n")
        f.write(f"SQLALCHEMY_DATABASE_URI={uri}\n")
        f.write(f"JWT_SECRET_KEY={jwt}\n")
        f.write(f"PEPPER={pepper}\n")
        f.write(f"SECRET_KEY={secret_key}\n")
        f.write("# Set to true when the web UI is served over TLS (reverse proxy).\n")
        f.write("SESSION_COOKIE_SECURE=false\n")
        f.write("FORCE_HTTPS_REDIRECT=false\n")

    os.chmod(ENV_PATH, 0o600)
    logger.info(f".env file created at {ENV_PATH}")

    # Ensure the database file exists and is writable
    # Deletion is required because new secrets will change the database saved hashes
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        logger.info(f"Deleted existing database file: {DB_PATH}")

# Load .env file
if not os.path.isfile(ENV_PATH):
    logger.warning(".env file not found, creating one...")
    generate_env_file()

load_dotenv(dotenv_path=ENV_PATH, override=False)

# Mandatory settings – raise immediately if not provided
try:
    for var in ("SQLALCHEMY_DATABASE_URI", "JWT_SECRET_KEY", "PEPPER"):
        val = os.getenv(var)
        if not val or not is_valid_env(var, val):
            raise RuntimeError(f"Environment variable '{var}' is invalid or missing")
except RuntimeError as e:
    logger.error(f"{e}")
    # Need to regenerate .env file and remove the database as well
    response = input("Do you want to regenerate the .env file? This will delete your database. [y/N]: ").strip().lower()
    if response == 'y':
        logger.info("Regenerating .env with new valid values...")
        generate_env_file()
        load_dotenv(ENV_PATH)
    else:
        logger.error("Exiting due to invalid environment configuration.")
        exit(1)


def ensure_secret_key(env_path=None):
    """Return the persistent Flask SECRET_KEY stored in the .env file,
    generating one (and appending it with 0600 permissions) if absent."""
    env_path = Path(env_path or ENV_PATH)
    values = dotenv_values(env_path) if env_path.is_file() else {}
    key = values.get("SECRET_KEY")
    if not key or not is_valid_env("SECRET_KEY", key):
        key = secrets.token_hex(32)
        with open(env_path, "a") as f:
            f.write(f"SECRET_KEY={key}\n")
        os.chmod(env_path, 0o600)
        logger.info(f"SECRET_KEY generated and stored in {env_path}")
    return key


def apply_session_security(app, env_path=None):
    """Configure a Flask app with the persistent SECRET_KEY and hardened
    session-cookie attributes. SESSION_COOKIE_SECURE and FORCE_HTTPS_REDIRECT
    are opt-in so the plaintext HTTP bench keeps working until TLS is
    terminated in front of the UI."""
    env_path = Path(env_path or ENV_PATH)
    values = dotenv_values(env_path) if env_path.is_file() else {}
    app.config.update(
        SECRET_KEY=ensure_secret_key(env_path),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_env_flag("SESSION_COOKIE_SECURE", values),
        FORCE_HTTPS_REDIRECT=_env_flag("FORCE_HTTPS_REDIRECT", values),
    )
    return app


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ["SQLALCHEMY_DATABASE_URI"]
    JWT_SECRET_KEY = os.environ["JWT_SECRET_KEY"]
    PEPPER = os.environ["PEPPER"]

class DevConfig(Config):
    SQLALCHEMY_TRACK_MODIFICATIONS = False  # keep performance parity with prod
    DEBUG = True

class ProdConfig(Config):
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DEBUG = False
    ENV = "production"
