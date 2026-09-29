import { Routes } from '@angular/router';

import { Synthesizer } from './synthesizer/synthesizer';

/** Exposed to the shell as './Routes' (mounted at /agents/synthesizer). */
export const routes: Routes = [{ path: '', component: Synthesizer }];
