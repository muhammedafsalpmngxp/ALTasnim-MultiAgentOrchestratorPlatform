import { loadRemoteModule } from '@angular-architects/native-federation';
import { Routes } from '@angular/router';

import { RemoteUnavailable } from './remote-unavailable';

/** Lazy-load a remote's './Routes'. If the remote is down, show a fallback for that section only. */
function remote(name: string) {
  return () =>
    loadRemoteModule(name, './Routes')
      .then((m) => m.routes as Routes)
      .catch((err) => {
        console.warn(`[shell] remote ${name} unavailable`, err);
        return [{ path: '**', component: RemoteUnavailable, data: { remote: name } }] as Routes;
      });
}

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'flow' },
  // platform micro-frontends (frontend team)
  { path: 'flow', loadChildren: remote('flow') },
  { path: 'runs', loadChildren: remote('runs') },
  { path: 'approvals', loadChildren: remote('approvals') },
  { path: 'admin', loadChildren: remote('admin') },
  // agent micro-frontends (each agent team)
  { path: 'agents/web-search', loadChildren: remote('web-search-ui') },
  { path: 'agents/communication', loadChildren: remote('communication-ui') },
  { path: 'agents/verifier', loadChildren: remote('verifier-ui') },
  { path: 'agents/rag', loadChildren: remote('rag-ui') },
  { path: '**', redirectTo: 'flow' },
];
