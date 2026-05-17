# API Access Discovery

Use this only when the server-side IM agent needs to establish or diagnose API access.

Do not perform discovery before every normal API call. Prefer reusing the runtime's configured API client or a client already validated during the current task.

Run discovery when:

- no `base_url` or API client is configured
- `BACKTEST_DATA_API_TOKEN` is not configured and no token is available from the runtime secret/config channel
- the user asks whether this server can reach the home/local backtest backend
- a call returns `401`, `403`, `404`, timeout, DNS error, connection refused, TLS error, or `502`/`503`/`504`
- the operator changed the base URL, token, or forwarding path

## Inputs

Find API client inputs in this order:

1. Existing runtime API client, if the host application provides one.
2. Environment variables:
   - `BACKTEST_DATA_API_BASE_URL`: HTTP origin that should reach the backtest data-source API from this server runtime.
   - `BACKTEST_DATA_API_TOKEN`: bearer token for the data-source API.
3. Runtime secret/config channel supplied by the host application.
4. Ask the user/operator for only the missing value.

Use `BACKTEST_DATA_API_TOKEN` as the client-side token variable. Do not read `FRP_TOKEN`. Use `BACKTEST_DATA_SOURCE_TOKEN` only when the runtime explicitly documents it as a compatibility alias for API clients.

Never print, echo, log, or summarize token values in chat. It is safe to say the token is configured, missing, rejected, or expired.

## Probe Sequence

Normalize `base_url` by removing trailing slashes, then probe in order:

```text
GET <base_url>/api/health
GET <base_url>/api/data-sources
```

Both requests must include:

```text
Authorization: Bearer <configured token>
```

Interpretation:

- `200 /api/health`: the current server can reach a backtest data-source service.
- `200 /api/data-sources`: the API is usable for source-aware operations.
- `401` or `403`: endpoint exists but token is missing, wrong, or unauthorized.
- timeout, DNS error, connection refused, TLS error, or `502`/`503`/`504`: the current server cannot currently reach the local backtest service through its configured path.
- `404`: the base URL is probably wrong or points at a non-backtest service.

## Behavior

If discovery fails, stop before job submission, retry, or data reads. Report the failure category and ask for a corrected `base_url`/token or for an operator to repair the forwarding path.

If discovery succeeds, treat the API client as available and reuse it for later calls. Do not repeat health probes unless a later call fails, configuration changes, or the user explicitly asks for a connectivity check.

Do not mention whether the path uses Nginx, frp, or direct networking unless the probe result or user-provided configuration proves it.
