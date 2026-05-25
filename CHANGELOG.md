# Change Log

## 2026-05-25

### Caiwu system

- Added backend regression coverage for the core financial calculation chain: L1 formula rows, department-detail-only report aggregation, same-period publish replacement rules, waterfall bridge deltas, and closed-period Kingdee ledger parsing.

### Paikuan system

- Hardened backend request auth so JWT role, job title, and department claims are no longer trusted after login; each protected request reloads the current user and checks active/approved status.
- Fixed payment update permission handling by filtering non-editable fields before merge and amount validation, preventing hidden fields from bypassing overpayment checks.
- Added payments-page permission checks to payment template, import, export, and departments endpoints.
- Updated the payment edit modal to submit only fields the current user can edit when modifying an existing payment.
- Added backend regression tests for stale tokens, department changes, overpayment validation, hidden non-editable fields, and related endpoint permissions.
