# Production Acceptance Report — 2026-09-20

## Scope

Targets:

- Local application: `http://localhost:8502`
- Streamlit Community Cloud: `https://stockfinder-vkvrmef3hdzmbrudvhajtc.streamlit.app/`

No SMTP credentials, recipients, licensed-provider credentials, portfolio records,
or alert settings were created or changed during acceptance.

## Local Result: Pass

| Check | Result | Evidence |
| --- | --- | --- |
| Automated tests | Pass | 146 tests passed before deployment checks |
| Lint | Pass | Ruff reported no issues |
| Command Center | Pass | Market-risk and ranked-stock widgets rendered |
| Instrument Workbench | Pass | Instrument, score, trade-plan, and peer widgets rendered |
| Portfolio Monitor | Pass | Alert, FX, position, and watchlist controls rendered |
| Legacy navigation | Pass | Fixed Portfolio route and Stocks → Watchlist tab absent |
| Responsive layout | Pass | 390 px and 1,440 px viewports had no horizontal overflow |
| Runtime exceptions | Pass | No Streamlit traceback or application exception observed |
| Provider discovery | Pass | Four capability contracts available; zero adapters installed |

## Streamlit Community Cloud Result: Conditional Failure

| Check | Result | Evidence |
| --- | --- | --- |
| Authenticated app boot | Pass | Stockfinder shell and Command Center rendered |
| Provider download | Pass | Reached 6,196/6,196 symbols with 5,829 usable histories |
| Scan completion | Fail | Remained in sector/industry aggregation for more than 65 seconds after downloads completed |
| Full dashboard acceptance | Blocked | Ranked stocks and downstream widgets were unavailable while aggregation remained active |
| Application exception | Pass | No Streamlit traceback or application exception observed |
| Anonymous health endpoint | Fail | `/_stcore/health` returned repeated HTTP 303 redirects to `/-/login` |
| Revision parity | Not verified | The deployed revision cannot be proven from the browser and current local changes were not deployed by this acceptance run |

## Required Deployment Actions

1. Deploy the current tested revision before final Cloud acceptance.
2. Run `stockfinder-refresh` outside the web request path before users open the app.
3. Use a host with persistent `STOCKFINDER_DATA_DIR` storage, or publish a completed snapshot through an approved artifact workflow.
4. Monitor `stockfinder-health --json` from an authenticated job environment because the anonymous Streamlit health endpoint is access-controlled.
5. Re-run all three dashboard checks after a completed snapshot is available.
6. Install licensed provider adapters only after provider contracts and credentials are selected.

The Cloud deployment is reachable, but it does not currently meet ready-for-use acceptance because a cold browser session performs the full broad-market scan synchronously.
