"""Admin education-catalog management API.

Every route requires the shared admin token/RBAC (`actor_for_request` +
permissions) — regular users and students can never reach these endpoints, and
the HTTP layer cannot be bypassed via the UI. All mutations are audited
(AdminActionLog) with before/after values.

Routes (all JSON, AJAX-friendly, filterable, paginated):
  GET    /api/v1/admin/catalog/overview
  GET    /api/v1/admin/catalog/archive
  GET    /api/v1/admin/catalog/{entity}                list (q/filters/sort/page)
  POST   /api/v1/admin/catalog/{entity}                create
  GET    /api/v1/admin/catalog/{entity}/{id}           detail
  PATCH  /api/v1/admin/catalog/{entity}/{id}           update
  DELETE /api/v1/admin/catalog/{entity}/{id}           hard delete (dependency-guarded)
  GET    /api/v1/admin/catalog/{entity}/{id}/dependencies
  POST   /api/v1/admin/catalog/{entity}/{id}/archive
  POST   /api/v1/admin/catalog/{entity}/{id}/restore
  POST   /api/v1/admin/catalog/academic-years/{id}/copy-structure
  POST   /api/v1/admin/catalog/editions/{id}/pdf       multipart upload (never publishes)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.db.session import get_session as _get_session  # noqa: F401 (parity with other admin routers)
from app.services import admin_catalog_service as service
from app.services import permissions
from app.services.admin_user_service import actor_for_request

from app.api.admin import require_admin  # noqa: E402  (shared admin-session guard)

router = APIRouter(
    prefix="/api/v1/admin/catalog",
    tags=["admin-catalog"],
    dependencies=[Depends(require_admin)],  # 401 without a real admin session
)

ENTITIES = (
    "cycles",
    "grades",
    "branches",
    "grounds",
    "fields",
    "subjects",
    "textbooks",
    "links",
    "academic-years",
    "editions",
    "program-availability",
)


async def _admin(request: Request, session: AsyncSession = Depends(get_session)):
    actor = await actor_for_request(request, session)
    # Router-level require_admin already 401s anonymous callers. The legacy
    # admin console session (kind=admin_session) is a REAL admin session and
    # stays allowed; students/regular users never pass require_admin at all.
    # Catalog management uses its own permission — NOT can_read_users — because
    # managing the national catalog is admin-only (moderators are read-only on
    # user files and must never edit the catalog).
    if not permissions.can_manage_education_catalog(actor):
        raise HTTPException(status_code=403, detail="مدیریت نظام آموزشی فقط برای نقش‌های مدیریتی مجاز است.")
    return actor


@router.get("/overview")
async def overview(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    await _admin(request, session)
    return {"counts": await service.catalog_overview(session), "entities": list(ENTITIES)}


@router.get("/archive")
async def archive(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    await _admin(request, session)
    return await service.list_archived(session, page=page, page_size=page_size)


@router.get("/{entity}")
async def list_items(
    entity: str,
    request: Request,
    q: str | None = None,
    sort: str = "id",
    direction: str = "asc",
    page: int = 1,
    page_size: int = 25,
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    await _admin(request, session)
    if entity not in ENTITIES:
        raise HTTPException(status_code=404, detail="موجودیت کاتالوگ شناخته‌شده نیست.")
    filters: dict[str, Any] = {
        key: request.query_params.get(key)
        for key in request.query_params.keys()
        if key not in {"q", "sort", "direction", "page", "page_size", "include_archived"}
    }
    return await service.list_entity(
        session,
        entity,
        q=q,
        filters=filters,
        sort=sort,
        direction=direction,
        page=max(1, page),
        page_size=min(200, max(1, page_size)),
        include_archived=include_archived,
    )


@router.post("/{entity}", status_code=201)
async def create_item(
    entity: str, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    actor = await _admin(request, session)
    if entity not in ENTITIES:
        raise HTTPException(status_code=404, detail="موجودیت کاتالوگ شناخته‌شده نیست.")
    payload = await request.json()
    return await service.create_entity(session, actor=actor, entity=entity, payload=payload)


@router.get("/{entity}/{item_id}")
async def get_item(
    entity: str, item_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    await _admin(request, session)
    return await service.get_entity(session, entity, item_id)


@router.patch("/{entity}/{item_id}")
async def update_item(
    entity: str,
    item_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    actor = await _admin(request, session)
    payload = await request.json()
    return await service.update_entity(session, actor=actor, entity=entity, obj_id=item_id, payload=payload)


@router.delete("/{entity}/{item_id}")
async def delete_item(
    entity: str, item_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    actor = await _admin(request, session)
    snapshot = await service.delete_entity(session, entity, item_id)
    await service.log_action(
        session,
        actor=actor,
        action="delete",
        entity=entity,
        entity_id=item_id,
        before=snapshot,
        result="deleted",
    )
    await session.commit()
    return {"deleted": True, "id": item_id}


@router.get("/{entity}/{item_id}/dependencies")
async def item_dependencies(
    entity: str, item_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    await _admin(request, session)
    deps = await service.entity_dependencies(session, entity, item_id)
    return {"dependencies": deps, "total": sum(deps.values())}


@router.post("/{entity}/{item_id}/archive")
async def archive_item(
    entity: str, item_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    actor = await _admin(request, session)
    result = await service.set_archived(session, entity, item_id, archived=True)
    await service.log_action(
        session, actor=actor, action="archive", entity=entity, entity_id=item_id, before=result["before"], after=result["after"]
    )
    await session.commit()
    return {"archived": True, "id": item_id}


@router.post("/{entity}/{item_id}/restore")
async def restore_item(
    entity: str, item_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    actor = await _admin(request, session)
    result = await service.set_archived(session, entity, item_id, archived=False)
    await service.log_action(
        session, actor=actor, action="restore", entity=entity, entity_id=item_id, before=result["before"], after=result["after"]
    )
    await session.commit()
    return {"restored": True, "id": item_id}


@router.post("/academic-years/{year_id}/copy-structure")
async def copy_year(
    year_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    actor = await _admin(request, session)
    payload = await request.json()
    source_year_id = payload.get("source_year_id")
    if not isinstance(source_year_id, int):
        raise HTTPException(status_code=422, detail="source_year_id الزامی است.")
    stats = await service.copy_year_structure(
        session, actor=actor, target_year_id=year_id, source_year_id=source_year_id
    )
    return {"copied": stats}


@router.post("/editions/{edition_id}/pdf")
async def upload_pdf(
    edition_id: int,
    request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    actor = await _admin(request, session)
    content = await file.read()
    result = await service.upload_edition_pdf(
        session, actor=actor, edition_id=edition_id, filename=file.filename or "book.pdf", content=content
    )
    return result
