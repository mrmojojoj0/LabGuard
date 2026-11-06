import { api } from "../../lib/api";
import type { AuditEvent } from "../../lib/types";
export const auditApi = {
  list: () => api<AuditEvent[]>("/audit-events?limit=25"),
};
