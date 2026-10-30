// Self-test harness for dsh-env-doctor.
// Sets DSH_ENV_DOCTOR_GUARD=0 before loading the plugin so a test run never
// starts the background guard (which would otherwise append to guard-log.txt).
process.env.DSH_ENV_DOCTOR_GUARD = "0";

const { apply } = await import("./index.js");

const tools = {};
// v0.4 started using ctx.effect for the background guard timer, so the mock
// context has to provide it too. The callback returns its cleanup function.
const ctx = {
  tools: { register: (d) => { tools[d.name] = d; } },
  effect: (fn) => {
    const cleanup = fn();
    return typeof cleanup === "function" ? cleanup : () => {};
  },
};
apply(ctx, { workspace: "D:\work" });

const def = tools.env_doctor;
if (!def) throw new Error("tool not registered");

const which = process.argv[2] || "all";
const args = { only: which };
if (process.argv.includes("--deep")) args.deep = true;
if (process.argv.includes("--fix")) args.fix = true;
if (process.argv.includes("--no-network")) args.noNetwork = true;

const out = await def.execute(args);
console.log(out);
