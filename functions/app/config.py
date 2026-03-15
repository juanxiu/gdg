import os 
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """환경 변수 기반 설정"""

    # 환경 구분
    environment: str = "local"  # local | production

    # GCP
    gcp_project_id: str = "gdg-solution-challenge-490015"
    gcp_region: str = "asia-northeast3"

    # Google Maps API
    google_maps_api_key: str = ""

    # Firestore
    firestore_collection_prefix: str = ""  # 환경별 분리: "dev_", "prod_"
    firestore_database_id: str = "(default)"
    firestore_env_collection: str = "environment"

    class Config:
        # functions/ 디렉토리 내부 혹은 프로젝트 루트(..)에서 .env 검색
        env_file = [".env", os.path.join("..", ".env")]
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """환경 변수 캐싱 (앱 수명 동안 1회만 로드)"""
    return Settings()
