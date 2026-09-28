# Frontend: Angular micro-frontends

Angular 22 workspace with **Native Federation**. A shell (host) loads each micro-frontend at runtime.
Every agent team owns its own micro-frontend, next to the platform ones. All calls to the backend use
`@langchain/langgraph-sdk` against the orchestrator (LangGraph Agent Server :8100).

```
frontend/
├── angular.json · package.json · tsconfig.json · proxy.conf.json
├── apps/                                   [frontend team]
│   ├── shell/        :4200  host: layout, navigation, loads remotes, provides the agent-widget loader
│   │   └── public/federation.manifest.json   remote name → URL (swap per environment)
│   ├── flow/         :4201  Multi Agent Flow: run a task → live flow diagram + approvals/clarifications
│   ├── runs/         :4202  run history + run detail (flow diagram, results, full state)
│   ├── approvals/    :4203  HITL inbox: threads.search({status: "interrupted"})
│   └── admin/        :4204  agents the supervisor can use (/platform/agents) + policies
├── agents/                                 [one owner per agent, same person as the backend agent]
│   ├── web-search-ui/     :4301  ./Routes (agent page) · ./Widget (findings view)
│   ├── communication-ui/  :4302  ./Routes · ./Widget (email approval form + sent view)
│   ├── verifier-ui/       :4303  ./Routes · ./Widget (verdict view)
│   └── rag-ui/            :4304  ./Routes (document ingestion: upload files to the Rag agent :8000)
└── libs/shared/                            [frontend team] @altasnim/shared (singleton at runtime)
    ├── styles/theme.css         design tokens (light/dark), imported by every app
    └── src/lib/
        ├── models.ts            TS mirror of backend contracts (Plan, Step, AgentResult, interrupts…)
        ├── orchestrator.service.ts  LangGraph SDK: threads, runs.stream / wait, threads.search
        ├── run-session.ts       one flow thread as signals (values + custom events)
        ├── flow/                flow-model (plan → stages/nodes/edges), flow-diagram (SVG), flow-icons
        ├── agent-widget.ts      AgentWidget contract + AGENT_WIDGET_LOADER token
        └── ui/                  step-result, decision-panel, status-badge, json-view, agent-card-view
```

Each app folder is standard Angular: `federation.config.mjs` (name + exposes), `src/main.ts` (initFederation),
`src/bootstrap.ts`, `src/app/app.routes.ts` (exposed as `./Routes`), and the page components.

## How the pieces connect

| What | How |
|---|---|
| Shell loads a section | `loadRemoteModule('<remote>', './Routes')`. If a remote is down, only that section shows a fallback. |
| Agent-specific UI inside Multi Agent Flow / Runs / Approvals | The shell provides `AGENT_WIDGET_LOADER`, which loads `<agent>-ui/./Widget`. It uses `resultView` for results and `approvalForm` for approvals, with a generic JSON view and approve/reject as fallback. |
| Backend calls | `/api/orchestrator/*` goes to :8100 and `/api/agents/<name>/*` to that agent's custom routes (dev: `proxy.conf.json`; prod: API gateway). No CORS needed. |
| Live progress | `runs.stream(..., streamMode: ['values', 'custom'])`: state snapshots plus the node events `plan`, `step_started`, `step_finished`, `step_waiting_approval`, `final`. |
| Approvals | Interrupts come from `threads.get(...).interrupts`, and resuming is `runs.stream/wait(..., {command: {resume: decision}})`. |
| Flow diagram | `buildFlow()` in `libs/shared/src/lib/flow/flow-model.ts` turns the plan into stages: Input → Routing → Chaining / Parallelization / Reflection → Human-in-the-loop → Action → Output. Stages come from the plan's waves (`depends_on` / `after`) and each agent's `approval_mode`, so new agents appear automatically. Before a run, the diagram shows every available agent. `iconForAgent()` picks an icon from the agent's name. |

## Setup and run

Node 20+ (tested with Node 24, npm 11).

```powershell
cd frontend
npm install
npm start
```

`npm start` runs all 8 dev servers. Open http://localhost:4200.
The backend must be running (`cd backend; docker compose up`, or `langgraph dev` per agent).

Run a single app on its own (e.g. while a team works on its agent UI): `npm run start:communication-ui` → http://localhost:4302

Production build of all apps into `dist/`:

```powershell
npm run build
```

Stop `npm start` before running `npm run build`. Both write shared federation artifacts to `dist/`, and a mixed
dev/prod build fails in the browser with `ngDevMode is not defined`. If that happens: stop, delete `dist/`, start again.

## Add a UI for a new agent (e.g. `data`, port 4304)

```powershell
npx ng g application data-ui --project-root=agents/data-ui --style=css --ssr=false --skip-tests
npx ng g @angular-architects/native-federation:init --project data-ui --port 4304 --type remote
```

Then:
1. In `agents/data-ui/federation.config.mjs`, expose `./Routes` and `./Widget`
   (copy one of the existing agent UIs; the remote name must be `<agent name with ->-ui`).
2. Add `"data-ui": "http://localhost:4304/remoteEntry.json"` to `apps/shell/public/federation.manifest.json`,
   a route in `apps/shell/src/app/app.routes.ts`, and a link in the shell sidebar.
3. Add `proxyConfig` to the project in `angular.json`, and `/api/agents/data` to `proxy.conf.json`.
4. Add the owner to `.github/CODEOWNERS`.

## Rules

- A micro-frontend never imports another micro-frontend. Share code only through `libs/shared`.
- Agent UIs call only their own agent's custom routes (`agentApiUrl('<agent>')`). They never start runs
  themselves; execution always goes through the orchestrator.
- Changes to `libs/shared` affect every app, so they need frontend-lead review.
