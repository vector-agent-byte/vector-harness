# Vector Harness frontend

React and TypeScript views consume server-owned tasks. Start the development server with `npm run dev`; `/api` is proxied to `127.0.0.1:8787` (override with `VECTOR_WEB_PORT`).

## Feature boundaries

- `src/features/agent/`: agent API transport, session/SSE and settings controllers, file browsing, transcript navigation, layout, and focused presentation components. Root `App.tsx` composes the application shell.
- `src/features/deepresearch/`: research view, interaction hook, and server snapshot types.
- `src/features/autoresearch/`: modeling view, interaction hook, log formatting, form defaults, and server snapshot types. `demo.ts` contains isolated demonstration fixtures.
- `src/features/tasks/`: typed API transport, shared task loading/stream lifecycle, and legacy import.
- `DeepResearch.tsx`, `SelfModeling.tsx`, `deepResearch.ts`, and `modeling.ts` remain compatibility entrypoints. The saved application view `modeling` remains supported.

The browser sends configuration and user follow-up text. Prompt construction, configuration validation, report parsing, research projection, experiment ranking, baseline selection, and improvement calculations belong to the backend. The chart uses server-selected best/baseline IDs and improvement; its best-result reference line represents the server-selected result. Sorting and filtering only change presentation. Raw execution messages remain available in logs.

## Task transport

| Request | Payload / response |
| --- | --- |
| `POST /api/deepresearch/tasks` | `{topic, engine}` → task identity/configuration with `status: "idle"` |
| `POST /api/autoresearch/tasks` | `{config, parentSessionId?, parentExperimentId?}` → idle task |
| `GET /api/{kind}/tasks` | `{tasks, running_id}` |
| `GET /api/{kind}/tasks/:id` | `{task, messages, warnings}` |
| `POST /api/{kind}/tasks/:id/run` | `{}` → existing SSE events, additive `task_snapshot`, and `run_result` |
| `POST /api/deepresearch/tasks/:id/messages` | `{text}` → continuation SSE stream |
| `POST /api/{kind}/tasks/:id/stop` | `{}`; reload authoritative detail |
| `DELETE /api/{kind}/tasks/:id` | Delete a task |
| `GET /api/autoresearch/options` | `{defaults, fields, enums}`; drive form defaults, selectors, bounds, and conditional requirements |

`kind` is `deepresearch` or `autoresearch`. Dates use server epoch seconds. Task statuses are `idle`, `running`, `completed`, `stopped`, `error`, and `interrupted`. The generic agent list requests `/api/sessions?kind=agent`.

The shared hook uses `api.ts`'s SSE reader. It applies increasing snapshot revisions, polls task lists and selected/running details every three seconds, and reloads detail after every stream termination, including disconnects and request errors. A dropped stream never changes the task status locally. Polling continues to recover authoritative state. Research details and selection use stable task IDs. Continuations send parent identities, never browser-cached experiments; demo configuration can be copied into a fresh task without a server parent.

Missing tasks are removed from both list and detail caches. Successful deletion and accepted task lists invalidate older requests so late responses cannot restore deleted selections. Detail errors from a previous selection do not appear on the current selection. Research subtasks retain the backend `unknown` status; detail/source `inferred` flags display explicit unverified-inference labels.

AutoResearch form choices come from field enums or the options enums, including metric choices by task. Numeric ranges, metric-specific maxima, integer steps, and conditional required fields use typed field metadata. Switching task type uses the first server-listed metric and `fields.threshold.defaultByTask`; templates retain descriptive content but use the same server defaults. Late options replace untouched placeholder values while preserving individually edited draft fields. Launch remains disabled until options load.

## Legacy records

Migration reads `vh-research-ids` / `vh-research-meta` and `vh-modeling-sessions-v1`, then posts only `{id, kind, config}` to `/api/tasks/import-legacy`. Stored status, score, reports, and output never populate live task views. Only `imported` and `already_imported` items are removed, after checking storage has not changed during the request. Concurrent mounts share an import request. Failed, conflicting, missing, and malformed records remain available with a raw JSON export link. The export preserves the original storage strings. Browser drafts and UI preferences remain local.

## Verification

Run `node --test *.test.ts` and `npm run build` from `web/`. The Node suite covers transport, migration, server-authoritative result display, presentation, and compatibility.

`modeling.browser.mjs` runs the existing Chrome smoke suite against a development server on port 5181, using mocked task APIs and isolated browser storage. It exercises layout, navigation, metadata-driven forms, SSE logs, history reload, stop errors, disconnect recovery, research task identity after reordering, unknown status, inference labels, deletion/navigation races, follow-up requests, and mobile overflow. Set `CHROME_PATH` or `BROWSER_DEBUG_PORT` if needed. Run it with `node modeling.browser.mjs`; it writes screenshots to the system temporary directory.

`backend.browser.mjs` starts a real Python WebServer with a scripted provider in a temporary workspace and serves the production build. After `npm run build`, run `node backend.browser.mjs` with optional `PYTHON_PATH` and `CHROME_PATH` overrides. It checks research, modeling and agent workflows through the actual HTTP/SSE endpoints, verifies persisted reloads, and cleans up its server and browser profile. It performs no external model calls or real training.
