"""ORM models. Imported so Alembic autogenerate sees every table."""

from app.models.auth import (  # noqa: F401
    BillingSettings,
    OtpCode,
    PaymentTransaction,
    Plan,
    TokenUsageLog,
    User,
    UserFile,
    UserSession,
)
from app.models.chat import ChatSession  # noqa: F401
from app.models.curriculum import (  # noqa: F401
    AcademicYear,
    Book,
    BookCurriculumLink,
    BookPage,
    BookPageObjective,
    CurriculumUnit,
    EducationBranch,
    EducationCycle,
    FieldOfStudy,
    Grade,
    LearningObjective,
    LearningEvidence,
    Major,
    ObjectivePrerequisite,
    Subject,
)
from app.models.exam import ExamSession  # noqa: F401
from app.models.concepts import ConceptLink  # noqa: F401
from app.models.learner_memory import LearnerMemory  # noqa: F401
from app.models.phase6 import (  # noqa: F401
    AudioCacheEntry,
    LivingBookCache,
    Notebook,
    NotebookBlock,
)
from app.models.phase5 import (  # noqa: F401
    AdminActionLog,
    DeepSolveSession,
    MasteryBookSettings,
    MasteryChapterProgress,
    MistakeBankItem,
    QuizValidationLog,
)
from app.models.flashcards import (  # noqa: F401
    Flashcard,
    FlashcardDeck,
    FlashcardReview,
    FlashcardStudySession,
)
from app.models.podcast import (  # noqa: F401
    PodcastEpisode,
    PodcastFeedback,
    PodcastQuestion,
    PodcastSegment,
)
from app.models.catalog import (  # noqa: F401
    CatalogCourseTextbook,
    CatalogImportRun,
    CatalogSource,
    CatalogTextbook,
    EducationGround,
    ProgramAvailability,
    StudentAcademicProfile,
)
from app.models.capabilities import (  # noqa: F401
    Capability,
    KbIngestionJob,
    Skill,
    SkillVersion,
    SourceFigure,
)
from app.models.governance import (  # noqa: F401
    AiAuditLog,
    AiProvider,
    FeatureModelRoute,
    UserQuota,
)

__all__ = [
    "Grade",
    "Major",
    "Book",
    "BookPage",
    "EducationCycle",
    "EducationBranch",
    "FieldOfStudy",
    "AcademicYear",
    "Subject",
    "BookCurriculumLink",
    "CurriculumUnit",
    "LearningObjective",
    "LearningEvidence",
    "ObjectivePrerequisite",
    "BookPageObjective",
    "ExamSession",
    "ChatSession",
    "FlashcardDeck",
    "Flashcard",
    "FlashcardReview",
    "Plan",
    "BillingSettings",
    "User",
    "OtpCode",
    "PaymentTransaction",
    "TokenUsageLog",
    "UserSession",
    "UserFile",
    "AiProvider",
    "FeatureModelRoute",
    "UserQuota",
    "AiAuditLog",
    "Capability",
    "Skill",
    "SkillVersion",
    "KbIngestionJob",
    "SourceFigure",
]
