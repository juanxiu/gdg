# SafePath Backend

🌿 **기후 취약계층을 위한 건강 최우선 경로 탐색 API** (SDG 3 + 13)

## 프로젝트 구조

- `/functions`: 메인 API 서버 (FastAPI + Cloud Functions 2nd gen)
- `/pipeline`: 환경 데이터 수집기 (Cloud Scheduler + Cloud Functions 2nd gen)

## 로컬 실행 방법

### 1. 의존성 설치
```bash
cd functions
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 환경 변수 설정
`.env.example`을 복사하여 `.env`를 만들고 `GOOGLE_MAPS_API_KEY`를 입력합니다.

### 3. 서버 실행
```bash
# FastAPI 직접 실행 (추천)
python main.py

# 또는 functions-framework 이용
functions-framework --target=safepath_api --port=8080 --debug
```

### 4. API 문서 확인
- **로컬 실행 시**: [http://localhost:8080/docs](http://localhost:8080/docs) 접속
- **배포 후 (GCF)**: `https://asia-northeast3-PROJECT_ID.cloudfunctions.net/safepath-api/docs` 접속
  - *참고: GCF 2nd gen 특성 상 함수 이름(`/safepath-api`)이 경로에 포함되어야 정확히 접속됩니다.*

## 배포 (CI/CD)

GitHub Actions를 통해 가장 간단하고 안전하게 배포할 수 있습니다.

### 1. GitHub Secrets 설정
GitHub 리포지토리의 `Settings > Secrets and variables > Actions`에 다음 항목을 추가합니다:

- `GCP_PROJECT_ID`: GCP 프로젝트 ID (예: `safepath-prod`)
- `GCP_SA_KEY`: GCP 서비스 계정 키 (JSON 전체 내용)
- `GOOGLE_MAPS_API_KEY`: Google Maps API 키

### 2. 자동 배포
GitHub `main` 브랜치에 코드가 push되면 자동으로 배포 파이프라인이 실행됩니다.
- **API (Swagger)**: `https://asia-northeast3-PROJECT_ID.cloudfunctions.net/safepath-api/docs`
- **Pipeline**: 데이터 수집 파이프라인 자동 실행 및 스케줄링
