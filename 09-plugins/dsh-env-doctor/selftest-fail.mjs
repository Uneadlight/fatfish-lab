import { apply } from "./index.js";

const tools = {};
apply({ tools: { register: (d) => { tools[d.name] = d; } } }, {});
const def = tools.env_doctor;

console.log("=== FAIL 路径：owner 不是当前用户的目录 ===");
console.log(def.execute({ workspace: "C:\\Windows\\System32", only: "workspace" }));

console.log("\n=== 不存在的工作区 ===");
console.log(def.execute({ workspace: "Z:\\nope-nope-nope", only: "workspace" }));
