let token: string | null = null;

export function getCachedCsrfToken(): string | null {
  return token;
}

export function setCsrfToken(nextToken: string): void {
  token = nextToken;
}

export function clearCsrfToken(): void {
  token = null;
}
