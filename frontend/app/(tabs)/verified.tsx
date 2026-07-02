import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  ActivityIndicator,
  ScrollView,
  Pressable,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Image } from "expo-image";
import { api } from "@/src/api";
import { C, S, TYPE, scoreColor, platformIcon } from "@/src/theme";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

const REEL_BG = "https://images.unsplash.com/photo-1742805382148-48e9953ad797?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NTYxOTJ8MHwxfHNlYXJjaHwxfHxuZXdzJTIwc3R1ZGlvJTIwYWJzdHJhY3R8ZW58MHx8fHwxNzgyMzM2OTAwfDA&ixlib=rb-4.1.0&q=85";

type Row = { post: any; report: any; render_job: any };

const FILTERS = [
  { key: "all", label: "ALL" },
  { key: "verified", label: "VERIFIED" },
  { key: "debunked", label: "DEBUNKED" },
];

export default function VerifiedScreen() {
  const router = useRouter();
  const [rows, setRows] = useState<Row[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const enriched: Row[] = await api.postsEnriched("verified,debunked", 100);
      enriched.sort((a, b) => (b.post.updated_at || "").localeCompare(a.post.updated_at || ""));
      setRows(enriched);
    } catch (e) {}
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      await load();
      setLoading(false);
    })();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  const filtered = rows.filter((r) => {
    if (filter === "all") return true;
    return r.post.verdict === filter || r.post.status === filter;
  });

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="verified-screen">
      <View style={styles.header}>
        <Text style={[TYPE.label, { color: C.onSurface2 }]}>NEWSAI // ARCHIVE</Text>
        <Text style={styles.h1}>VERIFIED / DEBUNKED</Text>
      </View>

      <View style={styles.chipRow}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipScroll}>
          {FILTERS.map((f) => {
            const active = filter === f.key;
            return (
              <Pressable
                key={f.key}
                onPress={() => setFilter(f.key)}
                style={[styles.chip, active && styles.chipActive]}
                testID={`filter-${f.key}`}
              >
                <Text style={[styles.chipText, active && styles.chipTextActive]}>{f.label}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={C.onSurface} />
        </View>
      ) : filtered.length === 0 ? (
        <View style={styles.center}>
          <Text style={[TYPE.mono, { color: C.onSurface2 }]}>NO VERIFIED CLAIMS</Text>
        </View>
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(r) => r.post.id}
          contentContainerStyle={{ padding: S.lg, paddingBottom: S.xxxl, gap: S.md }}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={async () => {
                setRefreshing(true);
                await load();
                setRefreshing(false);
              }}
            />
          }
          renderItem={({ item }) => {
            const verdict = item.post.verdict || "uncertain";
            const verdictColor =
              verdict === "verified" ? C.success : verdict === "debunked" ? C.error : C.warning;
            const score = item.post.confidence_score ?? item.report?.confidence_score ?? 0;
            const p = platformIcon(item.post.platform);
            return (
              <Pressable
                onPress={() => router.push({ pathname: "/post/[id]", params: { id: item.post.id } })}
                style={styles.card}
                testID={`verified-card-${item.post.id}`}
              >
                <View style={[styles.verdictBanner, { backgroundColor: verdictColor }]}>
                  <Ionicons
                    name={verdict === "verified" ? "checkmark-circle" : "close-circle"}
                    size={16}
                    color="#fff"
                  />
                  <Text style={styles.verdictText}>{verdict.toUpperCase()}</Text>
                </View>

                <View style={styles.cardBody}>
                  <View style={styles.platformRow}>
                    <Ionicons name={p.name} size={14} color={p.color} />
                    <Text style={[TYPE.label, { marginLeft: 4 }]}>{p.label}</Text>
                  </View>
                  <Text style={styles.claim} numberOfLines={3}>
                    {item.post.content}
                  </Text>

                  <View style={styles.scoreRow}>
                    <Text style={[TYPE.label, { color: C.onSurface2 }]}>CONFIDENCE</Text>
                    <Text style={[styles.scoreNum, { color: scoreColor(score) }]}>
                      {Number(score).toFixed(2)}
                    </Text>
                  </View>
                  <View style={styles.bar}>
                    <View
                      style={[
                        styles.barFill,
                        { width: `${Math.max(2, Math.round(Number(score) * 100))}%`, backgroundColor: scoreColor(score) },
                      ]}
                    />
                  </View>

                  {item.report?.logic_breakdown ? (
                    <Text style={styles.logic} numberOfLines={3}>
                      {item.report.logic_breakdown}
                    </Text>
                  ) : null}

                  {item.render_job?.status === "completed" ? (
                    <View style={styles.reelWrap}>
                      <Image source={REEL_BG} style={styles.reelImg} contentFit="cover" />
                      <View style={styles.reelOverlay}>
                        <Ionicons name="play-circle" size={48} color="#fff" />
                        <Text style={styles.reelText}>9:16 REEL READY</Text>
                      </View>
                    </View>
                  ) : null}
                </View>
              </Pressable>
            );
          }}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.surface },
  header: {
    paddingHorizontal: S.lg,
    paddingTop: S.sm,
    paddingBottom: S.md,
    borderBottomWidth: 2,
    borderBottomColor: C.border,
  },
  h1: { fontSize: 24, fontWeight: "900", letterSpacing: -1 },
  chipRow: { borderBottomWidth: 2, borderBottomColor: C.border, height: 56, justifyContent: "center" },
  chipScroll: { paddingHorizontal: S.lg, gap: S.sm, alignItems: "center" },
  chip: {
    height: 36,
    paddingHorizontal: S.md,
    borderWidth: 2,
    borderColor: C.border,
    justifyContent: "center",
    backgroundColor: C.surface,
    flexShrink: 0,
  },
  chipActive: { backgroundColor: C.inverse },
  chipText: { fontWeight: "800", letterSpacing: 1, fontSize: 11, color: C.onSurface },
  chipTextActive: { color: C.onInverse },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  card: { borderWidth: 2, borderColor: C.border, backgroundColor: C.surface },
  verdictBanner: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: S.md,
    paddingVertical: S.sm,
    gap: 6,
  },
  verdictText: { color: "#fff", fontWeight: "900", letterSpacing: 2, fontSize: 12 },
  cardBody: { padding: S.md },
  platformRow: { flexDirection: "row", alignItems: "center", marginBottom: S.sm },
  claim: { fontSize: 15, fontWeight: "700", color: C.onSurface, marginBottom: S.md, lineHeight: 21 },
  scoreRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" },
  scoreNum: { fontSize: 28, fontWeight: "900", fontFamily: "monospace" },
  bar: { height: 6, backgroundColor: C.surface3, borderWidth: 1, borderColor: C.border, marginTop: S.sm },
  barFill: { height: "100%" },
  logic: { fontSize: 13, color: C.onSurface2, marginTop: S.md, lineHeight: 18 },
  reelWrap: { marginTop: S.md, height: 180, borderWidth: 2, borderColor: C.border, position: "relative" },
  reelImg: { width: "100%", height: "100%" },
  reelOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(17,17,17,0.4)",
  },
  reelText: { color: "#fff", fontWeight: "900", letterSpacing: 2, marginTop: 4, fontSize: 12 },
});
