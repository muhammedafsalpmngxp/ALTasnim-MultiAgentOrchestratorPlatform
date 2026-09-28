"""
Document management with auto DWG→PDF conversion on upload.
Uses RAGFlow's task pipeline via Redis Streams.
"""
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from api.core.deps import AuthUser
from api.routes.projects import _ts

router = APIRouter()


ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".txt", ".md", ".csv", ".html", ".htm", ".json", ".xml",
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff",
    ".dwg", ".dxf",  # CAD — auto-converted to PDF
}

CAD_EXTENSIONS = {".dwg", ".dxf"}


def _convert_cad_to_pdf(file_path: str) -> str:
    """Convert DWG/DXF to PDF using LibreOffice headless. Returns new PDF path."""
    import subprocess
    out_dir = str(Path(file_path).parent)
    try:
        # "soffice" (not "libreoffice") is the actual binary LibreOffice installs — on Windows
        # there is no "libreoffice.exe" at all, only soffice.exe; on Linux "libreoffice" is just
        # an extra convenience symlink that also points to soffice. Using "soffice" works
        # identically on both platforms, so this doesn't affect the Docker/Linux deployment.
        result = subprocess.run(
            ["soffice", "--headless", "--convert-to", "pdf", "--outdir", out_dir, file_path],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="LibreOffice not installed. Install it to support CAD file conversion.",
        )
    pdf_path = str(Path(file_path).with_suffix(".pdf"))
    if not Path(pdf_path).exists():
        raise RuntimeError("LibreOffice ran but PDF not produced")
    return pdf_path


def _convert_office_to_pdf(file_path: str) -> str:
    """Convert PPT/PPTX/DOC/DOCX to PDF using LibreOffice headless. Returns new PDF path.

    Kept separate from _convert_cad_to_pdf (even though the underlying LibreOffice call is
    identical) purely so error messages stay accurate to what the user actually uploaded — the
    conversion mechanics themselves are the same, format-agnostic `libreoffice --convert-to pdf`.

    Rendering a presentation or Word document to PDF this way makes every slide/page (text AND
    embedded images/diagrams/tables) part of the resulting PDF's page images, so it goes through
    the exact same, unmodified PDF pipeline (deepdoc OCR + YOLOv10 layout analysis + table
    structure recognition) as a native PDF upload — this is how both formats now get full
    OCR/layout/table coverage instead of relying on each format's native (more limited) parser.
    """
    import subprocess
    out_dir = str(Path(file_path).parent)
    try:
        # See the matching comment in _convert_cad_to_pdf — "soffice" is the real binary name
        # on both Windows and Linux; "libreoffice" doesn't exist on Windows at all.
        result = subprocess.run(
            ["soffice", "--headless", "--convert-to", "pdf", "--outdir", out_dir, file_path],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="LibreOffice not installed. Install it to support PPT/PPTX/DOC/DOCX conversion.",
        )
    pdf_path = str(Path(file_path).with_suffix(".pdf"))
    if not Path(pdf_path).exists():
        raise RuntimeError("LibreOffice ran but PDF not produced")
    return pdf_path


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif", ".webp", ".svg"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".flv", ".mpeg", ".mpg", ".webm", ".wmv", ".3gp", ".mkv"}
_PRESENTATION_EXTS = {".ppt", ".pptx"}
_DOCX_CONVERT_EXTS = {".doc", ".docx"}


def _auto_parser_id(filename: str, default: str) -> str:
    """Return the appropriate RAGFlow parser_id based on file extension."""
    ext = Path(filename).suffix.lower()
    if ext in _PRESENTATION_EXTS:
        # The "naive" parser (rag/app/naive.py) never supported .ppt/.pptx at all — it raises
        # NotImplementedError for both. RAGFlow ships a dedicated "presentation" parser
        # (rag/app/presentation.py) that specifically handles both extensions
        # (re.search(r"\.pptx?$", ...)); it just was never auto-selected for uploads.
        return "presentation"
    if ext in _IMAGE_EXTS:
        return "picture"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext in _VIDEO_EXTS:
        return "picture"  # picture parser handles video via VLM
    return default


def _enqueue_parse(doc_id: str, kb_id: str):
    """Queue document for parsing via RAGFlow's task_service."""
    try:
        import json as _json
        from api.db.services.document_service import DocumentService
        from api.db.services.knowledgebase_service import KnowledgebaseService
        ok, doc_obj = DocumentService.get_by_id(doc_id)
        if not ok or not doc_obj:
            return
        ok, kb = KnowledgebaseService.get_by_id(kb_id)
        if not ok or not kb:
            return
        doc_dict = dict(doc_obj.__data__)
        # Peewee __data__ returns JSONField values as raw strings — deserialize them
        if isinstance(doc_dict.get("parser_config"), str):
            try:
                doc_dict["parser_config"] = _json.loads(doc_dict["parser_config"])
            except Exception:
                doc_dict["parser_config"] = {}
        DocumentService.run(tenant_id=str(kb.tenant_id), doc=doc_dict, kb_table_num_map={})
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to queue parse task for {doc_id}: {e}")


def _live_progress(d) -> float:
    """Page-weighted live document progress.

    Large documents are split into sequential page-batch tasks (task_service.py: ~12 pages per
    task), and the stored document `progress` is a coarse aggregate that lags behind — so the UI
    bar sat at ~1% through a whole batch and then leapt (1% → 40%) each time a batch finished.
    This computes progress on-demand from the live task rows instead, weighting each task by the
    number of pages it covers:

        progress = Σ(task_progress × pages_in_task) / total_pages

    A 37-page doc (3 batches) then ramps ~7% → 12% → 19% → ... instead of stair-stepping, and the
    granularity scales with document size automatically (more pages → more batches → smoother) —
    no per-file-type logic needed. Non-paginated formats (txt/xlsx: a single whole-document task
    whose to_page is a huge sentinel) weigh as one unit, same behavior as before. Falls back to
    the stored value on any problem — progress display must never break a listing."""
    stored = float(getattr(d, "progress", 0) or 0)
    if stored >= 1 or stored < 0:  # done or failed — the stored value is authoritative
        return stored
    try:
        from api.db.services.task_service import TaskService
        tasks = TaskService.query(doc_id=str(d.id))
        if not tasks:
            return stored
        total_weight = 0.0
        weighted = 0.0
        for t in tasks:
            frm = int(getattr(t, "from_page", 0) or 0)
            to = int(getattr(t, "to_page", 0) or 0)
            pages = to - frm
            # Whole-document sentinel (non-paginated formats) or degenerate range → 1 unit.
            weight = float(pages) if 0 < pages <= 10000 else 1.0
            p = float(getattr(t, "progress", 0) or 0)
            if p < 0:  # a failed task — surface the stored (failure-aware) value instead
                return stored
            weighted += min(p, 1.0) * weight
            total_weight += weight
        if total_weight <= 0:
            return stored
        live = weighted / total_weight
        # The stored aggregate occasionally runs ahead right at completion boundaries — never
        # show the bar moving backwards.
        return round(max(stored, min(live, 1.0)), 4)
    except Exception:
        return stored


def _fmt_doc(d) -> dict:
    return {
        "id": str(d.id),
        "name": d.name,
        "kb_id": str(d.kb_id),
        "size": getattr(d, "size", 0),
        "type": getattr(d, "type", ""),
        "status": getattr(d, "run", "pending"),
        "chunk_count": getattr(d, "chunk_num", 0),
        "token_count": getattr(d, "token_num", 0),
        "progress": _live_progress(d),
        "message": getattr(d, "progress_msg", ""),
        "created_at": _ts(getattr(d, "create_time", "")),
    }


def _get_kb(project_id: str, user: AuthUser):
    """Helper: fetch KB and verify ownership. Returns kb object."""
    from api.db.services.knowledgebase_service import KnowledgebaseService
    ok, kb = KnowledgebaseService.get_by_id(project_id)
    if not ok or not kb or str(kb.tenant_id) != user.tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return kb


def _get_doc(doc_id: str, project_id: str):
    """Helper: fetch document and verify it belongs to project. Returns doc object."""
    from api.db.services.document_service import DocumentService
    ok, doc = DocumentService.get_by_id(doc_id)
    if not ok or not doc or str(doc.kb_id) != project_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _validate_embedding_provider(kb):
    """Ensure the KB's embd_id is in the new @ format and registered in the provider registry.

    If the KB still has the old ___ format, migrates it in-place before proceeding.
    If the KB has an empty or unsupported embedding provider, auto-heals it using the configured active model.
    """
    import logging as _log
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.core.config import settings
    from rag.llm import EmbeddingModel

    embd_id = str(getattr(kb, "embd_id", "") or "")

    # Auto-migrate old ___ format → new @ format on the fly
    if "___" in embd_id and "@" not in embd_id:
        parts = embd_id.split("___")
        if len(parts) == 2:
            new_embd_id = f"{parts[0]}@default@{parts[1]}"
            try:
                KnowledgebaseService.update_by_id(str(kb.id), {"embd_id": new_embd_id})
                embd_id = new_embd_id
                _log.getLogger(__name__).info(f"Migrated KB {kb.id} embd_id: {parts[0]}___{parts[1]} → {new_embd_id}")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to migrate embedding ID: {e}")

    # Parse provider name
    parts = embd_id.split("@")
    provider_name = parts[-1] if parts else ""

    # Auto-heal: If the provider is completely missing or unsupported (e.g., BAAI),
    # dynamically update the KB's embd_id to the configured active model from .env
    if not embd_id or provider_name not in EmbeddingModel:
        new_embd_id = settings.active_embedding_ragflow_id
        try:
            KnowledgebaseService.update_by_id(str(kb.id), {"embd_id": new_embd_id})
            embd_id = new_embd_id
            parts = embd_id.split("@")
            provider_name = parts[-1]
            _log.getLogger(__name__).warning(
                f"KB {kb.id} had invalid/unsupported embedding model '{getattr(kb, 'embd_id', '')}'. "
                f"Automatically updated/healed to active model: '{new_embd_id}'"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to update KB embedding ID to active configured model: {e}"
            )

    # Parse provider name (last @ segment)
    parts = embd_id.split("@")
    provider_name = parts[-1]

    # Ensure provider is registered; register on-the-fly if missing
    try:
        from api.db.db_models import TenantModelProvider, TenantModelInstance, TenantModel
        from api.core.config import settings
        import uuid as _uuid

        tenant_id = str(kb.tenant_id)

        try:
            prov = TenantModelProvider.get(
                TenantModelProvider.tenant_id == tenant_id,
                TenantModelProvider.provider_name == provider_name,
            )
            prov_id = prov.id
        except TenantModelProvider.DoesNotExist:
            prov_id = _uuid.uuid4().hex
            TenantModelProvider.insert({
                "id": prov_id,
                "provider_name": provider_name,
                "tenant_id": tenant_id,
            }).execute()
            _log.getLogger(__name__).info(f"Registered embedding provider '{provider_name}' on-the-fly")

        try:
            inst = TenantModelInstance.get(
                TenantModelInstance.provider_id == prov_id,
                TenantModelInstance.instance_name == "default",
            )
            inst_id = inst.id
        except TenantModelInstance.DoesNotExist:
            api_key = settings.OPENAI_API_KEY if provider_name == "OpenAI" else ""
            inst_id = _uuid.uuid4().hex
            TenantModelInstance.insert({
                "id": inst_id,
                "instance_name": "default",
                "provider_id": prov_id,
                "api_key": api_key,
                "status": "active",
                "extra": "{}",
            }).execute()

        model_name = parts[0] if len(parts) >= 2 else embd_id
        exists = TenantModel.select().where(
            TenantModel.provider_id == prov_id,
            TenantModel.instance_id == inst_id,
            TenantModel.model_type == "embedding",
            TenantModel.model_name == model_name,
        ).count()
        if not exists:
            TenantModel.insert({
                "id": _uuid.uuid4().hex,
                "model_name": model_name,
                "provider_id": prov_id,
                "instance_id": inst_id,
                "model_type": "embedding",
                "status": "active",
                "extra": "{}",
            }).execute()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not register embedding provider: {e}")


@router.post("/projects/{project_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    parser_id: Optional[str] = Form(None),
    user: AuthUser = None,  # stays Optional for multipart/form-data compat; checked below
):
    """Upload a file. DWG/DXF files are auto-converted to PDF before processing."""
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")


    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    try:
        kb = _get_kb(project_id, user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Pre-validate embedding provider BEFORE touching storage or DB.
    # If not configured, reject immediately with a clear error.
    _validate_embedding_provider(kb)

    # Read file bytes (needed for MinIO upload)
    file_bytes = await file.read()

    # Auto-convert CAD files
    final_name = file.filename
    final_bytes = file_bytes
    if suffix in CAD_EXTENSIONS:
        from api.core.config import settings as _s
        upload_dir = Path(_s.STORAGE_PATH) / project_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        temp_path = upload_dir / f"{uuid.uuid4().hex}_{file.filename}"
        temp_path.write_bytes(file_bytes)
        try:
            pdf_path = _convert_cad_to_pdf(str(temp_path))
            final_bytes = Path(pdf_path).read_bytes()
            final_name = Path(file.filename).with_suffix(".pdf").name
            Path(pdf_path).unlink(missing_ok=True)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"CAD conversion failed: {e}")
        finally:
            temp_path.unlink(missing_ok=True)

    # Auto-convert PPT/PPTX and DOC/DOCX to PDF so they get the same full OCR + layout + table
    # recognition pipeline as native PDFs. For presentations this replaces the old text-only
    # extraction that silently skipped slide images. For DOCX, the native parser (deepdoc's Docx
    # class) does detect embedded images, but only ever describes them via an optional Vision-LLM
    # caption step that is a complete no-op when no IMAGE2TEXT model is configured (the case
    # here) — it never runs real OCR — so any text baked into a picture/diagram/screenshot was
    # invisible either way. Routing both through this same conversion makes image/table coverage
    # unconditional instead of depending on an optional model being set up. The PDF ingestion
    # pipeline itself is completely untouched by this — a converted file simply becomes a normal
    # PDF upload from that point on.
    elif suffix in _PRESENTATION_EXTS or suffix in _DOCX_CONVERT_EXTS:
        from api.core.config import settings as _s
        upload_dir = Path(_s.STORAGE_PATH) / project_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        temp_path = upload_dir / f"{uuid.uuid4().hex}_{file.filename}"
        temp_path.write_bytes(file_bytes)
        try:
            pdf_path = _convert_office_to_pdf(str(temp_path))
            final_bytes = Path(pdf_path).read_bytes()
            final_name = Path(file.filename).with_suffix(".pdf").name
            Path(pdf_path).unlink(missing_ok=True)
        except Exception as e:
            kind = "PPT/PPTX" if suffix in _PRESENTATION_EXTS else "DOC/DOCX"
            raise HTTPException(status_code=500, detail=f"{kind} conversion failed: {e}")
        finally:
            temp_path.unlink(missing_ok=True)

    # Upload to storage
    doc_id = uuid.uuid4().hex
    minio_key = f"{doc_id}/{final_name}"
    try:
        from common import settings as _settings
        _settings.STORAGE_IMPL.put(project_id, minio_key, final_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {e}")

    # Save document record to DB — rollback storage on failure
    try:
        from api.db.services.document_service import DocumentService
        effective_parser = parser_id if parser_id and parser_id not in ("", "string") else _auto_parser_id(final_name, getattr(kb, "parser_id", "naive"))
        # Use DocumentService.insert(), not .save() — insert() also calls
        # KnowledgebaseService.atomic_increase_doc_num_by_id() to keep the project's document
        # count in sync. .save() only inserts the row, silently leaving doc_num at 0 forever
        # (while chunk_num updates fine through a separate path during embedding) — that
        # mismatch is exactly why the Projects page always showed "0 documents" despite chunks
        # being present, and why deleting documents could even push the count negative.
        DocumentService.insert({
            "id": doc_id,
            "kb_id": project_id,
            "created_by": user.id,
            "name": final_name,
            "location": minio_key,
            "size": len(final_bytes),
            "type": Path(final_name).suffix.lstrip("."),
            "parser_id": effective_parser,
            "parser_config": getattr(kb, "parser_config", {}),
            "run": "0",
            "status": "1",
        })
        ok, doc = DocumentService.get_by_id(doc_id)
        _enqueue_parse(doc_id, project_id)
        return _fmt_doc(doc)
    except Exception as e:
        # DB save failed — remove the already-uploaded file from storage so nothing is orphaned
        try:
            from common import settings as _settings
            _settings.STORAGE_IMPL.rm(project_id, minio_key)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/documents")
async def list_documents(project_id: str, user: AuthUser):
    try:
        from api.db.services.document_service import DocumentService
        _get_kb(project_id, user)
        docs = DocumentService.query(kb_id=project_id, status="1")
        return [_fmt_doc(d) for d in docs]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/documents/{doc_id}")
async def get_document(project_id: str, doc_id: str, user: AuthUser):
    try:
        _get_kb(project_id, user)
        doc = _get_doc(doc_id, project_id)
        return _fmt_doc(doc)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/documents/{doc_id}/status")
async def document_status(project_id: str, doc_id: str, user: AuthUser):
    try:
        _get_kb(project_id, user)
        doc = _get_doc(doc_id, project_id)
        return {
            "id": doc_id,
            "status": getattr(doc, "run", "pending"),
            "progress": _live_progress(doc),
            "message": getattr(doc, "progress_msg", ""),
            "chunk_count": getattr(doc, "chunk_num", 0),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/documents/{doc_id}/reparse")
async def reparse_document(project_id: str, doc_id: str, user: AuthUser):
    try:
        _get_kb(project_id, user)
        doc = _get_doc(doc_id, project_id)
        from api.db.services.document_service import DocumentService
        DocumentService.update_by_id(doc_id, {"run": "0", "progress": 0, "progress_msg": ""})
        _enqueue_parse(doc_id, project_id)
        return {"message": "Re-parse queued"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{project_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(project_id: str, doc_id: str, user: AuthUser):
    try:
        _get_kb(project_id, user)
        doc = _get_doc(doc_id, project_id)
        from api.db.services.document_service import DocumentService
        DocumentService.remove_document(doc, user.tenant_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/documents/{doc_id}/download")
async def download_document(project_id: str, doc_id: str, user: AuthUser):
    try:
        import tempfile
        import common.settings as _cs
        _get_kb(project_id, user)
        doc = _get_doc(doc_id, project_id)
        location = getattr(doc, "location", "")
        if not location:
            raise HTTPException(status_code=404, detail="File location not recorded")
        if ".." in location or location.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid file location")
        # location is a MinIO/storage object key — fetch via storage backend
        file_bytes = _cs.STORAGE_IMPL.get(project_id, location)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(doc.name).suffix)
        tmp.write(file_bytes)
        tmp.close()
        return FileResponse(tmp.name, filename=doc.name, background=None)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
