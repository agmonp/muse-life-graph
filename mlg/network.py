"""The people network: who belongs with whom, measured, filtered and laid out.

Raw co-appearance counts make a hairball: the owner (and anyone photographed a lot) is tied to
everyone. So, in order:

1. Tie strength, normalised for how often each person appears: shared pictures (+ half a point per
   shared event) over sqrt(n_a * n_b) - the cosine of their appearance vectors. Two people who are
   almost always photographed together score near 1 even if both are rare.
2. Backbone: the disparity filter (Serrano, Boguna & Vespignani, PNAS 2009) keeps a tie only if it
   carries more of a person's strength than a random split would (alpha < 0.05 for either end), and
   every person keeps their strongest tie. The owner is left out of the structure - they are in
   every picture by construction - and drawn at the centre, their ties shown on demand.
3. Circles: the owner's own groups from the Life Graph where they exist; everyone else is placed by
   Louvain community detection on the tie strengths. A circle with labelled members inherits their
   group when most of them share it; the rest are named by Muse Spark from the memories they share.
4. Bridges: betweenness centrality on the backbone (distance = 1 / strength) - the few people
   whose ties connect otherwise separate circles.
5. Layout: circles are islands placed by how strongly they connect, sized by their people; inside
   an island a weighted spring layout puts strong ties close; no two people overlap.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict

import networkx as nx
import numpy as np

from mlg import library
from mlg.config import CACHE

ALPHA = 0.05
NAMES = CACHE / "circle_names.json"
_CACHE: dict = {"key": None, "data": None}


def _ties(ms: list[dict]) -> dict[tuple[str, str], dict]:
    """Per pair: pictures together, events together, first and last year together."""
    ties: dict[tuple[str, str], dict] = defaultdict(lambda: {"pics": 0, "events": 0, "years": []})
    groups: dict[str, set] = defaultdict(set)
    for m in ms:
        ps = sorted(set(m["people"]))
        y = m["date"][:4] if m["date"] else None
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                t = ties[(ps[i], ps[j])]
                t["pics"] += 1
                if y:
                    t["years"].append(y)
        groups[library.memory_key(m)].update(ps)
    for key, ps in groups.items():
        ps = sorted(ps)
        y = key.split(":")[-1][:4] if key != "undated" else None
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                t = ties[(ps[i], ps[j])]
                t["events"] += 1
                if y and y.isdigit():
                    t["years"].append(y)
    return ties


def _backbone(g: nx.Graph) -> nx.Graph:
    keep = set()
    for n in g.nodes:
        edges = g.edges(n, data="w")
        k = len(edges)
        if not k:
            continue
        total = sum(w for _, _, w in edges)
        best = max(edges, key=lambda e: e[2])
        keep.add(frozenset(best[:2]))
        if k == 1:
            continue
        for a, b, w in edges:
            if (1 - w / total) ** (k - 1) < ALPHA:
                keep.add(frozenset((a, b)))
    bb = nx.Graph()
    bb.add_nodes_from(g.nodes(data=True))
    bb.add_edges_from((a, b, g.edges[a, b]) for a, b in (tuple(e) for e in keep))
    return bb


def _circle_names(circles: dict[int, list[str]], ms: list[dict], ppl: dict) -> dict[int, str]:
    """Muse Spark names unlabelled circles from what their people share (cached per membership)."""
    try:
        cache = json.loads(NAMES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    todo = {}
    for cid, members in circles.items():
        sig = hashlib.md5("|".join(sorted(members)).encode()).hexdigest()[:12]
        if sig not in cache:
            mems = Counter(library.memory_key(m) for m in ms if set(m["people"]) & set(members))
            titles = library._titles()
            todo[sig] = {"people": [ppl[p]["name"] for p in members][:12],
                         "albums": sorted({m["album"] for m in ms if m["album"] and set(m["people"]) & set(members)})[:8],
                         "memories": [titles.get(k, {}).get("title", k) for k, _ in mems.most_common(10)]}
        circles[cid] = (sig, members)
    if todo:
        try:
            from mlg.muse import chat
            ans = chat.ask([chat.text(json.dumps(todo, ensure_ascii=False))], system=(
                "Each key is a circle of people from someone's photo library, with the albums and memories they "
                "appear in. Name each circle in 2-4 words the way the owner would ('Army friends', 'Poker nights', "
                "'Tel Aviv flatmates', 'India trip 2015'). Only what the albums and memories support; if nothing "
                "is clear, 'Friends' plus the most common place or year."),
                schema={"type": "object", "additionalProperties": False, "required": ["circles"],
                        "properties": {"circles": {"type": "array", "items": {
                            "type": "object", "additionalProperties": False, "required": ["key", "name"],
                            "properties": {"key": {"type": "string"}, "name": {"type": "string"}}}}}},
                schema_name="circle_names", effort="low")
            for c in (ans.data or {}).get("circles", []):
                if c.get("key") in todo and c.get("name"):
                    cache[c["key"]] = c["name"].strip()[:40]
            NAMES.parent.mkdir(parents=True, exist_ok=True)
            NAMES.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:  # noqa: BLE001 - unnamed circles get a plain name
            print("circle names:", e)
    return {cid: cache.get(sig, f"Circle {i + 1}") for i, (cid, (sig, _)) in enumerate(circles.items())}


def _separate(pos: dict, rad: dict, gap: float, iters: int = 300, centre=None, bound=None) -> None:
    """Push overlapping discs apart (and back inside `bound` around `centre` when given)."""
    keys = list(pos)
    for _ in range(iters):
        moved = False
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = keys[i], keys[j]
                d = pos[b] - pos[a]
                dist = float(np.hypot(*d)) or 1e-6
                need = rad[a] + rad[b] + gap
                if dist < need:
                    push = (need - dist) / 2 * d / dist
                    pos[a] -= push
                    pos[b] += push
                    moved = True
        if centre is not None and bound:
            for k in keys:
                d = pos[k] - centre
                dist = float(np.hypot(*d))
                if dist > bound - rad[k]:
                    pos[k] = centre + d / dist * (bound - rad[k])
        if not moved:
            break


def build() -> dict:
    ms, ppl = library.data()
    key = library._CACHE["key"]
    if _CACHE["key"] == key and _CACHE["data"]:
        return _CACHE["data"]
    seen = Counter(pid for m in ms for pid in m["people"])
    people = [p for p in ppl if seen.get(p)]
    owner = next((p for p in people if ppl[p].get("owner")), None)
    ties = _ties(ms)
    g = nx.Graph()
    for p in people:
        if p != owner:
            g.add_node(p)
    for (a, b), t in ties.items():
        if owner in (a, b) or a not in g or b not in g:
            continue
        raw = t["pics"] + 0.5 * t["events"]
        g.add_edge(a, b, w=raw / math.sqrt((seen[a] + 1) * (seen[b] + 1)), pics=t["pics"], events=t["events"])
    bb = _backbone(g)

    # circles: the owner's own groups first, Louvain for the rest
    comms = nx.community.louvain_communities(g, weight="w", resolution=1.0, seed=7) if g.number_of_edges() else \
        [set(g.nodes)]
    comm_of = {p: i for i, c in enumerate(comms) for p in c}
    label: dict[str, str] = {}
    inferred: set[str] = set()
    for p in g.nodes:
        if ppl[p]["groups"]:
            label[p] = ppl[p]["groups"][0]
    unnamed: dict[int, list[str]] = defaultdict(list)
    for i, c in enumerate(comms):
        own = Counter(label[p] for p in c if p in label)
        top, n = own.most_common(1)[0] if own else (None, 0)
        for p in c:
            if p in label:
                continue
            if top and n >= 2 and n >= 0.5 * sum(own.values()):
                label[p] = top
                inferred.add(p)
            else:
                unnamed[i].append(p)
    names = _circle_names(dict(unnamed), ms, ppl) if unnamed else {}
    for cid, members in unnamed.items():
        for p in members:
            label[p] = names.get(cid, f"Circle {cid + 1}")
    # tiny circles of one person join the circle they are most tied to
    sizes = Counter(label.values())
    for p in g.nodes:
        if sizes[label[p]] == 1 and g.degree(p):
            best = max(g.edges(p, data="w"), key=lambda e: e[2])[1]
            sizes[label[p]] -= 1
            label[p] = label[best]
            sizes[label[p]] += 1

    # bridges: shortest paths along strong ties
    for a, b, d in bb.edges(data=True):
        d["dist"] = 1 / max(d["w"], 1e-6)
    btw = nx.betweenness_centrality(bb, weight="dist", normalized=True) if bb.number_of_edges() else {}

    # layout: islands for circles, springs inside them
    max_n = max(seen.values())
    rad = {p: 16 + 30 * math.sqrt(seen[p] / max_n) for p in people}
    circles = defaultdict(list)
    for p in g.nodes:
        circles[label[p]].append(p)
    cr = {c: 34 + 1.35 * math.sqrt(sum((rad[p] + 12) ** 2 for p in ps)) for c, ps in circles.items()}
    meta = nx.Graph()
    meta.add_nodes_from(circles)
    for a, b, d in g.edges(data=True):
        ca, cb = label[a], label[b]
        if ca != cb:
            meta.add_edge(ca, cb, w=meta.edges[ca, cb]["w"] + d["w"] if meta.has_edge(ca, cb) else d["w"])
    cpos = nx.spring_layout(meta, weight="w", seed=3, k=2.2 / math.sqrt(max(1, len(circles)))) if len(circles) > 1 \
        else {next(iter(circles)): np.zeros(2)}
    span = sum(cr.values()) / max(1, math.pi) * 1.2
    cpos = {c: np.array(v, dtype=float) * span for c, v in cpos.items()}
    own_r = (rad[owner] + 60) if owner else 0
    cpos["__owner__"] = np.zeros(2)
    crad = dict(cr, __owner__=own_r)
    _separate(cpos, crad, gap=50, iters=600)
    # compact: draw the islands in toward the owner until they touch, so no space is wasted
    for _ in range(60):
        for c in cpos:
            if c != "__owner__":
                cpos[c] = cpos["__owner__"] + (cpos[c] - cpos["__owner__"]) * 0.93
        _separate(cpos, crad, gap=46, iters=200)
    shift = cpos.pop("__owner__")
    pos = {}
    for c, ps in circles.items():
        centre = cpos[c] - shift
        if len(ps) == 1:
            pos[ps[0]] = centre.copy()
            continue
        sub = g.subgraph(ps)
        inner = nx.spring_layout(sub, weight="w", seed=5, k=1.4 / math.sqrt(len(ps)), iterations=200)
        arr = np.array(list(inner.values()))
        arr = arr - arr.mean(axis=0)
        # one far-out person must not squash everyone else into the middle: scale by the 80th percentile
        spread = float(np.percentile(np.hypot(arr[:, 0], arr[:, 1]), 80)) or 1.0
        scale = (cr[c] - 30) * 0.8 / spread
        mid = np.array(list(inner.values())).mean(axis=0)
        inner = {p: inner[p] - mid for p in inner}
        local = {p: centre + np.array(inner[p]) * scale for p in ps}
        _separate(local, rad, gap=10, iters=400, centre=centre, bound=cr[c])
        pos.update(local)
    if owner:
        pos[owner] = np.zeros(2)

    edges = [{"a": a, "b": b, "w": round(d["w"], 3), "pics": d["pics"], "events": d["events"],
              "inside": label[a] == label[b]} for a, b, d in bb.edges(data=True)]
    if owner:
        for (a, b), t in ties.items():
            if owner in (a, b) and a in pos and b in pos:
                o = b if a == owner else a
                raw = t["pics"] + 0.5 * t["events"]
                edges.append({"a": owner, "b": o, "w": round(raw / math.sqrt((seen[owner] + 1) * (seen[o] + 1)), 3),
                              "pics": t["pics"], "events": t["events"], "owner": True})
    circle_list = [{"name": c, "size": len(ps), "x": round(float(cpos[c][0] - shift[0]), 1),
                    "y": round(float(cpos[c][1] - shift[1]), 1), "r": round(cr[c], 1),
                    "own": any(not (p in inferred) and ppl[p]["groups"] and ppl[p]["groups"][0] == c for p in ps)}
                   for c, ps in circles.items()]
    bridges = sorted(((p, b) for p, b in btw.items() if b > 0), key=lambda t: -t[1])[:6]
    data = {
        "owner": owner,
        "nodes": [{"id": p, "name": ppl[p]["name"], "name_en": ppl[p].get("name_en"), "count": seen[p],
                   "x": round(float(pos[p][0]), 1), "y": round(float(pos[p][1]), 1), "r": round(rad[p], 1),
                   "circle": label.get(p, "me"), "inferred": p in inferred, "owner": p == owner,
                   "relation": ppl[p].get("relation"), "bridge": round(btw.get(p, 0.0), 3),
                   "has_ref": bool(ppl[p].get("crop"))} for p in people],
        "edges": edges, "circles": circle_list,
        "bridges": [{"id": p, "name": ppl[p]["name"], "score": round(b, 3),
                     "joins": sorted({label[n] for n in bb.neighbors(p)} - {label[p]})[:3]} for p, b in bridges],
        "stats": {"people": len(people), "ties": g.number_of_edges(), "backbone": bb.number_of_edges(),
                  "circles": len(circles),
                  "modularity": round(nx.community.modularity(g, comms, weight="w"), 3) if g.number_of_edges() else 0},
    }
    _CACHE.update(key=key, data=data)
    return data


def ties_of(pid: str) -> dict | None:
    """One person's ties, strongest first, with when they were together."""
    ms, ppl = library.data()
    if pid not in ppl:
        return None
    seen = Counter(p for m in ms for p in m["people"])
    out = []
    for (a, b), t in _ties(ms).items():
        if pid not in (a, b):
            continue
        o = b if a == pid else a
        if o not in ppl:
            continue
        ys = sorted(t["years"])
        out.append({"id": o, "name": ppl[o]["name"], "pics": t["pics"], "events": t["events"],
                    "strength": round((t["pics"] + 0.5 * t["events"]) / math.sqrt((seen[pid] + 1) * (seen[o] + 1)), 3),
                    "from": ys[0] if ys else None, "to": ys[-1] if ys else None})
    out.sort(key=lambda t: (-t["pics"], -t["events"]))
    net = build()
    node = next((n for n in net["nodes"] if n["id"] == pid), {})
    return {"id": pid, "name": ppl[pid]["name"], "count": seen.get(pid, 0), "circle": node.get("circle"),
            "bridge": node.get("bridge", 0), "ties": out}


def insights() -> dict:
    """What the network says that a list of photos does not."""
    net = build()
    ms, ppl = library.data()
    owner = net["owner"]
    if not owner:
        return {}
    mine = ties_of(owner)["ties"]
    years = sorted({m["date"][:4] for m in ms if m["date"][:4].isdigit()})
    last = int(years[-1]) if years else 0
    closest = [t for t in mine if t["pics"]][:6]
    fading = [t for t in mine if t["pics"] + t["events"] >= 6 and t["to"] and int(t["to"]) <= last - 6][:6]
    rising = [t for t in mine if t["pics"] + t["events"] >= 4 and t["from"] and int(t["from"]) >= last - 4][:6]
    return {"closest": closest, "fading": fading, "rising": rising, "bridges": net["bridges"], "stats": net["stats"]}
