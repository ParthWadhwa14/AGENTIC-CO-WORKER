from app.db import Base, engine
import app.db_models  # noqa: F401


Base.metadata.create_all(bind=engine)
print("Database tables created.")
