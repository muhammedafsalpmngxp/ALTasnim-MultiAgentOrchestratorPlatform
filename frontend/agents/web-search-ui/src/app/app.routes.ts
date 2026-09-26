import { Routes } from '@angular/router';

import { WebSearchPage } from './web-search-page';

/** Exposed to the shell as './Routes' (mounted at /agents/web-search). */
export const routes: Routes = [{ path: '', component: WebSearchPage }];
