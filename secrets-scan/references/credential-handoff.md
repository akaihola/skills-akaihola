# Credential checks and Hermes handoff

Verified 2026-11-10 against a retained Matrix credential, a Gemini model-list
request, and a local Hermes installation. These notes cover checks explicitly
authorized by the user; they do not authorize revocation or a paid model call.

## Matrix

Read the homeserver and access token from the private environment file in the
same process that makes the request. Use the Authorization Bearer header, not a
command-line token or query parameter. Print only HTTP status and error fields.

- `GET /_matrix/client/v3/account/whoami` checks whether the saved token works.
- `GET /_matrix/client/v3/devices` lists devices only when the token is valid.
- HTTP 401 with `M_UNKNOWN_TOKEN` and `soft_logout: false` confirmed that the
  tested token could not authenticate. It does not establish why it stopped
  working, when that happened, or whether other account sessions remain.
- A rejected token cannot establish that a human has a logged-in Matrix client.
  Check the exact account before suggesting a device logout: another agent can
  use a different Matrix account on the same homeserver.

The [Matrix API specification](https://spec.matrix.org/latest/client-server-api/#common-error-codes)
defines the error fields. Logging a valid token out through the API was not
tested in this handoff; keep that path labelled untested.

## Hermes and Gemini

Inspect the installed Hermes code before relying on its environment behavior.
In the tested installation, the application virtual environment supplied
python-dotenv; the system interpreter did not.

- Hermes' `load_hermes_dotenv` loads the profile's `.env`, normally
  `~/.hermes/.env`. Its values take precedence over project `.env` fallback.
- The Gemini credential resolver accepts `GOOGLE_API_KEY` and `GEMINI_API_KEY`.
  Compare existing values in memory and resolve a conflicting destination key
  before replacing anything. Keep unrelated credentials and the default model.
- After writing the retained key with mode 0600, test both dotenv loading and
  `resolve_api_key_provider_credentials("gemini")`. Compare the resolved key to
  the source value in memory; print only the match result.
- `GET https://generativelanguage.googleapis.com/v1beta/models?pageSize=1` with
  the `x-goog-api-key` header returned HTTP 200 for the resolved key. This checks
  credential acceptance for metadata access; it does not prove that generation
  works or establish its quota or billing status. No generation was requested.
- The inspected gateway code reloads credentials at turn boundaries. This was
  code inspection, not verification of a subsequent gateway turn. Distinguish
  fresh-process resolution from a running gateway's behavior in reports.
- The virtual environment's Python initially failed TLS certificate validation.
  Using `ssl.create_default_context(cafile="/etc/ssl/certs/ca-certificates.crt")`
  succeeded with verification enabled. Resolve the host's actual CA bundle;
  keep certificate verification enabled.

Google documents header authentication in the
[Gemini API reference](https://ai.google.dev/api).
