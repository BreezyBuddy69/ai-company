# Debugging

- Reproduce before you theorize. A fix for a bug you haven't reproduced is a
  guess, not a fix.
- Find the root cause, not the nearest workaround — a caught exception that
  hides the real failure just moves the bug somewhere harder to find.
- Read the actual error message and stack trace fully before searching for
  the fix elsewhere.
- After fixing, explain in one sentence why the bug happened — if you can't,
  you probably patched a symptom.
