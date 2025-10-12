import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

    # Database
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_PORT = os.environ.get('DB_PORT', '3306')
    DB_NAME = os.environ.get('DB_NAME', 'image_generator')
    DB_USER = os.environ.get('DB_USER', 'root')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 10,
        "pool_recycle": 3600,
        "pool_pre_ping": True,
        "max_overflow": 20,
    }

    # API
    API_BASE_URL = os.getenv("API_BASE_URL", "https://api.infip.pro")
    API_KEY = os.getenv("API_KEY")

    # AWS
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    USE_S3 = os.getenv("USE_S3", "true").lower() == "true"
    S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
    
    # Optional: CloudFront (not used)
    CLOUDFRONT_DOMAIN = os.getenv("CLOUDFRONT_DOMAIN", "")

    # IAM Role (optional)
    USE_IAM_ROLE = os.getenv("USE_IAM_ROLE", "false").lower() == "true"

    # Upload
    MEDIA_FOLDER = "media"
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

    # Helper property: generate base S3 URL dynamically
    @staticmethod
    def get_s3_base_url():
        """Return the base S3 URL for public access"""
        if not Config.S3_BUCKET_NAME:
            return None
        return f"https://{Config.S3_BUCKET_NAME}.s3.{Config.AWS_REGION}.amazonaws.com"
