import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { AGENT_WIDGET_LOADER } from '@altasnim/shared';

import { routes } from './app.routes';
import { loadAgentWidget } from './widget-loader';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),
    { provide: AGENT_WIDGET_LOADER, useValue: loadAgentWidget },
  ],
};
