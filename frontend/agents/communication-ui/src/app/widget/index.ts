import { AgentWidget } from '@altasnim/shared';

import { EmailApprovalForm } from './email-approval-form';
import { EmailResultView } from './email-result-view';

/** Exposed as './Widget'. `approvalForm` is used when the communication agent asks for approval. */
export const widget: AgentWidget = {
  agent: 'communication',
  resultView: EmailResultView,
  approvalForm: EmailApprovalForm,
};
