from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "QuickDrop API"
    database_url: str = "sqlite+aiosqlite:///./quickdrop.db"
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    frontend_origin: str = "http://localhost:5173"
    environment: str = "development"
    
    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    
    # Apple OAuth
    apple_client_id: str = ""
    apple_team_id: str = ""
    apple_key_id: str = ""
    apple_private_key: str = ""
    
    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://localhost:3000"]

    model_config = SettingsConfigDict(env_file=".env.local", env_file_encoding="utf-8", case_sensitive=False)


settings = Settings()
