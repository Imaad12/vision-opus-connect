import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";

import { AppShell } from "@/components/app-shell";
import { meQueryOptions } from "@/hooks/use-auth";
import { supabase } from "@/integrations/supabase/client";

export const Route = createFileRoute("/_authenticated")({
  ssr: false,
  beforeLoad: async () => {
    const { data, error } = await supabase.auth.getUser();
    if (error || !data.user) throw redirect({ to: "/auth" });
    return { user: data.user };
  },
  loader: ({ context }) => {
    // Primes useMe()'s cache (profile/roles/permissions) as early as
    // routing into any authenticated page begins -- and, combined with
    // the router's defaultPreloadStaleTime: 0 (router.tsx), lets
    // hovering a nav link start this fetch before the user even
    // clicks. This whole route tree is ssr: false, so this never runs
    // server-side; it's a client-only prefetch. Doesn't change what's
    // fetched, how it's gated (every page's me.can(...) checks are
    // untouched), or when content renders -- only how soon the answer
    // is already sitting in the cache by the time a page asks for it.
    // A no-op network-wise if the cache entry is already fresh
    // (ensureQueryData respects staleTime, same as useQuery would).
    void context.queryClient.ensureQueryData(meQueryOptions(context.user.id));
  },
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
});
