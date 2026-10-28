import { serve } from "@hono/node-server";
import { Hono } from "hono";
import { cors } from "hono/cors";
import { auth } from "./auth.js";

const origins = (process.env.CORS_ORIGINS ?? "").split(",").map((s) => s.trim()).filter(Boolean);

const app = new Hono();

app.get("/health", (c) => c.json({ status: "ok" }));

app.use(
  "/api/auth/*",
  cors({
    origin: origins,
    allowHeaders: ["Content-Type", "Authorization", "expo-origin"],
    allowMethods: ["GET", "POST", "OPTIONS"],
    credentials: true,
  }),
);
app.on(["GET", "POST"], "/api/auth/*", (c) => auth.handler(c.req.raw));

serve({ fetch: app.fetch, port: Number(process.env.PORT ?? 3000) });
console.log("auth service listening");
