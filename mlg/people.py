"""Known people: the roster the Perceive pass may name, each with a reference crop.

    python -m mlg.people add "Ruth" --photo P --box x1,y1,x2,y2 [--note "..."] [--relation "grandmother"]
    python -m mlg.people list

`--box` is in source pixels (e.g. a SAM person box). The crop keeps the upper
part of the box (head and shoulders), which is what re-identification needs.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from mlg.config import DATA
from mlg.graph.db import session
from mlg.muse.media import open_image

CROPS = DATA / "people"


def slug(name: str) -> str:
    return re.sub(r"[^\w]+", "-", name.strip().lower()).strip("-")


def dataset_of(path: str) -> str:
    """'demo' for the fictional Muse Image family, 'real' for everything else."""
    return "demo" if "data\\demo" in path or "data/demo" in path else "real"


def add(name: str, photo: Path, box: tuple[float, float, float, float], note: str = "",
        relation: str = "", is_owner: bool = False, dataset: str = "real") -> str:
    pid = f"person:{slug(name)}"
    img = open_image(photo)
    x1, y1, x2, y2 = box
    crop = img.crop((int(x1), int(y1), int(x2), int(y1 + (y2 - y1) * 0.6)))
    crop.thumbnail((384, 384))
    CROPS.mkdir(parents=True, exist_ok=True)
    out = CROPS / f"{slug(name)}.jpg"
    crop.save(out, quality=90)
    with session() as s:
        s.run("""MERGE (p:Person {id: $id})
                 SET p.name = $name, p.note = $note, p.relation = $relation, p.is_owner = $owner,
                     p.confirmed = true, p.ref_crop = $crop, p.ref_photo = $photo, p.dataset = $ds""",
              id=pid, name=name, note=note, relation=relation, owner=is_owner,
              crop=str(out), photo=str(photo), ds=dataset).consume()
    return pid


def roster(dataset: str | None = None) -> list[dict]:
    with session() as s:
        rows = s.run("""MATCH (p:Person {confirmed: true})
                        WHERE $ds IS NULL OR coalesce(p.dataset, 'real') = $ds
                        OPTIONAL MATCH (p)-[:OBSERVED_AS]->(o)
                        RETURN p.id AS id, p.name AS name, p.note AS note, p.relation AS relation,
                               p.ref_crop AS crop, count(o) AS seen
                        ORDER BY seen DESC, name LIMIT 40""", ds=dataset)
        return [dict(r) for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("name")
    a.add_argument("--photo", type=Path, required=True)
    a.add_argument("--box", required=True, help="x1,y1,x2,y2 in pixels")
    a.add_argument("--note", default="")
    a.add_argument("--relation", default="")
    a.add_argument("--owner", action="store_true")
    sub.add_parser("list")
    args = ap.parse_args()
    if args.cmd == "add":
        box = tuple(float(v) for v in args.box.split(","))
        print(add(args.name, args.photo, box, args.note, args.relation, args.owner))
    else:
        for r in roster():
            print(r)


if __name__ == "__main__":
    main()
