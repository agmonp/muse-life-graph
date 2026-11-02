# Copywriter: blind test on 8 real films

The Copywriter (Muse Wonder) rewrote each film's narration as one host voice; Muse Spark, a different model, read both narration sets labelled only A and B, with every scene's evidence, and picked the better film narration. Each film was judged in both orders. Script: `scripts/eval_copywriter.py`.

- **Rewritten lines preferred in 16 of 16 viewings** (original 0, no preference 0).
- Judge flagged an unsupported fact: rewritten 0 times, original 0 times (out of 16 viewings each).
- Lines the code guard sent back to the original (too long for the scene, or naming something the scene's pictures don't show): 1.

| Film | Tone asked | Style chosen | Lines changed | Blind (both orders) |
|---|---|---|---|---|
| Agmon & Family | warm and a little funny | playful | 6 of 6 | new / new |
| Happy Birthday Taya! | warm and joyful | nostalgic | 4 of 4 | new / new |
| My 2026 | warm and reflective | nostalgic | 4 of 4 | new / new |
| Happy Birthday, Boaz! | warm and a little funny | playful | 6 of 6 | new / new |
| Taya Growing Up | tender then joyful and funny | nostalgic | 4 of 4 | new / new |
| Tamar & Agmon | warm and intimate | nostalgic | 3 of 4 | new / new |
| Taya Growing Up | tender then joyful and funny | nostalgic | 4 of 4 | new / new |
| Happy Birthday, Adam! | warm and a little funny | playful | 5 of 5 | new / new |

## Examples

**Agmon & Family** (playful)

- before: Agmon and family, at home together today.  
  after: This is Agmon — and his favourite crowd, at home.
- before: Childhood album: boy at ruins, making playful faces.  
  after: It started at ancient ruins in 1978 — tongue out, face pulled, already performing.
- before: Grandparents gathered together at home.  
  after: At home in 2003, Hinda held court — singing, reading, and bags everywhere.
- before: Sushi at home, waterfalls far away, wheat close by.  
  after: Sushi at home, a waterfall in 2009, then wheat fields — children happily hitched along.
- before: Under the chuppah, then a first hospital selfie.  
  after: Agmon and Tamar under the chuppah in 2011 — then a newborn, and a hospital selfie.
- before: Everyone together at home, still around one table.  
  after: From ruins to this table — Agmon's favourite crowd just keeps getting bigger.

**Happy Birthday Taya!** (nostalgic)

- before: Happy birthday, Taya — today we celebrate you.  
  after: Happy birthday, Taya — today, home is full of you.
- before: It began with this tiny, smiling beginning.  
  after: It started small — pink trim, a purple pacifier, that smile.
- before: Surrounded, held, and growing all along.  
  after: On a striped blanket, in the garden, with a red balloon — always held.
- before: With love, always — happy birthday, Taya.  
  after: Home is still full of you, Taya — happy birthday, with love.

**My 2026** (nostalgic)

- before: January begins close, at home.  
  after: 2026 starts close — Agmon, a baby in his lap, everyone nearby.
- before: February: remembering, then gathering again.  
  after: February begins at the cemetery, then gathers again around lunch.
- before: Late April, dressed up around the table.  
  after: Late April puts on crowns — gold on the table, props in hand.
- before: And still, all of us at the table.  
  after: Still close, still home — all of us at the table.

**Happy Birthday, Boaz!** (playful)

- before: Happy birthday, Boaz — straw hat, sunshine, and that grin.  
  after: Happy birthday, Boaz — straw hat, sunshine, and that grin we cannot resist.
- before: First, a leap into the pool.  
  after: It started with a pool leap in 1985 — some habits never dry off.
- before: With friends at night and at home, arms around shoulders.  
  after: Friends, late nights, arms around shoulders — Boaz has always collected people beautifully.
- before: Reading together, then sunshine in the garden.  
  after: Quiet stories on the sofa, a toddler in the sun — that is his soft spot.
- before: Sparklers over dessert — make a wish, Boaz.  
  after: Sparklers over dessert, twice the glow — go on, Boaz, make that wish.
- before: Everyone together on the garden swing and indoors.  
  after: Everyone squeezed together, dogs and all — still grinning, still so loved, Boaz.

