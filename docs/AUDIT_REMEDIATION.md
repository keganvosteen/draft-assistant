# Desktop audit remediation — 0.7.4

This change integrates the current-roster work from PR #38 and repairs the
confirmed audit findings against 0.7.3. Existing source checkouts and saved
player boards are not replaced during installation.

| Area | Result |
| --- | --- |
| Ownership | Provider roster snapshots stay separate from draft history. Stable IDs and unambiguous provider aliases survive source failure/recovery, unmatched draft picks, and backup restoration. |
| Weekly context | Projection buckets carry their own season/week. Wrong-week or unknown-provenance buckets use an explicitly labeled fallback, including after a failed refresh. |
| Byes | Collectors use the requested season's schedule. Weekly candidates/incumbents and draft penalties only use verified current-season/team byes. Old unverified byes remain unknown until player data is refreshed. |
| Roster legality | Exact overlapping FLEX assignment is shared by valuation, needs, replacement demand and feasibility. Recommendations preserve a path to filling all mandatory slots when the remaining pool/picks permit it. Impossible rosters receive a visible warning. |
| Explanations | Immediate gain excludes ranking bonuses. Availability uses the next relevant own-pick horizon. |
| Credentials | Unsupported keystores use locked, profile-scoped memory instead of plaintext. Keychain accounts are namespaced by profile/provider; legacy shared accounts remain available to other profiles during migration. |
| Pasted input | Six slow regex families are replaced with linear parsing. Size, line, candidate and numeric limits produce HTTP 400 errors. |
| Browser refresh | Projection/scoring changes invalidate recommendations. Aborted responses cannot restore stale scores. |
| Packaging | Windows build failures stop immediately; cleanup checks target paths. Temporary package smoke tests run hidden. |

## Validation

- 575 Python tests passed on Windows/Python 3.14 with optional data dependencies.
- Python 3.12 core suite passed; optional tests also run in the 3.12 CI job.
- Projection quality, vendor integrity, Python compilation, JS/JSX syntax,
  league identity/restore, workspace recovery and recommendation-refresh checks passed.
- 486 small-roster fixtures independently agree between the Python and browser
  lineup/needs implementations. The engine's exhaustive assignment regression
  also covers 486 fixtures.
- Actual 2,209-player board, 24 simulations: median rollout wall time increased
  from 1.367s to 1.419s, approximately 4%.
- Windows and universal macOS installers built successfully and passed first-run
  package smoke tests in GitHub Actions. The macOS binary contains both Intel
  and Apple Silicon architectures.
- Copied-data upgrade from 0.7.3 to 0.7.4 preserved four leagues, picks,
  preferences, the 2,946-player board and readable Yahoo credentials. Six
  important data files stayed byte-identical across the version change. Moving
  the test copy first rebased its local board path under 0.7.3; other settings
  were unchanged.
- Packaged browser UI exercised opening a league, calculating recommendations,
  recording a pick, and scanning weekly waivers with a changed week.

Native Windows DPAPI and macOS Keychain smoke checks use isolated synthetic
credentials to verify profile isolation, deletion and legacy Keychain migration
in the installer workflow. Authenticated provider connections have not been
exercised against live accounts. Roster feasibility describes the current pool and remaining
picks; opponents may still take needed players. CodeQL and cross-platform CI
results are tracked on the pull request; no public release is published by this
change. An initial CodeQL rescan found one additional numbered-team-prefix
pattern; it was replaced with a character scan and added to scaling coverage.
