# 45 — WU4 flexible Import and implementation realignment

**Status (2026-10-29): APPROVED PRODUCT ARCHITECTURE.** This document establishes WU4's unified ingestion direction and phase ordering. It is not an executable schema or evidence of implementation. Doc 46 contains the approved technical contracts; Phase 2R.1 still requires separate implementation authorization. Existing WU3 render generations, verified artifacts, security boundaries and acceptance records remain governed by Docs 31 and 38–40.

## 1. Unified project ingestion

- WU4 has one standard ingestion system, not user-visible “legacy” and “flexible” modes.
- The user selects a project directory beneath a server-configured trusted root. That canonical directory is the project/security boundary.
- Registration requires a safe directory boundary, not a specific internal layout, manifest, audio file, artwork file, channel name or album name.
- Import recursively discovers supported audio, image and video candidates while preserving portable project-relative paths. Flat and nested layouts are valid.
- Discovery is bounded, cancellable, non-destructive and reparse/symlink/junction safe. Source files are never renamed, rewritten, relocated or deleted.
- Unreadable or unsupported files produce scoped diagnostics. A safe project is not rejected merely because it is empty, lacks artwork, or contains aesthetically unsuitable media.
- Import inventories assets; it does not infer album identity, track ordering, A/B pairings, artwork roles, layers or artistic suitability.

## 2. Optional manifest enrichment

A recognized manifest may enrich a registered project with approved album/track identity, ordering, renderer configuration and provenance. It does not create a separate ingestion mode and is never rewritten automatically. Existing WU3 manifests remain strict render contracts; registration of an arbitrary directory does not make that directory renderable.

Unsupported, absent or invalid manifests are reported independently from project registration. A manifest-backed project may continue using the existing normalized album and editor services through a compatibility adapter while Phase 2R contracts are introduced.

## 3. Workflow and composition ownership

1. **Import / Project Library:** register the boundary, inventory files, display counts/diagnostics/capabilities, and rescan.
2. **Project handoff:** open all present, non-excluded assets in Review using the project identity plus observed inventory/preference revisions. Import does not choose output workflows or order tracks.
3. **Review / Creation:** create album containers and ordered assignments, enable independent Single/Short drafts, browse reusable project assets, assign roles and edit supported settings.
4. **Render:** validate the selected composition against an implemented authoritative renderer. Unsupported choices remain drafts and must not be described as renderable.

Background selection belongs downstream from Import. A solid color requires no imported artwork. Static image selection may use approved project assets. Layered/parallax, procedural generation and imported-video composition remain separately gated future capabilities.

## 4. Production-intended frontend

Phase 2A is retained as the beginning of the production React application, not as a disposable prototype. Its shell, Import/Review layout, WaveSurfer integration, approximate preview and tests should be evolved rather than duplicated. Temporary demonstration adapters must be explicit, isolated and visibly labeled. Failure of a real backend request must remain an error; it must not silently become a successful demo workspace.

Import is the first fully functional vertical slice. Shared asset browsers, audition controls, thumbnails and capability indicators should be reusable by Review and later workflows.

## 5. Capability truthfulness

The application must distinguish:

- discovered;
- successfully probed;
- safely streamable by the server;
- auditionable by the active browser;
- thumbnailable or inspectable;
- previewable by an implemented backend;
- renderable by an approved authoritative profile.

One capability never implies another. In particular, discovery of MP4 does not authorize video composition, and FFmpeg decode support does not prove browser playback support.

## 6. Approved sequencing

1. **Phase 2A:** preserve the existing interactive frontend candidate.
2. **Phase 2R.0:** reconcile documentation and propose technical contracts.
3. **Phase 2R.1:** registry migration, bounded recursive inventory, optional manifest enrichment and secure rescanning.
4. **Phase 2R.2:** secure media resources, auditioning, thumbnails and capability reporting.
5. **Phase 2R.3:** functional Import UI integration and truthful project-level handoff.
6. **Phase 2B:** production Review integration and revisioned composition/editor persistence.
7. **Phase 3:** authoritative motion-preview HTTP integration.
8. **Phase 4:** migration, regression, security, accessibility and acceptance hardening.

Each implementation phase requires approval and executable evidence. Phase 2R.0 did not authorize Phase 2R.1; a later consolidated Functional Import authorization satisfied the Phase 2R.1–2R.3 implementation gates. Their uncommitted candidates remain acceptance-pending.

The subsequent consolidated WU4 authorization also approved the smallest durable Review/Creation foundation needed for project-level handoff, exclusions and output planning. It supersedes the earlier requirement that Phase 2R.3 choose a workflow and ordered audio list in Import. Import now hands the project and relevant revisions to Review; Creation owns album ordering and Single/Short instances. This does not authorize Phase 3 motion-preview HTTP or any WU5–WU8 capability.

## 7. Preserved boundaries

- WU3 strict source manifests, immutable requests, renderer identities, output namespaces, verification and acceptance remain unchanged.
- WU4 owns Import and Review, not publishing metadata or batch rendering.
- WU5 owns publishing-metadata generation/review.
- WU6 owns authoritative render planning, batch operations and final Short rendering.
- WU7 owns advanced layered/title-aware/parallax composition and procedural visual work unless separately reassigned.
- WU8 owns imported video sources, clip playlists and their rendering semantics.

## 8. Explicit deferrals

Phase 2R does not include durable multiple-production-plan management or duplication, portable project packaging, automatic A/B matching, AI suitability analysis, filesystem watching, advanced layered/parallax rendering, procedural/fractal rendering, imported-MP4 composition, video clip playlists, metadata generation, batch rendering, upload, server autosave or durable edit history.

## 9. Acceptance intent

- Safe empty, manifestless, audio-only, image-only and manifest-backed directories can be registered under approved trusted roots once Phase 2R.1 is implemented.
- Recursive discovery never escapes the project boundary and commits only complete inventory revisions.
- Existing Phase 1 project IDs and editor relationships survive the approved migration.
- Rescan preserves user work and represents missing or changed referenced assets without silently substituting files.
- Import uses real backend services without hidden demo fallback once Phase 2R.3 is accepted.
- Capability labels accurately match implemented browser, preview and renderer support.
- Existing manifest-backed WU3 rendering and artifacts remain unchanged.

