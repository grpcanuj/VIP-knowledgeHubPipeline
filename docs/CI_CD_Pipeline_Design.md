# Integration Knowledge Hub — CI/CD Pipeline Design

How a vendor interface document dropped into SharePoint becomes a validated glossary, OpenAPI specs and a deployed Knowledge Hub UI, automatically, using GitHub Actions and a single virtual host machine (VM) serving UAT and Dev on separate ports.

| | |
|---|---|
| Audience | Architects, DevOps, integration reviewers, UAT owners |
| Companion documents | `Pipeline_Run_Guide_1.docx` (manual run order), `Interface_Onboarding_Methodology.md` (stage definitions) |
| Platform | GitHub Actions, SharePoint Online (Microsoft Graph), one Linux VM running nginx |

---

## 1. Purpose and scope

Today the pipeline is run by hand: someone copies a vendor Word document into `source_docs/`, runs nine commands in order, promotes drafts, and rebuilds the UI. This design automates that end to end while keeping the one step that needs judgement — **Stage 2 review** — as an explicit, auditable human gate.

**In scope**
- Detecting a new or revised document in SharePoint and fetching it.
- Running extract and lint, and presenting the results for human review.
- Running validate, compile, OpenAPI generation, reports and the UI build after review.
- Deploying to Dev (port 8081) and UAT (port 8080) on one VM, with approval, health check and rollback.
- Publishing reports and OpenAPI files back to SharePoint for non-technical stakeholders.

**Out of scope:** changes to the extraction/lint rules themselves, UI feature work, production (non-UAT) hosting.

## 2. Key facts about the system being automated

These facts drive every design decision below.

1. **There is no long-running backend.** The "Python backend" is a set of batch scripts. The output is a static React site plus generated files. Deployment is therefore copying static files, not running a service.
2. **YAML is the source of truth.** `domains/*/{fields,interfaces,flows}.yaml`, validated against `schemas/*.json`. The UI only reads the file that `compile_knowledge_hub.py` emits (`FIELDS`, `INTERFACES`, `FLOWS`, `REQUIREMENTS`), so the UI code never changes per interface.
3. **Order matters.** The real order is: extract → lint → manual review/promote → validate → compile → OpenAPI → run report → run report HTML → findings tracker (see the Run Guide). OpenAPI must run after promote, because it reads the promoted `interfaces.yaml`.
4. **Each interface needs three inputs the document alone does not give:** interface id (e.g. `CV07_02`), interface name, and target domain folder. Two extractor templates exist (JSON "Rank" template and XML master-data template).
5. **A failing run report is valid output.** The run report reports `Overall: FAIL` when lint has blocking findings against the vendor document. CI must treat this as a business finding to route to the vendor, not as a broken build.
6. **Local runs use Python 3.15 and offline wheels** because of laptop restrictions. CI runners have normal package access and use a pinned, supported Python (3.12).

## 3. Architecture overview

```
   SharePoint Online                         GitHub                                  VM (nginx)
 ┌──────────────────────┐   event/poll   ┌──────────────────────┐
 │ Integration Specs    │──────────────▶ │ 1. INGEST workflow   │
 │  (vendor .docx)      │                │  fetch → extract →   │
 │                      │◀──────────┐    │  lint → open PR      │
 └──────────────────────┘  publish  │    └──────────┬───────────┘
                                    │               │ human review (Stage 2)
 ┌──────────────────────┐           │               ▼
 │ Pipeline Outputs     │           │    ┌──────────────────────┐
 │  run reports, xlsx,  │◀──────────┴────│ 2. BUILD workflow    │
 │  OpenAPI             │                │  validate → compile →│
 └──────────────────────┘                │  OpenAPI → reports → │
                                         │  UI lint+build       │
                                         └──────────┬───────────┘
                                                    │ artifact: site
                              merge to develop      │      merge to main (approval)
                                       ┌────────────┴────────────┐
                                       ▼                         ▼
                              ┌────────────────┐        ┌────────────────┐
                              │ 3a. DEPLOY DEV │        │ 3b. DEPLOY UAT │
                              │ self-hosted    │        │ self-hosted    │
                              │ runner on VM   │        │ runner on VM   │
                              └───────┬────────┘        └───────┬────────┘
                                      ▼                         ▼
                              nginx :8081 (Dev)         nginx :8080 (UAT)
                              /var/www/.../dev/current  /var/www/.../uat/current
```

**Three workflows, one repository:**

| # | Workflow | Trigger | Runs on | Purpose |
|---|---|---|---|---|
| 1 | Ingest | SharePoint event, schedule, or manual | GitHub-hosted | Fetch document, extract, lint, open review PR |
| 2 | Build | Pull request, push to `develop`/`main` | GitHub-hosted | Validate, compile, generate, build UI, upload artifact |
| 3 | Deploy | After Build on `develop` (Dev) or `main` (UAT) | Self-hosted runner on VM | Publish release, health check, rollback on failure |

Workflows 2 and 3 are in one file today ([.github/workflows/knowledge-hub.yml](../.github/workflows/knowledge-hub.yml)). Workflow 1 is new work (see section 13).

**Why this split**
- Fetching and parsing untrusted `.docx` files runs on ephemeral GitHub-hosted runners, not on the VM that serves users.
- The VM only receives finished static files; it needs no inbound SSH and no SharePoint credentials.
- The human review gate is a normal pull request, so it is audited, branch-protected and reversible.

## 4. Environments and branching

| Environment | Branch | Port | Who uses it | Gate |
|---|---|---|---|---|
| Dev | `develop` | 8081 | Developers, integration team | None (automatic on merge) |
| UAT | `main` | 8080 | UAT business users | GitHub environment `uat` with required reviewers |

Flow of change:

```
ingest/<interface-id>  ──PR + review──▶  develop  ──deploys──▶  Dev :8081
                                            │
                                  PR develop → main (UAT sign-off)
                                            ▼
                                          main  ──approval──▶  UAT :8080
```

- Branch protection on `develop` and `main`: PR required, required check = Build, at least one reviewer, no force-push.
- `CODEOWNERS` on `domains/**` and `schemas/**` so data owners must approve.
- Dev and UAT run the **same artifact build process**; they differ only by which commit they were built from.
- This section describes the single-pipeline case. For several pipeline variants in separate branches sharing one UI, see section 16.

## 5. SharePoint integration

### 5.1 Assumptions
- SharePoint Online (Microsoft 365). If it is on-premises SharePoint, the fetch must run on a self-hosted runner inside the network instead.
- Two document libraries (or two folders in one library):
  - `Integration Specs` — vendor inputs. Read-only for the pipeline.
  - `Pipeline Outputs` — reports and generated files. Write access for the pipeline. **Must be separate from the input location**, otherwise publishing outputs would re-trigger ingestion.

### 5.2 Authentication

Use an Entra ID (Azure AD) app registration:

| Item | Setting |
|---|---|
| Permission type | Application permission `Sites.Selected` (Microsoft Graph) |
| Scope | Granted only to the one SharePoint site (read on Specs, write on Outputs) |
| Credential | Client certificate or client secret; prefer GitHub OIDC federated credential so no secret is stored |
| Consent | Tenant admin consent required once |

`Sites.Selected` is deliberate: the pipeline can see one site only, not the whole tenant.

### 5.3 Graph calls used

```
Token       POST https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token   (scope: https://graph.microsoft.com/.default)
Resolve     GET  /v1.0/sites/<host>:/sites/<site-name>
List        GET  /v1.0/sites/<site-id>/drive/root:/<folder>:/children?$select=id,name,eTag,lastModifiedDateTime,size,file
Download    GET  /v1.0/sites/<site-id>/drive/items/<item-id>/content        (302 redirect; follow it)
Publish     PUT  /v1.0/sites/<site-id>/drive/root:/<outputs>/<name>:/content  (files < 4 MB; use upload session above that)
```

### 5.4 How a change is detected (three triggers)

| Option | Mechanism | Latency | Notes |
|---|---|---|---|
| **A. Event (recommended)** | Power Automate flow: "When a file is created or modified" in `Integration Specs` → HTTP POST to the GitHub `repository_dispatch` API | Minutes | Needs a GitHub App token or fine-grained PAT stored in the flow's connection. Add a "Ready for ingestion" column or SharePoint content approval so half-saved drafts do not trigger runs. |
| **B. Schedule (safety net)** | Ingest workflow on `cron` (e.g. every 30 min) lists the folder and compares eTag/SHA with the committed lock file | Up to the interval | No setup on SharePoint side. Also catches missed events. |
| **C. Manual** | `workflow_dispatch` with the SharePoint path as input | Immediate | For re-runs and first onboarding. |

Run A and B together; C is always available.

Event payload sent by Power Automate:

```json
{
  "event_type": "sharepoint-doc-updated",
  "client_payload": {
    "item_id": "<drive item id>",
    "path": "/Integration Specs/Shippeo/CV07_02_TMS_2_SHIP_EVENTS.docx",
    "etag": "<eTag>",
    "modified_by": "<user>"
  }
}
```

### 5.5 Telling the pipeline what to do with each file

The document does not contain its interface id, name, domain folder or template type. Keep a **manifest in the repository** (versioned, reviewed):

```yaml
# pipeline/interfaces.manifest.yaml
interfaces:
  - id: CV07_02
    name: CV07_02_TMS_2_SHIP_EVENTS
    domain: cv07_02_shippeo_events
    template: json          # json -> extract_interface_from_docx.py ; xml -> extract_interface_from_docx_xml.py
    variant: default        # default -> PR to develop ; fms -> PR to variant/fms
    sharepoint_path: /Integration Specs/Shippeo/CV07_02_TMS_2_SHIP_EVENTS.docx
    enabled: true           # entries stay false until the real SharePoint path is set
  - id: CV10_01
    name: CV10_01_MD_TRUCKS_TRAILERS
    domain: cv10_fms
    template: xml
    variant: fms
    sharepoint_path: /Integration Specs/FMS/CV10_01 - Integration MD-Trucks Trailers.docx
    enabled: true
```

A file in SharePoint with no manifest entry, or with `enabled: false`, is **not processed**. `scripts/ingest_manifest.py` validates every field against a strict pattern before anything reaches a shell. This stops arbitrary uploads from running scripts and makes onboarding a new interface a reviewed PR.

### 5.6 Idempotency and traceability

The Ingest workflow records, per document, in `pipeline/source_docs.lock.json`:

```json
{ "CV07_02": { "sharepoint_item_id": "…", "etag": "…", "sha256": "…", "fetched_at": "…", "modified_by": "…" } }
```

- If the SHA-256 already matches the lock file, the run exits without changes (no duplicate PRs, no loops).
- The lock file is committed in the review PR, so every YAML change can be traced to an exact document version.
- The `.docx` itself is **not committed**. It lives in SharePoint, which is the system of record, and is deleted from the runner at job end.

## 6. Workflow 1 — Ingest (SharePoint to review PR)

```
 trigger ─▶ read manifest ─▶ get Graph token ─▶ download docx ─▶ sha256 changed? ─no─▶ stop
                                                       │yes
                                                       ▼
                         extract (json|xml) ─▶ lint ─▶ findings tracker
                                                       │
                          create branch ingest/<id> ◀──┘
                          commit drafts + reports + lock file
                          open PR to develop, label by lint result
```

Step by step (matches Run Guide steps 1, 2 and 9):

| Step | Command | Output committed to the PR |
|---|---|---|
| Fetch | `python scripts/fetch_from_sharepoint.py --id <ID> --sharepoint-path <path> --out-dir <tmp> --lock source_docs.lock.json` | `source_docs.lock.json` |
| Extract | `python scripts/extract_interface_from_docx[_xml].py <docx> --id <ID> --name <NAME> --out-dir domains/<domain>` | `fields.draft.yaml`, `interfaces.draft.yaml`, `REVIEW_REPORT.md` |
| Lint | `python scripts/lint_source_document.py <docx> --out-dir domains/<domain>` | `DOC_QUALITY_REPORT.md` |
| Tracker | `python scripts/generate_findings_tracker.py --domain-dir … --domain-name … --interface-id … --out …/<ID>_Findings_Tracker.xlsx` | Uploaded as artifact (not committed) |

**PR labelling by lint result**

| Lint result | Label | Effect |
|---|---|---|
| 0 blocking findings | `ready-for-review` | Reviewer can promote and merge |
| Blocking findings | `vendor-fix-required` | PR cannot merge until the vendor reissues the document (a new Ingest run updates the PR) or an approver adds a documented waiver label |

The PR body summarises: field count, review-flagged fields, lint counts by severity, and links to the tracker and reports.

## 7. Stage 2 — human review inside the PR

This is the only manual step, preserved on purpose.

1. Reviewer opens the PR and reads `REVIEW_REPORT.md` and `DOC_QUALITY_REPORT.md`.
2. Reviewer edits the draft YAML in the PR branch: sensitivity, mandatory/conditional, public constants.
3. Reviewer **promotes**: renames `fields.draft.yaml` → `fields.yaml` and `interfaces.draft.yaml` → `interfaces.yaml`, and removes any full field definition that already exists in another domain (shared meta fields such as `meta-senderid`), keeping only the reference.
4. The Build workflow runs automatically on the PR and must pass.
5. Approver (CODEOWNER) approves and merges to `develop`.

Optional improvement: a PR comment command `/promote` backed by a generic `scripts/promote_draft.py` (the existing `promote_cv07_draft.py` is CV07-specific) so promotion does not need local tooling.

## 8. Workflow 2 — Build (validate, generate, build UI)

Runs on every pull request and every push to `develop`/`main`. Mirrors Run Guide steps 4 to 9, then the UI.

| Order | Step | Command | Fails the build when |
|---|---|---|---|
| 1 | Install Python deps | `pip install -r requirements.txt` | Dependency resolution fails |
| 2 | Validate | `python scripts/validate_all.py` | Any record fails schema, unresolved reference, duplicate id |
| 3 | Compile | `python scripts/compile_knowledge_hub.py --out <ui>/src/data/exampleData.js` | Validation fails (it re-runs validation) |
| 4 | OpenAPI | `python scripts/generate_openapi.py --out-dir <ui>/public/openapi` | Any spec fails `openapi_spec_validator` |
| 5 | Run reports *(planned)* | `generate_run_report.py` per manifest interface, then `md_to_html.py` | Script error (an `Overall: FAIL` verdict is reported, not fatal; see 8.1) |
| 6 | Findings tracker *(planned)* | `generate_findings_tracker.py` per interface | Script error |
| 7 | UI install | `npm ci` | Lockfile mismatch |
| 8 | UI lint | `npm run lint` (oxlint) | Lint errors |
| 9 | UI build | `npm run build` | Build error |
| 10 | Stamp | writes the commit SHA to `dist/version.txt` | — |
| 11 | Upload | artifact `site` (dist incl. `/openapi`), artifact `reports` (HTML, xlsx) | No files produced |

Notes:
- The compile step overwrites the UI's `exampleData.js` **inside the CI workspace only**; the hand-written demo file in git is untouched.
- OpenAPI files are copied into the UI's `public/openapi`, so the same deployed site also serves the specs.
- Python is pinned to 3.12 in CI. Local runs on 3.14/3.15 are supported by the offline wheel bundles but should be validated against 3.12 once (see risks).

### 8.1 Handling `Overall: FAIL` in run reports

A run report can say FAIL because the vendor document has blocking findings. Policy:

- The Build job still completes and publishes the report (so people can read it).
- Ingest PRs carry the `vendor-fix-required` label until resolved (section 6).
- Merging to `develop` or `main` requires that label to be absent, enforced by a required status check that reads the report verdict.

## 9. Workflow 3 — Deploy to the VM (Dev and UAT)

### 9.1 VM layout

```
/var/www/knowledge-hub/
├── dev/
│   ├── releases/20261118101500-ab12cd3/   (immutable build)
│   ├── releases/…                         (last 5 kept)
│   └── current  ──symlink──▶  releases/20261118101500-ab12cd3
└── uat/
    ├── releases/…
    └── current  ──symlink──▶  releases/…
```

nginx serves `dev/current` on **8081** and `uat/current` on **8080** ([deploy/nginx/knowledge-hub.conf](../deploy/nginx/knowledge-hub.conf)). Because the site is static with hash routing, nginx needs only one-time configuration; deployments never reload nginx.

### 9.2 What a deployment does ([deploy/deploy.sh](../deploy/deploy.sh))

1. Copies the built site into a new timestamped release folder.
2. Atomically switches the `current` symlink to it (`mv -Tf`), so users never see a half-copied site.
3. Calls `http://127.0.0.1:<port>/version.txt` and checks it returns the exact commit SHA being deployed.
4. If the check fails, switches `current` back to the previous release and exits non-zero (the GitHub job fails).
5. Prunes to the newest 5 releases.

**Rollback:** automatic on failed health check. Manual: point `current` at an earlier release folder, or re-run the workflow on an earlier commit (`workflow_dispatch`).

### 9.3 The self-hosted runner

- Installed on the VM as a service under a dedicated low-privilege user.
- Label: `knowledge-hub`. Outbound HTTPS to GitHub only; no inbound ports.
- The user owns `/var/www/knowledge-hub` and needs **no sudo**.
- Contains no SharePoint or Graph credentials.
- Keep the runner software auto-updated, and restrict the repository's workflows to this runner for the Deploy jobs only.

### 9.4 Approval for UAT

GitHub environment `uat` has **Required reviewers**. The Deploy-UAT job pauses until a named approver (UAT owner) approves in GitHub. Approver identity and time are recorded in the run history.

## 10. End-to-end walkthrough (CV07_02 revised by the vendor)

1. Vendor uploads revised `CV07_02_TMS_2_SHIP_EVENTS.docx` to SharePoint and sets "Ready for ingestion".
2. Power Automate calls `repository_dispatch`. Ingest starts.
3. Ingest finds the SHA differs from the lock file, extracts and lints, and opens PR `ingest/CV07_02` to `develop` labelled `ready-for-review` (or `vendor-fix-required`).
4. The integration reviewer applies judgement calls, promotes the drafts, pushes to the PR branch.
5. Build runs on the PR: validate, compile, OpenAPI, reports, UI build all pass; preview artifact and reports are attached.
6. CODEOWNER approves and merges. Build runs on `develop`; Deploy-Dev publishes to `:8081`. Reports and OpenAPI files are published to the SharePoint `Pipeline Outputs` folder.
7. Integration team verifies the glossary at `:8081`.
8. A PR `develop → main` is raised for UAT sign-off. After merge and approval from the UAT owner, the same process deploys to `:8080`.
9. UAT users see the updated glossary. The commit SHA is visible at `:8080/version.txt`.

## 11. Configuration reference

**GitHub repository variables**

| Name | Example | Used by |
|---|---|---|
| `VM_HOST` | `kh-vm.company.local` | Environment URLs |
| `SP_TENANT_ID` | `…` | Ingest, publish |
| `SP_CLIENT_ID` | `…` | Ingest, publish |
| `SP_SITE` | `contoso.sharepoint.com:/sites/IntegrationHub` | Ingest, publish |
| `SP_SPECS_FOLDER` | `/Integration Specs` | Ingest |
| `SP_OUTPUTS_FOLDER` | `/Pipeline Outputs` | Publish |

**GitHub secrets** (environment- or repository-level): `SP_CLIENT_SECRET` or certificate (omit when using OIDC federation); `SYNC_TOKEN` (PAT or GitHub App token, used by Ingest and Sync so their PRs trigger Build); the token Power Automate uses to call GitHub lives in Power Automate, not in GitHub.

**GitHub environments:** `dev` (no rules), `uat` (required reviewers).

**Repository files** (`pipeline/` below means the Python pipeline folder, currently `Knowledge_Hub_Build_Pipeline_4/Knowledge_Hub_Build_Pipeline_4/`; the workflow variables `PIPELINE_DIR` and `UI_DIR` hold the real paths)

| Path | Purpose | Status |
|---|---|---|
| `.github/workflows/knowledge-hub.yml` | Build and Deploy | Created |
| `.github/workflows/ingest.yml` | SharePoint ingest | Created |
| `deploy/deploy.sh`, `deploy/nginx/*.conf` | VM deployment | Created |
| `pipeline/requirements.txt` | Python dependencies | Created |
| `pipeline/interfaces.manifest.yaml` | Document → id/name/domain/template/variant mapping | Created (all entries disabled) |
| `pipeline/scripts/ingest_manifest.py` | Validates the manifest and builds the ingest matrix | Created |
| `pipeline/source_docs.lock.json` | Source document version/hash record | Written by Ingest PRs |
| `pipeline/scripts/fetch_from_sharepoint.py` | Graph download | Created (publish to SharePoint still to build) |
| `pipeline/scripts/promote_draft.py` | Generic promote | Optional |

## 12. Security and compliance

| Risk | Control |
|---|---|
| Untrusted `.docx` input | Only manifest-listed files; `.docx` only (no macro formats); file size limit; parsed on ephemeral GitHub-hosted runner; deleted after the run |
| Over-broad SharePoint access | `Sites.Selected` on one site; separate read (Specs) and write (Outputs) locations |
| Credential leakage | OIDC federation or short-lived secrets in GitHub environment secrets; none on the VM |
| Unreviewed data reaching users | PR review required; branch protection; CODEOWNERS on `domains/**`; Stage 2 never bypassed |
| Tampered deploy | Deploy job downloads only the artifact produced by Build for that commit; version.txt must match SHA |
| Supply chain | Pinned Python and Node versions; lockfiles; Dependabot; `pip-audit` and `npm audit` in Build |
| Data exposure | Site is internal; place nginx behind the corporate network or SSO reverse proxy; glossary contains sensitivity labels (PII/confidential) but no record data |
| Audit | Every change traceable: SharePoint item/eTag → lock file → PR → commit SHA → artifact → release folder → `version.txt` |

## 13. Implementation plan

| Phase | Deliverable | Depends on |
|---|---|---|
| 0 | Create git repo, branches (`develop`, `main`), branch protection, environments, `VM_HOST` variable | — |
| 1 | VM setup: nginx, folders, firewall for 8080/8081, self-hosted runner (label `knowledge-hub`) | Phase 0 |
| 2 | Build and Deploy workflows operating on committed YAML | Phase 1 (**files already created**) |
| 3 | Entra app registration, `Sites.Selected` grant, SharePoint libraries | Tenant admin |
| 4 | `fetch_from_sharepoint.py`, manifest, lock file, `ingest.yml`, PR creation and labels | Phase 3 |
| 5 | Add run report, HTML and tracker steps to Build; publish outputs back to SharePoint | Phase 4 |
| 6 | Power Automate event trigger plus schedule safety net | Phase 4 |
| 7 | Required status check for `vendor-fix-required`; security scans; pytest golden tests on the two sample documents | Phase 5 |

## 14. Risks and open decisions

| Item | Risk | Proposed handling / decision needed |
|---|---|---|
| SharePoint is on-premises | Graph unavailable | Use a self-hosted runner and SharePoint REST; design otherwise unchanged |
| Python version difference (3.14/3.15 local vs 3.12 in CI) | Behaviour differences | Run the full pipeline once on 3.12 against CV07_01/CV07_02 and compare outputs |
| VM has no internet | Cannot `pip install` | Not needed for Deploy (static files only); Build runs on GitHub-hosted runners |
| Partial saves in SharePoint | Spurious ingest runs | "Ready for ingestion" column or content approval; SHA check suppresses no-change runs |
| Lint-blocking findings policy | Blocks UAT if too strict | Decide whether waivers are allowed, and who approves them |
| UAT approver | Gate ownership | Name the GitHub reviewers/team for `uat` |
| Authentication for UAT users | Open ports on internal network | Decide on SSO or reverse proxy in front of 8080 |
| Single VM | Single point of failure for both environments | Acceptable for UAT/Dev; releases are immutable and rebuildable from Git in minutes |

## 15. Operations

- **Monitoring:** GitHub Actions run history (failure notifications to email/Teams); a scheduled health check of `:8080/version.txt` and `:8081/version.txt` from the same workflow; nginx access and error logs on the VM.
- **Disk:** only 5 releases per environment are kept.
- **Re-run a deployment:** Actions → workflow → "Run workflow" on the desired commit.
- **Onboard a new interface:** add a manifest entry (PR), upload the document to SharePoint, wait for the ingest PR, review, merge.
- **Rotate credentials:** replace the SharePoint client secret/certificate in GitHub secrets; with OIDC federation there is nothing to rotate.

---

## 16. Multiple pipeline variants with one common UI

Some pipelines differ slightly from the base (different extractor behaviour, schema additions, domain sets). This section defines how to keep each variant in its own branch **without** letting the UI or the deployment tooling drift.

### 16.1 Options considered

| Option | Description | Strength | Weakness | Verdict |
|---|---|---|---|---|
| A. Trunk plus config profiles | One `main`; differences expressed as per-variant config and domain folders | No drift, simplest | Needs the differences to be expressible as config | Best long-term target |
| **B. Long-lived variant branches** | One `variant/<name>` branch per pipeline, kept in sync with `main` | Isolates code changes per variant | Drift and merge conflicts if not governed | **Chosen for now, with the controls below** |
| C. Separate repositories | UI repo plus one repo per pipeline | Hard isolation | Highest overhead; UI version coordination | Consider if variants exceed about 4 or have different owners |

Rule of thumb: if a variant difference can be a setting, put it in config on `main`; use a variant branch only for real code differences. Review each variant's diff quarterly and fold shared changes back into `main`.

### 16.2 Branch model

```
main (common baseline: UI, deploy, shared scripts)  ── tags v1.0.0, v1.1.0 …
  │
  ├── develop ............... integration for the common code, deploys Dev /default
  │     └── feature/*, fix/* ... short-lived, PR into develop
  │
  ├── variant/fms ........... long-lived; only the FMS pipeline differences
  │     └── ingest/CV10_01 .... bot PRs for FMS documents
  ├── variant/shippeo ....... long-lived; only the Shippeo pipeline differences
  │     └── ingest/CV07_02 .... bot PRs for Shippeo documents
  └── (more variants)
```

| Branch | Lifetime | Created from | Merges into | Deploys to |
|---|---|---|---|---|
| `main` | Permanent | — | — | UAT, variant `default` (approval) |
| `develop` | Permanent | `main` | `main` via PR | Dev, variant `default` |
| `feature/*`, `fix/*` | Days | `develop` | `develop` via PR | Build and preview only |
| `variant/<name>` | Permanent | `main` | Never into `main` | Dev, variant `<name>` on every merge |
| `ingest/<id>` | Until reviewed | The variant (or `develop`) branch named in the manifest | That same branch via PR | Build only |
| tag `uat/<name>/vX.Y.Z` | Immutable | A commit on `variant/<name>` | — | UAT, variant `<name>` (approval) |

### 16.3 Rules that keep the UI common

1. **The UI is changed only on the common line:** `feature/*` → `develop` → `main`. Variant branches never edit `ui/`, `deploy/` or `.github/`.
2. **Common changes flow down, never up.** Every merge to `main` is merged into every `variant/*` branch (section 16.5). If a variant fix is generally useful, re-apply it as a `feature/*` PR against `develop`.
3. **A path guard enforces rule 1.** A required check on every `variant/*` PR runs `git diff --name-only origin/main...HEAD` and fails if any file under `ui/`, `deploy/` or `.github/` differs. Variants may change only `pipeline/**` (and their own `domains/**`).
4. **Variant-specific values live in one file:** `pipeline/variants/<name>/variant.yaml` (name, domains, template defaults), so most variant differences are data, not code, and diffs stay small.
5. **Branch protection** on `main`, `develop` and the pattern `variant/*`: PR required, Build check required, CODEOWNERS review, no force-push, no direct commits.
6. **Release names are tags, not branches,** so UAT users always know exactly what they are testing.

### 16.4 How the UI behaves across variants

The UI source is identical everywhere. It imports one compiled data module, so each variant is the **same UI code built with that variant's data**.

```
 ui/ (common source) ──┐
                       ├─▶ npm run build ─▶ dist/  (UI + this variant's data + OpenAPI)
 variant data: compile ┘                      deployed to /<variant>/
```

- Every variant build uses the UI as merged from `main`, so the UI version of a variant is simply the `main` version it last merged.
- Show the variant name and commit in the UI footer by writing them into `version.txt` (`<variant> <sha>`).
- If the number of variants grows, move the UI to its own repository and have each variant's Build check out a pinned UI tag (`UI_REF`), so a UI release is adopted by changing one line per variant.

### 16.5 CI/CD for variants

**One shared set of workflows, identical on every branch.** Put the build and deploy logic into reusable workflows (`workflow_call`) so branches never need to edit `.github/`, which removes the main source of merge conflicts.

```
.github/workflows/
├── knowledge-hub.yml     triggers + variant/env resolution, calls the two below
├── _build.yml            reusable: validate → compile → OpenAPI → reports → UI build
├── _deploy.yml           reusable: deploy to the VM (inputs: env, variant)
├── guard-variant.yml     PR check for variant/* (path guard, rule 3)
├── sync-variants.yml     merges main into each variant branch (below)
└── ingest.yml            SharePoint ingest (inputs: variant)
```

**Resolving variant and environment from the Git ref**

| Ref that triggered the run | Variant | Environment | Gate |
|---|---|---|---|
| `develop` | `default` | Dev | None |
| `main` | `default` | UAT | `uat` environment approval |
| `variant/<name>` | `<name>` | Dev | None |
| tag `uat/<name>/vX.Y.Z` | `<name>` | UAT | `uat` environment approval |
| Pull request (any) | — | none | Build and guard checks only |

Sketch of the resolution step:

```yaml
- id: target
  run: |
    ref="${GITHUB_REF}"
    case "$ref" in
      refs/heads/develop)      v=default; e=dev ;;
      refs/heads/main)         v=default; e=uat ;;
      refs/heads/variant/*)    v="${ref#refs/heads/variant/}"; e=dev ;;
      refs/tags/uat/*/v*)      t="${ref#refs/tags/uat/}"; v="${t%%/*}"; e=uat ;;
      *)                       v=""; e="" ;;
    esac
    echo "variant=$v" >> "$GITHUB_OUTPUT"; echo "env=$e" >> "$GITHUB_OUTPUT"
```

Other CI/CD rules for variants:
- **Concurrency per target:** `group: deploy-${{ env }}-${{ variant }}`, so two variants can deploy in parallel but one variant never overlaps itself.
- **Build once, deploy that artifact:** the Deploy job always uses the artifact built from the same commit.
- **Ingest targets the right branch:** the manifest gets a `variant:` field per interface; Ingest checks out `variant/<name>` and opens the PR against it.
- **Reports and outputs** are published to `Pipeline Outputs/<variant>/`.

**Automatic downstream sync (`sync-variants.yml`)**

On every push to `main` (and weekly), for each `origin/variant/*` branch:
1. Try `git merge origin/main`.
2. If it merges cleanly, push it to a short-lived `sync/<name>` branch and open a PR to the variant (so Build and the guard run before it lands).
3. If it conflicts, open a PR with the conflict marked and assign the variant owner.
4. Include `git diff --stat origin/main...variant/<name>` in the PR body as a drift report.

### 16.6 Hosting several variants on one VM with two ports

Keep exactly two ports. Variants become **sub-paths**: `:8080/<variant>/` for UAT and `:8081/<variant>/` for Dev. This works with the current build because the UI uses `base: './'` and hash routing.

```
/var/www/knowledge-hub/
├── dev/
│   ├── default/   releases/… current ─▶ …
│   ├── fms/       releases/… current ─▶ …
│   └── shippeo/   releases/… current ─▶ …
└── uat/
    ├── default/ …   ├── fms/ …   └── shippeo/ …

URLs:  http://<vm>:8081/fms/      Dev FMS
       http://<vm>:8080/shippeo/  UAT Shippeo
```

nginx (replaces the per-server `root` with a variant-aware lookup):

```nginx
server {
    listen 8080;                      # UAT (8081 identical with /dev)
    root /var/www/knowledge-hub/uat;

    location ~ ^/(?<variant>[a-z0-9_-]+)/(?<rest>.*)$ {
        try_files /$variant/current/$rest /$variant/current/$rest/index.html =404;
    }
    location = / { return 302 /default/; }
}
```

Implemented in the repository:
- `deploy/deploy.sh` takes a variant (`deploy.sh <env> <variant> <site-dir> <sha>`), writes to `<env>/<variant>/releases`, and health-checks `/<variant>/version.txt`.
- `deploy/nginx/*.conf` contain the variant-aware lookup.
- Workflows: `knowledge-hub.yml` (ref → variant/env), `_build.yml`, `_deploy.yml`, `guard-variant.yml`, `sync-variants.yml`.
- Variant names are restricted to `[a-z0-9_-]`, so a branch name can never become an arbitrary path.
- `sync-variants.yml` needs a `SYNC_TOKEN` secret (PAT or GitHub App token), because PRs created with the default token do not trigger Build or the guard.

### 16.7 End-to-end example: a Shippeo-only change

1. Developer creates `feature/shippeo-timezone` from `variant/shippeo`, changes `pipeline/scripts/extract_interface_from_docx.py` and the variant config.
2. PR to `variant/shippeo`: Build and the path guard pass (only `pipeline/**` touched). Reviewer merges.
3. Dev deploys to `http://<vm>:8081/shippeo/`. Integration team verifies.
4. Release manager tags `uat/shippeo/v1.3.0` on that commit. The `uat` approver approves, and UAT users get `http://<vm>:8080/shippeo/`.
5. Meanwhile, a UI fix merges to `main`. `sync-variants.yml` opens `sync/shippeo` and `sync/fms` PRs. After their checks pass they merge, and each variant picks up the new UI at its next Dev deploy and UAT tag.

### 16.8 Controls summary

| Concern | Control |
|---|---|
| UI drift across variants | Path guard plus main-to-variant sync |
| Variant drift in code | Drift report on every sync PR; quarterly review; move shared changes to `main` |
| Workflow conflicts | Reusable workflows; `.github/**` identical on all branches |
| Wrong variant deployed | Variant derived only from the Git ref; strict name pattern; concurrency group per target |
| UAT traceability | Immutable `uat/<variant>/vX.Y.Z` tags; `version.txt` shows variant and SHA |
| Access | CODEOWNERS per variant folder; `uat` environment reviewers |
