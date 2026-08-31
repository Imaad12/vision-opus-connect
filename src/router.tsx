import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";

export const getRouter = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        // React Query's own default is staleTime: 0, which refetches
        // every active query on every component remount AND on every
        // browser window refocus -- including useMe()'s 5-way parallel
        // Supabase fetch (profile/roles/role_permissions/user_permissions/
        // user_scopes), refired on essentially every navigation between
        // pages. None of this data changes from outside the app's own
        // mutations (which already call invalidateQueries), so a short
        // staleTime removes those redundant round trips without risking
        // stale data after any real write.
        staleTime: 60_000,
        gcTime: 5 * 60_000,
      },
    },
  });

  const router = createRouter({
    routeTree,
    context: { queryClient },
    scrollRestoration: true,
    defaultPreloadStaleTime: 0,
  });

  return router;
};
