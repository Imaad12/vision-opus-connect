import { createFileRoute } from "@tanstack/react-router";

import { SignInScreen } from "@/components/sign-in-card";

export const Route = createFileRoute("/")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "Sign in — VINCO ERP | Vision Contracting Co." },
      {
        name: "description",
        content:
          "Secure sign-in for Vision Contracting Co. staff to the VINCO internal ERP and CRM workspace.",
      },
      { property: "og:title", content: "Sign in — VINCO ERP" },
      {
        property: "og:description",
        content: "Internal ERP and CRM workspace for Vision Contracting Co.",
      },
    ],
  }),
  component: SignInScreen,
});
