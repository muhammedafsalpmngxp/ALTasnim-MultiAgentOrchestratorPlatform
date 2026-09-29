import { provideHttpClient, withFetch } from '@angular/common/http';
import { Routes } from '@angular/router';

import { WebSearchPage } from './web-search-page';

/**
 * Exposed to the shell as './Routes' (mounted at /agents/web-search).
 * HttpClient is provided here, so the page works whether or not the host provides it.
 */
export const routes: Routes = [{ path: '', component: WebSearchPage, providers: [provideHttpClient(withFetch())] }];
