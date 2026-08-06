# Shipping to the Mac App Store

Short version: **the App Store is not the way to get this to friends for
testing.** Use the `.dmg` from [DISTRIBUTION.md](DISTRIBUTION.md). The App Store
is worth pursuing only if the goal is public distribution to strangers, and it
is a separate project rather than a flag on the existing build.

This document is what that project would involve, and where it is likely to go
wrong, so the decision can be made with real numbers.

---

## What it costs before you start

| Requirement | Notes |
| --- | --- |
| Apple Developer Program | **$99/year**, and the account must be an individual or a registered legal entity |
| A Mac | Required to build, sign and upload. CI cannot do the App Store upload without one |
| Xcode + command line tools | For `productbuild`, `notarytool`, Transporter |
| Privacy policy at a public URL | Mandatory for any app that makes network calls — this one does |
| App Review | Days per submission, and each rejection restarts it |

Note that the same $99 also buys **Developer ID signing and notarization**,
which removes the Gatekeeper warning from the plain `.dmg`. That is a much
cheaper win than App Store review, and it is the recommended first step.

---

## The three real obstacles

These are specific to this app, and are the reason this is not a
weekend task.

### 1. PyInstaller bundles and App Sandbox fight each other

The direct-download build signs with these hardened-runtime exceptions
(see [`entitlements.plist`](../packaging/macos/entitlements.plist)):

- `com.apple.security.cs.allow-unsigned-executable-memory`
- `com.apple.security.cs.disable-library-validation`
- `com.apple.security.cs.allow-jit`

**None of those are permitted on the Mac App Store.** Library validation must
stay on, which means every bundled `.dylib` and `.so` has to be signed with the
same identity as the app — PyInstaller does not do this reliably, and CPython
extension modules are exactly the thing that trips it.

The App Store build also needs an entirely different entitlement set
([`entitlements-mas.plist`](../packaging/macos/entitlements-mas.plist)):
App Sandbox on, plus `network.server` (the app serves its UI from a
`127.0.0.1` HTTP server), `network.client` (Sleeper/ESPN/Yahoo imports) and
`files.user-selected.read-write` (the CSV import picker).

Under the sandbox, `~/Library/Application Support/DraftAssistant` is silently
redirected into a per-app container. That part is fine —
[`paths.py`](../draft_assistant/paths.py) already resolves it correctly — but it
does mean an App Store install cannot see data from a `.dmg` install.

**If you pursue this, do not use PyInstaller.** Use
[Briefcase](https://briefcase.readthedocs.io/), which supports macOS App Store
packaging as a first-class target, or `py2app`. Budget for rebuilding the
packaging layer; the application code in `draft_assistant/` carries over
unchanged, since it is stdlib-only.

### 2. Guideline 4.2 — "Minimum Functionality"

Apple rejects apps that are mainly a web view around a website. This app *looks*
like that from the outside: a native window pointing at a local server.

The defensible argument is that the Monte Carlo engine in
[`rollout.py`](../draft_assistant/rollout.py) does real local computation and
the app works fully offline — there is no website it is wrapping. That is a
genuine distinction and apps like this do get approved, but expect to have to
make the case, possibly more than once.

### 3. NFL data and third-party APIs

This is the risk most likely to be underestimated. The app ships a player board
built from NFL player names and projections, and imports from Sleeper, ESPN and
Yahoo.

App Review commonly asks for documentation showing you are authorized to use
third-party data and to integrate with those services. Guideline 5.2 covers
this. Review the terms of service for each source before submitting, and be
ready to explain the provenance of `data/projections.json`.

There is no way to pre-clear this — it comes up during review.

---

## If you decide to go ahead

Rough order of operations:

1. **Join the Apple Developer Program** ($99/yr) and, on the Mac, sign in to
   Xcode so the certificates sync.
2. **Ship the notarized `.dmg` first.** Same certificate purchase, no review
   queue, and it makes the app pleasant to install immediately. Use it to shake
   out real bugs with testers before spending review cycles.
3. **Register the bundle ID** `com.keganvosteen.draftassistant` in the Apple
   Developer portal. Change this in
   [`DraftAssistant.spec`](../packaging/DraftAssistant.spec) if you want a
   different one — it must match the portal exactly.
4. **Rebuild the packaging layer on Briefcase** targeting the App Store, using
   `entitlements-mas.plist`. This is the bulk of the work.
5. **Sign** the app with *3rd Party Mac Developer Application* and the installer
   package with *3rd Party Mac Developer Installer*, embedding the App Store
   provisioning profile.
6. **Build a `.pkg`** with `productbuild` and upload it via Transporter.
7. **Fill in App Store Connect**: screenshots, description, support URL, privacy
   policy URL, age rating, and the App Privacy questionnaire (declare the
   network calls to Sleeper/ESPN/Yahoo).
8. **Submit**, and expect at least one round of questions.

## TestFlight

If the actual goal is structured testing with more people than a few friends,
**TestFlight supports macOS apps** and is a better fit than the App Store. It
still requires the $99 account and the App Store build above, and external
testers still need a (lighter) review pass — but there is no public listing and
no marketing metadata to maintain.
