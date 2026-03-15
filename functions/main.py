from app import create_app

app = create_app()

# 로컬 개발 및 Cloud Run 실행용
if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
