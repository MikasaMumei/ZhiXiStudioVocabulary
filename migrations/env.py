from alembic import context
from sqlalchemy import create_engine
from englishwords.models import Base
import os

config = context.config
engine = config.attributes.get("engine")
if engine is None:
    from englishwords import create_app
    engine = create_app().extensions["engine"]
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
