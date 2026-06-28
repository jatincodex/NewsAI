import { View, Text, StyleSheet, ScrollView } from "react-native";
import { C, S, TYPE } from "@/src/theme";

type Stats = {
  total_posts: number;
  verified: number;
  debunked: number;
  pending_review: number;
  rendering: number;
  cache?: { live_keys: number; total_keys: number };
};

export default function StatsBar({ stats }: { stats: Stats | null }) {
  const items = [
    { label: "TOTAL", value: stats?.total_posts ?? 0 },
    { label: "VERIFIED", value: stats?.verified ?? 0, color: C.success },
    { label: "DEBUNKED", value: stats?.debunked ?? 0, color: C.error },
    { label: "REVIEW", value: stats?.pending_review ?? 0, color: C.warning },
    { label: "RENDER", value: stats?.rendering ?? 0, color: C.info },
    { label: "CACHE", value: stats?.cache?.live_keys ?? 0 },
  ];
  return (
    <View style={styles.wrap} testID="stats-bar">
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
        {items.map((it) => (
          <View key={it.label} style={styles.cell}>
            <Text style={[TYPE.label, { color: C.onSurface2 }]}>{it.label}</Text>
            <Text style={[styles.value, { color: it.color || C.onSurface }]}>{it.value}</Text>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: C.surface,
    borderBottomWidth: 2,
    borderBottomColor: C.border,
  },
  row: {
    paddingHorizontal: S.lg,
    paddingVertical: S.md,
    gap: S.md,
  },
  cell: {
    minWidth: 78,
    paddingHorizontal: S.md,
    paddingVertical: S.sm,
    borderWidth: 2,
    borderColor: C.border,
    backgroundColor: C.surface,
    flexShrink: 0,
  },
  value: {
    fontSize: 22,
    fontWeight: "800",
    letterSpacing: -0.5,
    marginTop: 2,
  },
});
