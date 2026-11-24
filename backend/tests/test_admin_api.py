"""Admin API validation tests (no LLM calls)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.preview import render_single_preview


ADMIN_HEADERS = {"X-Admin-Username": "admin", "X-Admin-Password": "123"}


@pytest.mark.asyncio
async def test_admin_endpoints_require_authentication_and_login_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unauth_session = await client.get("/api/v1/admin/auth/session")
        assert unauth_session.status_code == 200
        assert unauth_session.json() == {"authenticated": False, "username": None}

        for method, path in (
            ("GET", "/api/v1/admin/books"),
            ("GET", "/api/v1/admin/books/1/status"),
            ("GET", "/api/v1/admin/books/1/pages"),
            ("GET", "/api/v1/admin/books/1/pages/1/image"),
            ("GET", "/api/v1/admin/books/1/preview"),
            ("PUT", "/api/v1/admin/books/1/pages/1"),
            ("POST", "/api/v1/admin/books/upload-and-ingest"),
        ):
            res = await client.request(method, path)
            assert res.status_code == 401, f"{method} {path} returned {res.status_code}"

        bad_user = await client.post(
            "/api/v1/admin/auth/login", json={"username": "root", "password": "123"}
        )
        assert bad_user.status_code == 401

        bad_pass = await client.post(
            "/api/v1/admin/auth/login", json={"username": "admin", "password": "wrong"}
        )
        assert bad_pass.status_code == 401

        good_login = await client.post(
            "/api/v1/admin/auth/login", json={"username": "admin", "password": "123"}
        )
        assert good_login.status_code == 200
        login_payload = good_login.json()
        assert login_payload["authenticated"] is True
        assert login_payload["username"] == "admin"
        assert isinstance(login_payload["token"], str) and login_payload["token"]
        assert "iran_tutor_admin" in client.cookies

        authed_session = await client.get("/api/v1/admin/auth/session")
        assert authed_session.json() == {"authenticated": True, "username": "admin"}

        logout = await client.post("/api/v1/admin/auth/logout")
        assert logout.status_code == 200
        assert logout.json() == {"authenticated": False}

        after_logout = await client.get("/api/v1/admin/books")
        assert after_logout.status_code == 401

        # Bearer and X-Admin-Token work even when cookies are blocked (e.g. cross-site iframe preview).
        bearer_session = await client.get(
            "/api/v1/admin/auth/session",
            headers={"Authorization": f"Bearer {login_payload['token']}"},
        )
        assert bearer_session.json() == {"authenticated": True, "username": "admin"}

        x_token_preview = await client.get(
            "/api/v1/admin/books/1/preview?status=bogus",
            headers={"X-Admin-Token": login_payload["token"]},
        )
        assert x_token_preview.status_code == 422


@pytest.mark.asyncio
async def test_preview_rejects_unknown_status():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/admin/books/1/preview?status=bogus",
            headers=ADMIN_HEADERS,
        )
    assert response.status_code == 422
    assert "invalid status filter" in response.json()["detail"]


@pytest.mark.asyncio
async def test_preview_rejects_inverted_page_range():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/admin/books/1/preview?page_from=5&page_to=2",
            headers=ADMIN_HEADERS,
        )
    assert response.status_code == 422
    assert "invalid page range" in response.json()["detail"]


@pytest.mark.asyncio
async def test_preview_rejects_negative_page_index():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/admin/books/1/preview?page_from=0",
            headers=ADMIN_HEADERS,
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_rejects_invalid_pdf_and_out_of_bounds_page_range(monkeypatch, tmp_path):
    class FakeResult:
        def __init__(self, value):
            self._value = value

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def scalar(self, stmt):
            sql = str(stmt)
            if "grades" in sql:
                return SimpleNamespace(id=12, number=12, has_major=True)
            if "majors" in sql:
                return SimpleNamespace(id=1, code="math_physics")
            if "education_branches" in sql:
                return SimpleNamespace(
                    id=3, code="theoretical", min_grade=10, max_grade=12, is_active=True
                )
            if "fields_of_study" in sql:
                return SimpleNamespace(
                    id=2, code="math_physics", branch_id=3, title="ریاضی‌فیزیک", is_active=True
                )
            return None

        async def scalars(self, stmt):
            return SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        id=3, code="theoretical", min_grade=10, max_grade=12, is_active=True
                    )
                ]
            )

    from app.api import admin as admin_api

    monkeypatch.setattr(admin_api, "async_session_factory", lambda: FakeSession())
    monkeypatch.setattr(admin_api, "UPLOAD_DIR", tmp_path)

    doc = pymupdf.open()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bad_pdf = await client.post(
            "/api/v1/admin/books/upload-and-ingest",
            headers=ADMIN_HEADERS,
            data={
                "grade_number": "12",
                "major_code": "math_physics",
                "book_title": "کتاب آزمایشی",
                "start_page": "1",
                "end_page": "1",
            },
            files={"pdf_file": ("not_a_pdf.pdf", b"not-valid-pdf-bytes", "application/pdf")},
        )
        assert bad_pdf.status_code == 422
        assert "not a valid PDF" in bad_pdf.json()["detail"]

        too_many_pages = await client.post(
            "/api/v1/admin/books/upload-and-ingest",
            headers=ADMIN_HEADERS,
            data={
                "grade_number": "12",
                "major_code": "math_physics",
                "book_title": "کتاب آزمایشی",
                "start_page": "1",
                "end_page": "3",
            },
            files={"pdf_file": ("one_page.pdf", pdf_bytes, "application/pdf")},
        )
        assert too_many_pages.status_code == 422
        assert "only 1 pages" in too_many_pages.json()["detail"]


def test_single_preview_renders_each_page_without_single_queryselector_collision(tmp_path):
    from PIL import Image

    img1 = tmp_path / "p1.png"
    img2 = tmp_path / "p2.png"
    Image.new("RGB", (20, 20), "white").save(img1)
    Image.new("RGB", (20, 20), "white").save(img2)

    out = render_single_preview(
        1,
        "demo-vision",
        [
            {"pdf_page_index": 1, "image_path": str(img1), "markdown": "صفحه اول", "status": "done", "warnings": [], "visual_elements": []},
            {"pdf_page_index": 2, "image_path": str(img2), "markdown": "صفحه دوم", "status": "done", "warnings": [], "visual_elements": []},
        ],
        tmp_path / "preview.html",
    )
    html_text = out.read_text(encoding="utf-8")
    assert html_text.count('class="md-body"') == 2
    assert "t.nextElementSibling" in html_text
    assert "document.querySelector('.md-body[data-model=" not in html_text


def test_single_preview_handles_missing_image_gracefully(tmp_path):
    out = render_single_preview(
        1,
        "demo-vision",
        [
            {
                "pdf_page_index": 1,
                "image_path": str(tmp_path / "does_not_exist.png"),
                "markdown": "صفحه بدون تصویر",
                "status": "failed",
                "warnings": [],
                "visual_elements": [],
            }
        ],
        tmp_path / "preview.html",
    )
    html_text = out.read_text(encoding="utf-8")
    assert "تصویر صفحه موجود نیست" in html_text


@pytest.mark.asyncio
async def test_fix_page_clears_warnings_supports_null_and_serves_admin_lists(monkeypatch, tmp_path):
    from PIL import Image
    from app.api import admin as admin_api

    img_path = tmp_path / "page_0015.png"
    Image.new("RGB", (12, 12), "white").save(img_path)

    book_obj = SimpleNamespace(
        id=2,
        title="فیزیک ۳",
        grade_id=12,
        major_id=1,
        academic_year_id=None,
        edition_label=None,
        print_year=None,
        publisher=None,
        official_source_url=None,
        source_checksum=None,
        approved_at=None,
        catalog_status="approved",
        total_pdf_pages=1,
        status="ready",
    )
    page_obj = SimpleNamespace(
        book_id=2,
        pdf_page_index=15,
        printed_page_number=99,
        chapter_number=1,
        chapter_title="حرکت",
        markdown_content="متن قبلی",
        visual_elements=[],
        page_image_path=str(img_path),
        status="needs_review",
        error_message="خطای قدیمی",
        extraction_model="demo-vision",
        warnings=["DEMO_MODE: OCR واقعی اجرا نشده"],
        edited_by_human=False,
    )

    class FakeExecResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeScalarsResult:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, model, key):
            if key == 2:
                return book_obj
            return None

        async def scalar(self, stmt):
            return page_obj

        async def scalars(self, stmt):
            return FakeScalarsResult([page_obj])

        async def execute(self, stmt):
            sql = str(stmt)
            if "COUNT" in sql.upper() or "count(" in sql.lower():
                return FakeExecResult([(2, page_obj.status, 1)])
            return FakeExecResult([(book_obj, 12, "math_physics")])

        async def commit(self):
            return None

    monkeypatch.setattr(admin_api, "async_session_factory", lambda: FakeSession())
    monkeypatch.setattr("app.services.ingestion_service.STORAGE_DIR", tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        books_resp = await client.get("/api/v1/admin/books", headers=ADMIN_HEADERS)
        assert books_resp.status_code == 200
        assert books_resp.json()[0]["id"] == 2
        assert books_resp.json()[0]["pages"] == {"needs_review": 1}

        pages_resp = await client.get("/api/v1/admin/books/2/pages", headers=ADMIN_HEADERS)
        assert pages_resp.status_code == 200
        assert pages_resp.json()[0]["image_url"] == "/api/v1/admin/books/2/pages/15/image"

        img_resp = await client.get("/api/v1/admin/books/2/pages/15/image", headers=ADMIN_HEADERS)
        assert img_resp.status_code == 200
        assert img_resp.headers["content-type"].startswith("image/png")

        fix_resp = await client.put(
            "/api/v1/admin/books/2/pages/15",
            headers=ADMIN_HEADERS,
            json={
                "printed_page_number": None,
                "chapter_number": 1,
                "chapter_title": "حرکت بر خط راست",
                "markdown_content": "# مثال اصلاح‌شده",
            },
        )
        assert fix_resp.status_code == 200
        assert fix_resp.json()["status"] == "done"
        assert fix_resp.json()["edited_by_human"] is True

    assert page_obj.printed_page_number is None
    assert page_obj.chapter_title == "حرکت بر خط راست"
    assert page_obj.markdown_content == "# مثال اصلاح‌شده"
    assert page_obj.warnings == []
    assert page_obj.error_message is None
    assert (tmp_path / "books" / "2" / "book.md").is_file()
    assert (tmp_path / "books" / "2" / "book.json").is_file()


def test_unbalanced_dollars_warning_ignores_escaped_currency():
    from app.services.ingestion_service import _unbalanced_dollars_warning

    assert _unbalanced_dollars_warning(r"قیمت \$10 و فرمول $v = \frac{\Delta x}{\Delta t}$") is None
    assert _unbalanced_dollars_warning("فرمول ناقص $v = at") is not None


def test_document_parser_supports_markdown_json_and_html():
    from app.services.document_parser import (
        detect_document_format,
        parse_html_document,
        parse_json_document,
        parse_markdown_document,
    )

    assert detect_document_format("physics.MD") == "markdown"
    assert detect_document_format("book.markdown") == "markdown"
    assert detect_document_format("data.json") == "json"
    assert detect_document_format("lesson.htm") == "html"
    assert detect_document_format(None, "text/html; charset=utf-8") == "html"
    with pytest.raises(ValueError):
        detect_document_format("notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    md_bytes = (
        "---\n"
        "chapter_number: 1\n"
        "chapter_title: حرکت بر خط راست\n"
        "---\n"
        "<!-- page: pdf=1 printed=8 chapter=1 -->\n"
        "# فصل ۱: حرکت بر خط راست\n\n"
        "تعریف سرعت متوسط $v = \\frac{\\Delta x}{\\Delta t}$.\n\n"
        "![نمودار مکان-زمان](chart.png)\n\n"
        "<!-- page: ۹ -->\n"
        "مثال حل‌شده با فرمول باز $x = v t\n"
    ).encode("utf-8")
    md_pages = parse_markdown_document(md_bytes)
    assert len(md_pages) == 2
    assert md_pages[0].printed_page_number == 8
    assert md_pages[0].chapter_number == 1
    assert md_pages[0].chapter_title == "حرکت بر خط راست"
    assert len(md_pages[0].visual_elements) == 1
    assert md_pages[0].warnings == []
    assert md_pages[1].printed_page_number == 9
    assert md_pages[1].warnings == ["unbalanced $ delimiters in markdown"]

    json_bytes = (
        '{"chapter_number": 2, "chapter_title": "دینامیک", "pages": ['
        '{"page_index": 3, "printed_page_number": 21, "markdown_content": "قانون دوم نیوتن $F = ma$", '
        '"visual_elements": [{"label": "شکل ۲-۱", "type": "diagram", "scientific_description": "نمودار نیرو"}]},'
        '{"printed_page_number": 22, "sections": [{"title": "اصطکاک", "text": "نیروی اصطکاک جنبشی"}]}'
        "]}"
    ).encode("utf-8")
    json_pages = parse_json_document(json_bytes)
    assert len(json_pages) == 2
    assert json_pages[0].page_index == 3
    assert json_pages[0].printed_page_number == 21
    assert json_pages[0].chapter_number == 2
    assert json_pages[0].visual_elements[0]["label"] == "شکل ۲-۱"
    assert "## اصطکاک" in json_pages[1].markdown_content

    html_bytes = (
        "<html><head><title>شیمی دهم</title><style>body{color:red}</style></head><body>"
        "<script>alert(1)</script>"
        "<!-- page: 14 -->"
        "<h1>فصل ۲: آب آهنگ زندگی</h1>"
        "<p>فرمول آب <script type='math/tex'>H_2O</script> است.</p>"
        "<img src='mol.png' alt='ساختار مولکول آب' />"
        "<hr class='page-break' />"
        "<table><tr><th>عنصر</th><th>نماد</th></tr><tr><td>هیدروژن</td><td>H</td></tr></table>"
        "</body></html>"
    ).encode("utf-8")
    html_pages = parse_html_document(html_bytes)
    assert len(html_pages) == 2
    assert html_pages[0].printed_page_number == 14
    assert html_pages[0].chapter_number == 2
    assert "$H_2O$" in html_pages[0].markdown_content
    assert "alert(1)" not in html_pages[0].markdown_content
    assert html_pages[0].visual_elements[0]["scientific_description"] == "ساختار مولکول آب"
    assert "| عنصر | نماد |" in html_pages[1].markdown_content


@pytest.mark.asyncio
async def test_upload_structured_markdown_json_and_html_books(monkeypatch, tmp_path):
    from app.api import admin as admin_api

    stored_books: dict[int, SimpleNamespace] = {}
    stored_pages: dict[int, list[SimpleNamespace]] = {}
    next_book_id = 10

    class FakeScalarsResult:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class FakeSession:
        def __init__(self):
            self._pending: list[object] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def scalar(self, stmt):
            sql = str(stmt)
            if "grades" in sql:
                return SimpleNamespace(id=12, number=12, has_major=True)
            if "majors" in sql:
                return SimpleNamespace(id=1, code="math_physics")
            if "education_branches" in sql:
                return SimpleNamespace(
                    id=3, code="theoretical", min_grade=10, max_grade=12, is_active=True
                )
            if "fields_of_study" in sql:
                return SimpleNamespace(
                    id=2, code="math_physics", branch_id=3, title="ریاضی‌فیزیک", is_active=True
                )
            return None

        async def scalars(self, stmt):
            sql = str(stmt)
            if "education_branches" in sql:
                return FakeScalarsResult([
                    SimpleNamespace(
                        id=3, code="theoretical", min_grade=10, max_grade=12, is_active=True
                    )
                ])
            # Return pages for the most recently created book
            latest_id = max(stored_pages) if stored_pages else 0
            return FakeScalarsResult(stored_pages.get(latest_id, []))

        def add(self, obj):
            self._pending.append(obj)

        async def flush(self):
            nonlocal next_book_id
            for obj in self._pending:
                if hasattr(obj, "total_pdf_pages") and getattr(obj, "id", None) is None:
                    obj.id = next_book_id
                    next_book_id += 1
                    stored_books[obj.id] = obj
                    stored_pages.setdefault(obj.id, [])

        async def commit(self):
            await self.flush()
            for obj in self._pending:
                if hasattr(obj, "pdf_page_index"):
                    stored_pages.setdefault(obj.book_id, []).append(obj)
            self._pending.clear()

        async def get(self, model, key):
            return stored_books.get(key)

    monkeypatch.setattr(admin_api, "async_session_factory", lambda: FakeSession())
    monkeypatch.setattr(admin_api, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr("app.services.ingestion_service.STORAGE_DIR", tmp_path / "storage")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unsupported extension -> 422
        bad_ext = await client.post(
            "/api/v1/admin/books/upload-and-ingest",
            headers=ADMIN_HEADERS,
            data={"grade_number": "12", "major_code": "math_physics", "book_title": "نامعتبر"},
            files={"file": ("notes.docx", b"hello", "application/octet-stream")},
        )
        assert bad_ext.status_code == 422

        # 2. Invalid JSON -> 422
        bad_json = await client.post(
            "/api/v1/admin/books/upload-and-ingest",
            headers=ADMIN_HEADERS,
            data={"grade_number": "12", "major_code": "math_physics", "book_title": "خراب"},
            files={"file": ("broken.json", b"{not valid json", "application/json")},
        )
        assert bad_json.status_code == 422

        # 3. Markdown upload -> ready immediately
        md_resp = await client.post(
            "/api/v1/admin/books/upload-and-ingest",
            headers=ADMIN_HEADERS,
            data={"grade_number": "12", "major_code": "math_physics", "book_title": "فیزیک مارک‌داون"},
            files={
                "file": (
                    "physics.md",
                    "<!-- page: 10 -->\n# فصل ۱: حرکت\n\nسرعت متوسط برابر تغییر مکان بر زمان است.".encode("utf-8"),
                    "text/markdown",
                )
            },
        )
        assert md_resp.status_code == 200
        md_body = md_resp.json()
        assert md_body["status"] == "ready"
        assert md_body["format"] == "markdown"
        assert md_body["total_pages"] == 1
        md_book_id = md_body["book_id"]

        # Pages listing has image_url=None and preview explains structured source without PDF image
        pages_resp = await client.get(f"/api/v1/admin/books/{md_book_id}/pages", headers=ADMIN_HEADERS)
        assert pages_resp.status_code == 200
        assert pages_resp.json()[0]["image_url"] is None
        assert pages_resp.json()[0]["extraction_model"] == "structured-markdown"

        preview_resp = await client.get(f"/api/v1/admin/books/{md_book_id}/preview", headers=ADMIN_HEADERS)
        assert preview_resp.status_code == 200
        assert "منبع متنی/ساختاریافته (بدون تصویر PDF)" in preview_resp.text
        assert (tmp_path / "storage" / "books" / str(md_book_id) / "book.md").is_file()
        assert (tmp_path / "storage" / "books" / str(md_book_id) / "book.json").is_file()

        # 4. JSON upload -> ready immediately
        json_resp = await client.post(
            "/api/v1/admin/books/upload-and-ingest",
            headers=ADMIN_HEADERS,
            data={"grade_number": "12", "major_code": "math_physics", "book_title": "حسابان JSON"},
            files={
                "file": (
                    "calc.json",
                    '{"pages": [{"printed_page_number": 5, "chapter_number": 1, "markdown_content": "مشتق تابع $f(x)$"}]}'.encode("utf-8"),
                    "application/json",
                )
            },
        )
        assert json_resp.status_code == 200
        assert json_resp.json()["format"] == "json"
        assert json_resp.json()["status"] == "ready"

        # 5. HTML upload -> ready immediately
        html_resp = await client.post(
            "/api/v1/admin/books/upload-and-ingest",
            headers=ADMIN_HEADERS,
            data={"grade_number": "12", "major_code": "math_physics", "book_title": "شیمی HTML"},
            files={
                "file": (
                    "chem.html",
                    "<html><body><h1>فصل ۱: کیهان</h1><p>ساختار اتم و ایزوتوپ‌ها</p></body></html>".encode("utf-8"),
                    "text/html",
                )
            },
        )
        assert html_resp.status_code == 200
        assert html_resp.json()["format"] == "html"
        assert html_resp.json()["status"] == "ready"
