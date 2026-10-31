**What differs.** On search, Spark Open reads people more literally than the API: "the kids" became the owner
plus nine children, "grandma" became the two grandmothers, "we" in a Hebrew question became the owner, and
"Boaz" matched both people of that name. That is arguably closer to the question, though it narrows results.
One real miss: it dropped the year from "Who came to the wedding in 2017?". Search words overlap only a
quarter of the time because both models invent their own synonyms; the people and years drive the filters.
On the Picture Checker the two models nearly always make the same keep/drop call and agree on every
narration verdict; they frame a different person in about a third of the pictures (usually two people of
equal weight in the shot).

**Latency and cost.** Text calls are about as fast as the API (search median 3.7 s vs 3.8 s). Calls with
pictures are slower and much less predictable on Baseten: median 15.4 s vs 6.1 s, and four of 15 took over
3 minutes (the longest 314 s). The list price per token is the same, and the 30 calls cost the same within
3%. That is why the Picture Checker runs scenes in parallel and falls back to the API on an error, and why
perception of the whole library stays on the API.
