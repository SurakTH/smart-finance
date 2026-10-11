import os
from cryptography.fernet import Fernet

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./dev.db')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
APP_ORIGIN = os.getenv('APP_ORIGIN', 'http://localhost:3000').rstrip('/')
ALLOW_REGISTRATION = os.getenv('ALLOW_REGISTRATION', 'false').strip().lower() == 'true'
COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'true') == 'true'
EXTERNAL_AI_ENABLED = os.getenv('EXTERNAL_AI_ENABLED', 'false') == 'true'
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://ollama:11434/v1')
COMPATIBLE_URL = os.getenv('COMPATIBLE_URL', '')

def cipher():
    key = os.getenv('ENCRYPTION_KEY')
    if not key:
        raise RuntimeError('ENCRYPTION_KEY must be configured')
    return Fernet(key.encode())

# SMTP is explicit opt-in; credentials stay in the backend environment.
MAIL_ENABLED = os.getenv('MAIL_ENABLED','false').strip().lower() == 'true'
SMTP_HOST = os.getenv('SMTP_HOST','')
SMTP_PORT = int(os.getenv('SMTP_PORT','587'))
SMTP_SECURITY = os.getenv('SMTP_SECURITY','starttls')
SMTP_USERNAME = os.getenv('SMTP_USERNAME','')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD','')
SMTP_FROM = os.getenv('SMTP_FROM','')
