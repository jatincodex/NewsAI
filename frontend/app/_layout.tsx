import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect } from "react";
import { LogBox, StatusBar } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";

import { useIconFonts } from "@/src/hooks/use-icon-fonts";

// Disable logbox errors etc so that users can see the app
// and agent works as expected.
LogBox.ignoreAllLogs(true);

// Keep the native splash visible from cold start until icon fonts register.
SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [loaded, error] = useIconFonts();

  useEffect(() => {
    if (loaded || error) {
      SplashScreen.hideAsync();
    }
  }, [loaded, error]);

  if (!loaded && !error) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: "#FAFAFA" }}>
      <StatusBar barStyle="dark-content" backgroundColor="#FAFAFA" />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: "#FAFAFA" } }}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="post/[id]" options={{ presentation: "card" }} />
      </Stack>
    </GestureHandlerRootView>
  );
}
