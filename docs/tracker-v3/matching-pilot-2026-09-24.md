# Lightweight matching pilot — 2026-09-24

Status: retrospective pilot complete; no canonical job, score, status, or
application card was changed.

## Question and boundary

Can this single-user tracker explain existing match decisions without stable
profile evidence IDs, a new match artifact, or an extra write step? This pilot
reviews eight existing records. It does not re-evaluate vacancies, verify live
listings, infer new candidate facts, or change historical decisions.

The normal active index does not contain archived jobs or every archived
`match_score`. For this audit only, the eight selected rows were read by ID
from `data/jobs.csv`; the rest of the CSV was not used for analysis. The
profile's four-row evidence table and selected application cards were read to
understand the existing format; the full profile was not needed.

## Sample

The sample covers applied, rejected, reviewing, skipped and closed records,
with both detailed and mostly empty cards. `match_score` is the stored agent
assessment, not an outcome or a new score from this pilot.

| Job | Stored state / score | Can the existing record explain the decision? | Observation |
|---|---|---|---|
| `job-0022` Canonical | `not_started`, `other`; 8.5 | Yes, card plus current notes | Strong frontend overlap coexists with a later user decision against the computer-science/theory demands. A high score does not imply `apply`. |
| `job-0025` Game Gears | `not_started`, `closed`; 8.5 | Yes | The card explains the domain fit; the canonical closure reason prevents applying. Listing availability is separate from match. |
| `job-0032` MixRank | `applied`; 8 | Yes | The card records the frontend route and Python/PostgreSQL/Linux gaps, plus an explicit recommendation. |
| `job-0052` Storyteller | `applied`; 7.5 | Yes, card plus notes | The evidence and the non-frontend career-direction tradeoff are present. The card itself does not reflect the later submission. |
| `job-0056` Nortal | `rejected`; 8.2 | Partly, in notes | The card is an empty template; notes preserve fit and gaps. Rejection is an application outcome, not a revised match score. |
| `job-0278` kolum | `applied`; 8 | Partly, in notes | The card is an empty template; notes preserve fit and backend stretch, while eligible remote countries remain unspecified. |
| `job-0394` Umbrel | `applied`; 5.5 | No | The card is an empty template and notes record only the confirmed prior submission. The reason for 5.5 cannot be recovered from these fields. |
| `job-0449` Aside | `reviewing`; 6.5 | Partly, in notes | The card is an empty template; notes capture design-versus-frontend fit and unresolved Serbia eligibility. |

Four cards contain substantive requirements/evidence/risk analysis; four are
mostly the generated template. Seven of eight decisions have at least a
human-readable explanation across the card and current notes, but only four
have substantive analysis in the card itself. `job-0394` shows a real
information loss: the stored number has no preserved rationale in the reviewed
fields. These counts describe this deliberately varied sample, not the full
458-job dataset.

## Smallest useful trial format

For a **new full review only**, try a short summary in the existing application
card or existing one-line `notes`, using information already checked during
screening:

1. **Score and reason:** the agent's 1–10 score, if assigned, and one sentence
   explaining the strongest match.
2. **Gap or blocker:** the decisive gap, hard blocker, or explicit `unknown`;
   do not hide eligibility uncertainty inside the score.
3. **Decision:** apply, review, or skip and why. Keep listing closure and actual
   application lifecycle separate from match.

`applications/_TEMPLATE.md` now offers these three lines as the pilot format;
its detailed evidence table is optional when the short conclusion is enough.

Do not add this step for a discovery-stage hard blocker handled by `screen`.
Do not backfill historical cards from memory. The canonical CSV, event ledger,
and existing write path keep their current authority; prose cannot set
`applied` or claim a first-party verification.

## Result and next check

The pilot supports testing this three-part summary on a few future full
reviews before adding evidence IDs or a versioned match schema. Q-008 and D-005
remain open for the full Phase 3 proposal. A prospective check should ask
whether the summary was enough to explain a changed recommendation or a
disputed score; only a concrete failure should trigger a larger design.

Targeted reads are sufficient for this pilot: the eight cards total 17,093
bytes, with the largest at 5,331 bytes. No new bootstrap index is indicated by
this sample; Q-012 still requires measurement if new artifacts are introduced.
