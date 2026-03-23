# Reliability Baseline

Owner: TBD
Status: Draft
Last Updated: 2026-03-22

## Current Baseline
What works reliably today. Be honest — list only what's verified.

- [ ] Unit tests pass: `just test`
- [ ] Lint clean: `just lint`
- [ ] Architecture boundaries hold: `just arch`
- [ ] CI green on main

## Verification Commands
```bash
just ci          # all gates
just review      # full pre-push check
```

## Monitoring
<!-- What's monitored in production? Health checks, uptime, error rates. -->

## Known Gaps
<!-- What's NOT reliable yet? What fails silently? -->

## Runbook
<!-- Link to operational runbook if it exists, or inline key procedures. -->
