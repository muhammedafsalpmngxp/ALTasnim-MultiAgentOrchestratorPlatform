import { Routes } from '@angular/router';

import { VerifierPage } from './verifier-page';

/** Exposed to the shell as './Routes' (mounted at /agents/verifier). */
export const routes: Routes = [{ path: '', component: VerifierPage }];
