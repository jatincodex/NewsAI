import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  ActivityIndicator,
  Pressable,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { C, S, TYPE } from "@/src/theme";
import StatsBar from "@/src/components/StatsBar";
import PostCard, { PostT } from "@/src/components/PostCard";

export default function FeedScreen() {
  const [posts, setPosts] = useState<PostT[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([api.stats(), api.posts()]);
      setStats(s);
      setPosts(p);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load");
    }
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      await load();
      setLoading(false);
    })();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const onIngest = async () => {
    try {
      await api.ingest(3);
      setTimeout(load, 600);
    } catch {}
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="feed-screen">
      <View style={styles.header}>
        <View>
          <Text style={[TYPE.label, { color: C.onSurface2 }]}>NEWSAI // LIVE FEED</Text>
          <Text style={styles.h1}>VIRAL CLAIMS</Text>
        </View>
        <Pressable onPress={onIngest} style={styles.ingestBtn} testID="ingest-button">
          <Ionicons name="add" size={18} color={C.onInverse} />
          <Text style={styles.ingestText}>INJECT</Text>
        </Pressable>
      </View>

      <StatsBar stats={stats} />

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={C.onSurface} />
          <Text style={[TYPE.label, { marginTop: 8 }]}>BOOTING STREAM…</Text>
        </View>
      ) : error ? (
        <View style={styles.center}>
          <View style={styles.errorBox}>
            <Text style={[TYPE.label, { color: "#fff" }]}>CONNECTION FAILED</Text>
          </View>
          <Pressable onPress={load} style={styles.retryBtn}>
            <Text style={styles.retryText}>RETRY</Text>
          </Pressable>
        </View>
      ) : posts.length === 0 ? (
        <View style={styles.center}>
          <Text style={[TYPE.mono, { fontSize: 14, color: C.onSurface2 }]}>NO DATA STREAM</Text>
        </View>
      ) : (
        <FlatList
          data={posts}
          keyExtractor={(p) => p.id}
          renderItem={({ item }) => <PostCard post={item} />}
          contentContainerStyle={{ paddingTop: S.md, paddingBottom: S.xxxl }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.onSurface} />
          }
          testID="feed-list"
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.surface },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-end",
    paddingHorizontal: S.lg,
    paddingTop: S.sm,
    paddingBottom: S.md,
    borderBottomWidth: 2,
    borderBottomColor: C.border,
  },
  h1: { fontSize: 28, fontWeight: "900", letterSpacing: -1, color: C.onSurface },
  ingestBtn: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: C.inverse,
    paddingHorizontal: S.md,
    paddingVertical: S.sm,
    borderWidth: 2,
    borderColor: C.border,
    gap: 4,
  },
  ingestText: { color: C.onInverse, fontWeight: "800", letterSpacing: 1, fontSize: 12 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: S.xl },
  errorBox: { backgroundColor: C.error, padding: S.lg, borderWidth: 2, borderColor: C.border },
  retryBtn: {
    marginTop: S.md,
    paddingHorizontal: S.lg,
    paddingVertical: S.sm,
    borderWidth: 2,
    borderColor: C.border,
    backgroundColor: C.surface,
  },
  retryText: { fontWeight: "800", letterSpacing: 1 },
});
