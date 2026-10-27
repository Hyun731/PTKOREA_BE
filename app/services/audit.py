from __future__ import annotations

from typing import Any, Optional

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(db: Session, project_id: str, entity: str, entity_id: str, action: str, *, before: Any = None,
          after: Any = None, reason: Optional[str] = None, actor: str = "dev") -> None:
    db.add(AuditLog(project_id=project_id, entity=entity, entity_id=entity_id, action=action, before=jsonable_encoder(before),
                    after=jsonable_encoder(after), reason=reason, actor=actor))
