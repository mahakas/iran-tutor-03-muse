/** Capability Registry client (Phase 2). Student menu is rendered from this. */

export type CapabilityItem = {
  key: string;
  title_fa: string;
  description_fa: string;
  icon: string | null;
  is_enabled: boolean;
  default_route_key: string | null;
  sort_order: number;
};

export type MyCapabilitiesPayload = {
  capabilities: CapabilityItem[];
  role: string;
  plan_code: string | null;
};

/** Returns enabled capability keys, or `null` when the registry is unreachable. */
export async function fetchMyCapabilities(
  authHeaders: Record<string, string>,
): Promise<Set<string> | null> {
  try {
    const response = await fetch("/api/v1/capabilities/me", {
      cache: "no-store",
      credentials: "same-origin",
      headers: authHeaders,
    });
    if (!response.ok) return null;
    const payload = (await response.json()) as MyCapabilitiesPayload;
    return new Set(payload.capabilities.filter((item) => item.is_enabled).map((item) => item.key));
  } catch {
    return null;
  }
}
