import { Routes } from '@angular/router';

import { AdminPage } from './admin-page';

/** Exposed to the shell as './Routes' (mounted at /admin). */
export const routes: Routes = [{ path: '', component: AdminPage }];
