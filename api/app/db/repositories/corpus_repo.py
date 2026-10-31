"""Corpus and access-grant queries. Who may *read* a corpus is decided in services/rag/retriever."""

import uuid

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.db.models import Corpus, CorpusAccess, Document, User


def create(
    db: Session,
    name: str,
    description: str,
    is_public: bool,
    created_by: uuid.UUID | None,
    source_config: dict[str, str] | None = None,
) -> Corpus:
    corpus = Corpus(
        name=name,
        description=description,
        is_public=is_public,
        created_by=created_by,
        source_config=source_config or {},
    )
    db.add(corpus)
    db.commit()
    return corpus


def save(db: Session, corpus: Corpus) -> Corpus:
    db.add(corpus)
    db.commit()
    return corpus


def delete(db: Session, corpus: Corpus) -> None:
    db.delete(corpus)
    db.commit()


def get(db: Session, corpus_id: uuid.UUID) -> Corpus | None:
    return db.get(Corpus, corpus_id)


def get_by_name(db: Session, name: str) -> Corpus | None:
    return db.scalar(select(Corpus).where(Corpus.name == name))


def list_where(db: Session, condition: ColumnElement[bool] | None = None) -> list[Corpus]:
    query = select(Corpus).order_by(Corpus.name)
    if condition is not None:
        query = query.where(condition)
    return list(db.scalars(query))


def document_counts(db: Session, corpus_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Document.corpus_id, func.count())
        .where(Document.corpus_id.in_(corpus_ids))
        .group_by(Document.corpus_id)
    )
    return {corpus_id: count for corpus_id, count in rows if corpus_id is not None}


def granted_users(db: Session, corpus_id: uuid.UUID) -> list[User]:
    query = (
        select(User)
        .join(CorpusAccess, CorpusAccess.user_id == User.id)
        .where(CorpusAccess.corpus_id == corpus_id)
        .order_by(User.email)
    )
    return list(db.scalars(query))


def grant(db: Session, corpus_id: uuid.UUID, user_id: uuid.UUID) -> None:
    if db.get(CorpusAccess, (corpus_id, user_id)) is None:
        db.add(CorpusAccess(corpus_id=corpus_id, user_id=user_id))
        db.commit()


def revoke(db: Session, corpus_id: uuid.UUID, user_id: uuid.UUID) -> None:
    grant_row = db.get(CorpusAccess, (corpus_id, user_id))
    if grant_row is not None:
        db.delete(grant_row)
        db.commit()
