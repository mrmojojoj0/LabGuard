import { api } from "../../lib/api";

export interface ExamPolicy {
  network_mode: "MONITOR" | "ALLOW_LIST";
  allowed_networks: string[];
  restricted_apps: string[];
  restrict_browsers: boolean;
  restricted_browsers: string[];
  block_usb_storage: boolean;
  screenshot_on_violation: boolean;
}
export interface Exam {
  id: string;
  room_id: string;
  room_name: string;
  title: string;
  starts_at: string;
  ends_at: string;
  status: "SCHEDULED" | "ACTIVE" | "COMPLETED" | "CANCELLED";
  device_ids: string[];
  policy: ExamPolicy;
  created_at: string;
  updated_at: string;
  violations: number;
}
export interface ExamReport {
  exam: Exam;
  room_grid: { name: string; rows: number; columns: number } | null;
  devices: Array<{ device_id: string; device_name: string; agent_state: string;
    last_heartbeat_at: string | null; violation_count: number; row: number | null; column: number | null }>;
  violations: Array<{ id: string; device_id: string; kind: string; severity: string;
    occurred_at: string; details: Record<string, unknown> }>;
  generated_at: string;
}
export const examsApi = {
  list: () => api<Exam[]>("/exams"),
  create: (input: { title: string; room_id: string; device_ids: string[];
    starts_at: string; ends_at: string; policy: ExamPolicy }) =>
    api<Exam>("/exams", { method: "POST", body: JSON.stringify(input) }),
  cancel: (id: string) => api<Exam>(`/exams/${id}/cancel`, { method: "POST", body: "{}" }),
  report: (id: string) => api<ExamReport>(`/exams/${id}/report`),
};
