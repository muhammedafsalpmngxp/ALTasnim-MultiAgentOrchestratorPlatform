"""
Projects = RAGFlow Knowledge Bases.
Each project is an isolated document collection with its own search index.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from api.core.config import settings
from api.core.deps import AuthUser

router = APIRouter()


def _ts(value) -> str:
    """Convert a RAGFlow timestamp (Unix ms int or datetime) to ISO-8601 string."""
    if not value:
        return ""
    from datetime import datetime, timezone
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat()
    try:
        ms = int(value)
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return str(value)


class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    language: str = "English"
    parser_id: str = "naive"        # naive | laws | manual | qa | table | paper
    chunk_size: int = 512
    similarity_threshold: float = 0.2
    vector_similarity_weight: float = 0.3


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parser_id: Optional[str] = None
    chunk_size: Optional[int] = None
    similarity_threshold: Optional[float] = None
    vector_similarity_weight: Optional[float] = None


def _ready_doc_count(kb_id: str) -> int:
    """Count documents actually finished parsing (TaskStatus.DONE = "3"), not just uploaded.

    kb.doc_num (used previously) only tracks how many document rows were ever created for the
    KB — it doesn't reflect whether parsing/embedding actually completed, so a project with 3
    uploaded-but-still-parsing (or failed) files showed "3 documents" even though 0 were usable
    for chat. Querying the real, current status directly from the documents table keeps this
    number accurate and always in sync with the DB, matching what the Documents page itself
    shows as "Ready".
    """
    from api.db.services.document_service import DocumentService
    from common.constants import TaskStatus
    try:
        return len(DocumentService.query(kb_id=kb_id, status="1", run=TaskStatus.DONE.value))
    except Exception:
        return 0


def _fmt_project(kb) -> dict:
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": getattr(kb, "description", ""),
        "language": getattr(kb, "language", "English"),
        "parser_id": kb.parser_id,
        "doc_count": _ready_doc_count(str(kb.id)),
        "chunk_count": getattr(kb, "chunk_num", 0),
        "token_count": getattr(kb, "token_num", 0),
        "similarity_threshold": getattr(kb, "similarity_threshold", 0.2),
        "vector_similarity_weight": getattr(kb, "vector_similarity_weight", 0.3),
        "created_at": _ts(getattr(kb, "create_time", "")),
        "updated_at": _ts(getattr(kb, "update_time", "")),
    }


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(req: CreateProjectRequest, user: AuthUser):
    try:
        from api.db.services.knowledgebase_service import KnowledgebaseService
        kb_id = str(uuid.uuid4()).replace("-", "")
        KnowledgebaseService.save(**{
            "id": kb_id,
            "tenant_id": user.tenant_id,
            "created_by": user.id,
            "name": req.name,
            "description": req.description,
            "language": req.language,
            "parser_id": req.parser_id,
            "parser_config": {"chunk_token_num": req.chunk_size, "delimiter": "\n!?;。！？", "overlapped_percent": 15},
            "similarity_threshold": req.similarity_threshold,
            "vector_similarity_weight": req.vector_similarity_weight,
            "embd_id": settings.active_embedding_ragflow_id,
            "permission": "team",
            "status": "1",
        })
        ok, kb = KnowledgebaseService.get_by_id(kb_id)
        return _fmt_project(kb)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects")
async def list_projects(user: AuthUser):
    try:
        from api.db.services.knowledgebase_service import KnowledgebaseService
        kbs = KnowledgebaseService.query(tenant_id=user.tenant_id, status="1")
        return [_fmt_project(kb) for kb in kbs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}")
async def get_project(project_id: str, user: AuthUser):
    try:
        from api.db.services.knowledgebase_service import KnowledgebaseService
        ok, kb = KnowledgebaseService.get_by_id(project_id)
        if not ok or not kb or str(kb.tenant_id) != user.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")
        return _fmt_project(kb)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/projects/{project_id}")
async def update_project(project_id: str, req: UpdateProjectRequest, user: AuthUser):
    try:
        from api.db.services.knowledgebase_service import KnowledgebaseService
        ok, kb = KnowledgebaseService.get_by_id(project_id)
        if not ok or not kb or str(kb.tenant_id) != user.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")
        updates = req.model_dump(exclude_none=True)
        if "chunk_size" in updates:
            parser_cfg = getattr(kb, "parser_config", {}) or {}
            parser_cfg["chunk_token_num"] = updates.pop("chunk_size")
            updates["parser_config"] = parser_cfg
        KnowledgebaseService.update_by_id(project_id, updates)
        return {"message": "Project updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str, user: AuthUser):
    try:
        from api.db.services.knowledgebase_service import KnowledgebaseService
        from api.db.services.document_service import DocumentService
        ok, kb = KnowledgebaseService.get_by_id(project_id)
        if not ok or not kb or str(kb.tenant_id) != user.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")
        # Delete all documents (cleans up ES chunks, tasks, images)
        docs = DocumentService.query(kb_id=project_id, status="1")
        for doc in docs:
            try:
                DocumentService.remove_document(doc, user.tenant_id)
            except Exception as ex:
                import logging
                logging.warning(f"Failed to remove doc {doc.id} during project delete: {ex}")
        # Soft-delete the KB itself
        KnowledgebaseService.update_by_id(project_id, {"status": "0"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/stats")
async def project_stats(project_id: str, user: AuthUser):
    try:
        from api.db.services.knowledgebase_service import KnowledgebaseService
        from api.db.services.document_service import DocumentService
        ok, kb = KnowledgebaseService.get_by_id(project_id)
        if not ok or not kb or str(kb.tenant_id) != user.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")
        docs = DocumentService.query(kb_id=project_id)
        status_counts: dict = {}
        for d in docs:
            s = str(getattr(d, "run", "pending"))
            status_counts[s] = status_counts.get(s, 0) + 1
        return {
            "project_id": project_id,
            "doc_count": len(docs),
            "chunk_count": getattr(kb, "chunk_num", 0),
            "token_count": getattr(kb, "token_num", 0),
            "doc_status": status_counts,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
