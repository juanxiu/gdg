FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성 설치 (필요시)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 파이썬 라이브러리 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# Port 설정
EXPOSE 8080

# 실행 명령 (Cloud Run은 PORT 환경변수를 제공합니다. 이를 위해 Shell 형식을 사용하여 변수를 확장합니다.)
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
