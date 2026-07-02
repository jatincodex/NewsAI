import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  ActivityIndicator,
  Pressable,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { C, S, TYPE, scoreColor, platformIcon } from "@/src/theme";

type Item = { post: any; report: any };

export default function AdminScreen() {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.adminQueue();
      setItems(data);
    } catch {}
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

  const decide = async (id: string, action: "approve" | "reject") => {
    setBusy(id);
    try {
      if (action === "approve") await api.approve(id);
      else await api.reject(id);
      await load();
    } finally {
      setBusy(null);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="admin-screen">
      <View style={styles.header}>
        <Text style={[TYPE.label, { color: C.onSurface2 }]}>NEWSAI // OPERATIONS</Text>
        <Text style={styles.h1}>ADMIN QUEUE</Text>
        <Text style={[TYPE.monoDim, { fontSize: 11, marginTop: 4 }]}>
          {items.length} CLAIM(S) AWAITING HUMAN REVIEW
        </Text>
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={C.onSurface} />
        </View>
      ) : items.length === 0 ? (
        <View style={styles.center}>
          <Text style={[TYPE.mono, { fontSize: 14, color: C.onSurface2, textAlign: "center" }]}>
            QUEUE CLEAR.{"\n"}NO HUMAN REVIEW REQUIRED.
          </Text>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(i) => i.post.id}
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
            const p = platformIcon(item.post.platform);
            const score = item.post.confidence_score ?? item.report?.confidence_score ?? 0;
            const rawJson = JSON.stringify(item.post.raw_payload || {}, null, 2);
            const isBusy = busy === item.post.id;
            return (
              <View style={styles.card} testID={`admin-card-${item.post.id}`}>
                <View style={styles.row}>
                  <View style={styles.platformRow}>
                    <Ionicons name={p.name} size={14} color={p.color} />
                    <Text style={[TYPE.label, { marginLeft: 4 }]}>{p.label}</Text>
                  </View>
                  <View style={[styles.scoreBox, { borderColor: scoreColor(score) }]}>
                    <Text style={[TYPE.label, { color: C.onSurface2 }]}>SCORE</Text>
                    <Text style={[styles.scoreVal, { color: scoreColor(score) }]}>
                      {Number(score).toFixed(2)}
                    </Text>
                  </View>
                </View>

                <Text style={styles.claim}>{item.post.content}</Text>

                {item.report?.logic_breakdown ? (
                  <View style={styles.logicBlock}>
                    <Text style={[TYPE.label, { color: C.onSurface2 }]}>AI BREAKDOWN</Text>
                    <Text style={styles.logic}>{item.report.logic_breakdown}</Text>
                  </View>
                ) : null}

                <View style={styles.payloadBlock}>
                  <Text style={[TYPE.label, { color: C.onSurface2 }]}>RAW PAYLOAD</Text>
                  <Text style={styles.payload}>{rawJson}</Text>
                </View>

                <View style={styles.actionRow}>
                  <Pressable
                    onPress={() => decide(item.post.id, "reject")}
                    style={[styles.btn, { backgroundColor: C.error }]}
                    disabled={isBusy}
                    testID={`reject-${item.post.id}`}
                  >
                    <Ionicons name="close" size={16} color="#fff" />
                    <Text style={styles.btnText}>REJECT</Text>
                  </Pressable>
                  <Pressable
                    onPress={() => decide(item.post.id, "approve")}
                    style={[styles.btn, { backgroundColor: C.success }]}
                    disabled={isBusy}
                    testID={`approve-${item.post.id}`}
                  >
                    <Ionicons name="checkmark" size={16} color="#fff" />
                    <Text style={styles.btnText}>APPROVE & RENDER</Text>
                  </Pressable>
                </View>
              </View>
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
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: S.xl },
  card: { borderWidth: 2, borderColor: C.border, backgroundColor: C.surface, padding: S.md },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  platformRow: { flexDirection: "row", alignItems: "center" },
  scoreBox: { borderWidth: 2, paddingHorizontal: S.md, paddingVertical: 4, alignItems: "center" },
  scoreVal: {
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    fontSize: 20,
    fontWeight: "900",
  },
  claim: { fontSize: 16, fontWeight: "700", color: C.onSurface, marginTop: S.md, lineHeight: 22 },
  logicBlock: { marginTop: S.md, paddingTop: S.md, borderTopWidth: 1, borderTopColor: C.divider },
  logic: { fontSize: 13, color: C.onSurface, marginTop: 4, lineHeight: 18 },
  payloadBlock: {
    marginTop: S.md,
    backgroundColor: C.inverse,
    padding: S.md,
    borderWidth: 2,
    borderColor: C.border,
  },
  payload: {
    color: C.onInverse,
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    fontSize: 11,
    lineHeight: 16,
    marginTop: 4,
  },
  actionRow: { flexDirection: "row", gap: S.sm, marginTop: S.md },
  btn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: S.md,
    borderWidth: 2,
    borderColor: C.border,
    gap: 6,
  },
  btnText: { color: "#fff", fontWeight: "900", letterSpacing: 1, fontSize: 12 },
});
