/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_MODE?: string
  readonly VITE_API_URL?: string
  /** 'true' = every visitor must sign in first (multi-tenant product). Default: demo v0.1 behaviour. */
  readonly VITE_REQUIRE_LOGIN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
