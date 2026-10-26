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


def _save_crop(name: str, crop) -> Path:
    CROPS.mkdir(parents=True, exist_ok=True)
    n = 1
    while (out := CROPS / f"{slug(name)}_{n}.jpg").exists():
        n += 1
    crop = crop.convert("RGB")
    crop.thumbnail((384, 384))
    crop.save(out, quality=90)
    return out


def add_ref(pid: str, crop) -> str:
    """Another reference photo for a known person (from a confirmed face)."""
    with session() as s:
        name = s.run("MATCH (p:Person {id: $id}) RETURN p.name AS n", id=pid).single()["n"]
        out = _save_crop(name, crop)
        s.run("MATCH (p:Person {id: $id}) SET p.ref_crops = coalesce(p.ref_crops, []) + $c",
              id=pid, c=str(out)).consume()
    return str(out)


def remove_ref(pid: str, ref: str) -> None:
    with session() as s:
        s.run("""MATCH (p:Person {id: $id})
                 SET p.ref_crops = [c IN coalesce(p.ref_crops, []) WHERE c <> $ref]""", id=pid, ref=ref).consume()
    Path(ref).unlink(missing_ok=True)


def new_person(name: str, crop, dataset: str = "real", note: str = "") -> str:
    """A person first named on the Who-is-this screen; the confirmed face is the reference."""
    pid = f"person:{slug(name)}"
    with session() as s:
        exists = s.run("MATCH (p:Person {id: $id}) RETURN p.id AS id", id=pid).single()
    if exists:
        add_ref(pid, crop)
        return pid
    out = _save_crop(name, crop)
    with session() as s:
        s.run("""MERGE (p:Person {id: $id})
                 SET p.name = $name, p.note = $note, p.confirmed = true, p.ref_crop = $crop,
                     p.dataset = $ds, p.is_owner = false""",
              id=pid, name=name, note=note, crop=str(out), ds=dataset).consume()
    return pid


def roster(dataset: str | None = None) -> list[dict]:
    with session() as s:
        rows = s.run("""MATCH (p:Person {confirmed: true})
                        WHERE $ds IS NULL OR coalesce(p.dataset, 'real') = $ds
                        OPTIONAL MATCH (p)-[:OBSERVED_AS]->(o)
                        RETURN p.id AS id, p.name AS name, p.note AS note, p.relation AS relation,
                               p.ref_crop AS crop, coalesce(p.ref_crops, []) AS more, count(o) AS seen
                        ORDER BY seen DESC, name LIMIT 40""", ds=dataset)
        out = []
        for r in rows:
            d = dict(r)
            d["crops"] = [c for c in [d["crop"], *d.pop("more")] if c and Path(c).exists()]
            out.append(d)
        return out


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
