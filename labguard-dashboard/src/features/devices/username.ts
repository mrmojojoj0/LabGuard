export function shortWindowsUsername(username: string | null | undefined): string | null {
  if (!username) return null;
  const separator = username.lastIndexOf("\\");
  return separator >= 0 ? username.slice(separator + 1) : username;
}
