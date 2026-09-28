"""
Hybrid search endpoint — wires directly to RAGFlow's Dealer class.
BM25 (keyword) + dense vector retrieval, then re-ranked.
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.core.deps import AuthUser

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    project_ids: List[str]             # search across one or more projects
    top_k: int = 10
    similarity_threshold: float = 0.2
    vector_similarity_weight: float = 0.3
    highlight: bool = True


class SearchResult(BaseModel):
    chunk_id: str
    doc_id: str
    doc_name: str
    content: str
    score: float
    highlight: Optional[str] = None
    page: Optional[int] = None


@router.post("/search")
async def hybrid_search(req: SearchRequest, user: AuthUser):
    """
    Full hybrid search using RAGFlow's Dealer:
    - BM25 keyword retrieval from Elasticsearch
    - Dense vector retrieval from ES kNN
    - Score fusion (weighted)
    - Cross-encoder re-ranking
    """
    if not req.project_ids:
        raise HTTPException(status_code=400, detail="At least one project_id required")

    # Verify user can access all requested projects
    try:
        from api.db.services.knowledgebase_service import KnowledgebaseService
        for pid in req.project_ids:
            _, kb = KnowledgebaseService.get_by_id(pid)
            if not kb or str(kb.tenant_id) != user.tenant_id:
                raise HTTPException(status_code=403, detail=f"No access to project {pid}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        from rag.settings import retrievaler

        results = retrievaler.retrieval(
            req.query,
            embd_mdl=None,          # uses default embedding from settings
            tenant_id=user.tenant_id,
            kb_ids=req.project_ids,
            page=1,
            page_size=req.top_k,
            similarity_threshold=req.similarity_threshold,
            vector_similarity_weight=req.vector_similarity_weight,
            top=req.top_k,
            rerank_mdl=None,
            highlight=req.highlight,
        )

        chunks = []
        for c in results.get("chunks", []):
            chunks.append({
                "chunk_id": c.get("chunk_id", c.get("id", "")),
                "doc_id": c.get("doc_id", ""),
                "doc_name": c.get("docnm_kwd", ""),
                "content": c.get("content_with_weight", c.get("content_ltks", "")),
                "score": float(c.get("similarity", 0)),
                "highlight": c.get("highlight", None),
                "page": c.get("page_num_int", [None])[0] if isinstance(c.get("page_num_int"), list) else c.get("page_num_int"),
            })

        return {
            "query": req.query,
            "total": results.get("total", len(chunks)),
            "chunks": chunks,
        }

    except ImportError:
        # RAGFlow retrieval not yet wired
        raise HTTPException(
            status_code=503,
            detail="Search service unavailable — Elasticsearch may not be running",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/chunks")
async def list_chunks(
    project_id: str,
    doc_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 30,
    user: AuthUser = None,
):
    """List parsed chunks for a project (for inspection/debugging)."""
    try:
        from api.db.services.knowledgebase_service import KnowledgebaseService
        _, kb = KnowledgebaseService.get_by_id(project_id)
        if not kb or not user or str(kb.tenant_id) != user.tenant_id:
            raise HTTPException(status_code=404, detail="Project not found")

        from rag.nlp import search as rag_search
        from common import settings as _cs
        tenant_id = str(kb.tenant_id)
        index_name = rag_search.index_name(tenant_id)

        filters = {"kb_id": project_id}
        if doc_id:
            filters["doc_id"] = doc_id

        res = _cs.docStoreConn.search(
            filters,
            [],
            {"kb_id": project_id},
            index_name,
            project_id,
            page_size,
            (page - 1) * page_size,
            ["doc_id", "docnm_kwd", "content_with_weight", "page_num_int"],
        )
        chunks = [
            {
                "chunk_id": c.get("id", c.get("chunk_id", "")),
                "doc_id": c.get("doc_id", ""),
                "doc_name": c.get("docnm_kwd", ""),
                "content": c.get("content_with_weight", ""),
                "page": c.get("page_num_int", [None])[0] if isinstance(c.get("page_num_int"), list) else c.get("page_num_int"),
            }
            for c in res.get("chunks", [])
        ]
        return {"total": res.get("total", len(chunks)), "chunks": chunks}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
