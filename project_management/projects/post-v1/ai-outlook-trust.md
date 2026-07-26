# Post-V1: AI Outlook Trust (the full build)

**Status:** post-V1 design note. **The V1 slice ships in `projects/v1/` (P4)** — populate the bull/bear/
situation grades live for 2026, make them reproducible (news-hash cache, temperature 0, prompt version),
anchor them to the band, and gate them by confidence. **This doc is the remainder** — the deeper trust build
beyond what P4 ships. No V1 execution lives here.

## The insight (why this is two reads in one)

The §2 bull/bear/situation grades are "an AI read disguised as a number." But the read splits along a fault
line:

- **Bull / bear have a deterministic core.** `ros_player_band` already produces `ros_bull`/`ros_bear` as
  calibrated numbers (`ros_center ± BULL_Z·ros_sigma`, anchored to preseason ADP). Backtestable, in the
  measurement corpus.
- **Situation is irreducibly AI.** Role security, depth-chart moves, committee risk — from forward-only
  beat-writer RSS. There is no historical feed to backtest it against, ever. It is the **least-verifiable
  output in the product** and the most visible, which is why it must be the most conservative about what it
  asserts.

The design move: make the **band carry maximum load**, so the AI is a bounded garnish, not the load-bearing
signal.

## The remainder beyond P4

- **First-class anchor-divergence *analysis*.** P4 logs divergence (AI grade vs. band-implied grade); the
  post-V1 work is *using* it — systematic divergence is either a prompt bug or a sign the band is missing
  something real, and both are leads worth mining across the corpus.
- **Measure the band's standalone load (corpus study).** How well does the deterministic band *alone* sort
  realized ROS outcomes? If it sorts well, the AI is low-risk; if the band is weak and the grade is doing the
  real work, that's where trust risk concentrates. Answerable offline, and it reframes "can I trust the AI?"
  into "how much am I even leaning on it?"
- **Champion/challenger on the prompt** (loop L5) — worth it for a per-player read only once volume justifies
  the cost.
- **The confidence-honesty scorer slice for the grades** — error stratified by the read's own `confidence`,
  with suppression when it isn't monotone (the Week-8 pilot gate, → appendix: pilot-2026).

## Open questions

- How much may the AI move the band — a hard clamp on `|grade − band-implied|`, or free-but-logged?
- Should bull/bear (a calibrated number) and situation (a confidence-flagged AI read) be presented as
  **visibly different trust classes**?
- Is champion/challenger worth the per-player cost?

## Scope boundary

This never gets a full historical answer key (the news half is forward-only) — respect that as a property,
not a bug. Keep the AI conservative until it has earned a live season.
