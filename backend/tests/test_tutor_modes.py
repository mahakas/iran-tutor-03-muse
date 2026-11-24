from app.services.tutor_service import build_tutor_messages


def test_solver_and_designer_modes_add_distinct_grounded_instructions():
    solver = build_tutor_messages(
        query="این تمرین را حل کن",
        grade_number=12,
        context="منبع نمونه",
        mode="problem_solver",
    )
    designer = build_tutor_messages(
        query="از این درس سوال بساز",
        grade_number=12,
        context="منبع نمونه",
        mode="question_designer",
    )

    assert "مرحله‌به‌مرحله حل کن" in solver[0]["content"]
    assert "سه سؤال تمرینی" in designer[0]["content"]
    assert "منبع نمونه" in solver[1]["content"]
    assert "منبع نمونه" in designer[1]["content"]
