import os
import sys
import logging
import traceback

# 로깅 설정 (Cloud Run 로그에서 확인 가능)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("startup")

try:
    from app import create_app
    app = create_app()
    logger.info("✅ SafePath API initialized successfully")
except Exception as e:
    logger.error("❌ Critical Error during SafePath API initialization")
    logger.error(traceback.format_exc())
    sys.stderr.write(traceback.format_exc())
    sys.exit(1)

# 로컬 실행용 (python main.py 호출 시)
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"🚀 Starting local server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
