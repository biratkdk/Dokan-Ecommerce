# Project Timeline

This document explains how the project evolved from a standard academic ecommerce build into the stronger repository state that exists now.

It is important to read this correctly:

- the original project was a final year Django ecommerce system
- the current repository is that project plus later improvements and maintenance
- this file separates the academic baseline from the extended repository state

## 1. Initial Academic Scope

The original goal was to build a complete ecommerce web application using Python and Django within a final year project context.

At the baseline stage, the project focused on:

- product catalog
- product detail pages
- account creation and login
- cart and checkout
- order placement
- order history
- Django admin usage
- relational data modeling

This stage established the foundation expected in a serious student ecommerce submission.

## 2. Core Build Phase

Once the base data model and storefront were in place, the project moved into the main implementation phase.

Key work completed in this phase:

- catalog categories and product organization
- pricing and discount-ready product structure
- reusable templates for storefront pages
- cart operations and line-item handling
- checkout flow and order persistence
- order status tracking
- initial validation of the customer journey from browsing to purchase

This is the phase where the project became more than a static frontend demo.

## 3. Quality and Workflow Expansion

After the basic commerce path worked, the project was extended with workflows that add depth during evaluation.

These additions included:

- reviews and wishlist features
- compare and recently viewed flows
- coupon handling
- richer order metadata
- account activity tracking
- email verification
- password reset
- support threads
- return requests

This phase matters academically because it demonstrates that the project handles post-purchase and account-management concerns, not just a catalog and cart.

## 4. Payment and Reliability Phase

The next stage focused on making the order pipeline more realistic.

Implemented in this stage:

- Stripe Checkout integration
- `payment_pending` order state
- payment success and cancel handling
- webhook-aware payment confirmation
- reservation expiry cleanup
- stale pending payment cleanup
- notification logging

This phase significantly improved the backend credibility of the project because payment handling is usually one of the weakest areas in student submissions.

## 5. Operations and Internal Control Phase

The repository was later improved to include internal-role and operational visibility features.

This stage introduced:

- support and operations role groups
- inventory visibility by warehouse
- reservation tracking
- operations dashboard
- inventory dashboard
- internal access separation by permission

This is the point where the project started to feel less like a simple student shop and more like a maintainable commerce system.

## 6. Inventory Maturity Phase

The biggest backend improvement after the original academic scope was inventory maturity.

This phase added:

- warehouse model
- stock levels per warehouse
- reservation-based allocation during online payment
- stock movement ledger
- controlled stock adjustments
- warehouse transfers
- stock cache synchronization
- safety-stock synchronization

This change addressed one of the most common weaknesses in ecommerce student projects: stock is no longer just a single integer field updated manually without traceability.

## 7. API and Integration Phase

To make the system more integration-friendly, the API surface was expanded.

This phase added:

- structured JSON application endpoints
- DRF-based API v2
- token authentication
- throttling
- inventory and account endpoints
- reservation and movement visibility through API

For a final year project, this adds strong technical depth because it shows the system can serve more than just template-rendered pages.

## 8. Media and Notification Hardening Phase

The repository was also improved around operational polish:

- queue-backed email outbox flow
- email delivery tracking with retry visibility
- upload-managed product media
- gallery-backed product image support

These are not mandatory for a minimum submission, but they make the codebase much stronger and easier to defend in viva.

## Semester-Oriented Summary

If this project is explained in a semester timeline, the clearest breakdown is:

### Early phase

- requirements analysis
- schema design
- storefront structure
- catalog and user account baseline

### Middle phase

- cart and checkout workflows
- order persistence
- reviews, wishlist, compare
- support for core user journey

### Late phase

- payment integration
- returns and support workflows
- testing and cleanup
- deployment preparation

### Post-baseline enhancement stream

- role matrix
- inventory reservation model
- warehouse operations
- DRF v2
- email outbox
- upload-managed media

## Repository Interpretation

The current repository should not be presented as a frozen “day one” academic submission. It is better described as:

> the original final year Django ecommerce project, later improved with stronger operational, inventory, API, and deployment features

That framing is accurate and defensible.

## Why This Timeline Matters

In review or viva, this timeline helps explain:

- what the original project scope was
- what was built during the academic cycle
- what parts were extended later for quality and maturity
- why the current repository is stronger than a basic final year submission

## Final Position

At this point, the repository represents:

- a valid final year ecommerce capstone
- a stronger-than-average 5-credit project
- a Django monolith with enough backend depth to answer technical questioning confidently

