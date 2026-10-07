from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from labelforge.models.base import Base, TimestampMixin
from labelforge.models.enums import TaskType

if TYPE_CHECKING:
    from labelforge.models.image import Image
    from labelforge.models.label_class import LabelClass


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String(32), default=TaskType.OBJECT_DETECTION)

    classes: Mapped[list["LabelClass"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LabelClass.order_index",
    )
    images: Mapped[list["Image"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
