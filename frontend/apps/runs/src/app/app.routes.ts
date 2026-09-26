import { Routes } from '@angular/router';

import { RunDetail } from './run-detail';
import { RunsList } from './runs-list';

/** Exposed to the shell as './Routes' (mounted at /runs). */
export const routes: Routes = [
  { path: '', component: RunsList },
  { path: ':threadId', component: RunDetail },
];
