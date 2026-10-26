"""Neo4j connection and schema (constraints + indexes from docs/PRD.md section 5).

    python -m mlg.graph.db        # apply schema, print counts
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache

import certifi
from neo4j import Driver, GraphDatabase, TrustCustomCAs

from mlg.config import settings

ID_LABELS = ("Person", "MediaItem", "Frame", "Observation", "Moment", "Event", "LifeChapter",
             "Location", "Object", "Activity", "Conversation", "Utterance", "Blessing",
             "Inference", "Film", "Scene", "Shot")
NAME_LABELS = ("Emotion", "Topic")
INDEXES = (("MediaItem", "taken_at"), ("Event", "start"), ("Moment", "start"),
           ("Person", "name"), ("MediaItem", "kind"))


@lru_cache(maxsize=1)
def driver() -> Driver:
    s = settings()
    if not s.neo4j_uri:
        raise RuntimeError("NEO4J_URI is empty - put your AuraDB (or local) URI in .env")
    scheme, rest = s.neo4j_uri.split("://", 1)
    if scheme.endswith("+s"):
        # Windows' local root store may lack the CA AuraDB uses (SSL.com), so verify
        # against certifi's bundle instead of the "+s" scheme's system default.
        return GraphDatabase.driver(f"{scheme[:-2]}://{rest}", auth=(s.neo4j_user, s.neo4j_password),
                                    encrypted=True, trusted_certificates=TrustCustomCAs(certifi.where()),
                                    notifications_min_severity="OFF")
    return GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password),
                                notifications_min_severity="OFF")


@contextmanager
def session():
    with driver().session() as sess:
        yield sess


def schema_statements() -> list[str]:
    out = [f"CREATE CONSTRAINT {lbl.lower()}_id IF NOT EXISTS FOR (n:{lbl}) REQUIRE n.id IS UNIQUE"
           for lbl in ID_LABELS]
    out += [f"CREATE CONSTRAINT {lbl.lower()}_name IF NOT EXISTS FOR (n:{lbl}) REQUIRE n.name IS UNIQUE"
            for lbl in NAME_LABELS]
    out += [f"CREATE INDEX {lbl.lower()}_{prop} IF NOT EXISTS FOR (n:{lbl}) ON (n.{prop})"
            for lbl, prop in INDEXES]
    return out


def apply_schema() -> None:
    with session() as s:
        for stmt in schema_statements():
            s.run(stmt).consume()
        from mlg.perceive.schema import EMOTIONS
        s.run("UNWIND $names AS n MERGE (:Emotion {name: n})", names=list(EMOTIONS)).consume()


def counts() -> dict[str, int]:
    with session() as s:
        rows = s.run("MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) AS c ORDER BY l")
        return {r["l"]: r["c"] for r in rows}


if __name__ == "__main__":
    driver().verify_connectivity()
    apply_schema()
    print("schema applied;", counts())
