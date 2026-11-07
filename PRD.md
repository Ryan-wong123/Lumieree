# Lumieree – Product Requirements Document

> Living document. It describes the product **as implemented on this branch** plus the agreed roadmap. Any change to
> user-visible behaviour, roles, permissions, or data handling must update this file in the same change set
> (see `AGENTS.md`). Technical design lives in [`architecture.md`](architecture.md).

Status: Implemented = in the code today · Planned = not built yet · Last reviewed: 2026-11-07

## 1. Overview

**Lumieree** is a web-based point-of-sale and clinic-management system for Traditional Chinese Medicine (TCM)
clinics, originally built for a single Singapore clinic and now being prepared for **public, multi-clinic use**.
It replaces paper records and spreadsheets with one place to register patients, record consultations, prescribe
medicine and services, dispense at the front desk, keep inventory accurate, schedule appointments, and print receipts.

### 1.1 Problems it solves

* Prescriptions are written by the physician but dispensed and billed by front-desk staff: information gets lost.
* Medicine stock (many herbs, many batches, expiry dates) is hard to keep correct by hand.
* Receipts must be quick to produce and bilingual (English / Chinese).
* Patient data is sensitive and must not leak between clinics.

### 1.2 Goals

1. Fast daily workflow: patient → visit → prescription → dispense → receipt in a few clicks.
2. Correct stock: dispensing deducts inventory exactly once; voiding restores it.
3. Bilingual UI (English / 简体中文) and bilingual receipt header.
4. Safe to host publicly: strict tenant isolation, secure authentication, auditable deployment.
5. Operable: containerised, Kubernetes-ready, health probes, migrations, backups.

### 1.3 Non-goals (for now)

Payment processing / e-invoicing, insurance claims, electronic medical-record interchange, patient-facing portal,
native mobile apps, multi-branch inventory transfers, multiple staff sharing one clinic's data (see §10).

## 2. Users and roles

| Role | Who | Can do |
| --- | --- | --- |
| `staff` | Clinic account used by physician / front desk | Everything in §4 except the dashboard, CSV exports and account management |
| `admin` | Clinic owner / manager account | `staff` capabilities + dashboard + CSV exports |
| `super_admin` | Platform operator | `admin` capabilities + create / edit / disable / delete accounts. Created only through the CLI |

**Tenancy:** each account is its own tenant. Patients, visits, medicines, queue items and appointments are visible
only to the account that created them. Deleting an account deletes all of its data.

## 3. Key user journeys

1. **Consultation.** Physician opens a patient → *Visits* → records condition, adds medicines (autocomplete shows
   stock) and services (catalogue or free text with price), writes notes / discharge advice → **Save draft** (restored
   next time) or **Confirm**. A confirmed visit with medicines is sent to the front-desk queue.
2. **Dispensing.** Front desk sees the waiting queue → **Mark completed** (stock is deducted once) → receipt page →
   tick the lines to bill (or enter a custom line) → **Generate PDF receipt**. **Void** returns the order to waiting
   and restores stock.
3. **Inventory.** Add medicines/batches, edit, adjust stock, import a CSV, scan or type a barcode.
4. **Scheduling.** Pick a date on the calendar, fill the hourly grid (10:00–20:00), save; colours show how busy each day is.
5. **Management.** Admin reviews the dashboard (visits in a date range, low stock, recent orders) and exports CSVs.
6. **Platform operations.** Super admin creates clinic accounts with a temporary password; the clinic must change it
   at first login.

## 4. Functional requirements

### 4.1 Accounts and access (Implemented)

| ID | Requirement |
| --- | --- |
| AUTH-1 | Sign in with username + password; one generic error for wrong password, unknown user or disabled account |
| AUTH-2 | Passwords ≥ 12 characters, stored as salted scrypt hashes; users may change e-mail / password in Settings after confirming the current password |
| AUTH-3 | Login attempts are rate limited per client IP |
| AUTH-4 | Sessions last 8 hours; deactivation, role change or password change takes effect immediately |
| AUTH-5 | Accounts created by a super admin must change the temporary password at first login |
| AUTH-6 | Super admin can create (`staff`/`admin`), edit role / e-mail / active flag, reset passwords and delete accounts; cannot disable, demote or delete themselves or the last active super admin |
| AUTH-7 | The first super admin is created from the CLI (`create-super-admin`) or the idempotent bootstrap (`ensure-super-admin`) |
| AUTH-8 | `/admin/dashboard` and CSV exports require `admin`; account management requires `super_admin` |

### 4.2 Patients (Implemented)

| ID | Requirement |
| --- | --- |
| PAT-1 | Create / edit / delete patients: name (required), NRIC/ID, date of birth, gender, contact, e-mail, address |
| PAT-2 | Medical history: yes/no for diabetes, hypertension, heart disease, asthma, stroke, kidney disease, high cholesterol; taking western medicine (+ duration); other conditions; drug allergies |
| PAT-3 | Search by name, contact or NRIC (case-insensitive; wildcard characters are treated literally) |
| PAT-4 | The list shows each patient's confirmed-visit count |
| PAT-5 | Deleting a patient deletes their visits; queue history is kept and shown as "Unknown (Deleted)" |

### 4.3 Visits and prescriptions (Implemented)

| ID | Requirement |
| --- | --- |
| VIS-1 | A visit records date, condition, prescribed medicines (name, quantity, unit), services with prices, notes and discharge advice |
| VIS-2 | **Save draft** keeps one draft per patient, replacing any earlier one, and pre-fills the form next time; **Confirm** stores the visit and removes the draft |
| VIS-3 | Confirming a visit that has medicines creates a front-desk queue item |
| VIS-4 | Medicine autocomplete shows live stock (out-of-stock items last); running totals for medicines, services and grand total |
| VIS-5 | Past visits are listed oldest → newest and can be filtered by date range |

### 4.4 Front desk and receipts (Implemented)

| ID | Requirement |
| --- | --- |
| FD-1 | Queue has *waiting* and *completed* tabs, newest first |
| FD-2 | Completing an item deducts stock for each line (by medicine id, falling back to name), never below zero, and **only once** even if clicked repeatedly |
| FD-3 | Voiding a completed item restores the deducted stock and returns it to waiting |
| FD-4 | Receipt page lists medicines (priced from the current inventory price) and the visit's services with checkboxes |
| FD-5 | The PDF receipt is built on the server from stored data; the browser only chooses which lines to include. A single custom line + total may be entered when nothing is selected |
| FD-6 | PDF header (clinic name in Chinese and English, registration number, address) comes from configuration |

### 4.5 Inventory (Implemented)

| ID | Requirement |
| --- | --- |
| INV-1 | A medicine record is one batch: name (Chinese), English name, company, type (pills / grams / bottle), price, stock, expiry date, optional barcode, generated SKU |
| INV-2 | Inventory page groups batches by medicine name; search by name, English name or barcode |
| INV-3 | Add, edit, delete; set stock; adjust by barcode (scan with the camera or type) |
| INV-4 | CSV import (≤ 2 MB, ≤ 5000 rows; headers matched case-insensitively): creates or updates batches by SKU or by name + company + type + expiry |
| INV-5 | Invalid numbers, negative prices/stock and bad dates are rejected with a message (never a server error) |

### 4.6 Appointments (Implemented)

| ID | Requirement |
| --- | --- |
| APT-1 | Calendar with per-day booking counts coloured green (1–2), amber (3–5), red (6+) |
| APT-2 | Daily grid: patient name, contact and free text for each hour 10:00–20:00; saving replaces the day |
| APT-3 | Cancel a single patient's appointment from the grid |
| APT-4 | Names and notes are always displayed as text (no markup execution) |

### 4.7 Dashboard and exports (Implemented, admin)

| ID | Requirement |
| --- | --- |
| DASH-1 | Totals: patients and dispensed/queued prescriptions; visits in a chosen date range (default today); low-stock list (stock ≤ 10); five most recent completed orders |
| DASH-2 | CSV exports of confirmed visits and of the queue; spreadsheet formula injection is neutralised |

### 4.8 Language (Implemented)

English and Simplified Chinese UI, switchable at any time, remembered for the session. Missing strings fall back to the key.

### 4.9 Data migration (Implemented)

A one-off command imports the legacy Firebase data (users, patients, visits, medicines, queue, appointments).
Imported users receive random temporary passwords and must change them at first login (PRD AUTH-5).

## 5. Non-functional requirements

| Area | Requirement | Status |
| --- | --- | --- |
| Security | Tenant isolation on every query; CSRF protection; CSP and security headers; no secrets in the repository; production refuses to start with a weak `SECRET_KEY` | Implemented |
| Privacy | Patient data may include NRIC and medical history. Operators must run the service under applicable law (e.g. Singapore PDPA): TLS everywhere, access limited to authorised accounts, backups encrypted at rest, deletion on request (account deletion removes all data). *This document is not legal advice.* | Partly implemented (see §10) |
| Availability | Stateless web tier, ≥ 2 replicas, rolling updates with no downtime, PodDisruptionBudget, readiness/liveness probes | Implemented |
| Performance | Typical page renders < 300 ms for a clinic-sized dataset (thousands of patients); list pages query only the owner's rows through indexes | Target |
| Scalability | Horizontal scaling through the HPA; shared rate-limit state in Redis | Implemented |
| Data durability | PostgreSQL with daily logical backups (in-cluster overlay) or managed backups; restore procedure documented | Implemented |
| Accessibility / browsers | Current Chrome, Edge, Safari, Firefox; mobile-friendly layout (Bootstrap) | Target |
| Maintainability | Application factory + blueprints, automated tests on PostgreSQL, linting, docs kept in sync by CI | Implemented |

## 6. Release and deployment requirements

* Single container image published by CI; configuration only through environment variables and Secrets.
* Database changes only through Alembic migrations, applied by a Job before rollout; backward-compatible for one release.
* First super admin created by a bootstrap step, never through the public UI.
* Reference production target: a single AWS EC2 instance running k3s, a DuckDNS sub-domain with a Let's Encrypt
  certificate, and nightly database backups to a private encrypted S3 bucket (runbook: `docs/deployment.md`).
  High availability (EKS + RDS, custom domain) is a later step.
* Public deployment needs: a hostname with a TLS certificate, a managed PostgreSQL (or the in-cluster overlay with
  off-cluster backup copies), a `SECRET_KEY`, and the bootstrap admin credentials (see `docs/deployment.md`).

## 7. Success metrics

* 0 cross-tenant data exposures (guarded by automated isolation tests).
* Stock discrepancies after dispensing/void cycles: 0 in automated tests.
* Median time from "confirm visit" to "receipt PDF" < 1 minute for front-desk staff.
* Deployment frequency without downtime; mean time to restore from backup < 1 hour.

## 8. Dependencies and assumptions

* Bootstrap, FullCalendar and html5-qrcode are loaded from public CDNs; the camera scanner needs HTTPS and a camera.
* One account = one clinic = one data set. Several people who must share data currently share one login.
* The receipt header is configured per deployment (single clinic identity), not per account.

## 9. Resolved decisions

| Decision | Outcome |
| --- | --- |
| Database | Firebase/Firestore replaced by PostgreSQL |
| Authentication | Firebase Auth replaced by local accounts with hashed passwords |
| Hosting | Docker image on Kubernetes (manifests provided) |
| Roles | Dashboard/exports restricted to `admin`; user management restricted to `super_admin` |
| Dead features | The unreachable prescription-creation page and prescription receipt route were removed |
| Login identifier | Username (previously a Gmail address was synthesised from the typed name) |

## 10. Known limitations and roadmap

| Item | Priority |
| --- | --- |
| Several users per clinic (shared tenant) with per-user roles (physician vs front desk) | High |
| Per-clinic receipt header and logo (currently per deployment) | High |
| Batch-aware dispensing (FEFO: first-expiry-first-out across batches, expiry warnings) | High |
| Audit log of who viewed / changed patient records; data export and erasure tools for patients | High |
| Multi-factor authentication and password-reset by e-mail | Medium |
| Stricter CSP (remove inline scripts, add SRI or self-host CDN assets) | Medium |
| Metrics endpoint and tracing; alerting on low stock / expiring batches | Medium |
| Receipt numbering sequence and stored receipts (currently generated on demand, numbered by timestamp) | Medium |
| Pagination for very large patient / inventory lists | Low |

## 11. Open questions

1. Which jurisdictions will host clinics (data-residency and retention rules)?
2. Should receipts be immutable records (legal numbering) rather than generated on demand?
3. Is a shared-tenant model (clinic with several users) required before public launch?

## 12. Change log

| Date | Change |
| --- | --- |
| 2026-11-07 | §6: nightly S3 backup job made reliable on k3s (waits for PostgreSQL before dumping); AWS runbook verified end to end |
| 2026-11-07 | §6: release image build now works for mixed-case GitHub owners (lower-cased registry path) |
| 2026-11-07 | §6: documented the AWS reference deployment (EC2 + k3s + S3 backups + DuckDNS) |
| 2026-11-06 | Initial PRD written from the codebase after the PostgreSQL / Kubernetes migration. Documents roles, journeys, requirements AUTH-1…DASH-2, NFRs and roadmap |
