import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  afterRenderEffect,
  computed,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';

import { AgentCard, Plan, StepStatus } from '../models';
import { FLOW_ICONS } from './flow-icons';
import { FlowPhase, buildFlow } from './flow-model';

interface DrawnEdge {
  d: string;
  cls: string;
  marker: 'active' | 'idle' | 'ok' | 'danger';
  label?: string;
  lx: number;
  ly: number;
}

/**
 * Live flow of a multi-agent run, in stages (Input → Routing → Parallelization → Reflection →
 * Human-in-the-loop → Output). Columns and nodes come from the plan; edges are drawn in an SVG
 * overlay measured from the rendered nodes.
 */
@Component({
  selector: 'alt-flow-diagram',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './flow-diagram.html',
  styleUrl: './flow-diagram.css',
})
export class FlowDiagram {
  readonly plan = input<Plan | null | undefined>(null);
  readonly status = input<Record<string, StepStatus>>({});
  readonly waitingStepId = input<string | null>(null);
  readonly cards = input<Record<string, AgentCard>>({});
  readonly request = input<string>('');
  readonly phase = input<FlowPhase>('idle');
  readonly final = input<string | null | undefined>(null);
  readonly replans = input<number>(0);

  protected readonly icons = FLOW_ICONS;
  protected readonly graph = computed(() =>
    buildFlow({
      plan: this.plan(),
      status: this.status(),
      waitingStepId: this.waitingStepId(),
      cards: this.cards(),
      request: this.request(),
      phase: this.phase(),
      final: this.final(),
      replans: this.replans(),
    }),
  );

  protected readonly edges = signal<DrawnEdge[]>([]);
  protected readonly size = signal({ w: 0, h: 0 });
  private readonly track = viewChild.required<ElementRef<HTMLElement>>('track');

  constructor() {
    afterRenderEffect(() => {
      this.graph();
      this.layout();
    });
    const resize = new ResizeObserver(() => this.layout());
    afterNextRender(() => resize.observe(this.track().nativeElement));
    inject(DestroyRef).onDestroy(() => resize.disconnect());
  }

  private layout(): void {
    const root = this.track().nativeElement;
    const box = root.getBoundingClientRect();
    const pos = new Map<string, { l: number; r: number; y: number }>();
    root.querySelectorAll<HTMLElement>('[data-node]').forEach((el) => {
      const r = el.getBoundingClientRect();
      pos.set(el.dataset['node']!, { l: r.left - box.left, r: r.right - box.left, y: r.top - box.top + r.height / 2 });
    });

    const drawn: DrawnEdge[] = [];
    for (const e of this.graph().edges) {
      const a = pos.get(e.from);
      const b = pos.get(e.to);
      if (!a || !b) continue;
      const x1 = a.r + 6;
      const x2 = b.l - 8;
      const dx = Math.max(28, (x2 - x1) / 2);
      drawn.push({
        d: `M ${x1} ${a.y} C ${x1 + dx} ${a.y}, ${x2 - dx} ${b.y}, ${x2} ${b.y}`,
        cls: [e.active ? 'active' : 'idle', e.tone ?? '', e.dashed ? 'dashed' : ''].join(' ').trim(),
        marker: e.tone === 'danger' ? 'danger' : e.tone === 'ok' && e.active ? 'ok' : e.active ? 'active' : 'idle',
        label: e.label,
        lx: (x1 + x2) / 2,
        ly: (a.y + b.y) / 2 - 6,
      });
    }
    this.size.set({ w: root.scrollWidth, h: root.scrollHeight });
    this.edges.set(drawn);
  }
}
