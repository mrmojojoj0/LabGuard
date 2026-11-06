import { api, json } from "../../lib/api";
import type { Device, EnrollmentCode } from "../../lib/types";
export const enrollmentApi = {
  pending: () => api<Device[]>("/enrollment/requests"),
  approve: (id: string, assigned_name: string) =>
    api<Device>(
      `/enrollment/requests/${id}/approve`,
      json("POST", { assigned_name }),
    ),
  reject: (id: string) =>
    api<Device>(`/enrollment/requests/${id}/reject`, json("POST")),
  createCode: () => api<EnrollmentCode>("/enrollment-codes", json("POST")),
};
