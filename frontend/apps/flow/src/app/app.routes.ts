import { Routes } from '@angular/router';

import { FlowPage } from './flow-page';

/** Exposed to the shell as './Routes' (mounted at /flow). */
export const routes: Routes = [{ path: '', component: FlowPage }];
