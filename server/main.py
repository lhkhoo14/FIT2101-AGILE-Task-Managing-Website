import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import auth, projects, sprints

app = FastAPI() # To run the server, place `uvicorn main:app --reload` in the terminal.

# The frontend is deployed separately on Render. Set CORS_ORIGINS to its URL
# in production; the wildcard keeps the local development setup convenient.
cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Route Mounting
app.include_router(auth.router, prefix="/api", tags=["Auth"])
app.include_router(projects.router, prefix="/api", tags=["Projects"])
app.include_router(sprints.router, prefix="/api", tags=["Sprints"])


@app.get("/health")
def health_check():
    return {"status": "ok"}