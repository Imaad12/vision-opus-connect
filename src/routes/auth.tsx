import { createFileRoute } from "@tanstack/react-router";

import { SignInScreen } from "@/components/sign-in-card";

export const Route = createFileRoute("/auth")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "Staff sign-in — VINCO ERP" },
      {
        name: "description",
        content: "Sign in with your Vision Contracting Co. Google account to access VINCO ERP.",
      },
      { property: "og:title", content: "Staff sign-in — VINCO ERP" },
      {
        property: "og:description",
        content: "Sign in with your company account to access the VINCO workspace.",
      },
    ],
  }),
  component: SignInScreen,
});
