import { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api } from "@/src/api";
import { C, S, TYPE, scoreColor, platformIcon, statusLabel } from "@/src/theme";

const STEPS = ["queued", "rendering", "completed"];

export default function PostDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    if (!id) return;
    try {
      const d = await api.post(id);
      setData(d);
    } catch {}
  };

  useEffect(() => {
    (async () => {
      setLoading(true);
      await load();
      setLoading(false);
    })();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (loading || !data) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.center}>
          <ActivityIndicator color={C.onSurface} />
        </View>
      </SafeAreaView>
    );
  }

  const { post, report, render_job } = data;
  const score = post.confidence_score ?? report?.confidence_score ?? 0;
  const p = platformIcon(post.platform);
  const st = statusLabel(post.status);
  const renderStatus = render_job?.status || null;
  const currentStep = renderStatus ? STEPS.indexOf(renderStatus) : -1;

  return (
    <SafeAreaView style={styles.container} edges={["top"]} testID="post-detail-screen">
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="back-button" style={styles.backBtn}>
          <Ionicons name="arrow-back" size={20} color={C.onSurface} />
          <Text style={[TYPE.label, { marginLeft: 4 }]}>BACK</Text>
        </Pressable>
        <View style={[styles.statusChip, { backgroundColor: st.bg }]}>
          <Text style={[TYPE.label, { color: st.fg }]}>{st.label}</Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={{ padding: S.lg, paddingBottom: S.xxxl, gap: S.md }}>
        <View style={styles.platformRow}>
          <Ionicons name={p.name} size={16} color={p.color} />
          <Text style={[TYPE.label, { marginLeft: 4 }]}>{p.label}</Text>
          <Text style={[TYPE.monoDim, { marginLeft: S.md, fontSize: 11 }]}>
            {new Date(post.created_at).toISOString()}
          </Text>
        </View>

        <Text style={styles.claim}>{post.content}</Text>

        <View style={styles.split}>
          <View style={styles.splitCell}>
            <Text style={[TYPE.label, { color: C.onSurface2 }]}>CONFIDENCE SCORE</Text>
            <Text style={[styles.bigScore, { color: scoreColor(score) }]}>{Number(score).toFixed(2)}</Text>
            <View style={styles.bar}>
              <View
                style={[
                  styles.barFill,
                  { width: `${Math.max(2, Math.round(Number(score) * 100))}%`, backgroundColor: scoreColor(score) },
                ]}
              />
            </View>
            <Text style={[TYPE.monoDim, { fontSize: 11, marginTop: S.sm }]}>
              GATE: {score >= 0.95 ? ">= 0.95 — AUTO-RENDER" : "< 0.95 — HUMAN REVIEW"}
            </Text>
          </View>

          <View style={styles.splitCell}>
            <Text style={[TYPE.label, { color: C.onSurface2 }]}>VERDICT</Text>
            <Text
              style={[
                styles.verdict,
                {
                  color:
                    post.verdict === "verified"
                      ? C.success
                      : post.verdict === "debunked"
                      ? C.error
                      : C.warning,
                },
              ]}
            >
              {(post.verdict || "uncertain").toUpperCase()}
            </Text>
            {report?.cached ? (
              <View style={styles.cachedBadge}>
                <Ionicons name="flash" size={12} color={C.onInverse} />
                <Text style={[TYPE.label, { color: C.onInverse, marginLeft: 4 }]}>CACHE HIT</Text>
              </View>
            ) : null}
          </View>
        </View>

        <View style={styles.section}>
          <Text style={[TYPE.label, { color: C.onSurface2 }]}>AI LOGIC BREAKDOWN</Text>
          <Text style={styles.logic}>{report?.logic_breakdown || "Awaiting analysis…"}</Text>
          {report?.sources?.length ? (
            <View style={{ marginTop: S.md }}>
              <Text style={[TYPE.label, { color: C.onSurface2 }]}>SOURCES</Text>
              {report.sources.map((s: string, i: number) => (
                <Text key={i} style={styles.source}>
                  • {s}
                </Text>
              ))}
            </View>
          ) : null}
        </View>

        <View style={styles.section}>
          <Text style={[TYPE.label, { color: C.onSurface2 }]}>RENDER JOB</Text>
          {!render_job ? (
            <Text style={[TYPE.monoDim, { marginTop: S.sm, fontSize: 12 }]}>
              No render job. (Triggered automatically when score ≥ 0.95 or admin approves.)
            </Text>
          ) : (
            <View style={styles.steps}>
              {STEPS.map((s, idx) => {
                const reached = idx <= currentStep;
                return (
                  <View key={s} style={styles.stepRow}>
                    <View
                      style={[
                        styles.stepDot,
                        { backgroundColor: reached ? C.success : C.surface3 },
                      ]}
                    />
                    <Text style={[styles.stepText, reached && { fontWeight: "900" }]}>
                      {s.toUpperCase()}
                    </Text>
                    {idx < STEPS.length - 1 && (
                      <View
                        style={[
                          styles.stepLine,
                          { backgroundColor: idx < currentStep ? C.success : C.surface3 },
                        ]}
                      />
                    )}
                  </View>
                );
              })}
            </View>
          )}
          {render_job?.video_url ? (
            <Text style={[TYPE.mono, { fontSize: 11, marginTop: S.sm, color: C.info }]}>
              {render_job.video_url}
            </Text>
          ) : null}
        </View>

        <View style={styles.payloadBlock}>
          <Text style={[TYPE.label, { color: C.onSurface2 }]}>RAW PAYLOAD</Text>
          <Text style={styles.payload}>{JSON.stringify(post.raw_payload || {}, null, 2)}</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.surface },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: S.lg,
    paddingVertical: S.md,
    borderBottomWidth: 2,
    borderBottomColor: C.border,
  },
  backBtn: { flexDirection: "row", alignItems: "center" },
  statusChip: { paddingHorizontal: S.md, paddingVertical: 4, borderWidth: 2, borderColor: C.border },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  platformRow: { flexDirection: "row", alignItems: "center" },
  claim: { fontSize: 22, fontWeight: "900", color: C.onSurface, lineHeight: 28, letterSpacing: -0.5 },
  split: { flexDirection: "row", gap: S.md },
  splitCell: {
    flex: 1,
    borderWidth: 2,
    borderColor: C.border,
    padding: S.md,
    backgroundColor: C.surface,
  },
  bigScore: {
    fontSize: 44,
    fontWeight: "900",
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    marginTop: S.sm,
  },
  verdict: { fontSize: 28, fontWeight: "900", marginTop: S.sm, letterSpacing: -0.5 },
  bar: { height: 8, backgroundColor: C.surface3, borderWidth: 1, borderColor: C.border, marginTop: S.sm },
  barFill: { height: "100%" },
  cachedBadge: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: C.inverse,
    alignSelf: "flex-start",
    paddingHorizontal: S.sm,
    paddingVertical: 2,
    marginTop: S.sm,
    borderWidth: 1,
    borderColor: C.border,
  },
  section: { borderWidth: 2, borderColor: C.border, padding: S.md, backgroundColor: C.surface },
  logic: { fontSize: 14, color: C.onSurface, marginTop: S.sm, lineHeight: 20 },
  source: { fontSize: 12, color: C.onSurface, marginTop: 2 },
  steps: { marginTop: S.md, gap: S.sm },
  stepRow: { flexDirection: "row", alignItems: "center", gap: S.sm },
  stepDot: { width: 14, height: 14, borderWidth: 2, borderColor: C.border },
  stepText: { fontSize: 12, letterSpacing: 1, color: C.onSurface },
  stepLine: { flex: 1, height: 2 },
  payloadBlock: {
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
});
