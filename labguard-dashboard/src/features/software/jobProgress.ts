export function displayJobProgressMessage(status: string, message: string | null | undefined): string {
  if (!message) return "";
  if (status !== "RUNNING" && /\(\s*\d{1,3}%\s*\)/.test(message)) return "";
  return message.replace(/\s*\(\s*\d{1,3}%\s*\)/g, "").trim();
}
