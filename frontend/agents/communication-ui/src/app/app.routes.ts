import { Routes } from '@angular/router';

import { CommunicationPage } from './communication-page';

/** Exposed to the shell as './Routes' (mounted at /agents/communication). */
export const routes: Routes = [{ path: '', component: CommunicationPage }];
