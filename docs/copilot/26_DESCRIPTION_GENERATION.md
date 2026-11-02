# 26 — YouTube description and publishing drafts (v1.6 normative)

## Ownership
Video Studio creates **editable publishing drafts**, not uploads. User reviews/approves them in the Metadata screen. A prewritten `publishing_source.description` is allowed but never required. An LLM is optional future enhancement, not a POC dependency.

## Source precedence
1. Approved per-output `publishing_metadata` override (stable compilation/Short ID).
2. Explicit album or track `publishing_source` title/description/tags.
3. Offline deterministic templates using album story/setting/genre, channel branding, track titles, and optional scene/creative metadata.
4. Minimal factual fallback from album and track titles.

Generated drafts MUST be stored separately from user overrides. Regeneration cannot overwrite approved edits. Display `generated`, `supplied`, `edited`, `approved` state and source. Editing a draft does not automatically approve it; provide explicit approval action and revision/fingerprint. Bulk editing must preserve per-output identities and revisions.

WU5 materializes the explicitly approved merge as `output/metadata/youtube_metadata.json`; that export is not a render report or upload ledger. WU3A may refresh only its independently owned `chapters.txt` and factual render results; it must not read, validate, migrate, modify, or generate any `youtube_metadata.json`. A future uploader alone owns `youtube_publish_state.json`. Legacy/root publishing drafts require an explicit later-workflow import with source provenance rather than in-place mutation.

## Compilation draft structure
- Title from explicit source or template.
- Short introductory paragraph from approved creative album story/theme (do not invent facts about a track or promise licensing rights).
- Chapter listing from actual FFprobe-derived track durations and finalized compilation order; recompute when order/audio changes, warn if user-edited chapters would become stale.
- Brand boilerplate, optional supplied links, hashtags; never invent a URL or assert copyright-free/royalty-free status.

## Short draft structure
Track title + optional scene/atmosphere; concise description; optional full-compilation link placeholder if not yet available. If `{{compilation_url}}` remains unresolved, flag as blocking **publish-ready export**, not necessarily local video rendering. Link validation should not require internet access.

## Validation and safety
- YouTube title max 100 Unicode characters, description max 5000 Unicode characters; use an explicit counting policy and test boundary behavior. Tag limits and any other platform-specific rules must be centralized in versioned validation config, not scattered across React components.
- Escape/encode special characters for JSON, CSV, filenames, subtitles, and descriptions; preserve Unicode and line breaks. Reject unresolved placeholders for publish-ready status. Detect duplicate titles as warning; empty required title as error.
- Never hallucinate release dates, artist credits, sample clearances, rights, links, quality ratings, or analysis findings.
- Review screen supports compilation + per-Short edit, batch grid, preview of text, validation status, and explicit approval. Render/export uses a frozen approved metadata snapshot.

## Tests
Supplied text vs template fallback; Unicode/emoji/quotes/newlines; 99/100/101-character titles; 4999/5000/5001-character descriptions; duplicate titles; placeholder blocking; reordered tracks and chapters; manual edit survives regeneration; Short A edit does not affect Short B; stable output ordering; CSV/JSON round-trip.
