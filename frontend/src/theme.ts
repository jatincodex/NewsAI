import { Platform, StyleSheet } from "react-native";

export const C = {
  surface: "#FAFAFA",
  surface2: "#F0F0F0",
  surface3: "#E4E4E4",
  onSurface: "#111111",
  onSurface2: "#333333",
  inverse: "#111111",
  onInverse: "#FAFAFA",
  border: "#111111",
  divider: "#E4E4E4",
  success: "#059669",
  warning: "#D97706",
  error: "#DC2626",
  info: "#2563EB",
  xColor: "#000000",
  igColor: "#E1306C",
  ttColor: "#00F2EA",
};

export const S = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, xxxl: 48 };

export const TYPE = StyleSheet.create({
  mono: {
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    color: C.onSurface,
  },
  monoDim: {
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    color: C.onSurface2,
  },
  display: {
    fontWeight: "800",
    color: C.onSurface,
    letterSpacing: -0.5,
  },
  body: { color: C.onSurface, fontWeight: "500" },
  label: {
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    fontSize: 11,
    letterSpacing: 1,
    color: C.onSurface,
    textTransform: "uppercase",
  },
});

export function scoreColor(score: number | null | undefined): string {
  if (score == null) return C.onSurface2;
  if (score >= 0.95) return C.success;
  if (score >= 0.5) return C.warning;
  return C.error;
}

export function platformIcon(p: string): { name: any; color: string; label: string } {
  switch (p) {
    case "x":
      return { name: "logo-twitter", color: C.xColor, label: "X" };
    case "instagram":
      return { name: "logo-instagram", color: C.igColor, label: "IG" };
    case "tiktok":
      return { name: "logo-tiktok", color: C.ttColor, label: "TT" };
    default:
      return { name: "newspaper-outline", color: C.onSurface, label: p.toUpperCase() };
  }
}

export function statusLabel(status: string): { label: string; bg: string; fg: string } {
  switch (status) {
    case "pending":
      return { label: "PENDING", bg: C.surface3, fg: C.onSurface };
    case "verifying":
      return { label: "VERIFYING", bg: C.info, fg: "#FFF" };
    case "video_generation_pending":
      return { label: "RENDERING", bg: C.warning, fg: "#FFF" };
    case "human_review_required":
      return { label: "REVIEW", bg: C.warning, fg: "#FFF" };
    case "verified":
      return { label: "VERIFIED", bg: C.success, fg: "#FFF" };
    case "debunked":
      return { label: "DEBUNKED", bg: C.error, fg: "#FFF" };
    default:
      return { label: status.toUpperCase(), bg: C.surface3, fg: C.onSurface };
  }
}

export const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL || "http://127.0.0.1:8081";
