import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { C, S, TYPE, platformIcon, statusLabel, scoreColor } from "@/src/theme";

export type PostT = {
  id: string;
  content: string;
  platform: string;
  status: string;
  confidence_score?: number | null;
  verdict?: string | null;
  created_at: string;
  raw_payload?: any;
};

export default function PostCard({ post }: { post: PostT }) {
  const router = useRouter();
  const p = platformIcon(post.platform);
  const st = statusLabel(post.status);
  const score = post.confidence_score;
  const ts = new Date(post.created_at);
  const tStr = `${ts.getUTCHours().toString().padStart(2, "0")}:${ts.getUTCMinutes().toString().padStart(2, "0")}:${ts.getUTCSeconds().toString().padStart(2, "0")}Z`;

  return (
    <Pressable
      onPress={() => router.push({ pathname: "/post/[id]", params: { id: post.id } })}
      style={({ pressed }) => [styles.card, pressed && { opacity: 0.85 }]}
      testID={`post-card-${post.id}`}
    >
      <View style={styles.headerRow}>
        <View style={styles.platformBadge}>
          <Ionicons name={p.name} size={14} color={p.color} />
          <Text style={[TYPE.label, { marginLeft: 4 }]}>{p.label}</Text>
        </View>
        <Text style={[TYPE.monoDim, { fontSize: 11 }]}>{tStr}</Text>
      </View>

      <Text numberOfLines={3} style={styles.content}>
        {post.content}
      </Text>

      <View style={styles.footerRow}>
        <View style={[styles.statusChip, { backgroundColor: st.bg }]}>
          <Text style={[TYPE.label, { color: st.fg }]}>{st.label}</Text>
        </View>
        {score != null && (
          <View style={styles.scoreBlock}>
            <Text style={[TYPE.label, { color: C.onSurface2 }]}>SCORE</Text>
            <Text style={[styles.scoreValue, { color: scoreColor(score) }]}>{score.toFixed(2)}</Text>
          </View>
        )}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: C.surface,
    borderWidth: 2,
    borderColor: C.border,
    padding: S.md,
    marginHorizontal: S.lg,
    marginBottom: S.md,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: S.sm,
  },
  platformBadge: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: S.sm,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: C.border,
  },
  content: {
    fontSize: 15,
    lineHeight: 21,
    fontWeight: "600",
    color: C.onSurface,
    marginBottom: S.md,
    ...Platform.select({ web: { wordBreak: "break-word" as any } }),
  },
  footerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  statusChip: {
    paddingHorizontal: S.sm,
    paddingVertical: 4,
    borderWidth: 2,
    borderColor: C.border,
  },
  scoreBlock: { alignItems: "flex-end" },
  scoreValue: {
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    fontSize: 18,
    fontWeight: "800",
    marginTop: 2,
  },
});
