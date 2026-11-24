"use client";

import { useEffect, useState } from "react";
import { useAppContext } from "@/components/AppProvider";

type AccountAvatarProps = {
  size?: number;
  className?: string;
};

export default function AccountAvatar({ size = 34, className = "" }: AccountAvatarProps) {
  const { user, authFetch } = useAppContext();
  const [loaded, setLoaded] = useState<{ src: string; blobUrl: string } | null>(null);
  const avatarUrl = user?.avatar_url ?? null;

  useEffect(() => {
    if (!avatarUrl) return;
    let cancelled = false;
    let objectUrl: string | null = null;

    void (async () => {
      try {
        const res = await authFetch(avatarUrl);
        if (!res.ok || cancelled) return;
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setLoaded({ src: avatarUrl, blobUrl: objectUrl });
      } catch {
        if (!cancelled) setLoaded(null);
      }
    })();

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [authFetch, avatarUrl]);

  const activeBlobUrl = avatarUrl && loaded?.src === avatarUrl ? loaded.blobUrl : null;
  const initial =
    (user?.first_name || user?.full_name || "د").trim().slice(0, 1) || "د";

  return (
    <span
      className={`account-avatar ${className}`}
      style={{ width: size, height: size, flex: `0 0 ${size}px` }}
    >
      {activeBlobUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={activeBlobUrl}
          alt={user?.full_name || user?.masked_phone || "Avatar"}
          className="account-avatar-img"
        />
      ) : (
        <span>{initial}</span>
      )}
    </span>
  );
}
