import { createFileRoute, Outlet } from "@tanstack/react-router";

/**
 * Pure pass-through layout for the whole `/settings/*` subtree.
 *
 * TanStack Router's flat file-based routing nests `settings.users.tsx`
 * (and any other `settings.*` file) under this route by file-naming
 * convention alone -- this file becoming a parent layout is not
 * optional once a `settings.users.tsx` sibling exists, regardless of
 * whether it was intended as one. Previously this file both was that
 * parent layout AND rendered the Company Settings page's own content
 * directly, with no `<Outlet />` anywhere -- so `/settings/users`
 * matched `AuthenticatedSettingsUsersRoute` correctly, but its
 * component was never mounted: the parent's own static content was
 * all that ever rendered, for any `/settings/*` URL. Splitting the
 * previous content out to `settings.index.tsx` (matches `/settings`
 * exactly) and reducing this file to a bare `<Outlet />` fixes the
 * mapping structurally, rather than special-casing any one child
 * route -- the same fix that makes `/settings` and `/settings/users`
 * both render correctly also correctly serves any future
 * `/settings/*` route added the same way.
 */
export const Route = createFileRoute("/_authenticated/settings")({
  component: () => <Outlet />,
});
