import type { SupabaseClient } from "@supabase/supabase-js";

import { supabase } from "@/integrations/supabase/client";

/**
 * Loosely typed client used for the generic (table-name driven) CRUD screens.
 * Row Level Security still applies — every query runs as the signed-in user.
 */
export const db = supabase as unknown as SupabaseClient;

export type Row = Record<string, unknown>;

export const str = (v: unknown): string => (v == null ? "" : String(v));
export const num = (v: unknown): number => Number(v ?? 0);
