import { Routes } from '@angular/router';

import { IngestionPage } from './ingestion-page';

/** Exposed to the shell as './Routes' (mounted at /agents/rag). */
export const routes: Routes = [{ path: '', component: IngestionPage }];
