#!/usr/bin/env node
// Work on ONE agent: start only its backend container(s) and its micro-frontend. Everyone works on `pro`.
//
//   node dev.mjs                  list the agents
//   node dev.mjs rag              container(s) + UI on its own port (Ctrl+C stops the UI; the container keeps running)
//   node dev.mjs rag --shell      also the shell, to see the UI inside the platform (other sections show "unavailable")
//   node dev.mjs rag --backend    only (re)build + start the container(s), e.g. after a backend code change
//   node dev.mjs rag --ui         only the UI (the container is already running)
//   node dev.mjs rag --stop       stop the agent's container(s)
//
// Needs Docker Desktop and Node 20+. API ports: <AGENT>_PORT in backend/.env. UI ports: frontend/angular.json.
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = dirname(fileURLToPath(import.meta.url));
const BACKEND = join(ROOT, 'backend');
const FRONTEND = join(ROOT, 'frontend');

// agent -> its compose services (in backend/docker-compose.yml unless `compose` says otherwise) and its UI projects
const AGENTS = {
  'web-search': { services: ['web-search-agent'], ui: ['web-search-ui'], port: 'WEB_SEARCH_PORT', route: 'agents/web-search' },
  communication: { services: ['communication-agent'], ui: ['communication-ui'], port: 'COMMUNICATION_PORT', route: 'agents/communication' },
  verifier: { services: ['verifier-agent'], ui: ['verifier-ui'], port: 'VERIFIER_PORT', route: 'agents/verifier' },
  synthesizer: { services: ['synthesizer-agent'], ui: ['synthesizer-ui'], port: 'SYNTHESIZER_PORT', route: 'agents/synthesizer' },
  rag: { compose: 'Rag-agent/docker-compose.yml', services: ['qdrant', 'api'], ui: ['rag-ui'], port: 'RAG_PORT', route: 'agents/rag' },
  // the orchestrator's compose service also starts web-search, communication and verifier (depends_on)
  orchestrator: { services: ['orchestrator-agent'], ui: ['shell', 'flow', 'runs', 'approvals', 'admin'], port: 'ORCHESTRATOR_PORT', route: 'flow' },
};

function sh(cmd, cwd, { exit = true } = {}) {
  console.log(`\n> ${cmd}`);
  const { status } = spawnSync(cmd, { cwd, shell: true, stdio: 'inherit' });
  if (status !== 0 && exit) process.exit(status ?? 1);
  return status === 0;
}

function quiet(cmd, cwd = ROOT) {
  const r = spawnSync(cmd, { cwd, shell: true, encoding: 'utf8' });
  return r.status === 0 ? r.stdout.trim() : null;
}

/** KEY=value from backend/.env, else from .env.example. */
function envValue(key) {
  for (const file of ['.env', '.env.example']) {
    const path = join(BACKEND, file);
    const match = existsSync(path) && readFileSync(path, 'utf8').match(new RegExp(`^${key}=(.*)$`, 'm'));
    if (match && match[1].trim()) return match[1].trim();
  }
  return '?';
}

const angular = JSON.parse(readFileSync(join(FRONTEND, 'angular.json'), 'utf8')).projects;
const uiPort = (ui) => (angular[ui].architect['serve-original'] ?? angular[ui].architect.serve).options.port;

/** docker compose command for this agent, run from backend/. */
function compose(agent) {
  return agent.compose ? `docker compose -f ${agent.compose} --env-file .env` : 'docker compose';
}

function list() {
  console.log('node dev.mjs <agent> [--shell | --backend | --ui | --stop]\n');
  for (const [name, a] of Object.entries(AGENTS)) {
    const api = `API :${envValue(a.port)}`.padEnd(10);
    console.log(`  ${name.padEnd(14)} ${api}  UI :${uiPort(a.ui[0])} ${a.ui.join(', ')}`);
  }
}

// ------------------------------------------------------------------------------------------------ main
const [arg, ...flags] = process.argv.slice(2);
if (!arg || arg === '--help' || arg === '-h') {
  list();
  process.exit(0);
}
// accept folder names too: web_search_agent, Rag-agent, rag-ui ...
const name = arg.toLowerCase().replaceAll('_', '-').replace(/-(agent|ui)$/, '');
const agent = AGENTS[name];
if (!agent) {
  console.error(`Unknown agent '${arg}'.\n`);
  list();
  process.exit(1);
}
const has = (flag) => flags.includes(flag);
const backend = !has('--ui');
const ui = !has('--backend') && !has('--stop');

const branch = quiet('git branch --show-current');
if (branch && branch !== 'pro') console.warn(`! You are on '${branch}'. The team works on 'pro':  git switch pro && git pull`);

// Windows: docker build needs docker-credential-desktop, which sits next to docker.exe
const dockerBin = 'C:\\Program Files\\Docker\\Docker\\resources\\bin';
if (process.platform === 'win32' && existsSync(dockerBin) && !process.env.PATH.toLowerCase().includes(dockerBin.toLowerCase())) {
  process.env.PATH = `${dockerBin};${process.env.PATH}`;
}

if (backend) {
  if (quiet('docker info --format "{{.ServerVersion}}"') === null) {
    console.error('Docker is not running: start Docker Desktop, then run this again.');
    process.exit(1);
  }
  if (has('--stop')) {
    sh(`${compose(agent)} stop ${agent.services.join(' ')}`, BACKEND);
    process.exit(0);
  }
  if (!existsSync(join(BACKEND, '.env'))) {
    copyFileSync(join(BACKEND, '.env.example'), join(BACKEND, '.env'));
    console.log('Created backend/.env from backend/.env.example (git-ignored: put your keys there).');
  }
  sh(`${compose(agent)} up -d --build ${agent.compose ? '' : agent.services.join(' ')}`.trim(), BACKEND);
}

const apiUrl = `http://localhost:${envValue(agent.port)}`;
const uis = [...new Set([...(has('--shell') ? ['shell'] : []), ...agent.ui])];
console.log(`\n${name}`);
console.log(`  API    ${apiUrl}   (starting; status: cd backend && ${compose(agent)} ps)`);
if (ui) {
  console.log(`  UI     http://localhost:${uiPort(agent.ui[0])}`);
  if (uis.includes('shell') && agent.ui[0] !== 'shell') console.log(`  Shell  http://localhost:${uiPort('shell')}/${agent.route}`);
}
console.log(`  Logs   cd backend && ${compose(agent)} logs -f ${agent.compose ? '' : agent.services[0]}`.trimEnd());
console.log(`  Stop   node dev.mjs ${name} --stop`);
if (!ui) process.exit(0);

if (!existsSync(join(FRONTEND, 'node_modules'))) sh('npm install', FRONTEND);
const serve = uis.length === 1
  ? `npx ng serve ${uis[0]}`
  : `npx concurrently -k -n ${uis.join(',')} ${uis.map((u) => `"ng serve ${u}"`).join(' ')}`;
sh(serve, FRONTEND, { exit: false });
