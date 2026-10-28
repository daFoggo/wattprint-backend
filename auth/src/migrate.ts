import { getMigrations } from "better-auth/db/migration";
import { auth } from "./auth.js";

const { toBeCreated, toBeAdded, runMigrations } = await getMigrations(auth.options);
if (toBeCreated.length || toBeAdded.length) {
  await runMigrations();
  console.log("auth migrations applied");
} else {
  console.log("auth schema up to date");
}
process.exit(0);
