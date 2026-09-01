// Shared Supabase-key sanity checks used by both check-desktop-env.mjs and
// check-web-env.mjs. Can't prove a key is *correct* (that needs a live
// request to Supabase) -- catches the two concrete failure shapes a
// copy-paste mistake produces: a stub/placeholder value, and a key that
// names a different Supabase project than VITE_SUPABASE_URL.

function projectRefFromUrl(url) {
  try {
    return new URL(url).hostname.split(".")[0];
  } catch {
    return undefined;
  }
}

function projectRefFromLegacyJwt(key) {
  // Legacy Supabase anon/service_role keys are JWTs: header.payload.sig,
  // base64url-encoded. Decoding the payload to read its `ref` claim needs
  // no signature verification/secret -- it's not a security check, just
  // reading a public field to compare against SUPABASE_URL's subdomain.
  const parts = key.split(".");
  if (parts.length !== 3) return undefined;
  try {
    const payload = JSON.parse(Buffer.from(parts[1], "base64url").toString("utf8"));
    return typeof payload.ref === "string" ? payload.ref : undefined;
  } catch {
    return undefined;
  }
}

/** Returns a list of human-readable warning strings (empty = looks fine). */
export function checkSupabaseKey(url, key) {
  const urlRef = projectRefFromUrl(url);
  const warnings = [];

  const isNewFormatKey = key.startsWith("sb_publishable_") || key.startsWith("sb_secret_");
  const isLegacyJwtKey = key.startsWith("eyJ");

  if (key.startsWith("sb_secret_")) {
    warnings.push(
      "looks like a Supabase SECRET key (sb_secret_...), not a publishable/anon key. A " +
        "secret key must never ship in a client bundle -- use the publishable key from " +
        "Project Settings -> API instead.",
    );
  } else if (!isNewFormatKey && !isLegacyJwtKey) {
    warnings.push(
      `(length ${key.length}) matches neither known Supabase key format (legacy JWT ` +
        'starting "eyJ", or new sb_publishable_...). This is consistent with a ' +
        "placeholder/stub value rather than a real key copied from the Supabase Dashboard.",
    );
  } else if (isLegacyJwtKey) {
    const keyRef = projectRefFromLegacyJwt(key);
    if (keyRef && urlRef && keyRef !== urlRef) {
      warnings.push(
        `is a valid-looking JWT for project "${keyRef}", but VITE_SUPABASE_URL points at ` +
          `project "${urlRef}". A key from a different Supabase project is exactly what ` +
          'produces "Invalid API key" once a real request reaches Supabase -- the build ' +
          "and the sign-in screen both look fine regardless, since neither talks to " +
          "Supabase with this key until then.",
      );
    }
  }

  if (key.length < 40) {
    warnings.push(
      `is only ${key.length} characters -- shorter than any real Supabase publishable/` +
        "anon key. Likely a placeholder or a copy-paste that got truncated.",
    );
  }

  return warnings;
}
