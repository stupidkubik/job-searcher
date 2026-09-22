# Tracker v3 risk register

Статус: active. Review at every phase gate.

Probability/impact: low, medium, high. `Owner` обозначает responsible surface,
не конкретного человека.

| ID | Risk | Probability | Impact | Trigger/indicator | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|---|
| R-001 | Long-lived v3 branch diverges from frequently changing `main` canonical data | high | high | branch behind main; conflicts in CSV/generated views | code on fixtures; periodic merge checkpoints; no production CSV edits before cutover; fresh-main rehearsal | integration | active |
| R-002 | Event ledger and snapshot diverge during dual-write | medium | critical | validator finds different status/stage/dates | one transaction service; fault injection; no independent writers; consistency gate | write path | active |
| R-003 | Correction mutates or obscures historical events | medium | high | old event disappears or order changes after correction | append-only supersession; loop validation; render both fact and effective projection | event model | active |
| R-004 | Historical backfill invents chronology | high | high | midnight timestamps or inferred rounds appear as exact facts | precision field; migration source; no notes parsing; explicit unknown | migration | active |
| R-005 | Retry creates duplicate events | medium | high | same connector/user action produces two events | stable event/operation ID; uniqueness check; idempotency tests | event model | active |
| R-006 | New event command bypasses existing confirmation policy | medium | critical | applied/interview/offer from unconfirmed adapter input | contract allowlist; confirmed_by_user gate; negative tests; changed-path enforcement | connector | active |
| R-007 | Packet manifest points to changed files | high | high | hash mismatch after CV edit | raw-byte SHA-256; immutable packet version; fail closed; clear stale report | packet | active |
| R-008 | Packet/log leaks personal data or secrets | medium | high | CI/result contains document content, token or email body | paths/hashes only in machine result; redaction; local secret storage; fixtures synthetic | privacy | active |
| R-009 | Profile evidence links break on Markdown editing | high | high | analyses contain unresolved evidence IDs | stable explicit IDs or validated sidecar; deletion/rename semantics; referential tests | matching | active |
| R-010 | LLM variability changes score/recommendation | high | high | same inputs produce different numeric score | LLM extracts only; deterministic arithmetic/caps; versioned artifact; golden corpus | matching | active |
| R-011 | Source silence is interpreted as vacancy closure | medium | high | sweep absence changes listing status | separate health taxonomy; invariant test; no write authority in discovery | source health | active |
| R-012 | Inbox classifier advances wrong job/stage | high | critical | ambiguous email promoted automatically | proposal-only; deterministic-first; evidence preview; human review; fixtures | inbox | deferred |
| R-013 | Mail credentials/raw content enter Git or logs | medium | critical | token/session/email text in checkout/artifact | local protected dir; allowlist; redaction; permission audit; no provider exception text | inbox/privacy | deferred |
| R-014 | Event analytics double-counts corrected or migrated history | high | medium | funnel totals exceed applications or durations use date-only events | conservation tests; precision-aware metrics; supersession-aware projection | analytics | deferred |
| R-015 | Repository/bootstrap weight grows sharply | high | medium | normal agent boot reads event/packet corpus | compact indexes; targeted commands; measure bytes/tokens every phase | ergonomics | active |
| R-016 | AGPL implementation details contaminate project code | low | high | copied source/pattern too close to AGPL repo | use concepts/contracts only; original implementation; record provenance; review license | legal | active |
| R-017 | Scope expands into SPA/DB/browser before core contracts stabilize | high | high | new runtime/dependency before Gate 2 | D-008; phase gates; explicit new decision required | scope | active |
| R-018 | Timezone/date precision changes historical meaning | medium | high | naive timestamps or UTC date shifts | aware instants; Europe/Belgrade business dates; precision field; boundary tests | temporal | active |
| R-019 | Generated views/indexes become stale after new canonical layer | medium | high | CI mismatch or agent sees old projection | deterministic renderer; `--check`; workflow matrix update | projections | active |
| R-020 | Rollback reverts newer job operations together with migration | medium | critical | migration commit mixed with canonical operations | isolated cutover commit from fresh main; no unrelated writes; tested revert path | migration | active |

## Phase-gate review checklist

At each gate:

1. Re-evaluate probability/impact for active risks.
2. Add newly observed failure modes from tests/issues.
3. Link every critical risk to at least one verification row.
4. Confirm deferred risks did not enter current scope indirectly.
5. Record material changes in `work-log.md` and decisions when needed.

## New risk template

```text
| R-NNN | failure/outcome | probability | impact | measurable trigger |
  concrete mitigation | responsible surface | status |
```
