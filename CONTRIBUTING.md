# Contributing

Contributions that improve reliability across Anaplan regions, login flows,
macOS, or Windows are welcome.

1. Fork the repository and create a focused branch.
2. Do not commit `.env`, browser profiles, logs, diagnostics, webhook URLs, or
   real Anaplan workspace/model identifiers.
3. Keep live operations opt-in and preserve dry-run behavior.
4. Run the tests before opening a pull request:

   ```bash
   .venv/bin/python -m unittest discover -s tests -v
   ```

Describe the Anaplan page state or failure mode your change handles. Use
sanitized fixtures and screenshots only.
