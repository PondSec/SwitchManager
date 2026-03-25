import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-env")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///switchmanager.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    SSH_DEFAULT_TIMEOUT = int(os.getenv("SSH_DEFAULT_TIMEOUT", "8"))
    SSH_CONNECT_TIMEOUT = int(os.getenv("SSH_CONNECT_TIMEOUT", "8"))
    SSH_HOST_KEY_POLICY = os.getenv("SSH_HOST_KEY_POLICY", "reject")
    EXPERT_MODE = os.getenv("EXPERT_MODE", "false").lower() == "true"
