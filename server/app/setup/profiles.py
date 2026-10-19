"""Keep the active search profile stable while a target is populated."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ai.embeddings import Profile, configured_profile, persist_profile
from app.errors import Conflict, NotFound
from app.jobs.models import EmbeddingProfile, WorkItem
from app.setup.models import BankSettings, ProfileMigration


def active_profile(db: Session) -> Profile:
    settings = db.get(BankSettings, "default")
    if settings and settings.active_profile_key:
        return Profile.model_validate(db.get(EmbeddingProfile, settings.active_profile_key).settings)
    return configured_profile()


def initialize_active(db: Session) -> Profile:
    # All writers and cutover decisions serialize on this single bank row.
    db.execute(insert(BankSettings).values(key="default", active_profile_key=None).on_conflict_do_nothing(index_elements=[BankSettings.key]))
    settings = db.scalar(select(BankSettings).where(BankSettings.key == "default").with_for_update().execution_options(populate_existing=True))
    profile = (Profile.model_validate(db.get(EmbeddingProfile, settings.active_profile_key).settings)
               if settings.active_profile_key else configured_profile())
    persist_profile(db, profile)
    settings.active_profile_key = profile.key
    db.flush()
    return profile


def migration_status(db: Session, migration_id: UUID) -> dict:
    from app.discovery.service import pending_count
    item = db.get(ProfileMigration, migration_id)
    if not item:
        raise NotFound("Profile migration not found")
    return {"id": item.id, "status": item.status, "target_profile_key": item.target_profile_key,
            "source_profile_key": item.source_profile_key, "missing_explanations": pending_count(db, item.target_profile_key)}


def start_migration(db: Session, profile: Profile) -> dict:
    from app.jobs.service import enqueue
    from app.errors import NotConfigured
    with db.begin():
        persist_profile(db, profile)
        try:
            source = initialize_active(db).key
        except NotConfigured:
            source = None
            db.execute(insert(BankSettings).values(key="default", active_profile_key=None).on_conflict_do_nothing())
        db.scalar(select(BankSettings).where(BankSettings.key == "default").with_for_update())
        existing = db.scalar(select(ProfileMigration).where(ProfileMigration.status == "running"))
        if existing:
            if existing.target_profile_key != profile.key:
                raise Conflict("Another profile migration is still running")
            return migration_status(db, existing.id)
        item = ProfileMigration(target_profile_key=profile.key, source_profile_key=source, status="running")
        db.add(item)
        db.flush()
        enqueue(db, dedup_key=f"profile-migration:{item.id}", kind="profile_migration", arguments={"migration_id": str(item.id)})
        return migration_status(db, item.id)


def decide_migration(db: Session, migration_id: UUID, action: str) -> dict:
    from app.discovery.service import pending_count
    with db.begin():
        settings = db.scalar(select(BankSettings).where(BankSettings.key == "default").with_for_update())
        item = db.scalar(select(ProfileMigration).where(ProfileMigration.id == migration_id).with_for_update())
        if not item:
            raise NotFound("Profile migration not found")
        if item.status != "running":
            raise Conflict("Migration is already resolved")
        if action == "cutover":
            if pending_count(db, item.target_profile_key):
                raise Conflict("Current explanations are still missing target vectors")
            settings.active_profile_key = item.target_profile_key
            item.status = "completed"
        else:
            item.status = "cancelled"
            if settings.active_profile_key != item.target_profile_key:
                from sqlalchemy import update
                db.execute(update(WorkItem).where(WorkItem.kind == "embedding", WorkItem.profile_key == item.target_profile_key,
                    WorkItem.status.in_(["pending", "running"])).values(status="cancelled", lease_token=None, lease_until=None))
        db.flush()
        return migration_status(db, item.id)


def populate_migration(db: Session, arguments: dict) -> dict:
    from app.discovery.service import latest_revisions
    from app.knowledge.models import Concept, ConceptEmbedding, ExplanationRevision
    from app.jobs.service import enqueue
    from sqlalchemy import and_
    item = db.scalar(select(ProfileMigration).where(ProfileMigration.id == UUID(arguments["migration_id"])).with_for_update())
    if not item or item.status != "running":
        return {"cancelled": True}
    latest = latest_revisions()
    rows = db.scalars(select(ExplanationRevision.id).join(Concept, Concept.id == ExplanationRevision.concept_id)
        .join(latest, and_(latest.c.concept_id == Concept.id, latest.c.number == ExplanationRevision.revision_number))
        .outerjoin(ConceptEmbedding, and_(ConceptEmbedding.explanation_revision_id == ExplanationRevision.id,
                                        ConceptEmbedding.model_key == item.target_profile_key))
        .where(Concept.archived_at.is_(None), ConceptEmbedding.id.is_(None))).all()
    for revision_id in rows:
        enqueue(db, dedup_key=f"embedding:{revision_id}:{item.target_profile_key}", kind="embedding",
                revision_id=revision_id, profile_key=item.target_profile_key)
    return {"enqueued": len(rows), "migration_id": str(item.id)}
