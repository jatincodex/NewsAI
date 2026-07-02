import { Tabs } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { C } from "@/src/theme";

export default function TabsLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: C.onSurface,
        tabBarInactiveTintColor: "#999",
        tabBarStyle: {
          backgroundColor: C.surface,
          borderTopWidth: 2,
          borderTopColor: C.border,
          height: 64,
          paddingBottom: 8,
          paddingTop: 8,
        },
        tabBarLabelStyle: {
          fontSize: 10,
          fontWeight: "700",
          letterSpacing: 1,
          textTransform: "uppercase",
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Feed",
          tabBarIcon: ({ color }) => <Ionicons name="pulse" size={22} color={color} />,
          tabBarTestID: "tab-feed",
        }}
      />
      <Tabs.Screen
        name="verified"
        options={{
          title: "Verified",
          tabBarIcon: ({ color }) => <Ionicons name="shield-checkmark" size={22} color={color} />,
          tabBarTestID: "tab-verified",
        }}
      />
      <Tabs.Screen
        name="admin"
        options={{
          title: "Admin",
          tabBarIcon: ({ color }) => <Ionicons name="construct" size={22} color={color} />,
          tabBarTestID: "tab-admin",
        }}
      />
    </Tabs>
  );
}
