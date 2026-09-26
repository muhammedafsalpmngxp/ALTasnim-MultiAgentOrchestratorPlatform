import { Routes } from '@angular/router';

import { ApprovalsInbox } from './approvals-inbox';

/** Exposed to the shell as './Routes' (mounted at /approvals). */
export const routes: Routes = [{ path: '', component: ApprovalsInbox }];
