"""Firestore 데이터 접근 레이어"""
from google.cloud import firestore
from app.config import get_settings

_db_client = None


def get_db() -> firestore.AsyncClient:
    """Firestore 비동기 클라이언트 싱글톤"""
    global _db_client
    if _db_client is None:
        settings = get_settings()
        _db_client = firestore.AsyncClient(
            project=settings.gcp_project_id,
            database=settings.firestore_database_id
        )
    return _db_client


def get_collection(name: str):
    """프리픽스 적용된 컬렉션 참조 반환"""
    settings = get_settings()
    prefix = settings.firestore_collection_prefix
    return get_db().collection(f"{prefix}{name}")
