"""Flask extension instances (initialised in the app factory)."""

import datetime as dt

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, registry


class Base(DeclarativeBase):
    # Store every datetime as timestamptz so values are unambiguous across servers.
    registry = registry(type_annotation_map={dt.datetime: DateTime(timezone=True)})


db = SQLAlchemy(model_class=Base)
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)
