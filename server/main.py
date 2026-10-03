from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import auth, projects, sprints

app = FastAPI() # To run the server, place `uvicorn main:app --reload` in the terminal.

# Enable CORS so PyScript running in the browser can communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Route Mounting
app.include_router(auth.router, prefix="/api", tags=["Auth"])
app.include_router(projects.router, prefix="/api", tags=["Projects"])
app.include_router(sprints.router, prefix="/api", tags=["Sprints"])