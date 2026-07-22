# Coding Best Practices

- Match the existing stack and conventions of the repo you're working in —
  don't introduce a new framework/library for something the stdlib or an
  existing dependency already does.
- No speculative abstraction: build for the requirement in front of you, not
  a hypothetical future one.
- Every external input (user input, API responses, file contents) is
  untrusted until validated.
- Prefer explicit, readable code over clever one-liners.
- A change that isn't tested or at least manually verified isn't done.
