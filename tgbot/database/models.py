import datetime
from typing import Annotated, Optional
from sqlalchemy import BigInteger, ForeignKey, Index, text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

intpk = Annotated[int, mapped_column(primary_key=True)]
created_at = Annotated[
    datetime.datetime, mapped_column(server_default=text("TIMEZONE('utc', now())"))
]


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Deliberately NOT unique. Telegram frees usernames and hands them to other
    # people; with a unique constraint, the moment one user took another's old
    # @name, DatabaseMiddleware's update raised IntegrityError on every single
    # message from them and the bot went silent for that user. Indexed because
    # /addpremium looks users up by name.
    username: Mapped[Optional[str]] = mapped_column(index=True, nullable=True)
    registered_at: Mapped[created_at]
    language: Mapped[Optional[str]] = mapped_column(nullable=True, default="ru")  # User's language
    is_agreement_accepted: Mapped[Optional[bool]] = mapped_column(nullable=True, default=False)  # User agreement accepted
    welcome_sent: Mapped[bool] = mapped_column(Boolean, default=False)  # Welcome message sent
    style: Mapped[str] = mapped_column(default="anime")  # Image style
    premium_level: Mapped[int] = mapped_column(default=0)  # 0 = free, 1+ = premium levels
    premium_until: Mapped[Optional[datetime.datetime]] = mapped_column(nullable=True)  # Premium expiry
    photo_time: Mapped[Optional[str]] = mapped_column(nullable=True) # Time of day for pictures
    photo_skin: Mapped[Optional[str]] = mapped_column(nullable=True) # Picture finish (natural / soft)
    photo_light: Mapped[Optional[str]] = mapped_column(nullable=True) # Lighting for pictures


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Indexed: filtered on nearly every update, and it was a sequential scan.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(nullable=True)  # Character name
    style: Mapped[str] = mapped_column(default="anime")  # Image style of this character
    description: Mapped[str] = mapped_column(nullable=True)  # Free-form description
    appearance: Mapped[str] = mapped_column(nullable=True)  # Appearance (JSON)
    body_type: Mapped[str] = mapped_column(nullable=True)  # Build and height (JSON)
    clothing: Mapped[str] = mapped_column(nullable=True)  # Clothing
    personality: Mapped[str] = mapped_column(nullable=True)  # Personality
    location: Mapped[str] = mapped_column(nullable=True)  # Location (scene)
    role: Mapped[str] = mapped_column(nullable=True)  # Role
    reference_photo_url: Mapped[Optional[str]] = mapped_column(nullable=True)  # Reference picture URL (IP-Adapter)
    created_at: Mapped[created_at]


class ProfileMessageHistory(Base):
    __tablename__ = "profile_message_history"

    # Every query filters user_id AND profile_id and then sorts by created_at
    # DESC LIMIT 10. The two single-column indexes this replaced served none of
    # that: user_id is already a prefix here, and nothing looks up profile_id
    # on its own.
    __table_args__ = (
        Index(
            "ix_pmh_user_profile_created",
            "user_id",
            "profile_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE")
    )
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column()  # 'user' or 'bot'
    text: Mapped[str] = mapped_column()
    created_at: Mapped[created_at]
