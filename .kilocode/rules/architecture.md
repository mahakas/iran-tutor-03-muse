# Iran AI Tutor: Architecture Rules

Persian AI private tutor platform grounded ONLY in official Iranian textbooks.
These rules are persistent and apply to every phase. Build strictly phase by phase; never build beyond the step that was requested.

## Domain

- Scope: Iranian K-12 education.
- Grades 1-9: no major.
- Grades 10-12: major is required. Valid majors:
  - ریاضی‌فیزیک
  - علوم تجربی
  - علوم انسانی
- Konkoor mode synthesizes the grade 10 + 11 + 12 books of the student's major.
- The only knowledge source is the official textbooks. Answers must not rely on content outside the ingested books.

## Phases

1. **Vision PDF ingestion**: Persian RTL text + LaTeX for math + diagram descriptions + printed page number and chapter metadata.
2. **Hybrid RAG** (Qdrant + Postgres) + age-adaptive Socratic tutor with mandatory chapter/page citations.
3. **Image/voice input + 5 modes**:
   - tutor
   - problem solver
   - question designer
   - real exam UI with timer and report card
   - Konkoor master
4. **Admin panel**.
5. **Student web app**: Next.js, RTL Persian + LTR KaTeX.
6. **SMS OTP auth + plans** (normal / pro / VIP) + quotas.

## Tutor behavior

- Default: guide step by step first, and put the final answer at the end (collapsible).
- If the user explicitly asks for just the answer: give the answer first, then the explanation.
- Tone adapts to the student's grade.
- Every answer ends with its source: book, chapter, printed page numbers.
- Use symbols and notation exactly as they appear in Iranian textbooks.

## Coding rules

- Python 3.11+.
- FastAPI, async.
- Pydantic v2.
- SQLAlchemy 2, async.
- Type hints everywhere.
- Small modules.
- No hardcoded secrets, URLs, or model names: everything comes from `.env`.
- Structured logging.
- Every phase ends with a verifiable test.
- All LLM calls go through ONE client wrapper module, so provider and model are swappable.
- Future SMS and payment providers must sit behind abstract interfaces (hosting may be split between Iran and abroad).
- Design tables with a future `user_id` in mind, but do not build auth yet.

## Never commit

- `.env`
- PDFs
- `storage/`
- data folders
