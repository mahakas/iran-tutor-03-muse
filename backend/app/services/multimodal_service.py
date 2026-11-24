"""Image and voice question understanding before textbook-grounded tutoring."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.services.ai_gateway import (
    CallContext,
    transcribe_audio_via_gateway,
    vision_json_via_gateway,
)
from app.services.tutor_service import TutorMode, answer_from_textbook


class ImageQuestionExtraction(BaseModel):
    question_text: str = Field(min_length=1)
    visual_description: str = ""
    uncertain_parts: list[str] = Field(default_factory=list)


IMAGE_QUESTION_SYSTEM_PROMPT = """تصویر ارسالی دانش‌آموز را برای فهم صورت سؤال بخوان.
فقط محتوای قابل‌مشاهده را استخراج کن؛ چیزی را حدس نزن یا حل نکن.
متن فارسی، اعداد، واحدها و نمادها را با دقت حفظ کن و فرمول‌ها را به LaTeX استاندارد تبدیل کن.
اگر شکل یا نمودار برای فهم سؤال لازم است، محور‌ها، برچسب‌ها و ویژگی‌های مهمش را کوتاه توصیف کن.
هر بخش ناخوانا یا مبهم را در uncertain_parts بنویس.
فقط JSON مطابق این ساختار بده:
{"question_text":"...", "visual_description":"...", "uncertain_parts":[]}
"""


def _validate_image_extraction(parsed: dict[str, Any]) -> ImageQuestionExtraction:
    try:
        return ImageQuestionExtraction.model_validate(parsed)
    except ValidationError as error:
        raise ValueError("vision model did not return a valid question extraction") from error


async def answer_image_question(
    *,
    image_bytes: bytes,
    image_mime_type: str,
    grade_number: int,
    major_code: str | None,
    book_id: int,
    top_k: int = 5,
    mode: TutorMode = "tutor",
    user_id: str | None = None,
    session_id: str | None = None,
    db_session: Any | None = None,
) -> dict[str, Any]:
    """Read a photographed question and solve it using the selected textbook only."""
    settings = get_settings()
    vision_result = await vision_json_via_gateway(
        ctx=CallContext(
            feature_key="vision_ocr",
            user_id=user_id,
            session_id=session_id,
            book_id=book_id,
        ),
        system_prompt=IMAGE_QUESTION_SYSTEM_PROMPT,
        user_text="صورت سؤال و اطلاعات درسی لازم را از تصویر استخراج کن.",
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
        model=settings.vision_model_primary,
        session=db_session,
    )
    extraction = _validate_image_extraction(vision_result.content)
    query = extraction.question_text.strip()
    if extraction.visual_description.strip():
        query += "\n\nتوصیف شکل سؤال: " + extraction.visual_description.strip()
    result = await answer_from_textbook(
        query=query,
        grade_number=grade_number,
        major_code=major_code,
        book_id=book_id,
        top_k=top_k,
        mode=mode,
        user_id=user_id,
        session_id=session_id,
        db_session=db_session,
    )
    result["recognized_question"] = extraction.question_text
    result["visual_description"] = extraction.visual_description
    result["uncertain_parts"] = extraction.uncertain_parts
    return result


async def answer_audio_question(
    *,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    grade_number: int,
    major_code: str | None,
    book_id: int,
    top_k: int = 5,
    mode: TutorMode = "tutor",
    user_id: str | None = None,
    session_id: str | None = None,
    db_session: Any | None = None,
) -> dict[str, Any]:
    """Transcribe a Persian voice question, then answer from the selected book."""
    transcript_result = await transcribe_audio_via_gateway(
        ctx=CallContext(
            feature_key="stt",
            user_id=user_id,
            session_id=session_id,
            book_id=book_id,
        ),
        audio_bytes=audio_bytes,
        filename=filename,
        content_type=content_type,
        session=db_session,
    )
    transcript = transcript_result.content
    result = await answer_from_textbook(
        query=transcript,
        grade_number=grade_number,
        major_code=major_code,
        book_id=book_id,
        top_k=top_k,
        mode=mode,
        user_id=user_id,
        session_id=session_id,
        db_session=db_session,
    )
    result["transcript"] = transcript
    return result
