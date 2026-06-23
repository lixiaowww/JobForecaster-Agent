# Contributing to forecaster-agent

Thank you for contributing.  This document explains the engineering standards
the project holds itself to, and why they exist.

---

## Core principle: every module earns its place on the scoreboard

No component is assumed to add value.  Everything that feeds into a forecast —
the evolution prior, crowd contributions, signal sources — is tracked through
the Brier scoreboard.  If it doesn't improve calibration over time, it gets
down-weighted or removed.  Please keep this discipline when proposing additions.

---

## Engineering standards (the harness rules)

These are not style preferences.  They are what makes the system self-correcting.

### 1. Nondeterminism lives behind interfaces
The LLM judge, embedder, and any future external service must be hidden behind
a Protocol interface with a deterministic stub backend.  The test harness runs
entirely offline (no API key, no network).  If your code can't be tested offline
via the stub, the seam is in the wrong place.

### 2. The scoring core is pure functions
`js_divergence`, `aggregate`, `novelty`, `extract_conditional_rules` — these must
remain pure (no hidden state, no randomness without an explicit seed).  Tests
verify mathematical properties, not just "doesn't crash".

### 3. Every test is a behavioural specification
Tests must exercise the intended failure mode:
- Wrong: `assert result is not None`
- Right: `assert d.reason == "redundant"` (the echo was rejected *because* it was
  low-entropy, not for any other reason)

Add a test for every new gate decision or model behaviour.

### 4. Thresholds are configuration, not magic numbers
`tau_soundness`, `tau_novelty`, `k`, `threshold_percentile` live in `GateConfig`
and `config.yaml`.  Never hardcode a threshold inside a function.

### 5. Run the full suite before opening a PR
```bash
python -m pytest tests/          # must be 0 failures, 0 warnings
```

---

## Adding historical cases to the evolution agent

The case library (`evolution.py`, `CASE_LIBRARY`) is the foundation of the
job evolution prior.  Contribution rules:

- **Every numeric figure needs a citable source** in the `sources` list.
  Acceptable: peer-reviewed papers, BLS/OECD/Eurostat data, books with page
  numbers.  Not acceptable: news articles without underlying data, LLM-generated
  "facts", personal estimates presented as data.
- All 8 variables must be in range (0-1 except `diffusion_years`).
- The case must have a clear displaced occupation and a measurable outcome
  (`net_job_multiplier`, `lag_years`).
- Run `python -m pytest tests/test_evolution.py` after adding — the integrity test will catch
  missing sources and out-of-range values.

We need more non-Western cases (Japan, South Korea, India, Brazil).
We need more cases with `net_job_multiplier < 1` — the library must not
systematically over-represent the success stories.

---

## Crowd contributions

If you are adding a UI or API endpoint for human crowd forecasts, keep this rule:
**contributions must be submitted in `Prediction` schema format (falsifiable,
dated, confidence-scored, with evidence URLs) before the contributor sees the
agent's own forecast or the current aggregate.**  Without that sequencing, you
are collecting anchored opinions, not independent signals.

---

## The publishing guardrail (non-negotiable)

`require_review: true` is the default and must remain so in all example configs
and documentation.  Any PR that flips it to `false` in a default config will be
rejected.  The README must always show the review gate as the recommended path.

Auto-publishing speculative economic forecasts at scale is a reputational and
potentially legal risk.  The gate exists to protect contributors and users alike.

---

## What good PRs look like

- A new signal source → new class implementing the `Source` protocol + offline
  test with a fixture feed.
- A new publishing backend → new class implementing `.publish()` + integration
  test.
- A new historical case → added to `CASE_LIBRARY` with sources + passes
  `test_case_library_integrity`.
- A bug fix → the test that would have caught the bug, then the fix.

---

## What we will not merge

- Components that bypass the Brier scoreboard (they become unaccountable).
- Tests that require a network connection or API key.
- Magic-number thresholds hardcoded inside functions.
- Cases in the evolution library without citable sources.
- Anything that makes `require_review: false` the default.
