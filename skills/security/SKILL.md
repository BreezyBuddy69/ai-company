# Security

- Treat all user input, API responses, and file contents as untrusted.
- Never build a feature that stores credentials or payment details insecurely
  or collects them under false pretenses.
- No SQL string concatenation — parameterized queries only.
- No secrets in code, logs, or committed files — env vars / secret stores
  only.
- Never fake trust signals (fake reviews, fake urgency counters, fake
  security badges) — this violates the company's core "never manipulate
  users" rule regardless of conversion impact.
