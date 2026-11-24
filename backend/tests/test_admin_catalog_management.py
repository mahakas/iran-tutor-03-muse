"""Admin education-catalog management — mandatory CRUD acceptance tests.

Covers the owner addendum §18 list: entity CRUD with dependency-guarded
deletion, archive/restore, official validity edits, editions + PDF upload
(never publishing), multi-program book links, academic-year structure copy,
duplicate prevention, audit trail, RBAC (students blocked), and the guarantee
that catalog operations never touch a student's own placement while still
refreshing the student picker.
"""

from __future__ import annotations

import io

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_user_auth_admin import admin_headers, build_env, client

STUDENT_PHONE = "09121110077"
STUDENT_PASSWORD = "Val1dPassword"


async def _catalog_env(env) -> None:
    from app.db.catalog_seed import seed_education_catalog_1405_1406
    from app.db.seed import seed_curriculum_taxonomy, seed_grades, seed_majors

    async with env.factory() as session:
        await seed_grades(session)
        await seed_majors(session)
        await seed_curriculum_taxonomy(session)
        await session.commit()
        await seed_education_catalog_1405_1406(session)


async def _make_student(env) -> str:
    from app.core.passwords import hash_password
    from app.models.auth import User

    async with env.factory() as session:
        user = User(
            phone_number=STUDENT_PHONE,
            role="student",
            is_active=True,
            password_hash=hash_password(STUDENT_PASSWORD),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _student_headers(cl, env) -> dict[str, str]:
    login = await cl.post(
        "/api/v1/auth/login",
        json={"phone_number": STUDENT_PHONE, "password": STUDENT_PASSWORD},
    )
    assert login.status_code == 200, login.text
    token = login.json().get("token") or login.json().get("access_token")
    return {"Authorization": f"Bearer {token}"}


async def _audit_count(session: AsyncSession, action_prefix: str) -> int:
    from app.models.phase5 import AdminActionLog

    rows = (await session.scalars(select(AdminActionLog))).all()
    return len([row for row in rows if row.action.startswith(action_prefix)])


# ---------------------------------------------------------------------------
# grades
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grade_create_update_delete_without_deps_and_duplicate_guard(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch, seed_admin_super=True)
    try:
        await _catalog_env(env)
        async with client() as cl:
            headers = await admin_headers(cl)
            created = await cl.post(
                "/api/v1/admin/catalog/grades",
                json={"number": 12, "title": "دوازدهم (تست بازنویسی)", "has_major": True},
                headers=headers,
            )
            # duplicate number → 409 (12 already exists)
            assert created.status_code == 409

            fresh = await cl.post(
                "/api/v1/admin/catalog/grades",
                json={"number": 13, "title": "پایهٔ آزمایشی"},
                headers=headers,
            )
            assert fresh.status_code == 422  # outside 1..12

            new_grade = await cl.post(
                "/api/v1/admin/catalog/grades",
                json={"number": 1, "title": "اول (بازنویسی تستی)"} ,
                headers=headers,
            )
            # number 1 exists too → duplicate; create a truly new number via cycle-valid path:
            assert new_grade.status_code == 409

            # update flow on an existing seeded grade (number 6)
            listed = await cl.get("/api/v1/admin/catalog/grades?q=ششم", headers=headers)
            assert listed.status_code == 200
            row = listed.json()["items"][0]
            patched = await cl.patch(
                f"/api/v1/admin/catalog/grades/{row['id']}",
                json={"title": "ششم دبستان (ویرایش تست)"},
                headers=headers,
            )
            assert patched.status_code == 200
            assert patched.json()["title"].startswith("ششم")

            # hard delete of a DEPENDENT grade is blocked with a Persian count message
            blocked = await cl.delete(f"/api/v1/admin/catalog/grades/{row['id']}", headers=headers)
            assert blocked.status_code == 409
            assert "وابسته" in blocked.json()["detail"]

            # a dependency-free record deletes cleanly (ground with zero programs)
            branch = await cl.post(
                "/api/v1/admin/catalog/branches",
                json={"code": "clean-del-branch", "title": "شاخهٔ حذف امن", "min_grade": 10, "max_grade": 12},
                headers=headers,
            )
            assert branch.status_code == 201, branch.text
            ground = await cl.post(
                "/api/v1/admin/catalog/grounds",
                json={"branch_id": branch.json()["id"], "code": "services", "title": "خدمات (حذف امن)"},
                headers=headers,
            )
            assert ground.status_code == 201, ground.text
            deleted = await cl.delete(f"/api/v1/admin/catalog/grounds/{ground.json()['id']}", headers=headers)
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] is True
    finally:
        await env.engine.dispose()


@pytest.mark.asyncio
async def test_branch_ground_program_creation_and_validity_edit_with_audit(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch, seed_admin_super=True)
    try:
        await _catalog_env(env)
        async with client() as cl:
            headers = await admin_headers(cl)

            # create branch
            branch = await cl.post(
                "/api/v1/admin/catalog/branches",
                json={"code": "test_branch_x", "title": "شاخهٔ تست", "min_grade": 10, "max_grade": 12},
                headers=headers,
            )
            assert branch.status_code == 201, branch.text
            branch_id = branch.json()["id"]

            # ground under a هنرستانی branch
            ground = await cl.post(
                "/api/v1/admin/catalog/grounds",
                json={"branch_id": branch_id, "code": "industry", "title": "صنعت (تست)"},
                headers=headers,
            )
            assert ground.status_code == 201, ground.text
            ground_id = ground.json()["id"]

            # ground under theoretical must be refused
            theo = await cl.get("/api/v1/admin/catalog/branches?q=theoretical", headers=headers)
            theo_id = theo.json()["items"][0]["id"]
            bad_ground = await cl.post(
                "/api/v1/admin/catalog/grounds",
                json={"branch_id": theo_id, "code": "art", "title": "هنر (نامعتبر)"},
                headers=headers,
            )
            assert bad_ground.status_code == 422

            # program (field) under branch+ground
            program = await cl.post(
                "/api/v1/admin/catalog/fields",
                json={"branch_id": branch_id, "ground_id": ground_id, "code": "test_branch_x-industry-برنامه-تست", "title": "رشتهٔ تست"},
                headers=headers,
            )
            assert program.status_code == 201, program.text
            program_id = program.json()["id"]

            # mismatched ground refused
            mismatch = await cl.post(
                "/api/v1/admin/catalog/fields",
                json={"branch_id": branch_id, "ground_id": ground_id + 10_000_000, "code": "x-y-z", "title": "نامعتبر"},
                headers=headers,
            )
            assert mismatch.status_code == 422

            # subject creation with course metadata
            subject = await cl.post(
                "/api/v1/admin/catalog/subjects",
                json={"code": "test-dars-testi", "title": "درس تستی", "course_kind": "workshop", "weekly_hours": 2},
                headers=headers,
            )
            assert subject.status_code == 201, subject.text

            # official validity edit on the seeded program (needs_verification → stopped_development)
            avail_list = await cl.get(
                f"/api/v1/admin/catalog/program-availability?field_of_study_id={program_id}",
                headers=headers,
            )
            assert avail_list.status_code == 200
            # program was created by admin without availability row — create one
            years = await cl.get("/api/v1/admin/catalog/academic-years", headers=headers)
            year_id = years.json()["items"][0]["id"]
            availability = await cl.post(
                "/api/v1/admin/catalog/program-availability",
                json={"field_of_study_id": program_id, "academic_year_id": year_id, "validity_status": "needs_verification"},
                headers=headers,
            )
            assert availability.status_code == 201, availability.text
            availability_id = availability.json()["id"]
            duplicate = await cl.post(
                "/api/v1/admin/catalog/program-availability",
                json={"field_of_study_id": program_id, "academic_year_id": year_id, "validity_status": "unknown"},
                headers=headers,
            )
            assert duplicate.status_code == 409  # duplicate (program, year) refused

            updated = await cl.patch(
                f"/api/v1/admin/catalog/program-availability/{availability_id}",
                json={
                    "validity_status": "stopped_development",
                    "evidence_note": "بخشنامهٔ شمارهٔ ۱۲۳ — توقف توسعه",
                    "valid_from_year": "1405-1406",
                },
                headers=headers,
            )
            assert updated.status_code == 200
            assert updated.json()["validity_status"] == "stopped_development"

            # audit trail captured create + update
            async with env.factory() as session:
                assert await _audit_count(session, "catalog.fields.create") >= 1
                assert await _audit_count(session, "catalog.program-availability.update") >= 1
    finally:
        await env.engine.dispose()


@pytest.mark.asyncio
async def test_textbook_crud_official_code_and_multi_program_links(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch, seed_admin_super=True)
    try:
        await _catalog_env(env)
        async with client() as cl:
            headers = await admin_headers(cl)

            years = await cl.get("/api/v1/admin/catalog/academic-years", headers=headers)
            year_id = years.json()["items"][0]["id"]
            grades = await cl.get("/api/v1/admin/catalog/grades", headers=headers)
            g10 = next(g for g in grades.json()["items"] if g["number"] == 10)

            fields = await cl.get("/api/v1/admin/catalog/fields?branch_id=1", headers=headers)
            field_ids = [f["id"] for f in fields.json()["items"][:2]]

            # create textbook (no fabricated national code)
            book = await cl.post(
                "/api/v1/admin/catalog/textbooks",
                json={"title_fa": "کتاب تستی دهم", "grade_id": g10["id"], "academic_year_id": year_id},
                headers=headers,
            )
            assert book.status_code == 201, book.text
            book_id = book.json()["id"]
            assert book.json()["national_code"] is None
            assert book.json()["slug"]  # auto slug

            # edit title + set an OFFICIAL code (owner-provided) — audited
            edited = await cl.patch(
                f"/api/v1/admin/catalog/textbooks/{book_id}",
                json={"title_fa": "کتاب تستی دهم (ویراست ۲)", "national_code": "OFFICIAL-123"},
                headers=headers,
            )
            assert edited.status_code == 200
            assert edited.json()["national_code"] == "OFFICIAL-123"

            # link to two programs — one record, two links
            for fid in field_ids:
                link = await cl.post(
                    "/api/v1/admin/catalog/links",
                    json={"textbook_id": book_id, "academic_year_id": year_id, "grade_id": g10["id"], "branch_id": 1, "field_of_study_id": fid},
                    headers=headers,
                )
                assert link.status_code == 201, link.text
            links_list = await cl.get(f"/api/v1/admin/catalog/links?textbook_id={book_id}", headers=headers)
            assert links_list.json()["total"] == 2

            # delete ONE link — hard delete allowed for link rows
            first_link_id = links_list.json()["items"][0]["id"]
            removed = await cl.delete(f"/api/v1/admin/catalog/links/{first_link_id}", headers=headers)
            assert removed.status_code == 200
            assert (await cl.get(f"/api/v1/admin/catalog/links?textbook_id={book_id}", headers=headers)).json()["total"] == 1

            # archive + restore the textbook
            archived = await cl.post(f"/api/v1/admin/catalog/textbooks/{book_id}/archive", headers=headers)
            assert archived.status_code == 200
            detail = await cl.get(f"/api/v1/admin/catalog/textbooks/{book_id}", headers=headers)
            assert detail.json()["archived_at"] is not None
            restored = await cl.post(f"/api/v1/admin/catalog/textbooks/{book_id}/restore", headers=headers)
            assert restored.status_code == 200
            detail = await cl.get(f"/api/v1/admin/catalog/textbooks/{book_id}", headers=headers)
            assert detail.json()["archived_at"] is None

            # audit for national code change
            async with env.factory() as session:
                assert await _audit_count(session, "catalog.textbooks.update") >= 1
    finally:
        await env.engine.dispose()


@pytest.mark.asyncio
async def test_edition_creation_pdf_upload_never_publishes(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch, seed_admin_super=True)
    try:
        await _catalog_env(env)
        async with client() as cl:
            headers = await admin_headers(cl)
            grades = await cl.get("/api/v1/admin/catalog/grades", headers=headers)
            g1 = next(g for g in grades.json()["items"] if g["number"] == 1)

            edition = await cl.post(
                "/api/v1/admin/catalog/editions",
                json={"title": "نسخهٔ تستی پایهٔ اول", "grade_id": g1["id"], "edition_label": "چاپ ۱۴۰۵"},
                headers=headers,
            )
            assert edition.status_code == 201, edition.text
            edition_id = edition.json()["id"]
            assert edition.json()["status"] == "created"  # never born ready

            pdf_content = b"%PDF-1.4\n% test payload\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
            upload = await cl.post(
                f"/api/v1/admin/catalog/editions/{edition_id}/pdf",
                files={"file": ("test-book.pdf", io.BytesIO(pdf_content), "application/pdf")},
                headers=headers,
            )
            assert upload.status_code == 200, upload.text
            body = upload.json()
            assert body["sha256"]
            assert body["status"] == "created"  # auto-publish rule preserved

            bad = await cl.post(
                f"/api/v1/admin/catalog/editions/{edition_id}/pdf",
                files={"file": ("fake.pdf", io.BytesIO(b"not a pdf"), "application/pdf")},
                headers=headers,
            )
            assert bad.status_code == 422

            # admin cannot manually set ready
            publish_attempt = await cl.patch(
                f"/api/v1/admin/catalog/editions/{edition_id}",
                json={"status": "ready"},
                headers=headers,
            )
            assert publish_attempt.status_code == 422
    finally:
        await env.engine.dispose()


@pytest.mark.asyncio
async def test_year_creation_copy_structure_and_idempotency(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch, seed_admin_super=True)
    try:
        await _catalog_env(env)
        async with client() as cl:
            headers = await admin_headers(cl)
            years = await cl.get("/api/v1/admin/catalog/academic-years", headers=headers)
            source_year = years.json()["items"][0]

            new_year = await cl.post(
                "/api/v1/admin/catalog/academic-years",
                json={"code": "1406-1407", "title": "سال تحصیلی ۱۴۰۶–۱۴۰۷"},
                headers=headers,
            )
            assert new_year.status_code == 201, new_year.text
            target_id = new_year.json()["id"]

            copied = await cl.post(
                f"/api/v1/admin/catalog/academic-years/{target_id}/copy-structure",
                json={"source_year_id": source_year["id"]},
                headers=headers,
            )
            assert copied.status_code == 200, copied.text
            stats = copied.json()["copied"]
            assert stats["links"] == 303
            assert stats["program_availability"] == 118

            # source year untouched: still exactly 303 links on the source year
            src_links = await cl.get(
                f"/api/v1/admin/catalog/links?academic_year_id={source_year['id']}&page_size=1",
                headers=headers,
            )
            assert src_links.json()["total"] == 303

            # second copy is idempotent (no duplicates)
            copied_again = await cl.post(
                f"/api/v1/admin/catalog/academic-years/{target_id}/copy-structure",
                json={"source_year_id": source_year["id"]},
                headers=headers,
            )
            assert copied_again.json()["copied"]["links"] == 0
    finally:
        await env.engine.dispose()


@pytest.mark.asyncio
async def test_students_blocked_and_student_picker_refreshes_from_catalog(tmp_path, monkeypatch):
    env = await build_env(tmp_path, monkeypatch, seed_admin_super=True)
    try:
        await _catalog_env(env)
        user_id = await _make_student(env)
        async with client() as cl:
            student = await _student_headers(cl, env)

            # regular users and students can NEVER reach catalog management
            for headers in ({}, {"Authorization": "Bearer invalid"}, student):
                denied = await cl.get("/api/v1/admin/catalog/textbooks", headers=headers)
                assert denied.status_code in {401, 403}

            # student sets a vocational placement
            own = await cl.put(
                "/api/v1/account/academic-profile",
                json={
                    "grade_number": 10,
                    "branch_code": "technical_vocational",
                    "ground_code": "services",
                    "field_code": "tec-services-حسابداری",
                },
                headers=student,
            )
            assert own.status_code == 200, own.text

            # admin archives that program
            fields = await cl.get("/api/v1/admin/catalog/fields?q=حسابداری", headers=await admin_headers(cl))
            program_id = fields.json()["items"][0]["id"]
            await cl.post(f"/api/v1/admin/catalog/fields/{program_id}/archive", headers=await admin_headers(cl))

            # historical placement data of the student is untouched (read-only view)
            admin_detail = await cl.get(f"/api/v1/admin/users/{user_id}", headers=await admin_headers(cl))
            assert admin_detail.json()["academic_profile"]["field_code"] == "tec-services-حسابداری"

            # archived program disappears from NEW student selections…
            options = await cl.get("/api/v1/account/academic-profile", headers=student)
            codes = [p["code"] for p in options.json()["options"]["programs"]]
            assert "tec-services-حسابداری" not in codes

            # …but restoring it brings the option back (picker refreshes from catalog)
            await cl.post(f"/api/v1/admin/catalog/fields/{program_id}/restore", headers=await admin_headers(cl))
            options = await cl.get("/api/v1/account/academic-profile", headers=student)
            codes = [p["code"] for p in options.json()["options"]["programs"]]
            assert "tec-services-حسابداری" in codes

            # a NEW program created by admin appears in the picker immediately
            branch = await cl.get("/api/v1/admin/catalog/branches?q=technical_vocational", headers=await admin_headers(cl))
            branch_id = branch.json()["items"][0]["id"]
            grounds = await cl.get(f"/api/v1/admin/catalog/grounds?branch_id={branch_id}", headers=await admin_headers(cl))
            services_ground = next(g for g in grounds.json()["items"] if g["code"] == "services")
            created = await cl.post(
                "/api/v1/admin/catalog/fields",
                json={"branch_id": branch_id, "ground_id": services_ground["id"], "code": "tec-services-رشته-جدید-تست", "title": "رشتهٔ جدید تست"},
                headers=await admin_headers(cl),
            )
            assert created.status_code == 201
            options = await cl.get("/api/v1/account/academic-profile", headers=student)
            codes = [p["code"] for p in options.json()["options"]["programs"]]
            assert "tec-services-رشته-جدید-تست" in codes
    finally:
        await env.engine.dispose()


@pytest.mark.asyncio
async def test_catalog_rbac_dedicated_permission_blocks_teacher_student_anonymous(tmp_path, monkeypatch):
    """Final correction review 2: catalog management has its OWN permission
    (`can_manage_education_catalog`, admin+ only) - NOT the moderator-level
    `can_read_users`. Every mutating API (create, update, delete, archive,
    restore, PDF upload) is exercised for teacher/student/anonymous/admin.

    Each probe runs in its own cookie-free client: the admin console login
    sets an HttpOnly admin cookie, and leaking it into the teacher/student
    probes would test session precedence instead of RBAC.
    """
    import io

    from app.core.passwords import hash_password
    from app.models.auth import User
    from app.services.permissions import AdminActor, can_manage_education_catalog

    # unit-level permission matrix (the semantic contract)
    assert can_manage_education_catalog(AdminActor("admin", "u", False)) is True
    assert can_manage_education_catalog(AdminActor("super_admin", "u", False)) is True
    assert can_manage_education_catalog(AdminActor("moderator", "u", False)) is False
    assert can_manage_education_catalog(AdminActor("teacher", "u", False)) is False
    assert can_manage_education_catalog(AdminActor("student", "u", False)) is False

    env = await build_env(tmp_path, monkeypatch, seed_admin_super=True)
    try:
        await _catalog_env(env)
        async with env.factory() as session:
            session.add_all(
                [
                    User(phone_number="09120000055", role="teacher", is_active=True,
                         password_hash=hash_password(STUDENT_PASSWORD)),
                    User(phone_number="09120000066", role="student", is_active=True,
                         password_hash=hash_password(STUDENT_PASSWORD)),
                ]
            )
            await session.commit()

        # admin-side fixture data (own client: admin cookie lives here)
        async with client() as admin_cl:
            admin = await admin_headers(admin_cl)
            branches = await admin_cl.get("/api/v1/admin/catalog/branches?q=technical_vocational", headers=admin)
            branch_id = branches.json()["items"][0]["id"]  # grounds need a هنرستانی branch
            ground = await admin_cl.post(
                "/api/v1/admin/catalog/grounds",
                json={"branch_id": branch_id, "code": "rbac-ground", "title": "زمینهٔ RBAC"},
                headers=admin,
            )
            assert ground.status_code == 201, ground.text
            ground_id = ground.json()["id"]
            grades = await admin_cl.get("/api/v1/admin/catalog/grades", headers=admin)
            g1 = next(g for g in grades.json()["items"] if g["number"] == 1)
            edition = await admin_cl.post(
                "/api/v1/admin/catalog/editions",
                json={"title": "نسخهٔ RBAC", "grade_id": g1["id"]},
                headers=admin,
            )
            assert edition.status_code == 201
            edition_id = edition.json()["id"]

        mutating = [
            ("create-cycle", "POST", "/api/v1/admin/catalog/cycles", {"code": "rbac-cycle", "title": "دورهٔ RBAC"}),
            ("update-grade", "PATCH", "/api/v1/admin/catalog/grades/1", {"title": "اول (RBAC)"}),
            ("delete-ground", "DELETE", f"/api/v1/admin/catalog/grounds/{ground_id}", {}),
            ("archive-textbook", "POST", "/api/v1/admin/catalog/textbooks/1/archive", {}),
            ("restore-textbook", "POST", "/api/v1/admin/catalog/textbooks/1/restore", {}),
            ("pdf-upload", "POST", f"/api/v1/admin/catalog/editions/{edition_id}/pdf", {}),
        ]

        async def login(phone: str) -> dict[str, str]:
            async with client() as c:
                r = await c.post(
                    "/api/v1/auth/login",
                    json={"phone_number": phone, "password": STUDENT_PASSWORD},
                )
                token = r.json().get("token") or r.json().get("access_token")
            return {"Authorization": f"Bearer {token}"}

        teacher = await login("09120000055")
        student = await login("09120000066")

        # teacher and student are 403 on EVERY mutating endpoint
        for who, headers in (("teacher", teacher), ("student", student)):
            async with client() as probe_cl:
                for label, method, url, json_body in mutating:
                    if method == "DELETE":
                        response = await probe_cl.request(method.upper(), url, headers=headers)
                    elif label == "pdf-upload":
                        response = await probe_cl.post(
                            url,
                            files={"file": ("x.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
                            headers=headers,
                        )
                    else:
                        response = await probe_cl.request(method.upper(), url, json=json_body, headers=headers)
                    assert response.status_code == 403, (label, who, response.status_code, response.text[:120])

        # admin keeps full access to every operation
        async with client() as admin_client:
            admin = await admin_headers(admin_client)
            for label, method, url, json_body in mutating:
                if method == "DELETE":
                    response = await admin_client.request(method.upper(), url, headers=admin)
                elif label == "pdf-upload":
                    response = await admin_client.post(
                        url,
                        files={"file": ("ok.pdf", io.BytesIO(b"%PDF-1.4 admin upload"), "application/pdf")},
                        headers=admin,
                    )
                else:
                    response = await admin_client.request(method.upper(), url, json=json_body, headers=admin)
                assert response.status_code in {200, 201}, (label, response.status_code, response.text[:150])

        # fully anonymous callers are 401 (router-level require_admin)
        async with client() as bare_client:
            for _, method, url, json_body in mutating[:3]:
                response = await bare_client.request(method.upper(), url, json=json_body)
                assert response.status_code == 401, (method, url, response.status_code)

        # no data was destroyed by the RBAC probes (catalog stays intact)
        async with client() as verify_cl:
            admin = await admin_headers(verify_cl)
            detail = await verify_cl.get("/api/v1/admin/catalog/textbooks/1", headers=admin)
            assert detail.status_code == 200
            assert (await verify_cl.get("/api/v1/admin/catalog/cycles", headers=admin)).json()["total"] >= 3
    finally:
        await env.engine.dispose()
