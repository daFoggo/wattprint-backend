import { expo } from "@better-auth/expo";
import { betterAuth } from "better-auth";
import { bearer, jwt } from "better-auth/plugins";
import { Pool } from "pg";

const list = (v?: string) => (v ?? "").split(",").map((s) => s.trim()).filter(Boolean);

const dev = process.env.NODE_ENV !== "production";

export const auth = betterAuth({
  // Better Auth tables live in the auth schema, apart from the public schema used by FastAPI.
  database: new Pool({
    connectionString: process.env.DATABASE_URL,
    options: "-c search_path=auth",
  }),
  baseURL: process.env.BETTER_AUTH_URL,
  secret: process.env.BETTER_AUTH_SECRET,
  emailAndPassword: { enabled: true },
  plugins: [
    expo(),
    bearer(),
    // FastAPI verifies these tokens with the public keys at /api/auth/jwks.
    jwt({
      jwt: {
        issuer: process.env.BETTER_AUTH_URL,
        audience: process.env.API_AUDIENCE,
        definePayload: ({ user }) => ({
          name: user.name,
          email: user.email,
          emailVerified: user.emailVerified,
        }),
      },
    }),
  ],
  trustedOrigins: [
    ...list(process.env.EXPO_APP_SCHEMES),
    ...list(process.env.CORS_ORIGINS),
    ...(dev ? ["exp://", "exp://**"] : []),
  ],
});
