from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent import router as agent_router
from app.api.auth import router as auth_router
from app.api.drive import router as drive_router
from app.api.gmail import router as gmail_router
from app.api.references import router as references_router
from app.api.search import router as search_router
from app.api.sources import router as sources_router
from app.api.status import router as status_router
from app.api.sync import router as sync_router
from app.api.upload import router as upload_router
from app.config import settings
from app.storage.metadata_store import MetadataStore


app = FastAPI(title="Personal Workspace Ingestion API")

allowed_origins = [
    "http://localhost:3000",
    settings.FRONTEND_URL,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent_router)
app.include_router(auth_router)
app.include_router(drive_router)
app.include_router(gmail_router)
app.include_router(references_router)
app.include_router(search_router)
app.include_router(sources_router)
app.include_router(status_router)
app.include_router(sync_router)
app.include_router(upload_router)


@app.on_event("startup")
def startup() -> None:
    MetadataStore()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
