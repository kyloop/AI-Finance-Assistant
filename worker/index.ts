/** Cloudflare entry point: serves the built frontend (frontend/dist, via the `assets` config) and forwards /api/* —
 * including the NDJSON chat stream and the /api/market/stream WebSocket — to the FastAPI backend in a Container.
 * Keys live in the Cloudflare Secrets Store and are handed to the container as environment variables when it starts. */
import { Container, getContainer, type ContainerStartConfigOptions } from "@cloudflare/containers";

// Must match the `binding` names under `secrets_store_secrets` in wrangler.jsonc (the env var names the backend reads).
const SECRETS = [
  "OPENAI_API_KEY",
  "TURSO_DATABASE_URL",
  "TURSO_API_KEY",
  "QDRANT_CLUSTER_ENDPOINT",
  "QDRANT_CLUSTER_API_KEY",
  "TAVILY_API_KEY",
  "WOLFRAM_ALPHA_APP_ID",
  "LANGFUSE_SECRET_KEY",
  "LANGFUSE_PUBLIC_KEY",
  "LANGFUSE_BASE_URL",
] as const;

type Env = { BACKEND: DurableObjectNamespace<Backend>; ASSETS: Fetcher } & Record<(typeof SECRETS)[number], SecretsStoreSecret>;

/** Secrets that exist in the store; a missing or unreadable one is skipped so optional keys (Langfuse, Tavily…) can be left out. */
async function secretEnvVars(env: Env): Promise<Record<string, string>> {
  const pairs = await Promise.all(
    SECRETS.map(async (name) => {
      try {
        return [name, (await env[name]?.get())?.trim() ?? ""] as const;
      } catch (e) {
        console.warn(`secret ${name} not available: ${e}`);
        return [name, ""] as const;
      }
    }),
  );
  return Object.fromEntries(pairs.filter(([, value]) => value));
}

export class Backend extends Container<Env> {
  defaultPort = 8000;
  sleepAfter = "30m"; // idle time before the container stops (the news poller and live price stream stop with it)

  // Every (re)start goes through here, including the auto-start in fetch(): read the secrets fresh, so a value changed in
  // the Secrets Store applies from the next start, and allow longer than the 20 s default for Python to come up.
  override async startAndWaitForPorts(...args: Parameters<Container["startAndWaitForPorts"]>): Promise<void> {
    const [portsOrArgs, cancellation, start] = args;
    const opts: { ports?: number | number[]; cancellationOptions?: typeof cancellation; startOptions?: ContainerStartConfigOptions } =
      typeof portsOrArgs === "object" && portsOrArgs !== null && !Array.isArray(portsOrArgs)
        ? { ...portsOrArgs }
        : { ports: portsOrArgs, cancellationOptions: cancellation, startOptions: start };
    opts.cancellationOptions = { portReadyTimeoutMS: 90_000, ...opts.cancellationOptions };
    opts.startOptions = { ...opts.startOptions, envVars: { ...(await secretEnvVars(this.env)), ...opts.startOptions?.envVars } };
    return super.startAndWaitForPorts(opts);
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (pathname === "/api" || pathname.startsWith("/api/")) {
      return getContainer(env.BACKEND).fetch(request); // one shared backend instance
    }
    return env.ASSETS.fetch(request);
  },
} satisfies ExportedHandler<Env>;
