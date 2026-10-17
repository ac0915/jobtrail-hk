from fastapi import FastAPI

from app.jobs import router as jobs_router

app = FastAPI(title="JobTrail HK API")

app.include_router(jobs_router)


@app.get("/")
def read_root():
    return {"message": "JobTrail HK API is running"}