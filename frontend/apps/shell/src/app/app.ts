import { ChangeDetectionStrategy, Component, DestroyRef, afterNextRender, computed, effect, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { CurrentRun, OrchestratorService } from '@altasnim/shared';
import { filter, map } from 'rxjs';

import { ChatWidget } from './chat-widget';
import { Icon } from './icon';

interface NavLink {
  path: string;
  label: string;
  icon: string;
}

interface NavSection {
  title: string;
  links: NavLink[];
}

type ThemeChoice = 'system' | 'light' | 'dark';

const THEME_KEY = 'altasnim.theme';
const NAV_KEY = 'altasnim.nav';
const THEMES: ThemeChoice[] = ['system', 'light', 'dark'];

/** Per-viewer UI preferences (storage may be blocked: then nothing is remembered). */
function remembered(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function remember(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // not remembered
  }
}

/**
 * The platform frame around every micro-frontend: navigation (collapsible to icons), the top bar (where you are,
 * environment, theme, the assistant, the user) and the chat sidebar on the right.
 */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, ChatWidget, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  private readonly orchestrator = inject(OrchestratorService);
  private readonly run = inject(CurrentRun);
  private readonly router = inject(Router);
  protected readonly pending = signal(0);
  protected readonly backendUp = signal(true);
  /** The chat sidebar on the right (top bar button, the bottom-right button, or a page via CurrentRun). */
  protected readonly chatOpen = this.run.chatOpen;
  protected readonly collapsed = signal(remembered(NAV_KEY) === 'collapsed');
  protected readonly theme = signal<ThemeChoice>((remembered(THEME_KEY) as ThemeChoice) ?? 'system');
  /** Animate the columns only after the first render (never on page load). */
  protected readonly animate = signal(false);
  protected readonly environment = ['localhost', '127.0.0.1'].includes(location.hostname) ? 'Development' : 'Production';

  protected readonly sections: NavSection[] = [
    {
      title: 'Platform',
      links: [
        { path: '/flow', label: 'Multi Agent Flow', icon: 'flow' },
        { path: '/runs', label: 'Runs', icon: 'runs' },
        { path: '/approvals', label: 'Approvals', icon: 'approvals' },
        { path: '/admin', label: 'Admin', icon: 'admin' },
      ],
    },
    {
      title: 'Agents',
      links: [
        { path: '/agents/rag', label: 'RAG', icon: 'rag' },
        { path: '/agents/web-search', label: 'Web search', icon: 'web_search' },
        { path: '/agents/verifier', label: 'Verifier', icon: 'verifier' },
        { path: '/agents/synthesizer', label: 'Synthesizer', icon: 'synthesizer' },
        { path: '/agents/communication', label: 'Communication', icon: 'communication' },
      ],
    },
  ];

  private readonly url = toSignal(
    this.router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
    ),
    { initialValue: this.router.url },
  );
  /** Where the user is, for the breadcrumb. */
  protected readonly here = computed(() => {
    const url = this.url().split(/[?#]/)[0];
    for (const section of this.sections) {
      const link = section.links.find((l) => url === l.path || url.startsWith(`${l.path}/`));
      if (link) return { section: section.title, link };
    }
    return null;
  });
  /** A run is going or waiting for the user: shown on the Assistant button while the chat is closed. */
  protected readonly chatAttention = computed(() => {
    const session = this.run.session();
    return session.status() === 'running' || !!session.interrupt();
  });

  constructor() {
    effect(() => {
      const theme = this.theme();
      if (theme === 'system') delete document.documentElement.dataset['theme'];
      else document.documentElement.dataset['theme'] = theme;
      remember(THEME_KEY, theme === 'system' ? null : theme);
    });
    effect(() => remember(NAV_KEY, this.collapsed() ? 'collapsed' : null));
    afterNextRender(() => setTimeout(() => this.animate.set(true), 50));

    const poll = () =>
      this.orchestrator
        .pendingApprovals()
        .then((items) => {
          this.pending.set(items.length);
          this.backendUp.set(true);
        })
        .catch(() => this.backendUp.set(false));
    poll();
    const timer = setInterval(poll, 10_000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  protected nextTheme(): void {
    this.theme.update((t) => THEMES[(THEMES.indexOf(t) + 1) % THEMES.length]);
  }

  protected themeLabel(): string {
    return { system: 'Theme: system', light: 'Theme: light', dark: 'Theme: dark' }[this.theme()];
  }

  protected themeIcon(): string {
    return { system: 'system', light: 'sun', dark: 'moon' }[this.theme()];
  }
}
