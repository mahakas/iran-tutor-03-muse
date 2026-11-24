"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { LoaderCircle, LogOut, X } from "lucide-react";
import AuthFlowModal from "@/components/AuthFlowModal";
import { COPY } from "@/lib/i18n";
import {
  SESSION_EXPIRED_EVENT,
  apiRequest,
  clearCsrfMemo,
  currentCsrfToken,
  rememberCsrfToken,
} from "@/lib/apiClient";
import {
  applyPreferencesToDocument,
  DEFAULT_PREFERENCES,
  normalizePreferencesClient,
  readCachedPreferences,
  writeCachedPreferences,
} from "@/lib/preferences";
import type { StudentUser, UserPreferences } from "@/lib/types";

const USER_TOKEN_KEY = "iran_tutor_user_token";

export function readStoredUserToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(USER_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function storeUserToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) {
      window.sessionStorage.setItem(USER_TOKEN_KEY, token);
    } else {
      window.sessionStorage.removeItem(USER_TOKEN_KEY);
    }
  } catch {
    // ignore storage errors
  }
}

export function buildUserAuthHeaders(token: string | null): Record<string, string> {
  if (!token) return {};
  return {
    Authorization: `Bearer ${token}`,
    "X-User-Token": token,
  };
}

export type PreferencesPatch = Partial<{
  general: Partial<UserPreferences["general"]>;
  appearance: Partial<
    Omit<UserPreferences["appearance"], "light" | "dark"> & {
      light: Partial<UserPreferences["appearance"]["light"]>;
      dark: Partial<UserPreferences["appearance"]["dark"]>;
    }
  >;
  notifications: Partial<UserPreferences["notifications"]>;
  privacy: Partial<UserPreferences["privacy"]>;
}>;

type AppContextValue = {
  user: StudentUser | null;
  token: string | null;
  authReady: boolean;
  preferences: UserPreferences;
  systemIsDark: boolean;
  getActiveToken: () => string | null;
  setAuthSession: (token: string | null, user: StudentUser | null) => void;
  setUser: React.Dispatch<React.SetStateAction<StudentUser | null>>;
  refreshAccount: () => Promise<StudentUser | null>;
  authFetch: (input: string, init?: RequestInit) => Promise<Response>;
  updatePreferences: (patch: PreferencesPatch) => Promise<UserPreferences | null>;
  resetPreferences: (
    section: "all" | "general" | "appearance" | "notifications" | "privacy"
  ) => Promise<UserPreferences | null>;
  openLoginModal: (
    notice?: string,
    mode?: "login" | "register" | "recover" | "code"
  ) => void;
  requestLogout: () => void;
  performLogoutNow: () => Promise<void>;
};

const AppContext = createContext<AppContextValue | null>(null);

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error("useAppContext must be used within AppProvider");
  }
  return ctx;
}

function errorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return fallback;
}

function mergePrefsLocal(current: UserPreferences, patch: PreferencesPatch): UserPreferences {
  return normalizePreferencesClient({
    general: { ...current.general, ...(patch.general ?? {}) },
    appearance: {
      ...current.appearance,
      ...(patch.appearance ?? {}),
      light: { ...current.appearance.light, ...(patch.appearance?.light ?? {}) },
      dark: { ...current.appearance.dark, ...(patch.appearance?.dark ?? {}) },
    },
    notifications: { ...current.notifications, ...(patch.notifications ?? {}) },
    privacy: { ...current.privacy, ...(patch.privacy ?? {}) },
  });
}

export default function AppProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  const tokenRef = useRef<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<StudentUser | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [preferences, setPreferences] = useState<UserPreferences>(DEFAULT_PREFERENCES);
  const [systemIsDark, setSystemIsDark] = useState(false);

  // Auth modal state (phone + password flow lives in AuthFlowModal)
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authInitialMode, setAuthInitialMode] = useState<"login" | "register" | "recover" | "code">("login");
  const [authNotice, setAuthNotice] = useState("");

  // Logout confirmation dialog state
  const [logoutModalOpen, setLogoutModalOpen] = useState(false);
  const [logoutBusy, setLogoutBusy] = useState(false);

  const getActiveToken = useCallback((): string | null => {
    return tokenRef.current ?? readStoredUserToken();
  }, []);

  const clearClientAuth = useCallback(() => {
    tokenRef.current = null;
    setToken(null);
    storeUserToken(null);
    setUser(null);
    writeCachedPreferences(null);
    setPreferences(DEFAULT_PREFERENCES);
  }, []);

  const setAuthSession = useCallback(
    (nextToken: string | null, nextUser: StudentUser | null) => {
      if (!nextToken) clearCsrfMemo();
      tokenRef.current = nextToken;
      setToken(nextToken);
      storeUserToken(nextToken);
      setUser(nextUser);
      if (nextUser?.preferences) {
        const normalized = normalizePreferencesClient(nextUser.preferences);
        setPreferences(normalized);
        writeCachedPreferences(normalized);
      } else if (!nextUser) {
        writeCachedPreferences(null);
        setPreferences(DEFAULT_PREFERENCES);
      }
    },
    []
  );

  // Sync system dark-mode listener on mount
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (event: MediaQueryListEvent) => setSystemIsDark(event.matches);
    const initialTimer = window.setTimeout(() => {
      setSystemIsDark(mq.matches);
      const cached = readCachedPreferences();
      if (cached && readStoredUserToken()) {
        setPreferences(cached);
      }
    }, 0);
    mq.addEventListener?.("change", handler);
    return () => {
      window.clearTimeout(initialTimer);
      mq.removeEventListener?.("change", handler);
    };
  }, []);

  // Apply CSS variables & document dir/lang whenever preferences or system theme change
  // Admin routes manage their own independent Admin Appearance preferences.
  const isAdminRoute = pathname?.startsWith("/admin") ?? false;
  useEffect(() => {
    if (isAdminRoute) return;
    applyPreferencesToDocument(preferences, systemIsDark);
  }, [isAdminRoute, preferences, systemIsDark]);

  const updateUserSynced = useCallback(
    (updater: React.SetStateAction<StudentUser | null>) => {
      setUser(updater);
      if (typeof updater !== "function") {
        if (updater?.preferences) {
          const normalized = normalizePreferencesClient(updater.preferences);
          setPreferences(normalized);
          writeCachedPreferences(normalized);
        } else if (!updater) {
          setPreferences(DEFAULT_PREFERENCES);
          writeCachedPreferences(null);
        }
      }
    },
    []
  );

  const refreshAccount = useCallback(async (): Promise<StudentUser | null> => {
    const activeToken = getActiveToken();
    try {
      const res = await fetch("/api/v1/auth/me", {
        cache: "no-store",
        credentials: "same-origin",
        headers: buildUserAuthHeaders(activeToken),
      });
      if (!res.ok) {
        clearClientAuth();
        return null;
      }
      const payload = (await res.json()) as {
        authenticated?: boolean;
        user?: StudentUser | null;
        csrf_token?: string;
      };
      if (payload.csrf_token) rememberCsrfToken(payload.csrf_token);
      if (payload.authenticated && payload.user) {
        tokenRef.current = activeToken;
        setToken(activeToken);
        setUser(payload.user);
        if (payload.user.preferences) {
          const normalized = normalizePreferencesClient(payload.user.preferences);
          setPreferences(normalized);
          writeCachedPreferences(normalized);
        }
        return payload.user;
      }
      clearClientAuth();
      return null;
    } catch {
      return null;
    }
  }, [clearClientAuth, getActiveToken]);

  useEffect(() => {
    const stored = readStoredUserToken();
    tokenRef.current = stored;
    let active = true;
    void (async () => {
      await refreshAccount();
      if (active) setAuthReady(true);
    })();
    return () => {
      active = false;
    };
  }, [refreshAccount]);

  // Re-validate session on browser bfcache restore (`pageshow`) so back button cannot resurrect logged-out views
  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) {
        void refreshAccount();
      }
    };
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [refreshAccount]);

  // Session revocation from any AJAX call (401) or from another tab.
  useEffect(() => {
    const onExpired = () => {
      clearClientAuth();
      clearCsrfMemo();
      setAuthNotice("نشست شما منقضی شده است. لطفاً دوباره وارد شوید.");
      setAuthInitialMode("login");
      setAuthModalOpen(true);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    const onStorage = (event: StorageEvent) => {
      if (event.key === USER_TOKEN_KEY && !event.newValue) {
        clearClientAuth();
      }
    };
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
      window.removeEventListener("storage", onStorage);
    };
  }, [clearClientAuth]);

  const authFetch = useCallback(
    async (input: string, init?: RequestInit): Promise<Response> => {
      const activeToken = getActiveToken();
      const mergedHeaders = new Headers(init?.headers ?? {});
      for (const [k, v] of Object.entries(buildUserAuthHeaders(activeToken))) {
        if (!mergedHeaders.has(k)) mergedHeaders.set(k, v);
      }
      // Cookie sessions are CSRF-checked; echo the token the API handed us.
      const method = (init?.method ?? "GET").toUpperCase();
      if (method !== "GET" && !mergedHeaders.has("X-CSRF-Token")) {
        const csrfToken = currentCsrfToken();
        if (csrfToken) mergedHeaders.set("X-CSRF-Token", csrfToken);
      }
      const res = await fetch(input, {
        ...init,
        cache: "no-store",
        credentials: "same-origin",
        headers: mergedHeaders,
      });
      const csrf = res.headers.get("X-CSRF-Token");
      if (csrf) rememberCsrfToken(csrf);
      if (res.status === 401) {
        clearClientAuth();
        clearCsrfMemo();
        if (pathname?.startsWith("/account") && pathname !== "/account/help") {
          router.replace("/");
        }
      }
      return res;
    },
    [clearClientAuth, getActiveToken, pathname, router]
  );

  const updatePreferences = useCallback(
    async (patch: PreferencesPatch): Promise<UserPreferences | null> => {
      const optimistic = mergePrefsLocal(preferences, patch);
      setPreferences(optimistic);
      writeCachedPreferences(optimistic);

      const activeToken = getActiveToken();
      if (!activeToken && !user) return optimistic;

      const res = await authFetch("/api/v1/account/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (user?.preferences) {
          const rollback = normalizePreferencesClient(user.preferences);
          setPreferences(rollback);
          writeCachedPreferences(rollback);
        }
        throw new Error(errorMessage(payload, "ذخیره تنظیمات انجام نشد."));
      }
      const saved = normalizePreferencesClient(payload.preferences);
      setPreferences(saved);
      writeCachedPreferences(saved);
      if (payload.user) {
        setUser(payload.user as StudentUser);
      } else {
        setUser((prev) => (prev ? { ...prev, preferences: saved } : prev));
      }
      return saved;
    },
    [authFetch, getActiveToken, preferences, user]
  );

  const resetPreferences = useCallback(
    async (
      section: "all" | "general" | "appearance" | "notifications" | "privacy"
    ): Promise<UserPreferences | null> => {
      const res = await authFetch("/api/v1/account/preferences/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ section }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(errorMessage(payload, "بازنشانی تنظیمات انجام نشد."));
      }
      const saved = normalizePreferencesClient(payload.preferences);
      setPreferences(saved);
      writeCachedPreferences(saved);
      if (payload.user) {
        setUser(payload.user as StudentUser);
      } else {
        setUser((prev) => (prev ? { ...prev, preferences: saved } : prev));
      }
      return saved;
    },
    [authFetch]
  );

  const openLoginModal = useCallback((notice?: string, mode: "login" | "register" | "recover" | "code" = "login") => {
    setAuthNotice(notice ?? "");
    setAuthInitialMode(mode);
    setAuthModalOpen(true);
  }, []);

  const performLogoutNow = useCallback(async () => {
    const activeToken = getActiveToken();
    setLogoutBusy(true);
    try {
      // Goes through the shared client so the CSRF token for cookie sessions is attached.
      await apiRequest("/api/v1/auth/logout", {
        method: "POST",
        headers: buildUserAuthHeaders(activeToken),
        fallbackMessage: "خروج از حساب انجام نشد.",
      });
    } catch {
      // proceed with client cleanup even if network fails
    } finally {
      clearClientAuth();
      setLogoutBusy(false);
      setLogoutModalOpen(false);
      if (pathname?.startsWith("/account")) {
        router.replace("/");
      }
    }
  }, [clearClientAuth, getActiveToken, pathname, router]);

  const requestLogout = useCallback(() => {
    setLogoutModalOpen(true);
  }, []);

  const lang = preferences.general.language === "en" ? "en" : "fa";
  const copy = COPY[lang];

  const contextValue = useMemo<AppContextValue>(
    () => ({
      user,
      token,
      authReady,
      preferences,
      systemIsDark,
      getActiveToken,
      setAuthSession,
      setUser: updateUserSynced,
      refreshAccount,
      authFetch,
      updatePreferences,
      resetPreferences,
      openLoginModal,
      requestLogout,
      performLogoutNow,
    }),
    [
      user,
      token,
      authReady,
      preferences,
      systemIsDark,
      getActiveToken,
      setAuthSession,
      updateUserSynced,
      refreshAccount,
      authFetch,
      updatePreferences,
      resetPreferences,
      openLoginModal,
      requestLogout,
      performLogoutNow,
    ]
  );

  return (
    <AppContext.Provider value={contextValue}>
      {children}

      <AuthFlowModal
        open={authModalOpen}
        initialMode={authInitialMode}
        notice={authNotice}
        onClose={() => setAuthModalOpen(false)}
        onAuthenticated={(nextToken, loggedUser) => {
          setAuthSession(nextToken, loggedUser);
          setAuthNotice("");
          void refreshAccount();
        }}
      />

      {/* Global Log Out Confirmation Dialog */}
      {logoutModalOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={(event) => {
            if (!logoutBusy && event.target === event.currentTarget) setLogoutModalOpen(false);
          }}
        >
          <section
            className="exam-setup-modal logout-confirm-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="logout-dialog-title"
          >
            <button
              className="modal-close icon-button"
              onClick={() => setLogoutModalOpen(false)}
              disabled={logoutBusy}
              aria-label={copy.auth.logoutConfirmNo}
            >
              <X size={18} />
            </button>
            <div className="modal-icon danger-icon">
              <LogOut size={22} />
            </div>
            <h2 id="logout-dialog-title">{copy.auth.logoutConfirmTitle}</h2>
            <p>{copy.auth.logoutConfirmBody}</p>
            <div className="dialog-actions-row">
              <button
                type="button"
                className="outline-button"
                disabled={logoutBusy}
                onClick={() => setLogoutModalOpen(false)}
              >
                {copy.auth.logoutConfirmNo}
              </button>
              <button
                type="button"
                className="danger-button"
                disabled={logoutBusy}
                onClick={() => void performLogoutNow()}
              >
                {logoutBusy ? (
                  <>
                    <LoaderCircle className="spin" size={16} />
                    {copy.auth.loggingOut}
                  </>
                ) : (
                  <>
                    <LogOut size={16} />
                    {copy.auth.logoutConfirmYes}
                  </>
                )}
              </button>
            </div>
          </section>
        </div>
      )}
    </AppContext.Provider>
  );
}
