# ClassFlow MVP — Design

- **Date:** 2026-11-15
- **Status:** Approved 2026-11-15
- **Author:** Fatemeh Pakpour (with Claude as architect/reviewer)

## 1. Intent and the why

A single Danish sports club (~1,000 members, one hall) runs class registration
through WhatsApp messages to admins, who then update a spreadsheet by hand.
This causes two problems:

1. **Overbooking.** There is no single live count of places. Several admins and
   several chats mean members are told "yes" before (or without) the sheet
   being updated.
2. **Admin overload.** Every booking, cancellation and "is there space?"
   question goes through an admin.

ClassFlow replaces the WhatsApp + spreadsheet booking workflow with a system
where members book and pay for classes themselves, capacity is enforced by the
system, and admins move from data entry to oversight.

This is a real project for a real club. It is built and maintained by one
developer, with a target launch **~3 months from 2026-11-15 (mid-February 2027)**
on a **small hosting budget**.

## 2. Goals, non-goals, anti-goals

### Goals (MVP)
- Members self-serve: sign up, browse the timetable, book, pay, cancel, join a
  waitlist, see their bookings.
- **Never overbook** — not under concurrent booking, not via waitlist, not via
  late payments, not via admin action.
- Online payment per class by **card and MobilePay** via Stripe; a booking is
  confirmed only after Stripe confirms payment.
- Automatic refunds according to the club's policy.
- Admins manage class types, weekly schedules, sessions, instructors and
  exceptions (cash bookings, goodwill refunds), with an audit trail.
- Instructors see their attendee lists and mark attendance.
- Admin **CSV export** of payments, refunds and cash bookings for a chosen date
  range, so the treasurer can reconcile with Stripe payouts. Member receipts
  are Stripe's automatic email receipts.

### Non-goals (explicitly later, not MVP)
- Memberships, subscriptions, class packs, credits or member-only pricing.
- Partial refunds.
- No-show penalties (attendance is recorded only).
- SMS / push notifications (email only).
- Native mobile app (responsive web only).
- Multiple halls/locations, multiple clubs (multi-tenancy).
- Reporting/analytics beyond simple lists and the payments CSV export.
- Booking on behalf of others (family/junior accounts). **Every participant is
  an adult with their own account** — the booker is always the participant.
- Generating VAT invoices (Stripe receipts + CSV export are sufficient for the
  MVP).
- Saving cards / automatic charging (incl. for waitlist).
- Migrating historical spreadsheet data.

### Anti-goals (failure even if it "works")
- Any path that lets confirmed bookings exceed capacity.
- A member charged without getting a place, and not refunded automatically.
- Trusting the browser about who the user is, their role, or whether they paid.
- Infrastructure a single developer cannot operate (no microservices, no
  Kubernetes, no message broker).
- Exposing members' personal data to people who don't need it (e.g.
  instructors seeing emails/payments).

## 3. Users and roles

| Role | Who | Can do |
|---|---|---|
| **Visitor** | Not logged in | Browse timetable and availability. |
| **Member** | Anyone who signs up (no approval) | Book & pay, cancel, join/leave waitlist, accept waitlist offers, see own bookings and payment status, edit own profile. |
| **Instructor** | Club staff, role assigned by admin | See **only their own** sessions; see attendee names; mark attendance. |
| **Admin** | Club staff, role assigned by admin | Everything: class types, schedules, sessions, instructors, all bookings, manual cash bookings, goodwill refunds, audit log. |

- Roles are stored in ClassFlow's database and checked on the server for every
  request. A user may hold more than one role (e.g. an instructor who also
  books classes as a member).
- The first admin is created by a one-off command/seed, not via the UI.

## 4. Business rules

### 4.1 Timetable
- **Class type:** name, description, price (DKK, integer øre), default capacity,
  duration. Created by admins.
- **Weekly schedule:** class type + weekday + start time + instructor +
  date range (start/end date). ClassFlow generates **sessions** from it.
- **Session:** a single dated occurrence with its own start time, duration,
  capacity, price and instructor (copied from schedule/class type at generation
  time; editable per session). Sessions are what members book.
- Per-session admin changes: cancel, change time, change capacity, swap
  instructor — without affecting the rest of the schedule.
- **One hall → no overlapping sessions.** Creating/moving a session or schedule
  that overlaps an existing non-cancelled session is rejected.
- **Booking horizon:** members can book sessions starting within the next
  **4 weeks**. Sessions are generated at least that far ahead.
- All times are stored in UTC and displayed/evaluated in **Europe/Copenhagen**
  (DST-aware). Weekly schedules are defined in local time.
- **Price is locked at booking time.** Later price changes don't affect
  existing bookings.
- Capacity cannot be lowered below the current number of places taken
  (confirmed + held).
- **Editing a weekly schedule** (time, weekday, instructor, capacity, end date)
  applies only to its **future sessions that have no bookings or waitlist
  entries**. Sessions with bookings are changed one at a time (see next rule),
  so admins consciously handle affected members. Shortening the end date never
  deletes booked sessions; the admin must cancel them explicitly. *(Architect's
  call.)*
- **Club-initiated session change** (time moved): booked and waitlisted members
  are emailed, and booked members may cancel with a **full refund regardless of
  the 24h rule** until session start (booking flagged refund-eligible).
  Instructor swaps need no notification. *(Architect's call.)*

### 4.2 Booking and payment
- A member may have **at most one active booking or waitlist entry per
  session** (active = pending payment, confirmed, or waitlisted/offered).
- Booking flow:
  1. Member taps **Book** → server, under a lock on the session, checks
     capacity. Places taken = confirmed + pending-payment holds + active
     waitlist offers.
  2. If a place is free → create booking in **pending payment** with a hold of
     **15 minutes** (builder's call within 10–20 min; see 6.3), create a Stripe
     Checkout Session (card + MobilePay, DKK), redirect member to Stripe.
  3. Stripe webhook (`checkout.session.completed` with paid status) →
     booking becomes **confirmed**. The browser redirect back to ClassFlow is
     **never** treated as proof of payment.
  4. Hold expires or member abandons → booking becomes **expired**, place
     released, and ClassFlow expires the Stripe Checkout Session via the API.
  5. **Late payment** (Stripe reports payment success for a booking that is no
     longer holding a place): if a place is still free, confirm it; otherwise
     **refund automatically** and notify the member.
- Bookings close at session start time.
- Every booking and refund is processed **idempotently**: duplicate or
  out-of-order Stripe events must not double-confirm, double-refund or
  double-count.

### 4.3 Cancellation and refunds
- **Member cancels ≥ 24h before start** → booking cancelled, place released,
  **full automatic refund** via Stripe.
- **Member cancels < 24h before start** → allowed (place released) but **no
  refund**. The UI states this clearly before confirming.
- **No-show** → no refund.
- **Club cancels a session** → all confirmed card bookings refunded
  automatically; pending holds and waitlist entries released; all affected
  members emailed. Cash bookings appear on an admin "to settle" list.
- The 24h cut-off is computed on the server against session start time.
- Stripe processing fees on refunds are borne by the club (club to confirm
  they accept this).

### 4.4 Waitlist
- When a session is full, a member can **join the waitlist** (free, ordered by
  join time).
- When a place opens (cancellation, expired hold, capacity increase, declined
  or expired offer), the first waiting member gets an **offer**: an email saying
  the place is held for them for **2 hours**. The offered place counts as taken.
- Member pays within the window (same Checkout flow; the booking hold is
  bounded by the offer expiry) → confirmed. Declines or times out → next in
  line.
- **Late cut-off:** if less than 2 hours remain before session start, no new
  offers are made; freed places become normally bookable (first come, first
  served) and remaining waitlisted members are emailed that a place is open.
  Any running offer ends at session start at the latest.
- At session start, the waitlist closes; remaining entries are marked expired.
- A member promoted within 24h of the session is already inside the
  no-refund window; this is shown before they pay.

### 4.5 Attendance
- Instructors see their sessions with attendee **names only** (confirmed
  bookings) and the waitlist count.
- Instructors mark each attendee present/absent from shortly before start
  until 24h after start; after that only admins can change it.
- Attendance is recorded only; no automatic consequences.

### 4.6 Admin exceptions
- **Manual cash booking:** admin books a member into a session marked *paid
  cash*. Respects capacity. To add someone to a full session, the admin must
  first raise capacity (a separate, logged action).
- Cancelling a cash booking records the cancellation; admin marks it
  *refunded in cash* when settled. ClassFlow never issues Stripe refunds for
  cash payments.
- **Goodwill refund:** admin can fully refund any card booking at any time
  (incl. < 24h or after a no-show). If the session hasn't started, the booking
  is cancelled and the place released.
- **Audit log:** every manual booking, refund, capacity change, session
  change/cancellation and role change records actor, timestamp, target and a
  **required reason**. Audit records are append-only.

### 4.7 Notifications (email)
Booking confirmed, booking cancelled (+ refund status), refund issued, session
cancelled by club, session time changed by club (with free-cancellation
notice), waitlist offer (with deadline), waitlist offer expired, place-open
notice (late cut-off), late-payment refund, refund failed (to admins).

### 4.8 Privacy (GDPR — the club is in Denmark)
- Collect only what's needed: name, email, optionally phone.
- Instructors see names only.
- Member can delete their account from their profile. Deletion is **blocked
  while they have upcoming bookings or waitlist entries**; the UI asks them to
  cancel those first (normal 24h rules apply). This keeps deletion a simple
  anonymise step and avoids refunds to a deleted contact. *(Architect's call.)*
  On deletion, personal data is removed/anonymised while payment/booking
  records needed for bookkeeping are kept in anonymised form; the Auth0 user
  is deleted too.
- Data hosted in the EU.
- Card data never touches ClassFlow (Stripe Checkout handles it).
- Never log secrets, access tokens or full payment payloads.

## 5. Approaches considered

All three share the same core: one PostgreSQL database, capacity enforced in
the database, Stripe Checkout + webhooks, a background worker with a
Postgres-backed job table.

| | Approach | Trade-off |
|---|---|---|
| **A** | **FastAPI JSON API + separate Next.js (React, TypeScript) frontend; Auth0** | Modern UI, clean API usable by a future mobile app. Two codebases/deployments in two languages; more integration work (API contract, auth between apps). |
| B | FastAPI with server-rendered pages (Jinja2 + HTMX); Auth0 | One codebase and deployment, least work, cheapest to host. Less modern UI; JSON API needed later for mobile. |
| C | Start as B, migrate to A | Pays A's costs without its benefits during the MVP. Rejected. |

Also noted: off-the-shelf Danish club systems (e.g. Holdsport, Conventus) cover
much of this. Worth the club confirming why they're not suitable.

**Chosen: A.** Architect's recommendation was B given one developer, 3 months
and a small budget. The developer chose A to practise React/Next.js for the job
market — a legitimate goal. Mitigation: keep the frontend deliberately plain
(no complex client state, no design system work) so the time goes into the
booking/payment core, which is where the risk is.

## 6. Design

### 6.1 System overview

```
 Browser ──► Next.js (React, TS) ──► FastAPI (JSON API) ──► PostgreSQL
               │  Auth0 login            │      ▲                ▲
               ▼                         │      │ webhooks       │
             Auth0                       ▼      │                │
                                      Stripe ───┘          Worker (same codebase
                                                           as FastAPI): expiries,
                                                           waitlist offers,
                                                           emails, refunds
```

- **Modular monolith backend** — one FastAPI codebase with modules:
  `accounts` (users, roles, profile), `timetable` (class types, schedules,
  sessions), `booking` (bookings, waitlist, capacity, attendance),
  `payments` (Stripe checkout, webhooks, refunds), `notifications` (email),
  `audit`.
- Each module separates **HTTP routers** → **services (business rules)** →
  **repositories (DB access)**, per CLAUDE.md. Modules call each other through
  service functions, not each other's tables.
- **Worker:** a separate process from the same codebase, running a loop that
  claims due jobs from a Postgres `jobs` table (`SELECT … FOR UPDATE SKIP
  LOCKED`) and runs periodic sweeps (expire holds/offers, issue offers, close
  waitlists at start). No Redis/Celery.
- **Next.js frontend:** separate app (proposed location: `frontend/` in the
  same repo — builder's call). Uses Auth0's Next.js SDK for login and obtains
  an access token to call FastAPI.

### 6.2 Authentication and authorisation
- Auth0 handles sign-up, login, password reset (email + password; social
  login optional later).
- FastAPI validates the Auth0 **access token (JWT)** on every request
  (signature via Auth0 JWKS, issuer, audience, expiry).
- On first request, FastAPI creates a local `user` row keyed by Auth0 `sub`.
- **Roles live in ClassFlow's database**, not Auth0, and are checked
  server-side. The frontend hides/shows UI based on roles fetched from the
  API, but the API is the authority.
- Instructor endpoints filter to sessions where the caller is the instructor.

### 6.3 Capacity and concurrency (core invariant)
- Invariant: for every session,
  `confirmed + active pending holds + active waitlist offers ≤ capacity`.
- Every operation that consumes or releases a place (book, cancel, expire,
  offer, accept, capacity change, manual booking, session cancel) runs in a
  transaction that first takes a **row lock on the session**
  (`SELECT … FOR UPDATE`), recounts, then writes.
- A partial unique index enforces **one active booking/waitlist entry per
  member per session**.
- Hold expiry is enforced both by the worker sweep and by treating expired
  holds as not counting when computing capacity (so a slow worker can't block
  bookings).
- **Stripe constraint (verified in Stripe docs):** a Checkout Session's
  `expires_at` must be 30 min–24 h after creation, so it cannot match a
  15-minute hold. ClassFlow therefore sets the shortest allowed Stripe expiry
  and **explicitly expires the Checkout Session** via the API when its own hold
  ends. Any payment that still slips through is handled by the late-payment
  rule (confirm if space, otherwise auto-refund).

### 6.4 Payments
- Stripe Checkout (hosted), `mode=payment`, currency DKK, payment methods
  card + MobilePay. MobilePay confirmation is immediate per Stripe docs.
- One Checkout Session per booking attempt; booking id in Checkout metadata
  and as idempotency key on creation.
- Webhook endpoint verifies the Stripe signature, stores each event id in a
  `stripe_events` table (unique) before processing — duplicates are no-ops.
- Events handled at minimum: `checkout.session.completed`,
  `checkout.session.expired`, refund outcome events.
- Refunds are created with an idempotency key derived from the booking id +
  refund reason, so retries never double-refund. Refunds are executed by the
  worker as jobs (retry with backoff on Stripe errors).
- Payment record per booking: amount, currency, method, Stripe ids, status
  (pending, paid, refunded, refund_failed, cash, cash_refunded).
- Amounts stored as integers (øre).

### 6.5 Data model (outline)
`users` (auth0_sub, name, email, phone, deleted_at), `user_roles`,
`class_types`, `schedules`, `sessions`, `bookings` (status: pending_payment,
confirmed, cancelled, expired, refunded…, hold_expires_at, price_locked,
source: online/cash), `waitlist_entries` (status: waiting, offered, accepted,
declined, expired; offer_expires_at), `payments`, `refunds`, `attendance`,
`stripe_events`, `jobs`, `audit_log`.
Exact columns and state machines are the builder's to detail in the plan.

### 6.6 Main screens
- **Public/member:** timetable (week view, places left, price, Book / Join
  waitlist), booking confirmation/return page, My bookings (cancel, refund
  status, accept/decline offer), profile + delete account.
- **Instructor:** my sessions, attendee list with present/absent toggles.
- **Admin:** class types, schedules (generate sessions), session detail
  (attendees, waitlist, cancel, change capacity/time/instructor, manual cash
  booking, goodwill refund), users & roles, cash "to settle" list, failed
  refunds list (retry), payments CSV export, audit log.

### 6.7 Hosting and operations (small budget)
- A single EU-hosted small VPS running Docker Compose: Next.js, FastAPI,
  worker, PostgreSQL, reverse proxy with TLS. (Vercel's free tier is not for
  commercial use, so the frontend is self-hosted too.) Provider is the
  builder's call.
- Daily automated Postgres backups stored off the server; restore tested once
  before launch.
- Transactional email via a low-cost provider with an EU option (builder's
  call).
- Secrets via environment variables, never committed or logged.
- Stripe test mode + Stripe CLI for local webhook testing.

### 6.8 Testing focus
- Unit tests for business rules (refund window, waitlist ordering and
  cut-offs, capacity math, DST edge cases).
- Integration tests against a real PostgreSQL for concurrency: N parallel
  booking attempts for the last place → exactly one wins.
- Webhook tests: duplicate events, out-of-order events, late payment after
  hold expiry.
- Authorisation tests: members can't see others' bookings; instructors only
  their sessions; only admins can do admin actions.

## 7. Existing code (as of 2026-11-15)
- uv / Python 3.14 project with FastAPI and pydantic-settings; dev tools
  pytest, ruff, mypy, httpx.
- `src/classflow_fastapi/__init__.py`: FastAPI app with a `/health` endpoint —
  currently has an **indentation error** (decorator/function over-indented), so
  the module does not import.
- `pyproject.toml` declares script `classflow_fastapi:main`, which doesn't
  exist.
- `src/test.py`: stray scratch function.
- No database layer, models, auth, tests, or frontend yet.
These should be fixed/cleaned up as the first step of the implementation plan.

## 8. Decided vs left to the builder

**Decided by the club/developer:** pay-per-class; card + MobilePay via Stripe;
confirmed only after payment; full refund ≥24h, none <24h; club cancellation
auto-refunds; open sign-up; all participants are adults with their own
accounts; payments CSV export in MVP; waitlist with 2-hour offer; weekly repeating
classes, per-class prices, one hall; instructors see attendees and mark
attendance; admin cash bookings and goodwill refunds; Next.js + React frontend
with FastAPI backend; solo developer, ~3-month launch, small budget.

**Architect's calls (correct if wrong):** 15-minute payment hold;
4-week booking horizon; members may still cancel <24h without refund; full
goodwill refunds only; attendance recorded with no penalties; email-only
notifications; instructors see names only; audit log with required reason;
roles stored in ClassFlow DB; Postgres-backed worker instead of a queue;
single-VPS Docker Compose hosting; late payment → confirm if space else
auto-refund; schedule edits only touch unbooked future sessions; club time
change → notify + full refund right; account deletion blocked while upcoming
bookings exist.

**Launch risk / club action item:** the club needs a Stripe account in its own
name, verified, with MobilePay enabled. Verification can take weeks — start it
early so the February launch doesn't slip on paperwork. Club also to confirm it
accepts Stripe fees on refunds.

**Left to the builder:** ORM/migration tooling (SQLAlchemy + Alembic expected
per CLAUDE.md), email provider, VPS provider, exact schema and state machines,
UI component library, repo layout for the frontend, worker polling interval.
