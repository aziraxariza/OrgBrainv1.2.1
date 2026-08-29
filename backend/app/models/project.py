import uuid
import enum

from sqlalchemy import String, Date, Enum as SAEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TenantMixin, TimestampMixin


class ProjectStatus(str, enum.Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    AT_RISK = "at_risk"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class Project(Base, TenantMixin, TimestampMixin):
    __tablename__ = "projects"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), default="")
    lead_employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.employee_id"), nullable=True)
    start_date: Mapped[Date] = mapped_column(Date, nullable=True)
    target_end_date: Mapped[Date] = mapped_column(Date, nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(SAEnum(ProjectStatus), default=ProjectStatus.PLANNED)

    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")
