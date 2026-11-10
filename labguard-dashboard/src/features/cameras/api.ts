import { api, apiBaseUrl, json } from "../../lib/api";

export interface LabCamera {
  id: string;
  room_id: string;
  room_name: string;
  name: string;
  enabled: boolean;
  state: string;
  error_code: string | null;
  last_frame_at: string | null;
  stream_configured: boolean;
}
export interface CameraDetection {
  id: string;
  camera_id: string;
  room_id: string;
  camera_name: string;
  room_name: string;
  label: string;
  count: number;
  confidence: number;
  occurred_at: string;
}
export const cameraApi = {
  list: (roomId?: string) => api<LabCamera[]>(`/lab-cameras${roomId ? `?room_id=${encodeURIComponent(roomId)}` : ""}`),
  detections: (roomId?: string) => api<CameraDetection[]>(`/lab-camera-detections?limit=200${roomId ? `&room_id=${encodeURIComponent(roomId)}` : ""}`),
  create: (roomId: string, name: string, stream_uri: string) => api<LabCamera>(`/rooms/${roomId}/cameras`, json("POST", { name, stream_uri })),
  update: (id: string, changes: Partial<Pick<LabCamera, "name" | "enabled">> & { stream_uri?: string }) => api<LabCamera>(`/lab-cameras/${id}`, json("PATCH", changes)),
  remove: (id: string) => api<void>(`/lab-cameras/${id}`, { method: "DELETE" }),
  frameUrl: (id: string, timestamp: string) => `${apiBaseUrl}/api/v1/lab-cameras/${id}/frame?at=${encodeURIComponent(timestamp)}`,
};
