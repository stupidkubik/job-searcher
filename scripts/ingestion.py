"""Pure normalization and classification helpers for ``jobs.py ingest``."""

try:  # Direct CLI execution places scripts/ on sys.path.
    from inbox import load_batch
except ModuleNotFoundError:  # Unit tests may import this module as scripts.ingestion.
    from scripts.inbox import load_batch


FRONTEND_SIGNALS = (
    "frontend", "front end", "react", "ui engineer", "ui developer",
    "user interface", "web developer", "web engineer", "creative developer",
    "design engineer", "product engineer",
)
TOO_SENIOR_SIGNALS = (
    "senior", " sr ", "lead", "staff", "principal", "manager", "director",
    "architect", "head of",
)
EXPLICIT_HARD_FILTER_REASONS = {
    "geo_restriction", "work_authorization", "seniority_too_high",
    "seniority_too_low", "stack_mismatch", "role_not_frontend",
    "salary_too_low", "company_not_interesting",
}


def normalize_record(record):
    """Map the raw contract to the data accepted by the canonical write path."""
    return {
        "company": record["company"].strip(),
        "role": record["role"].strip(),
        "source": record["source"].strip(),
        "source_url": record["source_url"].strip(),
        "source_job_id": record["source_job_id"].strip(),
        # Transient duplicate candidate only; it is neither a canonical field
        # nor a source reference until first-party verification proves it.
        "candidate_application_url": record["application_url"].strip(),
        # `application_url` is only an aggregator candidate. The canonical
        # original_url is populated by jobs.py verify after first-party proof.
        "original_url": "",
        "location": record["raw_location"].strip(),
        "posted_at": record["posted_at"].strip(),
        "found_at": record["found_at"].strip(),
        "application_status": "not_started",
        "listing_status": "unknown",
        "first_party_verified": "unknown",
        "apply_verified": "unknown",
        "remote_policy": "Unclear",
    }


def relevance_or_hard_filter(record, normalized_role):
    """Return ``(outcome, reason)`` before any duplicate matching."""
    role = normalized_role
    if not any(signal in role for signal in FRONTEND_SIGNALS):
        return "noise", "role_not_frontend"
    payload = record.get("payload") or {}
    explicit_reason = payload.get("hard_filter_reason")
    if explicit_reason in EXPLICIT_HARD_FILTER_REASONS:
        return "skipped", explicit_reason
    padded_role = f" {role} "
    if any(signal in padded_role for signal in TOO_SENIOR_SIGNALS):
        return "skipped", "seniority_too_high"
    return None, None


def deterministic_duplicate(
    values,
    job_rows,
    source_rows,
    norm,
    norm_url,
    *,
    shared_source_url_sources=(),
):
    """Match only safe duplicates in the prescribed order."""
    for reference in source_rows:
        if (
            reference["source"] == values["source"]
            and reference["source_job_id"]
            and reference["source_job_id"] == values["source_job_id"]
        ):
            return reference["job_id"], "source_job_id"

    candidate_original_url = norm_url(values.get("candidate_application_url") or values["original_url"])
    for job in job_rows:
        if (
            job["decision_reason"] != "duplicate_listing"
            and job["original_url"]
            and norm_url(job["original_url"]) == candidate_original_url
        ):
            return job["id"], "canonical_original_url"

    candidate_source_url = norm_url(values["source_url"])
    for reference in source_rows:
        if reference["source_url"] and norm_url(reference["source_url"]) == candidate_source_url:
            if (
                values["source"] in shared_source_url_sources
                and reference["source"] == values["source"]
                and values["source_job_id"]
                and reference["source_job_id"]
                and reference["source_job_id"] != values["source_job_id"]
            ):
                # One Telegram message may advertise several genuinely distinct
                # vacancies.  Their per-vacancy source IDs remain authoritative;
                # the shared post URL is discovery provenance, not a duplicate key.
                continue
            return reference["job_id"], "source_url"

    candidate_key = (norm(values["company"]), norm(values["role"]), norm(values["location"]))
    for job in job_rows:
        if job["decision_reason"] == "duplicate_listing":
            continue
        job_key = (norm(job["company"]), norm(job["role"]), norm(job["location"]))
        if candidate_key == job_key:
            return job["id"], "company_role_location"
    return None


def fuzzy_candidates(values, job_rows, without_noise, similarity, company_noise, role_noise):
    """Return candidates for a human decision; never treat them as a duplicate."""
    candidates = []
    company = without_noise(values["company"], company_noise)
    role = without_noise(values["role"], role_noise)
    for job in job_rows:
        if job["decision_reason"] == "duplicate_listing":
            continue
        company_score = similarity(company, without_noise(job["company"], company_noise))
        role_score = similarity(role, without_noise(job["role"], role_noise))
        if company_score >= 0.85 and role_score >= 0.75:
            candidates.append({
                "id": job["id"],
                "company": job["company"],
                "role": job["role"],
                "company_similarity": round(company_score, 4),
                "role_similarity": round(role_score, 4),
            })
    return candidates
